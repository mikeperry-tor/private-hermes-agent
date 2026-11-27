#!/usr/bin/env python3
"""Networkless native Hermes lifecycle investigation in an isolated named volume.

No operator mounts, provider keys, wallets or application deployment are used.
--omit experiments diagnose a grant; a successful boot alone is not qualification.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from deployment import engine_command, local_image

CAPS = ['CHOWN', 'DAC_OVERRIDE', 'FOWNER', 'KILL', 'SETUID', 'SETGID']
SNAPSHOT = '''import json,os
from pathlib import Path
rows=[]
for path in Path('/proc').glob('[0-9]*/status'):
 try:
  fields=dict(line.split(':',1) for line in path.read_text().splitlines())
 except FileNotFoundError: continue
 if int(fields['Pid'])==os.getpid(): continue
 rows.append({k:fields[k].strip() for k in ('Name','Pid','PPid','Uid','Gid','Groups','CapEff','CapPrm','CapInh','CapAmb','CapBnd','NoNewPrivs')})
print(json.dumps(rows,sort_keys=True))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--omit', choices=CAPS)
    parser.add_argument('--image', default=local_image('agent'))
    parser.add_argument('--probe-path', action='store_true', help='harmless native root-service PATH marker')
    parser.add_argument('--path', help='override container PATH for the PATH-order experiment')
    parser.add_argument('--expect-closed', action='store_true', help='assert the writable-PATH root path is closed')
    args = parser.parse_args()
    if args.expect_closed and not args.probe_path:
        parser.error('--expect-closed requires --probe-path')
    engine = engine_command()
    name = 'private-hermes-capability-' + uuid.uuid4().hex[:12]
    volume = name + '-data'

    def run(*command, check=True):
        result = subprocess.run([*engine, *command], capture_output=True, text=True)
        if check and result.returncode:
            raise RuntimeError(f'{command[:3]}: {result.stdout}\n{result.stderr}')
        return result

    def execute(*command, user='10000:10000', check=True):
        return run('exec', '--user', user, name, *command, check=check)

    def python(code, **kwargs):
        return execute('/opt/hermes/.venv/bin/python', '-c', code, **kwargs)

    def ready():
        # Test deadline, never an application progress/failure timeout.
        end = time.monotonic() + 120
        while time.monotonic() < end:
            result = execute('/command/s6-svstat', '/run/service/profile-gateways', check=False)
            if result.returncode == 0 and result.stdout.startswith('up '):
                return
            if run('inspect', '--format', '{{.State.Running}}', name).stdout.strip() != 'true':
                break
            time.sleep(.5)
        raise RuntimeError('Native profile supervision did not become ready')

    def assert_clean_startup():
        logs = run('logs', name, check=False)
        text = logs.stdout + logs.stderr
        for failure in ('Operation not permitted', 'Permission denied', 'exited 1'):
            assert failure not in text, f'Startup log contains {failure!r}'
        state = python("import os,stat; s=os.stat('/run/hermes-service'); print(s.st_uid,s.st_gid,oct(stat.S_IMODE(s.st_mode)))", user='0:0').stdout.split()
        assert state == ['10000', '10000', '0o755'], state

    try:
        run('volume', 'create', volume)
        grants = [item for cap in CAPS if cap != args.omit for item in ('--cap-add', cap)]
        path = ['-e', f'PATH={args.path}'] if args.path else []
        print(run('image', 'inspect', args.image, '--format', '{{.Id}} {{.Architecture}}').stdout.strip(), flush=True)
        run('run', '-d', '--name', name, '--network', 'none',
            '--security-opt', 'no-new-privileges:true', '--cap-drop', 'ALL', *grants,
            '-e', 'HERMES_UID=10000', '-e', 'HERMES_GID=10000', '-e', 'HERMES_DASHBOARD=0', *path,
            '-v', f'{volume}:/opt/data', args.image, 'sleep', 'infinity')
        ready()
        assert_clean_startup()
        print(python(SNAPSHOT, user='0:0').stdout, flush=True)
        if args.probe_path:
            python('''from pathlib import Path
p=Path('/opt/data/.local/bin/sleep'); p.parent.mkdir(parents=True,exist_ok=True)
p.write_text('#!/bin/sh\\n/usr/bin/id >> /opt/data/capability-path-marker\\nexec /usr/bin/sleep "$@"\\n'); p.chmod(0o755)
''')
            old = execute('/command/s6-svstat', '-o', 'pid', '/run/service/main-hermes').stdout.strip()
            execute('/command/s6-svc', '-r', '/run/service/main-hermes')
            # Observe the replacement after exec, rather than racing a fixed sleep.
            end = time.monotonic() + 10
            executable = None
            while time.monotonic() < end:
                pid = execute('/command/s6-svstat', '-o', 'pid', '/run/service/main-hermes').stdout.strip()
                if pid not in ('0', old):
                    result = python(f"from pathlib import Path; print(Path('/proc/{int(pid)}/exe').readlink())", user='0:0', check=False)
                    if result.returncode == 0 and result.stdout.strip().endswith('/sleep'):
                        executable = result.stdout.strip()
                        break
                time.sleep(.1)
            if executable is None:
                raise RuntimeError('Static service did not restart into sleep')
            marker = python("from pathlib import Path; p=Path('/opt/data/capability-path-marker'); print(p.read_text() if p.exists() else 'no writable-PATH execution')", user='0:0')
            print('PATH probe:', marker.stdout.strip(), 'exe:', executable, flush=True)
            if args.expect_closed:
                assert marker.stdout.strip() == 'no writable-PATH execution', marker.stdout
                assert executable != '/opt/data/.local/bin/sleep', executable
            python("from pathlib import Path; Path('/opt/data/.local/bin/sleep').unlink()")
        print(execute('/opt/hermes/bin/hermes', 'profile', 'create', 'capability-fixture').stdout, flush=True)
        python("from hermes_cli.service_manager import S6ServiceManager; assert 'capability-fixture' in S6ServiceManager().list_profile_gateways()")
        wrapper = execute('/bin/sh', '-c', 'command -v capability-fixture').stdout.strip()
        assert wrapper == '/opt/data/.local/bin/capability-fixture', wrapper
        execute('/bin/sh', '-c', 'capability-fixture --help >/dev/null')
        # Reproduce supported root-written state repair on warm bootstrap.
        python("from pathlib import Path; p=Path('/opt/data/config.yaml'); p.chmod(0o600)")
        run('restart', name)
        ready()
        assert_clean_startup()
        python("from pathlib import Path; import stat; p=Path('/opt/data/config.yaml'); assert stat.S_IMODE(p.stat().st_mode)==0o640, oct(p.stat().st_mode); assert p.stat().st_uid==10000; assert p.read_text()")
        execute('/opt/hermes/bin/hermes', '--version')
        stopped = run('stop', '--time', '30', name)
        state = run('inspect', '--format', '{{.State.ExitCode}} {{.State.OOMKilled}}', name).stdout.strip()
        assert state == '0 false', state
        print('PASS: native bootstrap, profile registration, warm permissions, CLI and clean stop', flush=True)
    except BaseException:
        print(run('logs', '--tail', '60', name, check=False).stdout, flush=True)
        print(run('logs', '--tail', '60', name, check=False).stderr, flush=True)
        raise
    finally:
        run('rm', '-f', name, check=False)
        run('volume', 'rm', volume, check=False)


if __name__ == '__main__':
    main()
