#!/usr/bin/env python3
"""Disposable public-numbered image canaries, with no uplink or published ports."""
import os
from pathlib import Path
import subprocess
import tempfile
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from deployment import compose_base  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
COMMAND = [*compose_base(), '-p', 'private-hermes-images-test', '-f', 'tests/images-compose.yaml']


def main():
    with tempfile.TemporaryDirectory(prefix='private-hermes-image-tls-') as folder:
        tls = Path(folder)
        tls.chmod(0o755)  # Disposable certificates must be reachable by container UID 10000.
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                        '-keyout', str(tls / 'key.pem'), '-out', str(tls / 'cert.pem'),
                        '-subj', '/CN=public.test', '-addext', 'subjectAltName=DNS:public.test'],
                       check=True, capture_output=True)
        (tls / 'key.pem').chmod(0o644)  # disposable fixture key only
        env = {**os.environ, 'COMPOSE_PROJECT_NAME': 'private-hermes-images-test', 'IMAGE_TEST_TLS': folder}
        def compose(*args, check=True):
            return subprocess.run([*COMMAND, *args], cwd=ROOT, env=env, check=check)
        try:
            compose('up', '-d', '--no-build', 'canary')
            compose('run', '--rm', '--no-deps', 'check')
        finally:
            compose('down', '--volumes', '--remove-orphans', check=False)


if __name__ == '__main__':
    main()
