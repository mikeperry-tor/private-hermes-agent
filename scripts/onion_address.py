#!/usr/bin/env python3
"""Create an offline onion identity or display its saved public address."""
import subprocess
import sys

from deployment import ROOT, check_bind_sources, maintenance_compose

sys.path.insert(0, str(ROOT / 'components/network'))
from onion import hostname


def maintenance(arguments, *, check=True):
    try:
        command = maintenance_compose()
        check_bind_sources(command, arguments)
        return subprocess.run([*command, *arguments], cwd=ROOT, text=True,
                              capture_output=True, check=check)
    except subprocess.CalledProcessError as error:
        raise RuntimeError('Onion maintenance command failed:\n' + (error.stderr or str(error))) from None


def inspect_address():
    if not (ROOT / 'data/tor').exists():
        return None
    result = maintenance(['run', '--rm', '--no-deps', '--pull', 'never', 'onion-inspect'], check=False)
    if result.returncode == 3:
        return None
    if result.returncode:
        raise RuntimeError('Cannot inspect onion address. Build its local image with '
                           'make build if absent.\n' + result.stderr)
    return hostname(result.stdout)


def saved_address():
    address = inspect_address()
    if address is None:
        raise ValueError('Onion address is missing. Run make onion-address before enabling onion ingress.')
    return address


def main():
    address = inspect_address()
    if address is None:
        from x402_treazury import operation_lock
        from storage import initialize
        with operation_lock(ROOT):
            # Another completed operation may have published the hostname.
            address = inspect_address()
            if address is None:
                # A restarting/paused container can become a writer again
                # without another managed operation. Require make down, which
                # removes that engine restart authority, before offline writes.
                result = maintenance(['ps', '-a', '-q', 'tor'])
                if result.stdout.strip():
                    raise RuntimeError('Stop runtime Tor with make down before creating or repairing the onion identity; '
                                       'remove its container even if it is paused, restarting or stopped.')
                initialize(ROOT / 'data', paths=('tor',))
                result = maintenance(['run', '--rm', '--no-deps', '--pull', 'never', 'onion-init'], check=False)
                if result.returncode:
                    raise RuntimeError('Offline onion initialization failed. Build the local image with '
                                       'make build if absent.\n' + result.stderr)
                address = hostname(result.stdout)
    print('http://' + address)


if __name__ == '__main__':
    sys.path.insert(0, str(ROOT / 'components/provisioning'))
    try:
        main()
    except (ValueError, RuntimeError, OSError) as error:
        raise SystemExit(str(error))
