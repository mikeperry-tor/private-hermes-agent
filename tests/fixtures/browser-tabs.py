"""Named tabs must be distinct before model code explicitly opens any tab."""
import json

from tools import browser_use_executor as remote
from tools import browser_use_cli as browser
from tools.bot_desktop import placement, runtime
from tools.environments import streams


def run(code, session):
    result = json.loads(browser.browser_exec(code, session=session, task_id='tab-regression'))
    assert result.get('success'), result
    return result['output'].strip()


assert browser.browser_exec_available()
assert runtime.start().running
try:
    first = run('import sys; assert __name__ == "__main__"; '
                'assert vars(sys.modules["__main__"]) is globals(); '
                'print(current_tab()["targetId"])', 'tab-first')
    second = run('print(current_tab()["targetId"])', 'tab-second')
    assert first != second, (first, second)
    assert run('print(current_tab()["targetId"])', 'tab-first') == first
    # An intentional switch remains selected on subsequent calls.
    switched = run('target = cdp("Target.createTarget", url="about:blank")["targetId"]; '
                   'switch_tab(target); print(current_tab()["targetId"])', 'tab-first')
    assert switched != first
    assert run('print(current_tab()["targetId"])', 'tab-first') == switched
    # Killing just the native daemon must repin before the next model call.
    raw = run('from browser_harness import _ipc,admin; print(_ipc.pid_path(admin.NAME).read_text())', 'tab-first')
    pid = json.loads(raw)['pid'] if raw.startswith('{') else int(raw)
    env = placement.terminal_environment()
    assert streams.run_in(env, ['kill', '-KILL', str(pid)]).returncode == 0
    recovered = run('print(current_tab()["targetId"])', 'tab-first')
    assert recovered not in (first, second, switched)
    assert run('print(current_tab()["targetId"])', 'tab-first') == recovered
    def scratch(task, code):
        result = json.loads(browser.browser_exec(code, session='scratch-shared-tab', task_id=task))
        assert result['success'], result
        return result['workspace'], result['output'].strip()

    first_space, tab = scratch('task-one', 'from pathlib import Path; Path("canary").touch(); print(current_tab()["targetId"])')
    second_space, same_tab = scratch('task-two', 'from pathlib import Path; assert not Path("canary").exists(); print(current_tab()["targetId"])')
    returned_space, _ = scratch('task-one', 'from pathlib import Path; assert Path("canary").is_file()')
    assert first_space == returned_space != second_space and tab == same_tab
    setup = browser._OWN_TAB_PREAMBLE
    try:
        browser._OWN_TAB_PREAMBLE = 'cdp = lambda *args, **kwargs: {}\n' + setup
        failure = json.loads(browser.browser_exec('raise AssertionError("model code ran")',
                                                 session='tab-failed-setup', task_id='tab-regression'))
        assert 'Could not create' in failure.get('stderr', ''), failure
        assert 'model code ran' not in failure.get('stderr', ''), failure
    finally:
        browser._OWN_TAB_PREAMBLE = setup
    assert run('print(current_tab()["targetId"])', 'tab-failed-setup')
    failure = json.loads(browser.browser_exec('# one\n# two\nraise RuntimeError("tab-trace")',
                                             session='tab-first', task_id='tab-regression'))
    assert failure['exit_code'] != 0 and 'line 3' in failure['stderr'], failure
    # A detached child keeps the CLI's output pipes open. A timeout must still
    # report outcome-unknown and clean the owner before a successor can run.
    import uuid
    stop = '/tmp/browser-pipe-stop-' + uuid.uuid4().hex
    descendant = (f'import pathlib,threading; stop=pathlib.Path({stop!r}); event=threading.Event()\n'
                  'while not stop.exists(): event.wait(0.01)')
    code = ('import subprocess,sys,threading\n'
            f'subprocess.Popen([sys.executable,"-c",{descendant!r}],start_new_session=True)\n'
            'threading.Event().wait()')
    try:
        interrupted = json.loads(browser.browser_exec(code, session='pipe-timeout',
            task_id='tab-regression', timeout_s=5))
        assert 'Do not replay automatically' in interrupted.get('error', ''), interrupted
    finally:
        assert streams.run_in(env, ['touch', stop]).returncode == 0
    assert run('print("after-pipe-timeout")', 'pipe-timeout') == 'after-pipe-timeout'
finally:
    remote.close()
    runtime.stop()
print('PASS: distinct initial named tabs, retained selection, daemon restart repinning and model traceback lines')
