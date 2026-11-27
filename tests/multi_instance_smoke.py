#!/usr/bin/env python3
"""Live concurrent two-instance qualification on Docker or rootless Podman."""
from http.cookiejar import CookieJar
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from deployment import compose_base, compose_files, engine, engine_command  # noqa: E402
from smoke import remove_storage_fixture  # noqa: E402


def free_ports(count):
    sockets = []
    try:
        for _ in range(count):
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.bind(('127.0.0.1', 0))
            sockets.append(sock)
        return [sock.getsockname()[1] for sock in sockets]
    finally:
        for sock in sockets:
            sock.close()


def copy_checkout(destination):
    destination.mkdir(parents=True, exist_ok=True)
    for name in ('Makefile', '.env.example', '.dockerignore', 'compose.yaml',
                 'compose.executor.yaml', 'compose.funnel.yaml',
                 'compose.podman.yaml', 'compose.podman.funnel.yaml'):
        shutil.copy2(ROOT / name, destination / name)
    for name in ('components', 'scripts'):
        shutil.copytree(ROOT / name, destination / name, ignore=shutil.ignore_patterns('__pycache__'))


def write_env(checkout, project, prefix, webapp_port, teep_port, *, onion=False, host_ports=None):
    env_text = (
        f'CONTAINER_ENGINE={engine()}\n'
        f'COMPOSE_PROJECT_NAME={project}\n'
        f'NETWORK_PREFIX={prefix}\n'
        f'WEBAPP_BIND=127.0.0.1\n'
        f'WEBAPP_PORT={webapp_port}\n'
        f'WEBAPP_USERNAME=admin\n'
        f'WEBAPP_EXTERNAL_CONTENT=tor_proxied\n'
        f'WEBAPP_TERMINAL_ENVIRONMENT=code\n'
        f'COMPUTER_USE_ENABLED=false\n'
        f'TEEP_ENABLED=true\n'
        f'TEEP_HOST_PORT={teep_port}\n'
        f'TEEP_INSTALL_MODEL=\n'
        f'VENICE_API_KEY=multi-instance-placeholder-not-a-real-key\n'
        f'TOR_ONION_ENABLED={"true" if onion else "false"}\n'
        f'TAILSCALE_FUNNEL_ENABLED=false\n'
    )
    if host_ports is not None:
        env_text += f'HERMES_INTEGRATIONS_ALLOWED_HOST_PORTS={host_ports}\n'
    path = checkout / '.env'
    path.write_text(env_text)
    path.chmod(0o600)


def instance_env():
    env = dict(os.environ)
    for key in ('COMPOSE_PROJECT_NAME', 'COMPOSE_ENV_FILES', 'NETWORK_PREFIX',
                'WEBAPP_PORT', 'WEBAPP_BIND', 'WEBAPP_USERNAME',
                'WEBAPP_EXTERNAL_CONTENT', 'WEBAPP_TERMINAL_ENVIRONMENT',
                'TEEP_HOST_PORT', 'TEEP_ENABLED', 'TEEP_SERVE_ARGS', 'TEEP_INSTALL_MODEL',
                'COMPUTER_USE_ENABLED', 'CODE_EXECUTOR_BIND_MOUNTS',
                'HERMES_INTEGRATIONS_ALLOWED_HOST_PORTS', 'HERMES_INTEGRATIONS_LAN_ENDPOINTS',
                'TOR_ONION_ENABLED', 'TAILSCALE_FUNNEL_ENABLED', 'TAILSCALE_HOSTNAME',
                'TAILSCALE_FUNNEL_HOST', 'TAILSCALE_FUNNEL_PORT'):
        env.pop(key, None)
    env['CONTAINER_ENGINE'] = engine()
    return env


def run_in(checkout, *args, check=True, capture=False, extra_env=None):
    env = instance_env()
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        args, cwd=checkout, env=env,
        text=True, capture_output=capture, check=check,
    )


def compose_exec(checkout, service, *args, user=None, check=True):
    cmd = [*compose_base(), *compose_files(False), 'exec', '-T']
    if user:
        cmd += ['--user', user]
    cmd += [service, *args]
    return run_in(checkout, *cmd, check=check, capture=True)


def http_request(opener, url, data=None, headers=None):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    try:
        with opener.open(req, timeout=10) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def wait_webapp_ready(port):
    opener = urllib.request.build_opener()
    url = f'http://127.0.0.1:{port}/login'
    for _ in range(120):
        try:
            code, _ = http_request(opener, url)
            if code == 200:
                return
        except OSError:
            pass
        time.sleep(0.5)
    raise AssertionError(f'WebApp on port {port} did not become ready')


def verify_webapp_login(port, password, wrong_password):
    origin = f'http://127.0.0.1:{port}'
    jar = CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    code, _ = http_request(opener, f'{origin}/api/config')
    assert code in (401, 403), f'Expected unauthenticated /api/config rejection on {port}, got {code}'

    bad_payload = json.dumps({'provider': 'basic', 'username': 'admin', 'password': wrong_password}).encode()
    bad_code, _ = http_request(
        opener, f'{origin}/auth/password-login', data=bad_payload,
        headers={'Content-Type': 'application/json', 'Origin': origin},
    )
    assert bad_code in (401, 403), f'Expected wrong password rejection on {port}, got {bad_code}'

    good_payload = json.dumps({'provider': 'basic', 'username': 'admin', 'password': password}).encode()
    good_code, _ = http_request(
        opener, f'{origin}/auth/password-login', data=good_payload,
        headers={'Content-Type': 'application/json', 'Origin': origin},
    )
    assert good_code == 200, f'Expected login 200 on {port}, got {good_code}'

    api_code, _ = http_request(opener, f'{origin}/api/config')
    assert api_code == 200, f'Expected authenticated /api/config 200 on {port}, got {api_code}'


def service_network_ip(checkout, project, service, network):
    cid = run_in(
        checkout, *compose_base(), *compose_files(False), 'ps', '-q', service,
        capture=True,
    ).stdout.strip()
    assert cid, f'No running container found for {project}/{service}'
    raw = subprocess.run(
        [*engine_command(), 'inspect', '--format', '{{json .NetworkSettings.Networks}}', cid],
        cwd=ROOT, text=True, capture_output=True, check=True,
    ).stdout
    networks = json.loads(raw) or {}
    ip = (networks.get(f'{project}_{network}') or {}).get('IPAddress', '')
    assert ip, f'No IP on {project}_{network} for {project}/{service}: {networks}'
    return ip


def verify_tcp(checkout, service, host, port, *, expect_open, user=None):
    if service == 'teep':
        result = compose_exec(
            checkout, service, 'sh', '-c',
            'nc -z -w 2 "$1" "$2" && echo OPEN || echo CLOSED', '_', host, str(port),
            user=user or '10002:10002',
        )
    else:
        probe = (
            'import socket; '
            f's = socket.socket(); s.settimeout(2); '
            f'rc = s.connect_ex(({host!r}, {port})); s.close(); '
            'print("OPEN" if rc == 0 else f"CLOSED:{rc}")'
        )
        python_bin = '/opt/hermes/.venv/bin/python' if service == 'hermes' else 'python3'
        result = compose_exec(checkout, service, python_bin, '-c', probe, user=user or '10000:10000')
    status = result.stdout.strip()
    if expect_open:
        assert status == 'OPEN', f'{checkout.name}/{service} could not reach {host}:{port}: {status}'
    else:
        assert status == 'CLOSED' or status.startswith('CLOSED:'), (
            f'{checkout.name}/{service} unexpectedly reached or failed probing {host}:{port}: {status}'
        )


def verify_instance(checkout, project, prefix, webapp_port, other_password):
    wait_webapp_ready(webapp_port)

    # 1. Generated resolv.conf and Tor DNSPort match the instance prefix.
    hermes_resolv = compose_exec(checkout, 'hermes', 'cat', '/etc/resolv.conf', user='10000:10000').stdout
    executor_resolv = compose_exec(checkout, 'executor', 'cat', '/etc/resolv.conf', user='10000:10000').stdout
    assert f'nameserver {prefix}.80.3' in hermes_resolv, hermes_resolv
    assert f'nameserver {prefix}.81.3' in executor_resolv, executor_resolv
    torrc = compose_exec(checkout, 'tor', 'cat', '/tmp/private-hermes-torrc', user='101:102').stdout
    assert f'DNSPort {prefix}.80.3:9053' in torrc, torrc
    assert f'DNSPort {prefix}.81.3:9053' in torrc, torrc

    # 2. SSH execution over the instance's prefix with strict pinned host key.
    ssh = compose_exec(
        checkout, 'hermes', 'ssh', '-F', '/etc/ssh/private-hermes-ssh.conf',
        '-i', '/run/agent-ssh/id_ed25519', '-p', '2222',
        f'runner@{prefix}.82.3', f'printf {project}-ok',
        user='10000:10000',
    )
    assert ssh.stdout.strip() == f'{project}-ok', ssh.stdout

    # 3. Teep reachable from hermes (and its own loopback control), denied from executor.
    verify_tcp(checkout, 'hermes', f'{prefix}.83.3', 8337, expect_open=True)
    verify_tcp(checkout, 'teep', '127.0.0.1', 8337, expect_open=True)
    verify_tcp(checkout, 'executor', f'{prefix}.83.3', 8337, expect_open=False)

    # 4. WebApp login succeeds with this instance's password and rejects the other's.
    password = (checkout / 'config/webapp/password').read_text().strip()
    verify_webapp_login(webapp_port, password, other_password)


def remove_data_dir(data_dir, project):
    if not data_dir.exists():
        return
    try:
        remove_storage_fixture(data_dir, secrets.token_hex(16), image=f'{project}-agent:local')
    except (OSError, subprocess.CalledProcessError):
        shutil.rmtree(data_dir, ignore_errors=True)


def cleanup_instance(checkout, project):
    pinned = {'COMPOSE_PROJECT_NAME': project}
    cmd = [*compose_base(), '-p', project, *compose_files(True), '--profile', '*']
    run_in(checkout, *cmd, 'down', '-v', '--remove-orphans', '--timeout', '5',
           check=False, capture=True, extra_env=pinned)
    run_in(
        checkout, sys.executable, '-c',
        'import sys; sys.path.insert(0, "scripts"); import deployment; '
        'deployment.remove_networks(deployment.maintenance_compose(all_ingress=True))',
        check=False, capture=True, extra_env=pinned,
    )
    remove_data_dir(checkout / 'data', project)
    for suffix in ('agent', 'network', 'executor-false', 'teep', 'x402_treazury', 'webapp-proxy', 'tailscale'):
        subprocess.run(
            [*engine_command(), 'image', 'rm', '-f', f'{project}-{suffix}:local'],
            cwd=ROOT, check=False, capture_output=True,
        )


def main():
    project_a, prefix_a = 'private-hermes-mi-a', '10.205'
    project_b, prefix_b = 'private-hermes-mi-b', '10.206'
    project_c = 'private-hermes-mi-c'
    webapp_a, teep_a, webapp_b, teep_b, port_c1, port_c2, port_c3 = free_ports(7)

    with tempfile.TemporaryDirectory(prefix='private-hermes-multi-') as directory:
        base = Path(directory)
        checkout_a = base / 'instance-a'
        checkout_b = base / 'instance-b'
        checkout_c = base / 'instance-c'
        for checkout in (checkout_a, checkout_b, checkout_c):
            copy_checkout(checkout)

        write_env(checkout_a, project_a, prefix_a, webapp_a, teep_a)

        try:
            print(f'Initializing and starting {project_a} ({prefix_a}) and {project_b} ({prefix_b})...', flush=True)
            run_in(checkout_a, sys.executable, 'scripts/init-config.py')
            run_in(checkout_a, sys.executable, 'scripts/stack.py', 'up')
            # Exercise the documented operator sequence on instance B: run init first
            # (with default .env), then customize .env, then run up.
            run_in(checkout_b, sys.executable, 'scripts/init-config.py')
            write_env(checkout_b, project_b, prefix_b, webapp_b, teep_b)
            run_in(checkout_b, sys.executable, 'scripts/stack.py', 'up')
            assert f'# NETWORK_PREFIX={prefix_b}\n' in (checkout_b / 'config/webapp/proxy.cfg').read_text()
            assert f'nameserver {prefix_b}.80.3\n' in (checkout_b / 'config/network/hermes-resolv.conf').read_text()

            password_a = (checkout_a / 'config/webapp/password').read_text().strip()
            password_b = (checkout_b / 'config/webapp/password').read_text().strip()

            verify_instance(checkout_a, project_a, prefix_a, webapp_a, password_b)
            verify_instance(checkout_b, project_b, prefix_b, webapp_b, password_a)
            print('PASS: both instances started concurrently with independent SSH, Tor DNS, Teep, and WebApp auth', flush=True)

            # Cross-instance forbidden paths: neither hermes, executor, nor tor can reach
            # any listener on the other instance (including published edge and teep-uplink
            # addresses), and teep cannot cross into the other instance's internal networks
            # (or its edge proxy on Podman, where isolate=strict and loopback port forwarding
            # block published bridges too).
            edge_a = service_network_ip(checkout_a, project_a, 'webapp-proxy', 'webapp-publish')
            edge_b = service_network_ip(checkout_b, project_b, 'webapp-proxy', 'webapp-publish')
            teep_uplink_a = service_network_ip(checkout_a, project_a, 'teep', 'teep-uplink')
            teep_uplink_b = service_network_ip(checkout_b, project_b, 'teep', 'teep-uplink')
            assert edge_a.startswith(f'{prefix_a}.90.'), edge_a
            assert edge_b.startswith(f'{prefix_b}.90.'), edge_b
            assert teep_uplink_a.startswith(f'{prefix_a}.89.'), teep_uplink_a
            assert teep_uplink_b.startswith(f'{prefix_b}.89.'), teep_uplink_b
            for src, target_prefix, target_edge_ip, target_webapp_port, target_teep_uplink_ip in (
                (checkout_a, prefix_b, edge_b, webapp_b, teep_uplink_b),
                (checkout_b, prefix_a, edge_a, webapp_a, teep_uplink_a),
            ):
                internal_targets = (
                    (f'{target_prefix}.85.2', 9120),
                    (f'{target_prefix}.82.3', 2222),
                    (f'{target_prefix}.83.3', 8337),
                )
                published_targets = (
                    (target_edge_ip, target_webapp_port),
                    (target_teep_uplink_ip, 8337),
                )
                for service in ('hermes', 'executor'):
                    for host, port in (*published_targets, *internal_targets):
                        verify_tcp(src, service, host, port, expect_open=False)
                for host, port in (*published_targets, *internal_targets):
                    verify_tcp(src, 'tor', host, port, expect_open=False, user='101:102')
                teep_targets = ((target_edge_ip, target_webapp_port), *internal_targets) if engine() == 'podman' else internal_targets
                for host, port in teep_targets:
                    verify_tcp(src, 'teep', host, port, expect_open=False)
            print('PASS: cross-instance bridge, tor, webapp-proxy, executor, and teep paths are blocked', flush=True)

            # Preflight rejects reusing an occupied NETWORK_PREFIX.
            write_env(checkout_c, project_c, prefix_a, port_c1, port_c2)
            conflict_net = run_in(checkout_c, sys.executable, 'scripts/preflight.py', check=False, capture=True)
            assert conflict_net.returncode != 0, 'Expected preflight to reject overlapping NETWORK_PREFIX'
            assert 'NETWORK_PREFIX' in conflict_net.stderr and f'{prefix_a}.' in conflict_net.stderr, conflict_net.stderr

            # Preflight rejects reusing an occupied host WEBAPP_PORT on a free NETWORK_PREFIX.
            write_env(checkout_c, project_c, '10.207', webapp_a, port_c3)
            conflict_port = run_in(checkout_c, sys.executable, 'scripts/preflight.py', check=False, capture=True)
            assert conflict_port.returncode != 0, 'Expected preflight to reject overlapping WEBAPP_PORT'
            assert str(webapp_a) in conflict_port.stderr, conflict_port.stderr

            # Preflight rejects LAN integration grants targeting another running instance's subnet.
            write_env(checkout_c, project_c, '10.207', port_c1, port_c3)
            with (checkout_c / '.env').open('a', encoding='utf-8') as stream:
                stream.write(f'HERMES_INTEGRATIONS_LAN_ENDPOINTS={prefix_a}.85.2:9120\n')
            conflict_lan = run_in(checkout_c, sys.executable, 'scripts/preflight.py', check=False, capture=True)
            assert conflict_lan.returncode != 0, 'Expected preflight to reject cross-instance LAN endpoint'
            assert ('HERMES_INTEGRATIONS_LAN_ENDPOINTS' in conflict_lan.stderr
                    and 'container networks' in conflict_lan.stderr), conflict_lan.stderr

            # Preflight warns about COMPOSE_PROJECT_NAME when reusing an existing project with a new prefix.
            write_env(checkout_c, project_a, '10.207', port_c1, port_c3)
            conflict_project = run_in(checkout_c, sys.executable, 'scripts/preflight.py', check=False, capture=True)
            assert conflict_project.returncode != 0, 'Expected preflight to reject reused project with new prefix'
            assert 'COMPOSE_PROJECT_NAME' in conflict_project.stderr, conflict_project.stderr
            print('PASS: preflight rejects overlapping NETWORK_PREFIX, host ports, cross-instance LAN grants, and reused project names', flush=True)

            # Stopping instance A leaves instance B's containers, volumes, images, and services intact.
            run_in(checkout_a, sys.executable, 'scripts/stack.py', 'down')
            verify_instance(checkout_b, project_b, prefix_b, webapp_b, password_a)
            inspected = subprocess.run(
                [*engine_command(), 'image', 'inspect', f'{project_b}-agent:local'],
                cwd=ROOT, check=False, capture_output=True,
            )
            assert inspected.returncode == 0, 'Instance B image was unexpectedly removed'
            print('PASS: stopping instance A leaves instance B containers, networks, volumes, and images intact', flush=True)

            # Create an offline onion identity on instance A, migrate its NETWORK_PREFIX
            # from 10.205 to 10.207 with onion enabled and an allowed host port, and
            # verify preserved identity, onion routing, host grant isolation, stack chat,
            # and x402_treazury custom-prefix namespace/SOCKS isolation alongside instance B.
            onion_url = run_in(checkout_a, sys.executable, 'scripts/onion_address.py', capture=True).stdout.strip()
            assert onion_url.startswith('http://') and onion_url.endswith('.onion'), onion_url
            onion_host = onion_url.removeprefix('http://')
            migrated_prefix = '10.207'

            class _HostGrantHandler(BaseHTTPRequestHandler):
                def do_GET(self):
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b'host-grant-ok')

                def log_message(self, *_args):
                    pass

            host_server = ThreadingHTTPServer(('0.0.0.0', 0), _HostGrantHandler)
            host_grant_port = host_server.server_port
            threading.Thread(target=host_server.serve_forever, daemon=True).start()
            try:
                write_env(checkout_a, project_a, migrated_prefix, webapp_a, teep_a,
                          onion=True, host_ports=host_grant_port)
                (checkout_a / 'config/network/mcp-allowlist.json').write_text(
                    json.dumps([{'ip': f'{migrated_prefix}.84.10', 'port': 8000}]) + '\n',
                    encoding='utf-8',
                )
                run_in(checkout_a, sys.executable, 'scripts/stack.py', 'up')
                verify_instance(checkout_a, project_a, migrated_prefix, webapp_a, password_b)
                assert (checkout_a / 'config/webapp/password').read_text().strip() == password_a
                torrc_migrated = compose_exec(checkout_a, 'tor', 'cat', '/tmp/private-hermes-torrc', user='101:102').stdout
                assert f'HiddenServicePort 80 {migrated_prefix}.86.3:8080' in torrc_migrated, torrc_migrated
                onion_probe = compose_exec(
                    checkout_a, 'tor', 'python3', '-c',
                    'import urllib.request; '
                    f'req = urllib.request.Request("http://{migrated_prefix}.86.3:8080/login", headers={{"Host": {onion_host!r}}}); '
                    'print(urllib.request.urlopen(req, timeout=10).status)',
                    user='101:102',
                )
                assert onion_probe.stdout.strip() == '200', onion_probe.stdout
                for service in ('hermes', 'executor'):
                    verify_tcp(checkout_a, service, f'{migrated_prefix}.86.3', 8080, expect_open=False)

                # Local-integration host grant works for instance A's hermes on 10.207
                # when the engine permits ip_forward, and fails closed otherwise (such
                # as native Linux Docker with default AppArmor). Always stays blocked
                # for instance A's executor and instance B's hermes.
                warnings = compose_exec(
                    checkout_a, 'tor', 'cat', '/tmp/local-grant-warnings', user='65534:65534',
                ).stdout
                if 'Could not enable IPv4 forwarding' in warnings:
                    verify_tcp(checkout_a, 'hermes', '198.18.255.254', host_grant_port, expect_open=False)
                    print('NOTE: host-grant allowed path skipped (engine denied ip_forward; verified fail-closed)', flush=True)
                else:
                    host_probe = compose_exec(
                        checkout_a, 'hermes', '/opt/hermes/.venv/bin/python', '-c',
                        'import urllib.request; '
                        f'print(urllib.request.urlopen("http://host.docker.internal:{host_grant_port}/", timeout=5).read().decode())',
                        user='10000:10000',
                    )
                    assert host_probe.stdout.strip() == 'host-grant-ok', host_probe.stdout
                verify_tcp(checkout_a, 'executor', '198.18.255.254', host_grant_port, expect_open=False)
                verify_tcp(checkout_b, 'hermes', '198.18.255.254', host_grant_port, expect_open=False)

                chat_help = run_in(checkout_a, sys.executable, 'scripts/stack.py', 'chat', '--help', capture=True)
                assert chat_help.returncode == 0
                chat_env = run_in(
                    checkout_a, sys.executable, 'scripts/stack.py', 'compose',
                    'run', '--rm', '-T', '--no-deps', '--entrypoint', 'sh', 'hermes', '-c',
                    'printf "%s %s" "$NETWORK_PREFIX" "$TERMINAL_SSH_HOST"',
                    capture=True,
                )
                assert chat_env.stdout.strip() == f'{migrated_prefix} {migrated_prefix}.82.3', chat_env.stdout
                creds = run_in(checkout_a, sys.executable, 'scripts/webapp-credentials.py', capture=True)
                assert creds.returncode == 0 and 'credentials for admin' in creds.stdout, creds.stdout
                plugins = run_in(checkout_a, sys.executable, 'scripts/plugins.py', 'list', capture=True)
                assert plugins.returncode == 0, plugins.stderr
                treasury_status = run_in(checkout_a, sys.executable, 'scripts/x402_treazury.py', 'status', capture=True)
                assert treasury_status.returncode == 0
                for checkout, expected_prefix in ((checkout_a, migrated_prefix), (checkout_b, prefix_b)):
                    detected = run_in(
                        checkout, sys.executable, '-c',
                        'import sys; sys.path.insert(0, "scripts"); import x402_treazury; '
                        'print(x402_treazury._running_stack_prefix())',
                        capture=True,
                    ).stdout.strip()
                    assert detected == expected_prefix, f'{checkout.name}: expected {expected_prefix}, got {detected}'
                # Verify x402_treazury-setup shares instance A's custom-prefix agent-net
                # namespace and private Tor SOCKS socket without reaching instance B.
                x402_probe = run_in(
                    checkout_a, sys.executable, 'scripts/stack.py', 'compose',
                    'run', '--rm', '-T', '--no-deps', '--entrypoint', 'python3',
                    'x402_treazury-setup', '-c',
                    'import socket; '
                    's = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); '
                    's.settimeout(5); s.connect("/run/tor-x402_treazury/socks"); s.close(); '
                    't = socket.socket(); t.settimeout(2); '
                    f'rc = t.connect_ex(({prefix_b + ".85.2"!r}, 9120)); t.close(); '
                    'assert rc != 0, f"unexpected cross-instance reach: {rc}"; '
                    'print("X402_OK")',
                    capture=True,
                )
                assert x402_probe.stdout.strip() == 'X402_OK', x402_probe.stdout
                verify_instance(checkout_b, project_b, prefix_b, webapp_b, password_a)
                print('PASS: migrated NETWORK_PREFIX, onion ingress, host grant, chat, and x402_treazury work alongside instance B', flush=True)
            finally:
                host_server.shutdown()
                host_server.server_close()
        finally:
            cleanup_instance(checkout_a, project_a)
            cleanup_instance(checkout_b, project_b)


if __name__ == '__main__':
    main()
