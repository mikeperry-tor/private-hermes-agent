#!/usr/bin/env python3
"""Artifact construction does not initialize or depend on disposable operator state."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from deployment import engine_command


def main():
    fixture_project = 'private-hermes-build-fixture'
    with tempfile.TemporaryDirectory(prefix='private-hermes-build-test-') as folder:
        root = Path(folder)
        for name in ('Makefile', 'compose.yaml', 'compose.executor.yaml', 'compose.funnel.yaml',
                     'compose.podman.yaml', 'compose.podman.funnel.yaml', '.dockerignore'):
            shutil.copyfile(ROOT / name, root / name)
        for name in ('components', 'scripts'):
            shutil.copytree(ROOT / name, root / name, ignore=shutil.ignore_patterns('__pycache__'))
        # Keep dotenv syntax parseable while command/policy/network values are invalid.
        (root / '.env').write_text("WEBAPP_EXTERNAL_CONTENT=invalid\nTEEP_HOST_PORT=invalid\nTEEP_SERVE_ARGS='\"'\nNETWORK_PREFIX=invalid\n")
        (root / 'config').write_text('not a configuration directory')
        (root / 'data').write_text('not a storage directory')
        original = {name: (root / name).read_bytes() for name in ('.env', 'config', 'data')}
        environment = dict(os.environ, COMPOSE_PROJECT_NAME=fixture_project)
        try:
            result = subprocess.run(['make', 'build'], cwd=root, env=environment,
                                    text=True, capture_output=True)
            if result.returncode:
                print(result.stdout, result.stderr)
                raise RuntimeError('Artifact-only fixture build failed')
            assert all((root / name).read_bytes() == value for name, value in original.items())
            assert not (root / '.operation.lock').exists()
            print('PASS: real Make image build succeeds despite invalid deployment policy/port/command and wrong-type operator paths; operator files remain unchanged')
        finally:
            for suffix in ('agent', 'network', 'executor-false', 'executor-true', 'teep', 'x402_treazury', 'webapp-proxy', 'tailscale'):
                subprocess.run([*engine_command(), 'image', 'rm', '-f', f'{fixture_project}-{suffix}:local'],
                               cwd=ROOT, check=False, capture_output=True)


if __name__ == '__main__':
    main()
