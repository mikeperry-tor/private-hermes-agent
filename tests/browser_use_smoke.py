#!/usr/bin/env python3
"""Disposable browser-harness qualification using the existing SSH/network fixture."""
import os
import json
from pathlib import Path
import tempfile
import sys
import smoke


def agent_python(code, check=True):
    return smoke.execute('hermes', '/opt/hermes/.venv/bin/python', '-c', code,
                         user='10000:10000', check=check)


def check():
    result = agent_python(Path('tests/fixtures/browser-use.py').read_text(), check=False)
    print(result.stdout, result.stderr, flush=True)
    if result.returncode:
        raise RuntimeError('Executor browser qualification failed')
    check_sandbox()
    check_tabs()


def check_tabs():
    result = agent_python(Path('tests/fixtures/browser-tabs.py').read_text(), check=False)
    print(result.stdout, result.stderr, flush=True)
    if result.returncode:
        raise RuntimeError('Named browser tab regression failed')


def check_sandbox():
    result = agent_python('''import json,re
from tools.browser_use_cli import browser_exec
r=json.loads(browser_exec('new_tab("chrome://sandbox"); wait_for_load(); print(js("document.body.innerText"))',session='sandbox-diagnostics'))
assert r.get('success'),r
text=r['output']
assert re.search(r'Layer 1 Sandbox\\s+Namespace',text),text
for layer in ('PID namespaces','Network namespaces','Seccomp-BPF sandbox'):
 assert re.search(re.escape(layer)+r'\\s+Yes',text),text
print('PASS: actual automation Chromium reports namespace, PID/network namespaces and seccomp sandbox layers')
''', check=False)
    print(result.stdout, result.stderr, flush=True)
    if result.returncode:
        raise RuntimeError('Automation Chromium sandbox qualification failed')


def missing_harness():
    # Hide only the image-built harness, retaining real SSH and GUI dependencies.
    # The override and mount belong exclusively to this disposable test project.
    original = smoke.COMPOSE
    with tempfile.TemporaryDirectory(prefix='private-hermes-missing-harness-') as folder:
        root = Path(folder)
        (root / 'empty').mkdir()
        override = root / 'compose.json'
        override.write_text(json.dumps({'services': {'executor': {'volumes': [
            {'type': 'bind', 'source': str(root / 'empty'), 'target': '/opt/browser-harness', 'read_only': True}
        ]}}}))
        try:
            smoke.COMPOSE = [*original, '-f', str(override)]
            smoke.compose('up', '-d', '--wait', '--no-deps', '--force-recreate', 'executor')
            agent_python('''import json
from pathlib import Path
from hermes_cli.private_computer_use import available
from tools.browser_use_cli import browser_exec_available,browser_exec
assert available(), 'desktop/SSH should remain available'
assert not browser_exec_available()
r=json.loads(browser_exec('from pathlib import Path; Path("/tmp/browser-missing-harness-canary").touch()'))
assert r.get('error'),r
assert not Path('/tmp/browser-missing-harness-canary').exists()
''')
        finally:
            smoke.COMPOSE = original
            smoke.compose('up', '-d', '--wait', '--no-deps', '--force-recreate', 'executor')
        agent_python('''import json
from tools.browser_use_cli import browser_exec_available,browser_exec
assert browser_exec_available()
r=json.loads(browser_exec('print("harness-recovered")'))
assert r.get('output','').strip()=='harness-recovered',r
''')
    print('PASS: actual missing harness refuses availability/execution without gateway fallback; restoring executor recovers', flush=True)


if __name__ == '__main__':
    os.environ['COMPUTER_USE_ENABLED'] = 'true'
    with smoke.storage_fixture():
        try:
            smoke.start_stack()
            if '--tabs-only' in sys.argv:
                check_tabs()
            else:
                check()
                missing_harness()
        finally:
            smoke.compose('down', '--volumes', '--remove-orphans', check=False)
