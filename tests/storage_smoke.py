#!/usr/bin/env python3
"""Qualify native database storage and persistence through ordinary Compose down."""
import json
import secrets
import subprocess
import tempfile
from pathlib import Path
import smoke


smoke.COMPOSE = ['docker', 'compose', '-p', 'private-hermes-storage-test',
                 *smoke.compose_files(False, extra=('tests/compose.yaml',))]


def main():
    marker = secrets.token_hex(16)
    targets = [('setup', '/opt/hermes/.venv/bin/python', '/opt/data'),
               ('x402_treazury-admin', 'python3', '/var/lib/x402')]
    with smoke.storage_fixture() as bind_root:
        try:
            # The stock image normally puts this user-writable directory on
            # PATH. Root setup must use its own trusted tool search path.
            smoke.compose('run', '--rm', '-T', '--no-deps', '--entrypoint',
                          '/opt/hermes/.venv/bin/python', 'setup', '-c',
                          "from pathlib import Path; p=Path('/opt/data/.local/bin/ssh-keygen'); p.parent.mkdir(parents=True); p.write_text('#!/bin/sh\\nexit 99\\n'); p.chmod(0o755)")
            smoke.compose('run', '--rm', '-T', '--no-deps', '--entrypoint',
                          '/opt/hermes/.venv/bin/python', 'setup', '-c', """
import sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,'/opt/private-hermes/provisioning')
import setup
sys.argv=['setup','init']
with patch('private_files.os.link', side_effect=OSError('injected interrupted publication')):
 try: setup.main()
 except OSError: pass
 else: raise AssertionError('Expected interrupted default publication')
assert not Path('/opt/data/config.yaml').exists()
assert not list(Path('/opt/data').glob('tmp*'))
""")
            smoke.initialize_setup(smoke.COMPOSE)
            print('PASS: interrupted initial Hermes default publication leaves no final file; real setup safely retries', flush=True)
            smoke.compose('run', '--rm', '-T', '--no-deps', 'hermes-config',
                          'set', 'model.default', 'setup-qualification-model')
            for job, interpreter, uid, forbidden in (
                    ('hermes-config', '/opt/hermes/.venv/bin/python', 10000,
                     ['/var/lib/x402/state', '/persistent-data', '/run/webapp/auth.json']),
                    ('x402_treazury-inspect', 'python3', 10003,
                     ['/opt/data', '/persistent-data', '/run/webapp/auth.json'])):
                smoke.compose('run', '--rm', '-T', '--no-deps', '--entrypoint', interpreter, job, '-c',
                              "import os,socket; from pathlib import Path; "
                              f"assert os.getuid()=={uid}; "
                              "assert len(Path('/proc/net/route').read_text().splitlines())==1; "
                              "assert all(l.split()[-1]=='lo' for l in Path('/proc/net/if_inet6').read_text().splitlines()); "
                              f"assert not any(Path(p).exists() for p in {forbidden!r}); "
                              "assert int(next(l.split()[1] for l in Path('/proc/self/status').read_text().splitlines() if l.startswith('CapEff:')),16)==0; "
                              "s=socket.socket(); s.settimeout(.5); assert s.connect_ex(('10.203.83.3',8337))!=0; s.close()")
            print('PASS: maintenance jobs use unprivileged identities, zero effective capabilities, no unrelated private mounts or internal network access', flush=True)
            snapshot = """import hashlib,json
from pathlib import Path
import hermes_yaml as yaml
root=Path('/persistent-data')
config=Path('/opt/data/config.yaml')
assert config.stat().st_uid==10000
assert yaml.safe_load(config.read_text())['model']['default']=='setup-qualification-model'
assert not Path('/var/lib/x402/state').exists()
print(json.dumps({name:hashlib.sha256((' '.join((root/name).read_text().split()[:2]).encode() if name.endswith('.pub') else (root/name).read_bytes())).hexdigest() for name in
 ('ssh/agent/id_ed25519.pub','ssh/executor/ssh_host_ed25519_key.pub',
  'ssh/agent/id_ed25519','ssh/executor/ssh_host_ed25519_key')}))
"""
            def identities():
                return smoke.compose('run', '--rm', '-T', '--no-deps', '--entrypoint',
                                     '/opt/hermes/.venv/bin/python', 'setup', '-c', snapshot).stdout
            original_identities = identities()
            smoke.compose('run', '--rm', '-T', '--no-deps', '--entrypoint',
                          '/opt/hermes/.venv/bin/python', 'setup', '-c',
                          "from pathlib import Path; root=Path('/persistent-data'); (root/'ssh/agent/id_ed25519.pub').write_bytes(b''); (root/'ssh/executor/ssh_host_ed25519_key.pub').write_bytes(b'ssh-ed25519 partial')")
            smoke.initialize_setup(smoke.COMPOSE)
            assert identities() == original_identities
            print('PASS: real setup reconstructs incomplete SSH public sidecars without replacing private identities', flush=True)
            # An already initialized profile may predate the picker catalog.
            smoke.compose('run', '--rm', '-T', '--no-deps', '--entrypoint',
                          '/opt/hermes/.venv/bin/python', 'setup', '-c',
                          "from pathlib import Path; import hermes_yaml as yaml; p=Path('/opt/data/config.yaml'); c=yaml.safe_load(p.read_text()); c.pop('providers'); p.write_text(yaml.safe_dump(c))")
            smoke.initialize_setup(smoke.COMPOSE)
            assert identities() == original_identities
            # An arbitrary Teep model is accepted; setup, not host make init,
            # applies the root preference to the persistent native profile.
            preferred = 'neardirect:qualification/arbitrary-model'
            smoke.compose('run', '--rm', '-T', '--no-deps', '-e',
                          'HERMES_DEFAULT_MODEL=' + preferred, 'setup', 'init')
            smoke.compose('run', '--rm', '-T', '--no-deps', '--entrypoint',
                          '/opt/hermes/.venv/bin/python', 'setup', '-c', """
from pathlib import Path
from unittest.mock import patch
import hermes_yaml as yaml
from hermes_cli.model_switch_providers import _PickerBuild, _lap_user_provider_rows
config = yaml.safe_load(Path('/opt/data/config.yaml').read_text())
assert config['model']['default'] == 'neardirect:qualification/arbitrary-model'
expected = set(yaml.safe_load(Path('/opt/private-hermes/hermes/config.example.yaml').read_text())['providers']['custom']['models'])
expected.add(config['model']['default'])
picker = _PickerBuild(current_provider='custom', current_base_url=config['model']['base_url'],
                      current_model=config['model']['default'], max_models=None,
                      for_picker=True, force_fresh_nous_tier=False, probe_custom_providers=True,
                      probe_current_custom_provider=True, refresh=False, excluded=set(), curated={})
with patch('hermes_cli.models.fetch_api_models', side_effect=AssertionError('Unexpected discovery')):
    _lap_user_provider_rows(picker, config['providers'])
row, = picker.results
assert row['slug'] == 'custom' and row['is_current']
assert set(row['models']) == expected
assert row['api_url'] == 'http://10.203.83.3:8337/v1'
""")
            smoke.initialize_setup(smoke.COMPOSE)
            smoke.compose('run', '--rm', '-T', '--no-deps', '--entrypoint',
                          '/opt/hermes/.venv/bin/python', 'setup', '-c',
                          "from pathlib import Path; import hermes_yaml as yaml; assert yaml.safe_load(Path('/opt/data/config.yaml').read_text())['model']['default']=='neardirect:qualification/arbitrary-model'")
            smoke.compose('run', '--rm', '-T', '--no-deps', 'hermes-config',
                          'set', 'model.default', 'setup-qualification-model')
            assert identities() == original_identities
            print('PASS: root model preference and native Teep picker accept additional model IDs without changing the inference route', flush=True)
            smoke.compose('run', '--rm', '-T', '--no-deps', 'hermes-config',
                          'set', 'terminal.backend', 'local')
            try:
                smoke.initialize_setup(smoke.COMPOSE)
            except RuntimeError as error:
                assert 'Offline setup failed' in str(error)
            else:
                raise AssertionError('Incompatible execution configuration permitted startup')
            status = smoke.compose('run', '--rm', '-T', '--no-deps', 'x402_treazury-inspect', 'status')
            assert 'has not been initialized' in status.stdout
            smoke.compose('run', '--rm', '-T', '--no-deps', 'hermes-config',
                          'set', 'terminal.backend', 'ssh')
            smoke.initialize_setup(smoke.COMPOSE)
            assert identities() == original_identities
            print('PASS: failed setup blocks startup; independent wallet inspection and offline config repair remain available', flush=True)
            # Maintenance must reuse successful setup, without rerunning init
            # and disconnecting a live research configuration.
            smoke.compose('run', '--rm', '-T', '--no-deps', 'mcp-config', 'connect')
            smoke.compose('run', '--rm', '-T', '--no-deps', 'x402_treazury-inspect', 'status')
            smoke.compose('run', '--rm', '-T', '--no-deps', '--entrypoint',
                          '/opt/hermes/.venv/bin/python', 'setup', '-c',
                          "import hermes_yaml as yaml; from pathlib import Path; c=yaml.safe_load(Path('/opt/data/config.yaml').read_text()); assert len([n for n in c['mcp_servers'] if n.startswith('x402_treazury_')])==12")
            from x402_treazury import Controller
            with tempfile.TemporaryDirectory(prefix='private-hermes-mcp-maintenance-') as folder:
                override = Path(folder) / 'bad-webapp.json'
                override.write_text(json.dumps({'services': {'setup': {'volumes': [
                    {'type': 'bind', 'source': str(Path(folder) / 'absent-webapp'),
                     'target': '/run/webapp', 'read_only': True, 'bind': {'create_host_path': False}}]}}}))
                controller = Controller([*smoke.COMPOSE, '-f', str(override)])
                controller.call('run', '--rm', '-T', '--no-deps', 'setup-storage', capture_output=True)
                controller.configure('connect')
                held = bind_root.with_name(bind_root.name + '-held')
                bind_root.rename(held)
                try:
                    assert controller.configure('disconnect')
                finally:
                    held.rename(bind_root)
                controller.configure('connect')
            print('PASS: root MCP publication needs no webapp/wallet mount; UID10000 disconnect publishes profile changes without any bind-data/auth path', flush=True)
            print('PASS: repeated offline setup preserves SSH identities and native CLI settings; wallet stays absent; maintenance reuses completed setup', flush=True)
            for service, interpreter, root in targets:
                script = """import sqlite3, sys
from pathlib import Path
root=Path(sys.argv[1]); marker=sys.argv[2]
with sqlite3.connect(root/'persistence-test.sqlite') as db:
 db.execute('PRAGMA journal_mode=WAL')
 db.execute('CREATE TABLE proof(value)')
 db.execute('INSERT INTO proof VALUES(?)',(marker,))
 db.commit()
(root/'persistence-test.txt').write_text(marker)
"""
                smoke.compose('run', '--rm', '-T', '--no-deps', '--user', '10000:10000' if service=='setup' else '10003:10003', '--entrypoint', interpreter,
                              service, '-c', script, root, marker)
            smoke.compose('down', '--timeout', '-1')
            for name in ('hermes-data', 'x402_treazury-data'):
                result = subprocess.run(['docker', 'volume', 'inspect',
                                         'private-hermes-storage-test_' + name],
                                        text=True, capture_output=True, check=True)
                assert json.loads(result.stdout)[0]['Labels']['com.docker.compose.project'] == 'private-hermes-storage-test'
            # Recreating the initializer and application containers must reuse
            # the same data; initialization must preserve existing files.
            smoke.initialize_setup(smoke.COMPOSE)
            for service, interpreter, root in targets:
                script = """import sqlite3, sys
from pathlib import Path
root=Path(sys.argv[1]); marker=sys.argv[2]
assert (root/'persistence-test.txt').read_text()==marker
with sqlite3.connect(root/'persistence-test.sqlite') as db:
 assert db.execute('SELECT value FROM proof').fetchall()==[(marker,)]
"""
                smoke.compose('run', '--rm', '-T', '--no-deps', '--entrypoint', interpreter,
                              service, '-c', script, root, marker)
            print('PASS: native volume locks enforced; files and SQLite data survive Compose down and container recreation', flush=True)
        except subprocess.CalledProcessError as error:
            print(error.stderr or '', flush=True)
            print(smoke.compose('logs', '--tail', '30', 'setup', check=False).stdout, flush=True)
            raise
        finally:
            # Only this disposable test project is deliberately erased.
            smoke.compose('down', '--volumes', '--remove-orphans')


if __name__ == '__main__':
    main()
