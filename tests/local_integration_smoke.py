#!/usr/bin/env python3
"""Test exact host/LAN forwarding with real Tor and disposable local services."""
import argparse
from contextlib import ExitStack
from http.server import ThreadingHTTPServer
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import secrets
import ssl
import subprocess
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from deployment import check_bind_sources, compose_base, compose_files, engine, engine_command, prepare_launch, remove_networks

IMAGE = 'private-hermes-network:local-integration-test'
HOST = 'host.docker.internal'
HOST_IP = '198.18.255.254'


def fixture(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'tests/fixtures' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def serve(scope, handler, address, tls=None):
    server = scope.enter_context(ThreadingHTTPServer((address, 0), handler))
    if tls:
        server.socket = tls.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    scope.callback(server.shutdown)
    return server.server_port


def tls_context(directory):
    cert = directory / 'cert.pem'
    key = directory / 'key.pem'
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                    '-subj', '/CN=' + HOST, '-addext', 'subjectAltName=DNS:' + HOST,
                    '-keyout', str(key), '-out', str(cert)], capture_output=True, check=True)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    observed_names = set()
    context.sni_callback = lambda _session, name, _context: observed_names.add(name) and None
    return context, cert, observed_names


FETCH = '''
import ssl, sys, urllib.request
context = ssl.create_default_context(cafile=sys.argv[2]) if len(sys.argv) > 2 else None
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context))
assert opener.open(sys.argv[1],timeout=3).status == 200
'''

TCP_PROBE = '''
import socket, sys
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
    client.settimeout(3)
    try:
        connected = client.connect_ex((sys.argv[1], int(sys.argv[2]))) == 0
    except TimeoutError:
        connected = False
    print('connected' if connected else 'closed')
'''

TOR_WITH_DENIED_FORWARDING = '''
import errno
import runpy

router = runpy.run_path('/opt/network.py')['router']
sysctl = router.__globals__['IP_FORWARD']

class DeniedForwarding:
    def read_text(self):
        return sysctl.read_text()

    def write_text(self, value):
        if value == '1\\n':
            raise PermissionError(errno.EACCES, 'fixture denies forwarding enable')
        return sysctl.write_text(value)

router.__globals__['IP_FORWARD'] = DeniedForwarding()
router()
'''

NATIVE_CLIENTS = r'''
import asyncio, json, os, runpy, ssl, sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import httpx
from agent import model_metadata, model_metadata_http
from agent.process_bootstrap import build_keepalive_http_client
from hermes_cli.env_loader import load_hermes_dotenv
from hermes_cli.models import probe_api_models
from openai import OpenAI
from tools.mcp_tool import MCPServerTask

host, lan, model, cert = sys.argv[1:]
proxy_names = ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy')
fixture_home = TemporaryDirectory()
root = Path(fixture_home.name)
managed, profile = root / 'managed', root / 'profile'
managed.mkdir()
profile.mkdir()
policy = runpy.run_path('/opt/hermes/docker/private-managed-policy.py')['policy']
_, dotenv = policy(dict(os.environ, WEBAPP_TERMINAL_ENVIRONMENT='code', WEBAPP_EXTERNAL_CONTENT='off',
                        TERMINAL_SSH_HOST='10.203.82.3', TERMINAL_SSH_PORT='2222',
                        TERMINAL_SSH_USER='runner', TERMINAL_SSH_KEY='/run/agent-ssh/id_ed25519'))
(managed / '.env').write_text(''.join(f'{key}={json.dumps(value)}\n' for key, value in dotenv.items()))
os.environ.update(HERMES_MANAGED_DIR=str(managed), HERMES_HOME=str(profile))
assert all(os.environ.get(name) == 'http://127.0.0.1:1' for name in proxy_names)
for port in (2, 3):
    (profile / '.env').write_text(''.join(f'{name}=http://127.0.0.1:{port}\n' for name in proxy_names))
    load_hermes_dotenv(hermes_home=profile, load_external_secrets=False)
    assert all(os.environ.get(name) == '' for name in proxy_names)

context = ssl.create_default_context(cafile=cert)
with patch('hermes_cli.models._custom_provider_ssl_context', return_value=context):
    catalog = probe_api_models('disposable-fixture', host)
assert model in catalog['models']
with patch.object(model_metadata_http, 'resolve_verify', return_value=context):
    assert model in model_metadata.fetch_endpoint_model_metadata(host, api_key='disposable-fixture', force_refresh=True)
with OpenAI(base_url=host, api_key='disposable-fixture',
            http_client=build_keepalive_http_client(host, verify=context), max_retries=0) as client:
    stream = client.chat.completions.create(model=model, stream=True, messages=[{'role':'user','content':'fixture'}])
    assert ''.join(chunk.choices[0].delta.content or '' for chunk in stream) == 'PRIVATE-CHAT-STREAM-OK'

async def mcp():
    server = MCPServerTask('local_fixture')
    runner = asyncio.create_task(server.run({'url':lan, 'connect_timeout':10}))
    try:
        await asyncio.wait_for(server._ready.wait(), timeout=20)
        assert server.session is not None, server._error
        assert {tool.name for tool in (await server.session.list_tools()).tools} == {'echo'}
        result = await server.session.call_tool('echo', {'text':'LAN MCP streamed'})
        assert not result.is_error and result.content[0].text == 'LAN MCP streamed'
    finally:
        await server.shutdown()
        await runner

async def diagnostic_redirects():
    server = MCPServerTask('redirect_fixture')
    for responses, methods in (
        ([307], ['HEAD']),
        ([405, 307], ['HEAD', 'GET']),
        ([200, 307], ['HEAD', 'POST']),
    ):
        observed = []

        def respond(request):
            observed.append(request.method)
            assert str(request.url) == lan, request.url
            status = responses[len(observed) - 1]
            headers = {'Location': host} if status == 307 else {'Content-Type': 'text/html'}
            return httpx.Response(status, headers=headers)

        with patch.object(httpx, 'AsyncHTTPTransport', return_value=httpx.MockTransport(respond)):
            await server._preflight_content_type(lan)
        assert observed == methods

asyncio.run(diagnostic_redirects())
asyncio.run(mcp())
'''


def run_fixture(args):
    host_bind = ipaddress.IPv4Address(args.host_bind)
    lan_address = ipaddress.IPv4Address(args.lan_address)
    inference = fixture('webapp-inference')
    mcp = fixture('mcp')
    with ExitStack() as scope:
        directory = Path(scope.enter_context(tempfile.TemporaryDirectory(prefix='hermes-local-proof-')))
        context, cert, sni = tls_context(directory)
        received_hosts = set()

        class Inference(inference.Handler):
            def do_POST(self):
                received_hosts.add(self.headers['Host'])
                super().do_POST()

        host_port = serve(scope, Inference, str(host_bind), context)
        ungranted_host = serve(scope, Inference, str(host_bind), context)
        if args.lan_ports:
            lan_port, ungranted_lan = args.lan_ports
        else:
            lan_port, ungranted_lan = [serve(scope, mcp.Handler, str(lan_address)) for _ in range(2)]

        overlay = directory / 'compose.json'
        definition = {'services': {
            'tor': {'image': IMAGE, 'volumes': ['tor-fixture-data:/var/lib/tor'],
                    'environment': {'PRIVATE_HERMES_X402_TREAZURY_SOCKS': '0'}},
            'agent-net': {'image': IMAGE, 'volumes': [
                f'{ROOT}/tests/fixtures/mcp-allowlist.json:/etc/private-hermes/mcp-allowlist.json:ro']},
            'executor-net': {'image': IMAGE},
            'hermes': {'image': 'private-hermes-agent:local-integration-test'},
        }, 'volumes': {'tor-fixture-data': {}}}
        overlay.write_text(json.dumps(definition))
        os.environ.update(COMPOSE_ENV_FILES='.env.example', NETWORK_PREFIX='10.203',
                          TOR_ONION_ENABLED='false',
                          HERMES_INTEGRATIONS_ALLOWED_HOST_PORTS='none',
                          HERMES_INTEGRATIONS_LAN_ENDPOINTS='none')
        project = 'private-hermes-local-proof-' + secrets.token_hex(4)
        command = [*compose_base(), '-p', project, *compose_files(False, (str(overlay),))]

        def compose(*arguments, **kwargs):
            return subprocess.run([*command, *arguments], text=True, check=True, **kwargs)

        def cleanup():
            compose('down', '--volumes')
            remove_networks(command)

        def client(owner, uid, image, executable, script, arguments, options=(), **kwargs):
            owner_id = None if owner is None else compose('ps', '-q', owner, capture_output=True).stdout.strip()
            if owner:
                assert owner_id
            network = ['--network', f'container:{owner_id}'] if owner_id else []
            return subprocess.run([*engine_command(), 'run', '--rm', '--pull', 'never', '--cap-drop', 'ALL',
                                   '--user', f'{uid}:{uid}', *network, *options, '--entrypoint', executable,
                                   image, '-c', script, *arguments], text=True, **kwargs)

        def fetch(owner, uid, url, *, tls=False, options=()):
            if tls:
                options = (*options, '--mount', f'type=bind,source={cert},target=/tmp/fixture.pem,readonly')
            client(owner, uid, IMAGE, 'python3', FETCH, [url, *(['/tmp/fixture.pem'] if tls else [])],
                   options, check=True)

        def probe(owner, uid, address, port, allowed, options=()):
            result = client(owner, uid, IMAGE, 'python3', TCP_PROBE, [str(address), str(port)],
                            options, capture_output=True, check=True)
            expected = 'connected' if allowed else 'closed'
            assert result.stdout.strip() == expected, (owner, uid, address, port, result.stdout, result.stderr)

        subprocess.run([sys.executable, 'scripts/preflight.py', project, '--skip-ports'], check=True)
        scope.callback(cleanup)
        if not args.no_build:
            compose('build', *(['tor'] if args.expect_lan_closed else ['tor', 'hermes']))
        prepare_launch(command, check_bind_sources(command, ['up', '--no-deps', 'tor', 'agent-net', 'executor-net']))
        # Wait for the real gateway before attaching application test users.
        compose('up', '-d', '--no-deps', '--wait', 'tor')
        compose('up', '-d', '--no-deps', '--wait', 'agent-net', 'executor-net')
        local_host = f'https://{HOST}:{host_port}'
        local_lan = f'http://{lan_address}:{lan_port}'

        # Prepare the next launch without changing the running default policy.
        os.environ.update(HERMES_INTEGRATIONS_ALLOWED_HOST_PORTS=str(host_port),
                          HERMES_INTEGRATIONS_LAN_ENDPOINTS=f'{lan_address}:{lan_port}')
        grant_model = check_bind_sources(command, ['up', '--no-deps', 'tor', 'agent-net'])
        prepare_launch(command, grant_model)
        native_host = os.environ['PRIVATE_HERMES_ENGINE_HOST_ADDRESS']
        assert native_host, 'The engine did not provide a host IPv4 mapping for the fixture'
        control_network = ('--network', grant_model['networks']['tor-uplink']['name'])
        # Independent controls on the same uplink prove the actual sockets are reachable.
        for port in (host_port, ungranted_host):
            probe(None, 10000, native_host, port, True, control_network)
        for port in (lan_port, ungranted_lan):
            fetch(None, 10000, f'http://{lan_address}:{port}/health', options=control_network)
        host_socket = (HOST_IP, host_port)
        lan_socket = (str(lan_address), lan_port)
        allowed = {host_socket} if args.expect_lan_closed else {host_socket, lan_socket}
        tested = {host_socket, lan_socket, (HOST_IP, ungranted_host), (str(lan_address), ungranted_lan),
                  (native_host, host_port), (native_host, ungranted_host)}
        for owner in ('agent-net', 'executor-net'):
            for address, port in sorted(tested):
                probe(owner, 10000, address, port, False)
        print('PASS: reachable host/LAN listeners are denied from both namespaces with default grants', flush=True)

        compose('up', '-d', '--no-deps', '--wait', 'tor')
        compose('up', '-d', '--no-deps', '--wait', 'agent-net')
        for address, port in sorted(tested):
            probe('executor-net', 10000, address, port, False)
        for address, port in sorted((tested | {(HOST_IP, lan_port), (str(lan_address), host_port)}) - allowed):
            probe('agent-net', 10000, address, port, False)
        if args.expect_lan_closed:
            print('PASS: explicit grants leave native Linux Docker LAN sockets and executor access closed', flush=True)
        warnings_command = ('exec', '-T', '--user', '65534:65534', 'tor', 'cat', '/tmp/local-grant-warnings')
        warnings = compose(*warnings_command, capture_output=True).stdout.strip()
        expected_warning = 'Docker LAN grants require Docker Desktop. LAN grants closed.' if args.expect_lan_closed else ''
        assert warnings == expected_warning, warnings
        for address, port in sorted(allowed):
            probe('agent-net', 10000, address, port, True)
            probe('agent-net', 10003, address, port, False)
        fetch('agent-net', 10000, local_host + '/health', tls=True)
        if args.expect_lan_closed:
            print('PASS: exact TLS host grant works and native Linux Docker keeps literal LAN grants closed', flush=True)
            return
        fetch('agent-net', 10000, local_lan + '/health')
        print('PASS: independent reachable controls, exact TLS host and LAN paths, UID and executor denial', flush=True)

        model = json.loads(compose('config', '--format', 'json', capture_output=True).stdout)
        hermes = model['services']['hermes']
        proxy_names = ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy')
        for name in proxy_names:
            assert hermes['environment'][name] == ''
        # Pollute the test process deliberately to exercise the managed dotenv
        # independently of Compose's startup-time protection.
        inherited = [part for name in proxy_names for part in ('--env', f'{name}=http://127.0.0.1:1')]
        client('agent-net', 10000, hermes['image'], '/opt/hermes/.venv/bin/python', NATIVE_CLIENTS,
               [local_host + '/v1', local_lan + '/mcp', inference.MODEL, '/tmp/fixture.pem'],
               ['--mount', f'type=bind,source={cert},target=/tmp/fixture.pem,readonly', '--env', 'HERMES_HOME=/tmp',
                *inherited], check=True)
        assert HOST in sni and f'{HOST}:{host_port}' in received_hosts
        print('PASS: managed proxy settings, diagnostic redirects, native inference and MCP, and original TLS/HTTP names', flush=True)

        compose('stop', 'tor')
        probe('agent-net', 10000, HOST_IP, host_port, False)
        probe('agent-net', 10000, lan_address, lan_port, False)
        compose('up', '-d', '--no-deps', '--wait', 'tor')
        fetch('agent-net', 10000, local_host + '/health', tls=True)
        fetch('agent-net', 10000, local_lan + '/health')
        assert not compose(*warnings_command, capture_output=True).stdout.strip()
        definition['services']['tor']['entrypoint'] = ['python3', '-c', TOR_WITH_DENIED_FORWARDING]
        overlay.write_text(json.dumps(definition))
        compose('up', '-d', '--no-deps', '--wait', '--force-recreate', 'tor')
        probe('agent-net', 10000, HOST_IP, host_port, False)
        probe('agent-net', 10000, lan_address, lan_port, False)
        warning = compose(*warnings_command, capture_output=True).stdout
        assert 'fixture denies forwarding enable' in warning and 'Local grants closed.' in warning, warning
        print('PASS: denied forwarding enable closes local grants while the real Tor service becomes healthy', flush=True)
        del definition['services']['tor']['entrypoint']
        overlay.write_text(json.dumps(definition))
        os.environ['PRIVATE_HERMES_ENGINE_HOST_ADDRESS'] = ''
        compose('up', '-d', '--no-deps', '--wait', '--force-recreate', 'tor')
        probe('agent-net', 10000, HOST_IP, host_port, False)
        fetch('agent-net', 10000, local_lan + '/health')
        warnings = compose(*warnings_command, capture_output=True).stdout
        assert 'Host grants closed.' in warnings
        print('PASS: a missing engine host mapping closes only host grants', flush=True)

        os.environ['HERMES_INTEGRATIONS_ALLOWED_HOST_PORTS'] = 'none'
        prepare_launch(command, check_bind_sources(command, ['up', '--no-deps', 'tor']))
        compose('up', '-d', '--no-deps', '--wait', '--force-recreate', 'tor')
        fetch('agent-net', 10000, local_lan + '/health')
        probe('agent-net', 10000, lan_address, ungranted_lan, False)
        probe('executor-net', 10000, lan_address, lan_port, False)
        assert not compose(*warnings_command, capture_output=True).stdout.strip()
        print('PASS: LAN-only grants start without host mapping and remain exact', flush=True)

        os.environ['HERMES_INTEGRATIONS_LAN_ENDPOINTS'] = 'none'
        prepare_launch(command, check_bind_sources(command, ['up', '--no-deps', 'tor']))
        compose('up', '-d', '--no-deps', '--wait', '--force-recreate', 'tor')
        probe('agent-net', 10000, HOST_IP, host_port, False)
        probe('agent-net', 10000, lan_address, lan_port, False)
        assert not compose(*warnings_command, capture_output=True).stdout.strip()
        final_model = json.loads(compose('config', '--format', 'json', capture_output=True).stdout)
        assert set(final_model['services']['tor']['security_opt']) == {
            'no-new-privileges:true', 'no-new-privileges=true',
        }
        print('PASS: gateway outage, restart and removal of grants with original clients still present', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('host_bind', help='Address on the engine host for the native host-alias listener')
    parser.add_argument('lan_address', help='Routed IPv4 fixture bind address')
    parser.add_argument('--lan-ports', nargs=2, type=int, metavar=('ALLOWED', 'DENIED'),
                        help='Ports on an existing routed MCP/HTTP fixture')
    parser.add_argument('--expect-lan-closed', action='store_true',
                        help='Check host grants and verify native Linux Docker denies literal LAN grants')
    parser.add_argument('--no-build', action='store_true', help='Use images already built under the fixture tags')
    args = parser.parse_args()
    if args.lan_ports and args.lan_ports[0] == args.lan_ports[1]:
        parser.error('--lan-ports requires distinct allowed and denied ports')
    os.chdir(ROOT)
    run_fixture(args)


if __name__ == '__main__':
    main()
