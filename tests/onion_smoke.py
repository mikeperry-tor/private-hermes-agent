#!/usr/bin/env python3
"""Disposable native onion identity, ingress and failure checks on either engine.

Tor networking is disabled: this suite does not publish a hidden service.
"""
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile

import smoke
from deployment import compose_base, engine_command
from settings import Settings, proxy_config
from auth import hash_password

ROOT = Path(__file__).resolve().parents[1]
PROJECT = 'private-hermes-onion-test'
smoke.COMPOSE = smoke.compose_command(
    PROJECT, funnel=True,
    extra=('tests/compose.yaml', 'tests/webapp-compose.yaml', 'tests/onion-compose.yaml'),
)


def run_suite(folder, data):
    # Exercise the actual host target in an isolated source copy; never the
    # operator's data/. Both maintenance jobs use disposable bind overrides.
    checkout = folder / 'checkout'
    for name in ('components', 'scripts'):
        shutil.copytree(ROOT / name, checkout / name, ignore=shutil.ignore_patterns('__pycache__'))
    for name in [p.name for p in ROOT.glob('compose*.yaml')] + ['Makefile', '.env.example']:
        shutil.copy2(ROOT / name, checkout / name)
    (checkout / '.env').write_text((ROOT / '.env.example').read_text())
    target_env = {**os.environ, 'COMPOSE_PROJECT_NAME': PROJECT,
                  'TOR_ONION_ENABLED': 'malformed', 'TAILSCALE_FUNNEL_ENABLED': 'malformed',
                  'TEEP_HOST_PORT': 'invalid', 'WEBAPP_EXTERNAL_CONTENT': 'invalid'}
    project_network_image = f'{PROJECT}-network:local'

    def target(check=True):
        result = subprocess.run([sys.executable, 'scripts/onion_address.py'], cwd=checkout,
                                env=target_env, text=True, capture_output=True)
        if check and result.returncode:
            raise RuntimeError(result.stderr)
        return result

    def state(code):
        return subprocess.check_output([*engine_command(), 'run', '--rm', '--network', 'none',
            '--user', '0:0', '--cap-drop', 'ALL', '--cap-add', 'DAC_OVERRIDE', '--cap-add', 'CHOWN',
            '--entrypoint', 'python3', '-v', f'{data / "tor"}:/var/lib/tor',
            project_network_image, '-c', 'from pathlib import Path; import hashlib,os; '
            'p=Path("/var/lib/tor/onion-service"); ' + code], text=True).strip()

    # A first-run interruption before writing any identity may leave only the
    # native clients directory; it must not be mistaken for an orphaned key.
    state('p.mkdir(mode=0o700); os.chown(p,101,102); (p/"authorized_clients").mkdir(mode=0o700); '
          'os.chown(p/"authorized_clients",101,102)')
    address = target().stdout.strip().removeprefix('http://')
    assert len(address) == 62
    identity = state('print(hashlib.sha256((p/"hs_ed25519_secret_key").read_bytes()).hexdigest())')
    assert target().stdout.strip() == 'http://' + address
    state('(p/"hostname").unlink(); (p/"hs_ed25519_public_key").unlink()')
    assert target().stdout.strip() == 'http://' + address
    assert state('print(hashlib.sha256((p/"hs_ed25519_secret_key").read_bytes()).hexdigest())') == identity
    assert state('print(oct(p.stat().st_mode&0o777),oct((p/"hs_ed25519_secret_key").stat().st_mode&0o777))') == '0o700 0o600'
    state('import shutil; backup=p.with_name("identity-backup"); shutil.copytree(p,backup); '
          'shutil.rmtree(p); shutil.copytree(backup,p); '
          '[os.chown(path,101,102) for path in [p,*p.rglob("*")]]; shutil.rmtree(backup)')
    assert target().stdout.strip() == 'http://' + address
    assert state('print(hashlib.sha256((p/"hs_ed25519_secret_key").read_bytes()).hexdigest())') == identity
    # Native corruption replacement must be blocked, with inputs preserved.
    state('(p/"hs_ed25519_secret_key").rename(p/"saved-secret"); (p/"hostname").rename(p/"saved-hostname"); '
          '(p/"hs_ed25519_secret_key").write_bytes(b"invalid")')
    refused = target(check=False)
    assert refused.returncode and 'invalid native format' in refused.stderr, refused.stderr
    guarded = subprocess.run([*engine_command(), 'run', '--rm', '--network', 'none',
        '--sysctl', 'net.ipv4.ip_forward=0',
        '--cap-drop', 'ALL', '--cap-add', 'DAC_OVERRIDE', '-e', 'TOR_ONION_ENABLED=true',
        '-v', f'{data / "tor"}:/var/lib/tor', '--entrypoint', 'python3',
        project_network_image, '/opt/network.py', 'router'], text=True, capture_output=True)
    assert guarded.returncode and 'invalid native format' in guarded.stderr, guarded.stderr
    state('assert (p/"hs_ed25519_secret_key").read_bytes()==b"invalid"; '
          '(p/"hs_ed25519_secret_key").unlink(); (p/"saved-secret").rename(p/"hs_ed25519_secret_key"); '
          '(p/"saved-hostname").rename(p/"hostname")')
    state('(p/"hs_ed25519_public_key").unlink()')
    assert target().stdout.strip() == 'http://' + address
    assert state('print((p/"hs_ed25519_public_key").exists())') == 'False'
    print('PASS: real host target offline creation/retry, native derived-file recovery, corruption refusal and private modes', flush=True)

    password = secrets.token_urlsafe(32)
    (folder / 'auth.json').write_text(json.dumps({'password_hash': hash_password(password), 'secret': secrets.token_urlsafe(48)}))
    (folder / 'password').write_text(password)
    values = dict(external_content='tor_proxied', onion_enabled='true', funnel_enabled='true',
                  webapp_bind='127.0.0.1', webapp_port='19120', webapp_username='admin',
                  funnel_host='webapp-test.example.ts.net', funnel_port='10000', tailscale_hostname='private-hermes')
    def render(enabled):
        values['onion_enabled'] = str(enabled).lower()
        (folder / 'proxy.cfg').write_text(proxy_config(Settings.read(values),
            loopback_forwarder=smoke.engine() == 'podman', onion_host=address if enabled else ''))
    render(True)
    tls = folder / 'tls'; tls.mkdir()
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                    '-keyout', str(tls / 'key.pem'), '-out', str(tls / 'cert.pem'),
                    '-subj', '/CN=webapp-test.example.ts.net'], check=True, capture_output=True)
    (tls / 'key.pem').chmod(0o644)
    torrc = folder / 'torrc'
    live = '--live' in sys.argv
    torrc.write_text((ROOT / 'components/network/torrc').read_text() + ('' if live else '\nDisableNetwork 1\n'))
    os.environ.update(TOR_ONION_ENABLED='true', TAILSCALE_FUNNEL_ENABLED='true', TS_AUTHKEY='',
                      WEBAPP_PORT='19120', WEBAPP_USERNAME='admin',
                      TAILSCALE_FUNNEL_HOST=values['funnel_host'], TAILSCALE_FUNNEL_PORT='10000',
                      WEBAPP_TEST_CONFIG=str(folder), WEBAPP_TEST_PROXY=str(folder / 'proxy.cfg'),
                      WEBAPP_TEST_TLS=str(tls), ONION_TEST_TORRC=str(torrc))
    try:
        smoke.compose('up', '-d', '--no-build', '--wait', '--wait-timeout', '600')
        from webapp_smoke import wait_ready
        wait_ready()
        assert state('print((p/"hs_ed25519_public_key").is_file())') == 'True'
        # webapp_smoke import selects its own fixture project; restore ours.
        smoke.COMPOSE = smoke.compose_command(
            PROJECT, funnel=True,
            extra=('tests/compose.yaml', 'tests/webapp-compose.yaml', 'tests/onion-compose.yaml'),
        )
        def tor_request(host=address):
            return smoke.execute('tor', 'python3', '-c',
                'import urllib.request; r=urllib.request.urlopen(urllib.request.Request('
                '"http://10.203.86.3:8080/login",headers={"Host":'+repr(host)+'}),timeout=5); print(r.status)', user='101:102', check=False)
        assert tor_request().stdout.strip() == '200'
        assert tor_request(address + ':80').stdout.strip() == '200'
        assert tor_request('a' * 56 + '.onion').returncode
        if live:
            subprocess.run([*engine_command(), 'run', '--rm', '-i', '--network', 'bridge',
                '--user', '101:102', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                '--read-only', '--tmpfs', '/tmp:mode=1777', '--entrypoint', 'python3',
                project_network_image, '-c', (ROOT / 'tests/fixtures/onion-client.py').read_text()],
                input=json.dumps([address, password]), text=True, check=True)
        assert target().stdout.strip() == 'http://' + address
        state('(p/"hostname").rename(p/"saved-hostname")')
        refused = target(check=False)
        assert refused.returncode and 'Stop runtime Tor' in refused.stderr, refused.stderr
        # Missing hostname can put enabled Tor in a restart loop. Its engine
        # restart policy must never race an offline identity writer.
        smoke.compose('restart', 'tor')
        refused = target(check=False)
        assert refused.returncode and 'Stop runtime Tor' in refused.stderr, refused.stderr
        smoke.compose('stop', 'tor')
        refused = target(check=False)
        assert refused.returncode and 'remove its container' in refused.stderr, refused.stderr
        state('(p/"saved-hostname").rename(p/"hostname")')
        smoke.compose('up', '-d', '--no-deps', '--wait', 'tor')
        for service in ('hermes', 'executor'):
            smoke.python(service, '''import socket
from pathlib import Path
assert not Path('/var/lib/tor/onion-service/hs_ed25519_secret_key').exists()
for address in [('10.203.86.3',8080),('10.203.86.2',8080)]:
 try: socket.create_connection(address,timeout=.5)
 except OSError: pass
 else: raise AssertionError(address)
''')
        smoke.python('webapp-proxy', '''import socket
for address in [('10.203.86.2',8080),('10.203.86.2',19080),('1.1.1.1',443),('169.254.169.254',80),('10.203.83.3',8337)]:
 try: socket.create_connection(address,timeout=.5)
 except OSError: pass
 else: raise AssertionError(address)
''')
        smoke.execute('tor', 'python3', '-c', '''import socket
for address in [('10.203.86.3',9120),('10.203.85.2',9120),('10.203.83.3',8337)]:
 try: socket.create_connection(address,timeout=.5)
 except OSError: pass
 else: raise AssertionError(address)
''', user='101:102')
        print('PASS: actual Tor→HAProxy, exact Host, live inspection/writer refusal and forbidden ingress/private paths', flush=True)
        identifier = smoke.compose('ps', '-q', 'tor').stdout.strip()
        subprocess.run([os.environ.get('WEBAPP_BROWSER_PYTHON', sys.executable),
                        str(ROOT / 'tests/onion_browser.py'), identifier, address, str(folder / 'password')], check=True)
        smoke.python('hermes', 'import sqlite3; '
            'db=sqlite3.connect("/opt/data/webapp-image-consent.sqlite3"); '
            'assert db.execute("SELECT browser_origin FROM tor_images WHERE external_origin=?",'
            '("https://public.test",)).fetchall()==[('+repr('http://' + address)+',)]')
        if os.environ.get('TOR_BROWSER_PYTHON'):
            subprocess.run([os.environ['TOR_BROWSER_PYTHON'], str(ROOT / 'tests/onion_tor_browser.py'),
                            identifier, address, str(folder / 'password')], check=True)
        # Reuse the maintained localhost/Funnel checks once while all three
        # frontends coexist, before restart tests interrupt their connections.
        subprocess.run([os.environ.get('WEBAPP_BROWSER_PYTHON', sys.executable),
                        str(ROOT / 'tests/webapp_browser.py'), str(folder / 'password')], check=True)
        for service in ('tor', 'webapp-proxy'):
            smoke.compose('restart', service)
            wait_ready()
            assert tor_request().stdout.strip() == '200'
        smoke.compose('stop', 'tor')
        wait_ready()
        assert target().stdout.strip() == 'http://' + address
        smoke.compose('up', '-d', '--no-deps', '--wait', 'tor')
        assert tor_request().stdout.strip() == '200'
        render(False); os.environ['TOR_ONION_ENABLED'] = 'false'
        smoke.compose('up', '-d', '--no-deps', '--force-recreate', '--wait', 'tor', 'webapp-proxy')
        wait_ready()
        assert tor_request().returncode
        smoke.python('tor', 'from pathlib import Path; assert "HiddenServiceDir" not in Path("/tmp/private-hermes-torrc").read_text()')
        render(True); os.environ['TOR_ONION_ENABLED'] = 'true'
        smoke.compose('up', '-d', '--no-deps', '--force-recreate', '--wait', 'tor', 'webapp-proxy')
        wait_ready()
        assert tor_request().stdout.strip() == '200'
        assert state('print(hashlib.sha256((p/"hs_ed25519_secret_key").read_bytes()).hexdigest())') == identity
        print('PASS: restart, outage, withdrawal and disable/re-enable preserve identity and localhost access', flush=True)
    finally:
        smoke.compose('down', '--volumes', '--remove-orphans')


def main():
    with tempfile.TemporaryDirectory(prefix='private-hermes-onion-') as directory:
        folder = Path(directory)
        os.environ.update(WEBAPP_TEST_CONFIG=str(folder), WEBAPP_TEST_PROXY=str(folder / 'proxy.cfg'),
                          WEBAPP_TEST_TLS=str(folder / 'tls'), ONION_TEST_TORRC=str(folder / 'torrc'))
        with smoke.storage_fixture(folder / 'checkout/data') as data:
            run_suite(folder, data)


if __name__ == '__main__':
    main()
