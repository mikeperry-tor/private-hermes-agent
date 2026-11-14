#!/usr/bin/env python3
"""Native readiness/errors in disposable networkless containers; no wallet or paid calls."""
import json
import signal
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from deployment import compose_base  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def main():
    project = 'private-hermes-endpoints-' + uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix=project) as directory:
        root = Path(directory)
        flags = root / 'flags'
        flags.mkdir(mode=0o755)
        (flags / 'gate').touch()
        # Only disposable MCP auth is shared; no treasury keys/state are mounted.
        token = 'unfunded-endpoint-fixture-' + uuid.uuid4().hex
        (root / 'token').write_text(token)
        (root / 'hermes.env').write_text('X402_TREAZURY_MCP_TOKEN=' + token + '\n')
        common = {'cap_drop': ['ALL'], 'security_opt': ['no-new-privileges:true'],
                  'read_only': True, 'tmpfs': ['/tmp:mode=1777'], 'working_dir': '/tmp',
                  'init': True, 'stop_grace_period': '-1s'}
        model = {'services': {
            'x402_treazury': {**common, 'image': 'private-hermes-x402_treazury:local',
                'network_mode': 'none', 'entrypoint': ['python3', '/opt/native-fixture.py'],
                'environment': {'RESEARCH_TEST_FLAGS': '/run/test-flags'},
                'volumes': [f'{ROOT}/tests/fixtures/x402_treazury.py:/opt/native-fixture.py:ro',
                            f'{root}/token:/run/x402_treazury-auth/token:ro', f'{flags}:/run/test-flags:ro']},
            'hermes': {**common, 'image': 'private-hermes-agent:local', 'user': '10000:10000',
                'network_mode': 'service:x402_treazury', 'entrypoint': ['sleep', 'infinity'],
                'environment': {'HERMES_HOME': '/tmp/profile', 'HOME': '/tmp'},
                'volumes': [f'{root}/hermes.env:/tmp/profile/.env:ro']}}}
        config = root / 'compose.json'
        config.write_text(json.dumps(model))
        command = [*compose_base(), '--env-file', '/dev/null', '-p', project, '-f', str(config)]

        def compose(*args):
            result = subprocess.run([*command, *args], text=True, capture_output=True)
            if result.returncode:
                logs = subprocess.run([*command, 'logs', '--tail', '30', 'x402_treazury'],
                                      text=True, capture_output=True)
                raise RuntimeError('Fixture Compose ' + args[0] + ' failed: ' + result.stderr + logs.stdout)
            return result

        code = ('import sys; sys.path.insert(0,' + repr(str(ROOT / 'scripts')) + '); '
                'from x402_treazury import Controller; '
                'Controller(' + repr(command) + ').wait_for_endpoints(); print("ENDPOINTS_READY",flush=True)')
        child = None
        try:
            compose('config', '--quiet')
            compose('up', '-d')
            identifier = compose('ps', '-q', 'x402_treazury').stdout.strip()
            def waiting():
                process = subprocess.Popen([sys.executable, '-c', code], stdout=subprocess.PIPE,
                                           stderr=subprocess.STDOUT, text=True)
                seen = ''
                while 'Waiting for all twelve' not in seen or 'Fixture waiting for start release.' not in seen:
                    line = process.stdout.readline()
                    assert line, seen
                    seen += line
                return process, seen
            child, seen = waiting()
            # Observe the actual remote probe before cancelling its controller.
            # There is no response from the placeholder listener until release.
            while '--watch-stdin' not in compose('exec', '-T', 'hermes', 'ps', '-eo', 'args').stdout:
                assert child.poll() is None
            child.send_signal(signal.SIGINT)
            output, _ = child.communicate(timeout=120)
            assert child.returncode != 0
            assert '--watch-stdin' not in compose('exec', '-T', 'hermes', 'ps', '-eo', 'args').stdout
            assert compose('ps', '-q', 'x402_treazury').stdout.strip() == identifier
            print('PASS: cancellation during an outstanding HTTP probe cleans up remote work without stopping the serving container')
            child, seen = waiting()
            (flags / 'gate').unlink()
            compose('exec', '-T', 'x402_treazury', 'python3', '-c',
                    "with open('/tmp/research-start-gate','w') as gate: gate.write('start')")
            output, _ = child.communicate(timeout=120)  # fixture watchdog, not runtime policy
            assert child.returncode == 0 and 'ENDPOINTS_READY' in output, seen + output
            print('PASS: delayed native startup remains pending, then all twelve authenticated endpoints become ready')

            (flags / 'broken').write_text('web')
            compose('stop', 'hermes')
            compose('restart', '--no-deps', 'x402_treazury')
            compose('up', '-d', '--no-deps', '--force-recreate', 'hermes')
            result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=120)
            assert result.returncode and 'catalog startup failed' in result.stderr, result.stderr
            assert 'unavailable endpoint functionality' in result.stderr, result.stderr
            assert compose('ps', '-q', 'x402_treazury').stdout.strip() == identifier
            # A live peer proves this is a native endpoint failure, not process exit.
            peer = '''import asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client,create_mcp_http_client
async def check():
 async with create_mcp_http_client(headers={'Authorization':'Bearer '+TOKEN}) as client:
  async with streamable_http_client('http://127.0.0.1:3010/mcp',http_client=client) as (read,write,*_):
   async with ClientSession(read,write) as session:
    await session.initialize()
    assert (await session.list_tools()).tools
asyncio.run(check())
'''
            compose('exec', '-T', 'hermes', '/opt/hermes/.venv/bin/python', '-c',
                    'TOKEN=' + repr(token) + '\n' + peer)
            assert '--watch-stdin' not in compose('exec', '-T', 'hermes', 'ps', '-eo', 'args').stdout
            print('PASS: exact native endpoint error fails activation while the process and a healthy peer remain available')

            (flags / 'broken').unlink()
            compose('stop', 'hermes')
            compose('restart', '--no-deps', 'x402_treazury')
            compose('up', '-d', '--no-deps', '--force-recreate', 'hermes')
            result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=120)
            assert result.returncode == 0 and 'ENDPOINTS_READY' in result.stdout, result.stderr
            assert compose('ps', '-q', 'x402_treazury').stdout.strip() == identifier
            assert 'catalog startup failed' not in result.stderr
            # No remote read-only probe remains after success or native failure.
            processes = compose('exec', '-T', 'hermes', 'ps', '-eo', 'args').stdout
            assert '--watch-stdin' not in processes, processes
            print('PASS: corrected restart ignores prior-lifetime endpoint errors; remote probe processes are cleaned up')

            (flags / 'empty').touch()
            compose('stop', 'hermes')
            compose('restart', '--no-deps', 'x402_treazury')
            compose('up', '-d', '--no-deps', '--force-recreate', 'hermes')
            result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=120)
            assert result.returncode == 0 and 'ENDPOINTS_READY' in result.stdout, result.stderr
            empty_peer = peer.replace('127.0.0.1:3010', '127.0.0.1:3011').replace(
                'assert (await session.list_tools()).tools', 'assert not (await session.list_tools()).tools')
            compose('exec', '-T', 'hermes', '/opt/hermes/.venv/bin/python', '-c',
                    'TOKEN=' + repr(token) + '\n' + empty_peer)
            assert 'ERROR' in result.stderr, result.stderr
            print('PASS: reduced coverage ERROR diagnostics and an empty endpoint do not block authenticated activation')
        finally:
            if child and child.poll() is None:
                child.communicate(timeout=120)
            compose('down', '--remove-orphans')


if __name__ == '__main__':
    main()
