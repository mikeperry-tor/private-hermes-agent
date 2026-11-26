#!/usr/bin/env python3
"""Offline derived-image qualification; anonymous disposable state, no private mounts."""
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from deployment import engine_command  # noqa: E402
IMAGE = 'private-hermes-agent:local'
PYTHON = '/opt/hermes/.venv/bin/python'


def run(*arguments, check=True):
    return subprocess.run([*engine_command(), *arguments], cwd=ROOT, check=check,
                          text=True, capture_output=True)


def main():
    config = json.loads(run('image', 'inspect', IMAGE, '--format', '{{json .Config}}').stdout)
    assert config['Entrypoint'] == ['/opt/hermes/docker/entrypoint-dispatch.sh']
    assert 'HERMES_WEBAPP_DIST=/opt/hermes/apps/desktop/dist-webapp' in config['Env']
    for mode in ('tor_proxied', 'ask', 'off', 'browser_native'):
        proof = """import os
import hermes_bootstrap
from hermes_cli.private_external_content import deployment_mode
assert deployment_mode() == os.environ['WEBAPP_EXTERNAL_CONTENT']
original = deployment_mode()
# Exercise the actual native dotenv loader, not just an os.environ mutation.
from pathlib import Path
from hermes_cli.env_loader import _load_dotenv_with_fallback
p = Path('/tmp/profile.env'); p.write_text('WEBAPP_EXTERNAL_CONTENT=browser_native\\n')
_load_dotenv_with_fallback(p, override=True)
assert os.environ['WEBAPP_EXTERNAL_CONTENT'] == 'browser_native'
assert deployment_mode() == original
from hermes_cli.web_server import _external_content_mode
assert _external_content_mode == original
"""
        result = run('run', '--rm', '--network', 'none', '-e', f'WEBAPP_EXTERNAL_CONTENT={mode}',
                     '--entrypoint', PYTHON, IMAGE, '-c', proof, check=False)
        if result.returncode:
            raise RuntimeError(result.stderr)
    for env in ([], ['-e', 'WEBAPP_EXTERNAL_CONTENT='], ['-e', 'WEBAPP_EXTERNAL_CONTENT=invalid']):
        result = run('run', '--rm', '--network', 'none', *env, '--entrypoint', PYTHON, IMAGE,
                     '-c', 'from hermes_cli.web_server import app', check=False)
        assert result.returncode != 0 and 'WEBAPP_EXTERNAL_CONTENT must be' in result.stderr, result.stderr
    result = run('run', '--rm', '--network', 'none', '-e', 'HERMES_UID=10000',
                 '-e', 'HERMES_GID=10000', '-e', 'WEBAPP_EXTERNAL_CONTENT=tor_proxied', IMAGE,
                 '--version', check=False)
    if result.returncode:
        raise RuntimeError(result.stderr)
    assert '0.23.4' in result.stdout, result.stdout
    result = run('run', '--rm', '--network', 'none', '-e', 'HERMES_UID=10000',
                 '-e', 'HERMES_GID=10000', '-e', 'WEBAPP_EXTERNAL_CONTENT=tor_proxied', IMAGE,
                 PYTHON, '-c', 'import os; assert os.getuid()==10000 and os.getgid()==10000')
    serving = {
        'WEBAPP_TERMINAL_ENVIRONMENT': 'code',
        'WEBAPP_EXTERNAL_CONTENT': 'tor_proxied',
        'TERMINAL_ENV': 'ssh',
        'HERMES_MANAGED_DIR': '/etc/hermes',
        'TERMINAL_SSH_HOST': '10.203.82.3',
        'TERMINAL_SSH_PORT': '2222',
        'TERMINAL_SSH_USER': 'runner',
        'TERMINAL_SSH_KEY': '/run/agent-ssh/id_ed25519',
    }
    env = [arg for name, value in serving.items() for arg in ('-e', f'{name}={value}')]
    run('run', '--rm', '--network', 'none', '-e', 'HERMES_UID=10000', '-e', 'HERMES_GID=10000',
        *env, IMAGE, PYTHON, '-c', r"""
import os
from pathlib import Path

home = Path('/opt/data')
files = [Path('/etc/hermes/config.yaml'), Path('/etc/hermes/.env')]
assert os.getuid() == 10000
assert all(file.stat().st_uid == 0 and not os.access(file, os.W_OK) for file in files)
assert not os.access(files[0].parent, os.W_OK)
(home / '.env').write_text(
    'HERMES_CONFIG_BACKEND=remote\nTERMINAL_ENV=local\nTERMINAL_SSH_HOST=profile.invalid\n'
    'HERMES_MANAGED_DIR=/tmp/profile-managed\nPYTEST_CURRENT_TEST=profile-override\n')
profile_cwd = home / 'profile workspace'
profile_cwd.mkdir()
(home / 'config.yaml').write_text(
    '{"terminal":{"backend":"local","ssh_host":"profile.invalid","cwd":"/opt/data/profile workspace"},'
    '"webapp":{"terminal_environment":"gateway"},'
    '"context_references":{"fetch_urls":true},"tools":{"disabled":[]}}')
from hermes_cli.env_loader import load_hermes_dotenv
from hermes_cli.config_backend import get_config_backend
from hermes_cli.config import reload_env
from hermes_cli.config_effective import load_user_config_effective
from hermes_cli.managed_scope import load_managed_config, load_managed_env
from hermes_cli.web_host_terminal import resolve_argv
from tools.hosted_tool_policy import tool_refusal

load_hermes_dotenv(hermes_home=home, load_external_secrets=False)
for _ in range(2):
    reload_env()
    assert os.environ['HERMES_MANAGED_DIR'] == '/etc/hermes'
    assert get_config_backend().name == 'file'
    assert os.environ['TERMINAL_ENV'] == 'ssh'
    assert load_managed_env()['TERMINAL_SSH_HOST'] == '10.203.82.3'
    config = load_user_config_effective(home / 'config.yaml')
    assert config['terminal']['backend'] == 'ssh'
    assert config['terminal']['ssh_host'] == '10.203.82.3'
    assert config['terminal']['cwd'] == str(profile_cwd)
    assert resolve_argv(home=home, use_profile_cwd=True)[1] == str(profile_cwd)
    assert config['context_references']['fetch_urls'] is False
    assert config['webapp']['terminal_environment'] == 'executor'
    assert 'browser_exec' in load_managed_config(strict=True)['tools']['disabled']
    assert tool_refusal('browser_exec') and not tool_refusal('terminal')
""")
    # No alternate/unpatched renderer path: native resolver selects our artifact.
    result = run('run', '--rm', '--network', 'none', '--entrypoint', PYTHON, IMAGE, '-c',
                 "from hermes_cli.webapp import packaged_webapp_dist; "
                 "p=packaged_webapp_dist(); assert str(p)=='/opt/hermes/apps/desktop/dist-webapp'; "
                 "assert (p/'index.html').is_file(); assert (p/'hermes-build.json').is_file()")
    # Native output verification also rejects stale inherited chunks left by COPY overlays.
    run('run', '--rm', '--network', 'none', '--entrypoint', 'node', IMAGE,
        '--input-type=module', '-e',
        "import {outputIntact} from '/opt/hermes/scripts/build/freshness.mjs'; "
        "if (!outputIntact('/opt/hermes/apps/desktop/dist-webapp','webapp')) "
        "throw new Error('Delivered renderer differs from its native build receipt')")
    run('run', '--rm', '--network', 'none', '--cap-drop', 'ALL',
        '-e', 'HERMES_HOME=/tmp/approval-probe-test', '--entrypoint', PYTHON, IMAGE, '-c', """
from unittest.mock import patch
from tools import approval

request = dict(pattern_key='image-probe', description='image probe', display_target='fixture',
               autoapprove_log_prefix='image probe', fail_closed_when_no_human=True)
with patch.object(approval, '_yolo_active', return_value=True), \\
     patch.object(approval, '_presence', return_value=(None, False, False, False)):
    assert approval._run_approval_gate(**request)['approved']
    result = approval._run_approval_gate(**request, allow_mode_bypass=False)
    assert result['approved'] is False, result
""")
    run('run', '--rm', '-i', '--network', 'none', '--cap-drop', 'ALL',
        '--entrypoint', PYTHON, IMAGE, '-c',
        (ROOT / 'tests/fixtures/ssh-workspace-files.py').read_text())
    print('PASS: native dispatch/version, selected rebuilt renderer, strict modes and profile-override resistance')


if __name__ == '__main__':
    main()
