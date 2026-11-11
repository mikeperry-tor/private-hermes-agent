#!/usr/bin/env python3
"""Native plugin install/update with a genuine local wheel dependency; no paid APIs."""
import os
from pathlib import Path
import subprocess
import smoke

smoke.COMPOSE = ['docker', 'compose', '-p', 'private-hermes-plugins-test',
                 *smoke.compose_files(False, extra=('tests/compose.yaml',))]
FIXTURE = (Path(__file__).parent / 'fixtures/plugin_lifecycle.py').read_text()


def fixture(action):
    result = smoke.execute('hermes', '/opt/hermes/.venv/bin/python', '-c', FIXTURE, str(action))
    print(result.stdout.strip(), flush=True)


def native(*args):
    result = smoke.execute('hermes', '/opt/hermes/.venv/bin/hermes', 'plugins', *args)
    print(result.stdout.strip(), flush=True)


def main():
    with smoke.storage_fixture():
        failed = True
        try:
            smoke.initialize_setup(smoke.COMPOSE)
            smoke.compose('up', '-d', '--no-deps', '--no-build', '--wait', '--wait-timeout', '600',
                          'tor', 'agent-net', 'hermes')
            fixture('create')
            native('install', 'file:///opt/data/qualification-plugin-source', '--enable', '--yes-deps')
            fixture(1)
            fixture('update')
            native('update', 'qualification-plugin')
            fixture(2)
            smoke.compose('up', '-d', '--no-deps', '--force-recreate', 'hermes')
            fixture(2)
            print('PASS: native dependency-bearing plugin install, explicit update and recreation persistence', flush=True)
            failed = False
        except subprocess.CalledProcessError as error:
            print(error.stdout or '', error.stderr or '', flush=True)
            raise
        finally:
            if failed and os.getenv('KEEP_FAILED_TEST_STACK') == '1':
                print('Retained disposable plugin test stack', flush=True)
            else:
                smoke.compose('down', '--volumes', '--remove-orphans', check=False)


if __name__ == '__main__':
    main()
