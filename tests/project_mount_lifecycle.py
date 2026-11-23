#!/usr/bin/env python3
"""Check project sharing through Make, the authenticated executor, and upgrades."""
import argparse
import io
import json
import os
from pathlib import Path
import shlex
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
from urllib.request import urlopen
import uuid

from project_mount_smoke import (ROOT, SETTING, engine, engine_command,
                                engine_views, prepare_fixture, run, runner_host_uid,
                                two_way_writes)

TARGET = '/mnt/projects/shared project'


def extract_revision(checkout, revision):
    # Only tracked files from a local revision enter the disposable checkout.
    archive = subprocess.check_output(['git', 'archive', revision], cwd=ROOT)
    with tarfile.open(fileobj=io.BytesIO(archive)) as files:
        files.extractall(checkout, filter='data')


def webapp_terminal(origin, password):
    from code_terminal_browser import close_shell, command, metadata, open_shell
    from playwright.sync_api import sync_playwright

    for _ in range(120):
        try:
            with urlopen(origin + '/login', timeout=2) as response:
                if response.status == 200:
                    break
        except OSError:
            time.sleep(1)
    else:
        raise RuntimeError('The disposable project WebApp did not become ready.')
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=['--no-proxy-server'])
        try:
            page = browser.new_page()
            page.goto(origin + '/login')
            page.locator('input[name=username]').fill('admin')
            page.locator('input[name=password]').fill(password.read_text())
            page.locator('button[type=submit]').click()
            page.wait_for_url(lambda url: '/login' not in url)
            open_shell(page, cwd=TARGET, environment='executor', action='start', startup=True)
            meta = metadata(page)
            assert meta['cwd'] == TARGET
            assert 'webapp project' in command(page, "printf 'webapp project\\n' > webapp.txt; cat webapp.txt")
            close_shell(page, meta)
        finally:
            browser.close()


def managed_probe(scratch, backend, variant, prior, browser):
    from smoke import remove_storage_fixture

    checkout, source = scratch / 'deployment', scratch / 'project $host$$'
    checkout.mkdir()
    uid = runner_host_uid(backend)
    prepare_fixture(source, uid)
    current = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    extract_revision(checkout, prior or current)
    project = 'hermes-project-test-' + uuid.uuid4().hex[:10]
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    base = {**os.environ, 'CONTAINER_ENGINE': backend, 'COMPOSE_PROJECT_NAME': project,
            'COMPUTER_USE_ENABLED': 'true' if variant == 'desktop' else 'false',
            'TEEP_ENABLED': 'false', 'TOR_ONION_ENABLED': 'false', 'TAILSCALE_FUNNEL_ENABLED': 'false',
            'WEBAPP_BIND': '127.0.0.1', 'WEBAPP_PORT': str(port), 'WEBAPP_USERNAME': 'admin',
            'WEBAPP_EXTERNAL_CONTENT': 'off', 'WEBAPP_TERMINAL_ENVIRONMENT': 'code',
            'HERMES_INTEGRATIONS_ALLOWED_HOST_PORTS': 'none', 'HERMES_INTEGRATIONS_LAN_ENDPOINTS': 'none',
            SETTING: ''}
    configured = {**base, SETTING: f'{source}:{TARGET}'}
    marker = uuid.uuid4().hex

    def make(target, environment=base):
        run('make', target, cwd=checkout, env=environment)

    def stack(*arguments):
        try:
            return run(sys.executable, 'scripts/stack.py', 'compose', *arguments,
                       cwd=checkout, env=base, capture_output=True).stdout.strip()
        except subprocess.CalledProcessError as error:
            print(error.stdout or '', error.stderr or '', file=sys.stderr, flush=True)
            raise

    def ssh(script):
        key = '/run/agent-ssh'
        command = ['exec', '-T', '--user', '10000:10000', 'hermes', 'ssh',
                   '-i', f'{key}/id_ed25519', '-o', f'UserKnownHostsFile={key}/known_hosts',
                   '-o', 'StrictHostKeyChecking=yes', '-p', '2222', 'runner@10.203.82.3',
                   'sh -eu -c ' + shlex.quote(script)]
        return stack(*command)

    def identities():
        agent = stack('exec', '-T', '--user', '10000:10000', 'hermes',
                      'stat', '-c', '%i %u %g', '/run/agent-ssh/id_ed25519')
        executor = stack('exec', '-T', 'executor', 'stat', '-c', '%i %u %g',
                         '/run/executor-auth/ssh_host_ed25519_key', '/home/runner', '/workspace')
        return agent, executor

    try:
        if prior:
            make('up')
            before = identities()
            ssh("printf preserved > /workspace/prior-work; printf preserved > ~/prior-home")
            make('down')
            extract_revision(checkout, current)
        rejected = {**base, SETTING: f'{checkout}:/mnt/projects/protected'}
        for target in ('up', 'gateway'):
            result = subprocess.run(['make', target], cwd=checkout, env=rejected, text=True, capture_output=True)
            assert result.returncode and 'overlaps a protected' in result.stderr, result.stderr
            assert not stack('ps', '-a', '-q')
        moved = source.rename(source.with_name('missing source'))
        try:
            result = subprocess.run(['make', 'up'], cwd=checkout, env=configured, text=True, capture_output=True)
            assert result.returncode and 'source is missing' in result.stderr and not source.exists()
        finally:
            moved.rename(source)
        make('up', configured)
        executor = stack('ps', '-q', 'executor')

        def restart_policy(container):
            return run(*engine_command(), 'inspect', '--format', '{{.HostConfig.RestartPolicy.Name}}',
                       container, capture_output=True).stdout.strip()

        assert restart_policy(executor) in ('no', 'never')
        config = stack('exec', '-T', '--user', '10000:10000', 'hermes', 'stat',
                       '-c', '%u:%g %a', '/etc/ssh/ssh_config.d/99-private-hermes.conf')
        assert config == '0:0 644', config
        if prior:
            assert before == identities()
            ssh('test "$(cat /workspace/prior-work)" = preserved; test "$(cat ~/prior-home)" = preserved')
        two_way_writes(source, uid, ssh, target=TARGET)

        # These use Hermes's SSH-backed tools, in addition to direct authenticated SSH.
        code = f"""import json
from tools.terminal_tool import terminal_tool
from tools.file_tools import read_file_tool, write_file_tool
root = {TARGET!r}
result = json.loads(terminal_tool("pwd -P; id -u; printf 'agent project' > agent.txt",
                                  workdir=root, task_id='project-mount'))
assert result['exit_code'] == 0 and result['output'].splitlines() == [root, '10000'], result
read = read_file_tool(root + '/host.txt', task_id='project-mount')
assert 'runner atomic' in read, read
blocked = json.loads(write_file_tool(root + '/outside-write-policy.txt', 'guard check', task_id='project-mount'))
assert 'HERMES_WRITE_SAFE_ROOT' in blocked.get('error', ''), blocked
"""
        stack('exec', '-T', '--user', '10000:10000', 'hermes', '/opt/hermes/.venv/bin/python', '-c', code)
        assert (source / 'agent.txt').read_text() == 'agent project'
        assert not (source / 'outside-write-policy.txt').exists()
        ssh('test ! -e /opt/data/config.yaml; test ! -e /run/agent-ssh/id_ed25519; test ! -e /var/lib/x402')
        denied = """import socket
try:
    connection = socket.create_connection(('10.203.82.2', 8642), timeout=3)
except OSError:
    pass
else:
    connection.close()
    raise AssertionError('Executor reached the agent-only MCP endpoint.')
"""
        ssh('python3 -c ' + shlex.quote(denied))
        for container in stack('ps', '-q').splitlines():
            details = json.loads(run(*engine_command(), 'inspect', container, capture_output=True).stdout)[0]
            mounts = {entry['Destination']: entry.get('RW') for entry in details['Mounts']}
            name = details['Config']['Labels']['com.docker.compose.service']
            assert (mounts.get(TARGET) is True if name == 'executor' else TARGET not in mounts), name
        if browser:
            webapp_terminal(f'http://127.0.0.1:{port}', checkout / 'config/webapp/password')
            assert (source / 'webapp.txt').read_text() == 'webapp project\n'
            print(f'PASS: {backend} {variant} Code WebApp wrote to the shared project', flush=True)
        else:
            print('SKIP: Code WebApp terminal (requested --skip-browser).', flush=True)
        # Stop the listener from inside the container so the engine observes
        # a process exit. An explicit engine stop suppresses restart policies.
        signal = 'kill -TERM "$(cat /run/sshd.pid)"'
        result = subprocess.run([*engine_command(), 'exec', executor, 'sh', '-c', signal],
                                text=True, capture_output=True)
        assert result.returncode in (0, 143), result.stderr
        run(*engine_command(), 'wait', executor, timeout=30, capture_output=True)
        assert not stack('ps', '-q', 'executor')
        make('up', configured)
        ssh('test -d ' + shlex.quote(TARGET))

        # Clearing the list goes through managed startup with the old share
        # still active, then restores the base executor's restart policy.
        make('up')
        assert restart_policy(stack('ps', '-q', 'executor')) == 'unless-stopped'
        ssh('test ! -e ' + shlex.quote(TARGET))
        assert (source / 'agent.txt').read_text() == 'agent project'
        print(f'PASS: {backend} {variant} managed project lifecycle', flush=True)
    finally:
        if (checkout / '.env').exists():
            run('make', 'down', cwd=checkout, env=base)
            stack('down', '--volumes')
        storage = checkout / 'data'
        if storage.is_dir():
            (storage / '.test-storage').write_text(marker)
            remove_storage_fixture(storage, marker)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--variant', choices=('lean', 'desktop'), default='lean')
    parser.add_argument('--prior-ref', help='Exercise the in-place upgrade from this local Git revision.')
    parser.add_argument('--skip-browser', action='store_true')
    args = parser.parse_args()
    backend = engine()
    engine_views(backend, Path.home().resolve())
    parent = Path('/private/tmp') if sys.platform == 'darwin' else Path.home()
    with tempfile.TemporaryDirectory(prefix='hermes-managed-share-', dir=parent) as directory:
        managed_probe(Path(directory).resolve(), backend, args.variant, args.prior_ref, not args.skip_browser)


if __name__ == '__main__':
    main()
