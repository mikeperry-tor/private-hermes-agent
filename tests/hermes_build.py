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
    assert '0.23.2' in result.stdout, result.stdout
    result = run('run', '--rm', '--network', 'none', '-e', 'HERMES_UID=10000',
                 '-e', 'HERMES_GID=10000', '-e', 'WEBAPP_EXTERNAL_CONTENT=tor_proxied', IMAGE,
                 PYTHON, '-c', 'import os; assert os.getuid()==10000 and os.getgid()==10000')
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
        '-e', 'WEBAPP_EXTERNAL_CONTENT=tor_proxied', '-e', 'COMPUTER_USE_ENABLED=true',
        '-e', 'HERMES_HOME=/tmp/desktop-probe-test', '--entrypoint', PYTHON, IMAGE,
        '-c', (ROOT / 'tests/fixtures/desktop-dependency-probe.py').read_text())
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
