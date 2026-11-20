#!/usr/bin/env python3
"""Cold Compose passthrough launches; disposable namespaces, no private mounts.

Run with the selected engine after building Hermes, with other fixed-subnet
fixtures/deployments stopped. No Tor, inference or wallet operation is started.
"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from deployment import engine, engine_command, compose_base, compose_files


def dry_run_checks(override):
    project = 'private-hermes-launch-' + uuid.uuid4().hex[:12]
    command = [sys.executable, str(ROOT / 'scripts/stack.py'), 'compose', '-p', project,
               '--env-file', '/dev/null', '-f', str(override)]
    def networks():
        return subprocess.check_output([*engine_command(), 'network', 'ls', '-q', '--filter',
                                        f'label=com.docker.compose.project={project}'], text=True).split()
    try:
        for arguments in (['up', '--dry-run', '-d', 'probe-owner'],
                          ['--dry-run', 'up', '--no-attach', '--dry-run=false', '-d', 'probe-owner'],
                          ['run', '--dry-run', '-d', '--no-deps', 'probe-networked']):
            result = subprocess.run([*command, *arguments], cwd=ROOT, text=True, capture_output=True)
            assert result.returncode == 0, result.stderr
            assert not networks(), 'Dry launch created real networks'
            containers = subprocess.check_output([*engine_command(), 'ps', '-a', '-q', '--filter',
                                                  f'label=com.docker.compose.project={project}'], text=True)
            assert not containers.strip(), 'Dry launch created real containers'
        # An unused network that normal project cleanup would remove must
        # survive `down --dry-run`, including the wrapper's Podman cleanup.
        name = project + '_inference'
        options = ['--opt', 'isolate=strict'] if engine() == 'podman' else []
        subprocess.run([*engine_command(), 'network', 'create', '--internal', '--subnet', '10.203.83.0/24',
                        '--label', f'com.docker.compose.project={project}',
                        '--label', 'com.docker.compose.network=inference', *options, name],
                       check=True, capture_output=True)
        before = networks()
        subprocess.run([*command, 'down', '--dry-run'], cwd=ROOT, check=True, capture_output=True)
        assert networks() == before, 'Dry shutdown removed a real network'
        print(f'PASS: {engine()} command-level dry up/run/down preserve real namespaces/networks', flush=True)
    finally:
        subprocess.run([*command, 'down', '--volumes', '--remove-orphans'], cwd=ROOT,
                       check=True, capture_output=True)
        assert not networks(), 'Disposable dry-run network was not removed'


def profile_cleanup_checks(override):
    # A stopped profiled container still holds its owner's namespace in Podman.
    # Default down can omit it; the shared fixture teardown must include it.
    import smoke
    project = 'private-hermes-launch-' + uuid.uuid4().hex[:12]
    previous = smoke.COMPOSE
    smoke.COMPOSE = [*compose_base(), '-p', project, '--env-file', '/dev/null',
                     *compose_files(False, extra=(str(override),))]
    try:
        smoke.compose('up', '-d', '--wait', 'probe-profiled')
        smoke.compose('stop', 'probe-profiled')
    finally:
        try:
            smoke.compose('down', '--volumes', '--remove-orphans')
        finally:
            smoke.COMPOSE = previous
    for kind in ('container', 'network', 'volume'):
        found = subprocess.check_output([*engine_command(), kind, 'ls', '-q',
                                         *(['-a'] if kind == 'container' else []), '--filter',
                                         f'label=com.docker.compose.project={project}'], text=True)
        assert not found.strip(), ('Profile cleanup left project resources', kind, found)
    print(f'PASS: {engine()} cleanup removes stopped profiled namespace users before owners', flush=True)


def main():
    with tempfile.TemporaryDirectory(prefix='private-hermes-launch-') as directory:
        override = Path(directory) / 'launch.yaml'
        override.write_text('''services:
  probe-owner:
    image: private-hermes-agent:local
    entrypoint: [/opt/hermes/.venv/bin/python]
    command: [-m, http.server, "8000", --bind, "127.0.0.1"]
    cap_drop: [ALL]
    networks: [inference]
    healthcheck:
      test: [CMD, curl, -fsS, http://127.0.0.1:8000]
      interval: 1s
      timeout: 3s
      retries: 30
  probe-profiled:
    profiles: [cleanup]
    image: private-hermes-agent:local
    init: true
    entrypoint: [sleep]
    command: [infinity]
    cap_drop: [ALL]
    network_mode: service:probe-owner
    depends_on:
      probe-owner: {condition: service_healthy}
  probe-shared:
    image: private-hermes-agent:local
    entrypoint: [/opt/hermes/.venv/bin/python]
    command: [-c, "import urllib.request; assert urllib.request.urlopen('http://127.0.0.1:8000').status == 200"]
    cap_drop: [ALL]
    network_mode: service:probe-owner
    depends_on:
      probe-owner: {condition: service_healthy}
  probe-offline:
    image: private-hermes-agent:local
    entrypoint: [/opt/hermes/.venv/bin/python]
    command: [-c, "print('offline')"]
    cap_drop: [ALL]
    network_mode: none
    depends_on:
      probe-owner: {condition: service_healthy}
  x402_treazury-inspect:
    network_mode: service:probe-owner
  probe-isolated:
    image: private-hermes-agent:local
    entrypoint: [/opt/hermes/.venv/bin/python]
    command: [-c, "print('isolated')"]
    cap_drop: [ALL]
    network_mode: none
  probe-offline-admin:
    image: private-hermes-agent:local
    entrypoint: [/opt/hermes/.venv/bin/python]
    command: [-c, "print('offline admin')"]
    cap_drop: [ALL]
    network_mode: none
    depends_on: [probe-isolated]
  probe-networked:
    image: private-hermes-agent:local
    entrypoint: [/opt/hermes/.venv/bin/python]
    command: [-c, "print('networked')"]
    cap_drop: [ALL]
    networks: [inference]
''')
        invalid = Path(directory) / 'invalid.env'
        invalid.write_text('WEBAPP_BIND=0.0.0.0\n')
        for arguments, networked, error in ((['probe-shared'], True, None), (['probe-offline'], True, None),
                                            (['--no-deps', '-Te', 'x402_treazury-inspect', 'probe-networked'], True, None),
                                            (['--no-deps', 'probe-offline'], True, None),
                                            (['--no-deps', 'probe-isolated'], False, None),
                                            (['--no-deps', 'probe-offline-admin'], False, None),
                                            (['--no-deps', 'x402_treazury-inspect'], False, 'Offline maintenance jobs require'),
                                            (['--no-deps', 'probe-isolated'], False, 'IPv4 loopback')):
            project = 'private-hermes-launch-' + uuid.uuid4().hex[:12]
            command = [sys.executable, str(ROOT / 'scripts/stack.py'), 'compose', '-p', project,
                       '--env-file', str(invalid) if error == 'IPv4 loopback' else '/dev/null', '-f', str(override)]
            def networks():
                return subprocess.check_output([*engine_command(), 'network', 'ls', '-q', '--filter',
                                                f'label=com.docker.compose.project={project}'], text=True).split()
            try:
                result = subprocess.run([*command, 'run', '--rm', '-T', *arguments], cwd=ROOT,
                                        text=True, capture_output=True)
                if error:
                    assert result.returncode and error in result.stderr, result.stderr
                else:
                    assert result.returncode == 0, result.stderr
                identifiers = networks()
                assert bool(identifiers) == networked, (arguments, identifiers)
                if error:
                    containers = subprocess.check_output([*engine_command(), 'ps', '-a', '-q', '--filter',
                                                          f'label=com.docker.compose.project={project}'], text=True)
                    assert not containers.strip(), 'Rejected launch created containers'
                if engine() == 'podman' and identifiers:
                    actual = json.loads(subprocess.check_output([*engine_command(), 'network', 'inspect',
                                                                 *identifiers], text=True))
                    assert all(n['options'].get('isolate') == 'strict' for n in actual), actual
                print(f'PASS: {engine()} cold run {arguments}, project networks={networked}, error={error}', flush=True)
            finally:
                subprocess.run([*command, 'down', '--volumes', '--remove-orphans'], cwd=ROOT,
                               check=True, capture_output=True)
                assert not networks(), 'Disposable project networks were not removed'
        dry_run_checks(override)
        profile_cleanup_checks(override)


if __name__ == '__main__':
    main()
