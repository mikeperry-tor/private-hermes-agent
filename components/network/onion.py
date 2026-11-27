"""Native Tor identity maintenance; no network or alternate identity store."""
import argparse
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time

STATE = Path('/var/lib/tor')
SECRET_HEADER = b'== ed25519v1-secret: type0 ==\x00\x00\x00'


def hostname(value):
    value = value.removesuffix('\n')
    if not re.fullmatch(r'[a-z2-7]{56}\.onion', value):
        raise ValueError('Saved onion hostname is not one canonical v3 onion address')
    return value


def read_address(state=STATE):
    return hostname((state / 'onion-service/hostname').read_text())


def require_secret(state=STATE):
    path = state / 'onion-service/hs_ed25519_secret_key'
    try:
        value = path.read_bytes()
    except FileNotFoundError:
        raise ValueError('Onion secret key is missing; restore data/tor/onion-service from backup. '
                         'Use make onion-address only for a new identity or repair from an intact secret.') from None
    if len(value) != 96 or value[:32] != SECRET_HEADER:
        # Tor silently regenerates malformed keys. Refuse that native behavior
        # to preserve the operator's existing identity; never print key material.
        raise ValueError('Onion secret key has invalid native format; restore it from backup. Existing files preserved.')


def initialize(state=STATE):
    service = state / 'onion-service'
    secret = service / 'hs_ed25519_secret_key'
    if any((service / name).exists() for name in ('hs_ed25519_secret_key', 'hostname', 'hs_ed25519_public_key')):
        require_secret(state)
    state.mkdir(exist_ok=True)
    os.chown(state, 101, 102)
    state.chmod(0o700)
    if service.exists():
        os.chown(service, 101, 102)
        service.chmod(0o700)
    # Existing native file ownership is preserved. Restore backups with their
    # original owner/modes; do not recursively repair private state here.
    with tempfile.TemporaryDirectory() as temporary:
        Path(temporary).chmod(0o755)
        config = Path(temporary) / 'torrc'
        config.write_text('')
        log = Path(temporary) / 'tor.log'
        with log.open('w+') as output:
            # Tor requires a HiddenServicePort target even with DisableNetwork 1;
            # it is not persisted, and runtime network.py configures <prefix>.86.3:8080.
            child = subprocess.Popen([
                'setpriv', '--reuid=101', '--regid=102', '--clear-groups',
                '--bounding-set=-all', '--inh-caps=-all', '--ambient-caps=-all', '--no-new-privs',
                'tor', '-f', str(config), '--DataDirectory', str(state),
                '--DisableNetwork', '1', '--SocksPort', '0', '--ControlPort', '0',
                '--HiddenServiceDir', str(service), '--HiddenServiceVersion', '3',
                '--HiddenServicePort', '80 127.0.0.1:8080', '--Log', 'notice stdout',
            ], stdout=output, stderr=subprocess.STDOUT)
            try:
                while True:
                    if child.poll() is not None:
                        output.seek(0)
                        raise RuntimeError('Offline Tor identity initialization failed:\n' + output.read())
                    if (secret.is_file() and (service / 'hostname').is_file()
                            and (service / 'hs_ed25519_public_key').is_file()):
                        require_secret(state)
                        try:
                            address = read_address(state)
                        except ValueError:
                            # Native Tor may not have finished publishing the file.
                            time.sleep(.05)
                            continue
                        break
                    time.sleep(.05)
            finally:
                if child.poll() is None:
                    child.terminate()
                code = child.wait()
            if code not in (0, -signal.SIGTERM):
                output.seek(0)
                raise RuntimeError('Offline Tor failed during shutdown:\n' + output.read())
    return address


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('inspect', 'initialize'))
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    if args.action == 'inspect':
        try:
            print(read_address())
        except FileNotFoundError:
            sys.exit(3)
    else:
        print(initialize())


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError, OSError) as error:
        raise SystemExit(str(error))
