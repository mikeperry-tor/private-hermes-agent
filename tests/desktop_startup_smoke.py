#!/usr/bin/env python3
"""Networkless desktop startup: reclaim coordination, preserve persistent data."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import uuid

PROFILE = Path('/home/runner/.hermes/bot-desktop/browser-profile')
COORDINATION = ('SingletonLock', 'SingletonSocket', 'SingletonCookie', 'DevToolsActivePort')
PRESERVED = {
    'Default/Network/Cookies': b'fixture cookie database',
    'Local State': b'{"fixture":"profile state"}',
    'SingletonOperatorNote': b'unrelated similarly named file',
    '../identity-canary': b'fixture identity, never rotate',
    '../link-target': b'symlink target must survive',
}


def container_stage(stage):
    assert os.getuid() == 10000
    status = dict(line.split(':', 1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
    assert all(int(status[key].strip(), 16) == 0 for key in ('CapEff', 'CapPrm', 'CapInh', 'CapAmb'))
    assert status['NoNewPrivs'].strip() == '1' and status['Seccomp'].strip() == '2'
    if stage == 'seed':
        PROFILE.mkdir(parents=True, mode=0o700)
        for name, value in PRESERVED.items():
            path = PROFILE / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(value)
        (PROFILE / 'SingletonLock').symlink_to('previous-container-172')
        (PROFILE / 'SingletonSocket').symlink_to(PROFILE / '../link-target')
        (PROFILE / 'SingletonCookie').symlink_to('missing-cookie-coordination-target')
        (PROFILE / 'DevToolsActivePort').write_text('12345\n/devtools/browser/stale\n')
    elif stage == 'block':
        (PROFILE / 'SingletonLock').mkdir()
        (PROFILE / 'SingletonLock' / 'keep').write_bytes(b'unexpected state must survive')
    elif stage == 'blocked':
        assert (PROFILE / 'SingletonLock' / 'keep').read_bytes() == b'unexpected state must survive'
        assert all((PROFILE / name).read_bytes() == value for name, value in PRESERVED.items())
        print('PASS: unexpected coordination directory refuses startup visibly without deleting state', flush=True)
    else:
        assert all(not os.path.lexists(PROFILE / name) for name in COORDINATION)
        assert all((PROFILE / name).read_bytes() == value for name, value in PRESERVED.items())
        print('PASS: actual desktop startup unlinks only stale coordination; profile, cookies, identity and symlink targets persist; runner caps zero, NNP/seccomp active', flush=True)


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / 'scripts'))
    from deployment import check_engine, engine, engine_command, local_image
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', default=local_image('executor-true'))
    args = parser.parse_args()
    check_engine()
    name = 'private-hermes-desktop-startup-' + uuid.uuid4().hex[:12]
    tmp_options = ',notmpcopyup' if engine() == 'podman' else ''
    policy = [] if engine() == 'podman' else [
        '--security-opt', 'seccomp=' + str(root / 'components/executor/seccomp-desktop.json')]
    script = '''set -eu
setpriv --reuid=10000 --regid=10000 --clear-groups python3 /fixture.py seed
# No auth keys are supplied. Native sshd must refuse after startup preparation.
if /usr/local/bin/executor-start >/tmp/startup.log 2>&1; then
    echo 'Unexpected SSH startup without host keys' >&2; exit 1
fi
if ! grep -qi 'no hostkeys available' /tmp/startup.log; then
    cat /tmp/startup.log >&2; exit 1
fi
setpriv --reuid=10000 --regid=10000 --clear-groups python3 /fixture.py verify
setpriv --reuid=10000 --regid=10000 --clear-groups python3 /fixture.py block
if /usr/local/bin/executor-start >/tmp/blocked.log 2>&1; then
    echo 'Unexpected startup with a coordination directory' >&2; exit 1
fi
if ! grep -q 'Is a directory' /tmp/blocked.log; then
    cat /tmp/blocked.log >&2; exit 1
fi
exec setpriv --reuid=10000 --regid=10000 --clear-groups python3 /fixture.py blocked
'''
    try:
        subprocess.run([*engine_command(), 'run', '--name', name, '--network', 'none',
            '--read-only', '--cap-drop', 'ALL', '--cap-add', 'SETUID', '--cap-add', 'SETGID',
            '--cap-add', 'SYS_CHROOT', '--security-opt', 'no-new-privileges=true', *policy,
            '--tmpfs', '/tmp:mode=1777' + tmp_options, '--tmpfs', '/run:mode=0755' + tmp_options,
            '--tmpfs', '/home/runner:mode=1777' + tmp_options,
            '--mount', f'type=bind,source={Path(__file__).resolve()},target=/fixture.py,readonly',
            '--entrypoint', '/bin/sh', args.image, '-c', script], check=True)
    finally:
        cleanup = subprocess.run([*engine_command(), 'rm', '--force', '--volumes', name],
                                 capture_output=True, text=True)
        if cleanup.returncode:
            print('Desktop startup fixture cleanup failed:', cleanup.stderr, file=sys.stderr)
            if sys.exc_info()[0] is None:
                cleanup.check_returncode()


if __name__ == '__main__':
    if len(sys.argv) == 2 and sys.argv[1] in ('seed', 'verify', 'block', 'blocked'):
        container_stage(sys.argv[1])
    else:
        main()
