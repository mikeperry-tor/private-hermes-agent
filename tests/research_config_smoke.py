#!/usr/bin/env python3
"""Exercise editable policy with the real image, offline and unfunded."""
import json
import os
import re
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from provisioning import initialize_research_config
from deployment import compose_base, engine, engine_command, local_image  # noqa: E402


def docker(*args, check=True):
    return subprocess.run([*engine_command(), *args], check=check, capture_output=True, text=True)


def main():
    identity = 'private-hermes-config-test-' + uuid.uuid4().hex
    image = local_image('x402_treazury')
    with tempfile.TemporaryDirectory(prefix=identity) as folder:
        root = Path(folder)
        initialize_research_config([*compose_base(), '-f', 'compose.yaml'], root)
        directory = root / 'config/x402_treazury'
        path = directory / 'research_desk.toml'
        original = path.read_text()
        docker('volume', 'create', identity)
        try:
            docker('image', 'tag', image, f'{identity}-x402_treazury:local')
            docker('run', '--rm', '--network', 'none', '--user', '0:0',
                   '--mount', f'type=volume,src={identity},dst=/var/lib/x402',
                   '--entrypoint', 'chown', image, '10003:10003', '/var/lib/x402')
            docker('run', '-d', '--name', identity, '--network', 'none', '--read-only',
                   '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
                   '--tmpfs', '/tmp:mode=1777',
                   '--mount', f'type=volume,src={identity},dst=/var/lib/x402',
                   '--mount', f'type=bind,src={directory},dst=/opt/x402/examples/deployments,readonly',
                   '--entrypoint', 'sleep', image, 'infinity')

            def execute(*args, check=True):
                return docker('exec', identity, *args, check=check)

            def inspect():
                return json.loads(execute('python3', '/opt/onboarding.py', 'inspect').stdout)

            def policy():
                return json.loads(execute('x402_treazury', 'config', 'show').stdout)

            def publish(text):
                temporary = directory / 'edited.toml'
                temporary.write_text(text)
                temporary.chmod(0o644)
                temporary.replace(path)

            assert policy()['servers']['web']['wallet'] == 'general'
            denied = execute('python3', '-c', "from pathlib import Path; Path('/opt/x402/examples/deployments/research_desk.toml').write_text('bad')", check=False)
            assert denied.returncode and 'Read-only file system' in denied.stderr
            assert inspect()['wallet_absent']
            # Exercise the actual Compose admin service, not the networked
            # setup service or this fixture container's hand-written mounts.
            override = root / 'admin.json'
            override.write_text(json.dumps({
                'services': {'x402_treazury-admin': {'volumes': [
                    {'type': 'bind', 'source': str(directory),
                     'target': '/opt/x402/examples/deployments', 'read_only': True}]}},
                'volumes': {'x402_treazury-data': {'external': True, 'name': identity}}}))
            command = [*compose_base(), '--env-file', '/dev/null', '-p', identity,
                       '-f', str(ROOT / 'compose.yaml'), '-f', str(override)]

            def admin(action, check=True):
                service = 'x402_treazury-inspect' if action in ('inspect', 'status') else 'x402_treazury-admin'
                return subprocess.run([*command, 'run', '--rm', '-T', '--no-deps',
                                       service, action],
                                      capture_output=True, text=True, check=check)

            assert 'has not been initialized' in admin('status').stdout
            execute('x402_treazury', 'wallet', 'init', '--birthday', '1', '--json')
            addresses = execute('x402_treazury', 'wallet', 'addresses').stdout
            address = json.loads(addresses)['receive_addresses'][0]['encoded_address']
            # Negative control reproduces the original missing-scratch defect
            # against exactly the same wallet, without networking or spending.
            scratch = root / 'read-only-scratch'
            scratch.mkdir(mode=0o755)
            denied = docker('run', '--rm', '--network', 'none', '--read-only',
                            '--mount', f'type=volume,src={identity},dst=/var/lib/x402',
                            '--mount', f'type=bind,src={directory},dst=/opt/x402/examples/deployments,readonly',
                            # Podman supplies writable /tmp even with --read-only.
                            # Force this negative control's scratch read-only on both engines.
                            '--mount', f'type=bind,src={scratch},dst=/tmp,readonly',
                            image, 'wallet', 'addresses', check=False)
            assert denied.returncode and 'Read-only file system' in denied.stderr, denied.stderr
            assert address in admin('status').stdout
            # Invoke the real host controller with disposable Compose state:
            # repeated init must take the offline branch and start no services.
            code = ('import sys; sys.path.insert(0, ' + repr(str(ROOT / 'scripts')) + '); '
                    'from x402_treazury import Controller; Controller(' + repr(command) + ').initialize()')
            for _ in range(2):
                result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, check=True)
                assert 'Wallet already initialized' in result.stdout and address in result.stdout
            running = subprocess.run([*command, 'ps', '-q', '--status', 'running'],
                                     capture_output=True, text=True, check=True)
            assert not running.stdout.strip(), running.stdout
            assert execute('x402_treazury', 'wallet', 'addresses').stdout == addresses
            assert not inspect()['prepared']
            # Controlled completion represents historical preparation only. No
            # bootstrap, warm, serve, funded operations or network run here.
            execute('python3', '-c', "import sys; sys.path.insert(0,'/opt'); import onboarding as o; o.write_record({'schema':1,'treasury_id':o.wallet(),'completed':['bootstrap','catalogs']})")
            assert inspect()['prepared']
            # Saved policies without bootstrap routing remain valid; applying
            # new defaults must not overwrite that operator choice or history.
            ordinary = re.sub(r'(?ms)^\[wallet_bootstrap\]\n.*?(?=^\[)', '', original)
            assert ordinary != original
            publish(ordinary)
            assert policy().get('wallet_bootstrap') is None
            assert inspect()['prepared']
            assert execute('x402_treazury', 'wallet', 'addresses').stdout == addresses
            initialize_research_config([*compose_base(), '-f', 'compose.yaml'], root)
            assert path.read_text() == ordinary
            publish(original)
            assert policy()['wallet_bootstrap']['bootstrap_group'] == 'general'
            assert inspect()['prepared']
            changed = original.replace('wallets.general', 'wallets.research').replace('wallet = "general"', 'wallet = "research"').replace('bootstrap_group = "general"', 'bootstrap_group = "research"')
            publish(changed)
            assert policy()['servers']['web']['wallet'] == 'research'
            assert inspect()['prepared']
            preview = json.loads(execute('x402_treazury', 'wallet', 'preview', '--json').stdout)
            assert 'research' in preview['managed'] and 'general' not in preview['managed']
            # The native rename route is offline and reaches the same store;
            # wallet init creates no saved managed groups, so source is absent.
            rename = execute('x402_treazury', 'wallet', 'rename', 'general', 'research', check=False)
            assert rename.returncode and 'source wallet group does not exist' in rename.stderr.lower(), rename.stderr
            docker('restart', identity)
            assert policy()['servers']['web']['wallet'] == 'research'
            assert inspect()['prepared']
            cases = (
                (changed.replace('socks_endpoint = "unix:/run/tor-x402_treazury/socks"', 'socks_endpoint = "127.0.0.1:9050"'), 'private Tor'),
                (changed.replace('listen = "127.0.0.1:3011"', 'listen = "0.0.0.0:3011"'), 'loopback'),
                (changed.replace('state_dir = "/var/lib/x402/state"', 'state_dir = "/tmp/state"'), 'state/key'),
                (changed.replace('bearer_token_env = "X402_TREAZURY_MCP_TOKEN"', 'bearer_token_env = "OTHER_TOKEN"'), 'loopback'),
            )
            for text, reason in cases:
                publish(text)
                assert inspect()['prepared'] and inspect()['wallet_valid']
                validation = admin('validate', check=False)
                assert validation.returncode and reason in validation.stderr, validation.stderr
                assert address in admin('status').stdout
                refused = admin('prepare', check=False)
                assert refused.returncode and reason in refused.stderr, refused.stderr
                refused = execute('python3', '-c', "import sys; sys.path.insert(0,'/opt'); import onboarding; onboarding.serve()", check=False)
                assert refused.returncode and reason in refused.stderr, refused.stderr
            publish('invalid TOML [')
            assert execute('x402_treazury', 'config', 'show', check=False).returncode
            assert inspect()['prepared'] and address in admin('status').stdout
            path.unlink()
            assert execute('x402_treazury', 'config', 'show', check=False).returncode
            assert inspect()['prepared'] and address in admin('status').stdout
            publish(changed)
            assert inspect()['prepared']
            # A harmless source edit retains the same historical completion.
            execute('python3', '-c', "from pathlib import Path; Path('/tmp/edited-onboarding.py').write_text(Path('/opt/onboarding.py').read_text()+'\\n# unrelated edit\\n')")
            result = execute('python3', '-c', "import sys,runpy; sys.path.insert(0,'/opt'); sys.argv=['onboarding','inspect']; runpy.run_path('/tmp/edited-onboarding.py',run_name='__main__')")
            assert json.loads(result.stdout)['prepared']
            # Exercise the actual Make entrypoints from an isolated public-code
            # copy. Invalid ingress settings and auth must not block inspection.
            for name in ('Makefile', '.env.example', 'compose.yaml', 'compose.executor.yaml',
                         'compose.funnel.yaml', 'compose.podman.yaml', 'compose.podman.funnel.yaml'):
                shutil.copyfile(ROOT / name, root / name)
            shutil.copytree(ROOT / 'scripts', root / 'scripts', ignore=shutil.ignore_patterns('__pycache__'))
            (root / 'components').symlink_to(ROOT / 'components', target_is_directory=True)
            compose_path = root / 'compose.yaml'
            compose_path.write_text(compose_path.read_text().replace(
                'x402_treazury-data: {}', 'x402_treazury-data: {external: true, name: ' + identity + '}'))
            (root / '.env').write_text('WEBAPP_PORT=invalid\nWEBAPP_BIND=invalid\nWEBAPP_EXTERNAL_CONTENT=invalid\nTAILSCALE_FUNNEL_ENABLED=invalid\nTAILSCALE_FUNNEL_HOST=invalid\nTEEP_HOST_PORT=invalid\n')
            auth = root / 'config/webapp/auth.json'
            auth.parent.mkdir(parents=True)
            auth.write_text('invalid auth')
            initialize_research_config([*compose_base(), '-f', 'compose.yaml'], root)
            assert path.read_text() == changed
            # The disposable .env deliberately contains broken policy and no
            # engine selector. Keep children on the engine that owns this wallet,
            # including when the parent's selection came from the real root .env.
            environment = dict(os.environ, CONTAINER_ENGINE=engine(), COMPOSE_PROJECT_NAME=identity)
            seeded = subprocess.run(['make', 'x402_treazury-config'], cwd=root,
                                    env=environment,
                                    capture_output=True, text=True, check=True)
            assert path.read_text() == changed
            assert not (root / 'data').exists()
            # Comparison is offline, textual and read-only even with malformed
            # policy and unrelated invalid deployment settings. Children keep
            # the engine that owns this fixture, including on Podman-only hosts.
            previous_mode = path.stat().st_mode & 0o777
            publish('invalid TOML [')
            compared = subprocess.run(['make', 'x402_treazury-config-diff'], cwd=root, env=environment,
                                      capture_output=True, text=True, check=True)
            assert '--- packaged default (local image)' in compared.stdout
            assert '+invalid TOML [' in compared.stdout
            assert path.read_text() == 'invalid TOML ['
            assert path.stat().st_mode & 0o777 == previous_mode
            assert not (root / 'data').exists()
            publish(changed)
            # Broken unrelated network/storage/config paths must not be mounted
            # or initialized by saved-wallet inspection or repeated init.
            network = root / 'config/network/mcp-allowlist.json'
            network.mkdir(parents=True)
            data = root / 'data'
            data.mkdir()
            (data / 'tailscale').write_text('unrelated wrong-type path')
            (data / 'executor').write_text('unrelated wrong-type path')
            held_policy = root / 'held-research-policy'
            directory.rename(held_policy)
            directory.write_text('unrelated wrong-type config path')
            for target in ('x402_treazury-status', 'x402_treazury-init'):
                result = subprocess.run(['make', target], cwd=root, env=environment,
                                        capture_output=True, text=True, check=True)
                assert address in result.stdout
            compared = subprocess.run(['make', 'x402_treazury-config-diff'], cwd=root, env=environment,
                                      capture_output=True, text=True)
            assert compared.returncode != 0, 'Explicit comparison masked an unreadable policy path'
            meta = ('import sys; sys.path.insert(0,' + repr(str(ROOT / 'scripts')) + '); '
                    'from x402_treazury import Controller; Controller(' + repr(command) + ').admin("activation-failed")')
            subprocess.run([sys.executable, '-c', meta], capture_output=True, text=True, check=True)
            assert inspect()['record']['activation'] == 'activation-failed'
            assert auth.read_text() == 'invalid auth'
            assert not (auth.parent / 'password').exists()
            assert inspect()['prepared']
            running = subprocess.run([*command, 'ps', '-q', '--status', 'running'],
                                     capture_output=True, text=True, check=True)
            assert not running.stdout.strip(), running.stdout
            assert directory.read_text() == 'unrelated wrong-type config path'
            print('PASS: Compose offline status/repeated init preserve wallet identity without starting services; missing-/tmp failure control; policy edits, read-only config, restart, retained completion after source edit/restart, invalid config permits inspection but refuses prepare/serve, actual Make entrypoints ignore unrelated ingress/auth/network/storage/policy paths, preview/rename error path and seed preservation')
        finally:
            docker('rm', '-f', identity, check=False)
            docker('volume', 'rm', identity)
            docker('volume', 'rm', identity + '_hermes-data', check=False)
            docker('image', 'rm', '-f', f'{identity}-x402_treazury:local', check=False)


if __name__ == '__main__':
    main()
