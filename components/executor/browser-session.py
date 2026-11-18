"""One SSH-owned browser-harness session; model programs never run in this process."""
import json
import os
from pathlib import Path
import queue
import re
import signal
import subprocess
import sys
import threading
import time


def main():
    # Called through env -i, before importing the harness (which reads workspace .env).
    for key in ('BH_HOME', 'BH_RUNTIME_DIR', 'BH_TMP_DIR', 'BH_AGENT_WORKSPACE', 'BH_DOWNLOAD_DIR'):
        Path(os.environ[key]).mkdir(mode=0o700, parents=True, exist_ok=True)
    from browser_harness import admin
    requests = queue.Queue()
    closed = threading.Event()

    def receive():
        try:
            for line in sys.stdin:
                requests.put(json.loads(line))
        finally:
            closed.set()
            requests.put(None)

    threading.Thread(target=receive, daemon=True).start()
    proc = None
    try:
        while not closed.is_set():
            request = requests.get()
            if request is None:
                break
            started = time.time()
            try:
                admin.ensure_daemon()
                if closed.is_set():
                    raise RuntimeError('Browser session closed during startup; model code was not launched')
                command = [sys.executable, '-c',
                           'import sys; sys.path.insert(0,"/opt/private-hermes"); '
                           'import browser_use_shot as shot; import browser_harness.helpers as helpers; '
                           'shot.install(helpers, activate="never"); '
                           'helpers.cdp("Browser.setDownloadBehavior",behavior="allow",'
                           'downloadPath=__import__("os").environ["BH_DOWNLOAD_DIR"]); '
                           'import browser_harness.run as harness; '
                           'harness.__name__="__main__"; sys.modules["__main__"]=harness; '
                           'exec(' + repr(request['setup']) + ', vars(harness)); harness.main()']
                proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, text=True, start_new_session=True,
                                        cwd=os.environ['BH_AGENT_WORKSPACE'])
                deadline = time.monotonic() + request['timeout']
                incoming = request['code']
                while True:
                    try:
                        stdout, stderr = proc.communicate(input=incoming, timeout=0.2)
                        break
                    except subprocess.TimeoutExpired:
                        incoming = None
                        if closed.is_set() or time.monotonic() >= deadline:
                            os.killpg(proc.pid, signal.SIGKILL)
                            stdout, stderr = proc.communicate()
                            raise TimeoutError('Browser execution interrupted or timed out; already-issued '
                                               'browser actions may have completed. Do not replay automatically.')
                if closed.is_set():
                    raise RuntimeError('Browser session closed; already-issued actions may have completed. '
                                       'Do not replay automatically.')
                result = dict(returncode=proc.returncode, stdout=stdout, stderr=stderr)
                # These are executor paths. The gateway must fetch, never open them locally.
                for candidate in reversed(re.findall(r'(/[^\s\"\']+?\.(?:png|jpe?g|webp))', stdout, re.I)):
                    p = Path(candidate)
                    if p.is_file() and p.stat().st_mtime >= started - 1:
                        result['screenshot'] = candidate
                        break
            except (OSError, RuntimeError, TimeoutError, subprocess.SubprocessError) as error:
                result = {'error': str(error)}
                # A timeout ends this identity rather than reusing uncertain in-flight CDP.
                closed.set()
            finally:
                proc = None
            print(json.dumps(result), flush=True)
    finally:
        if proc is not None and proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
        admin.restart_daemon()


if __name__ == '__main__':
    main()
