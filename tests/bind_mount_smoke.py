#!/usr/bin/env python3
"""Disposable actual-engine bind refusal and override checks; no public network."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from deployment import engine, engine_command, local_image


def main():
    agent_image = local_image('agent')
    with tempfile.TemporaryDirectory(prefix='private-hermes-bind-') as directory:
        root = Path(directory)
        present, missing = root / 'present', root / 'missing'
        present.mkdir()
        (present / 'proof').write_text('bind proof')
        (root / 'compose.executor.yaml').write_bytes((ROOT / 'compose.executor.yaml').read_bytes())
        override = root / 'bind.json'
        def job(source, **extra):
            return dict(image=agent_image, network_mode='none',
                        entrypoint=['/opt/hermes/.venv/bin/python'], command=['-c', "print('bind probe')"],
                        cap_drop=['ALL'], volumes=[{'type': 'bind', 'source': str(source), 'target': '/probe',
                                                   'read_only': True, 'bind': {'create_host_path': False}}], **extra)
        override.write_text(json.dumps({'services': {
            'hermes-config': {'image': agent_image},
            'bind-present': job(present), 'bind-absent': job(missing),
            'bind-dependent': job(present, depends_on={'bind-absent': {'condition': 'service_completed_successfully'}})}}))
        project = 'private-hermes-bind-' + uuid.uuid4().hex[:10]
        command = [sys.executable, str(ROOT / 'scripts/stack.py'), 'compose', '-p', project,
                   '--env-file', '/dev/null', '-f', str(override)]
        override_created = False
        try:
            for arguments in (['run', '--rm', 'bind-absent'], ['run', '--rm', 'bind-dependent'],
                              ['create', 'bind-absent'], ['up', '-d', 'bind-absent'],
                              ['up', '--no-attach', '--dry-run', '-d', 'bind-absent']):
                result = subprocess.run([*command, *arguments], cwd=ROOT, text=True, capture_output=True)
                assert result.returncode and 'Required bind source missing' in result.stderr, result.stderr
                assert not missing.exists(), 'Rejected launch created missing source'
                for kind in ('container', 'network'):
                    found = subprocess.check_output([*engine_command(), kind, 'ls', '-q',
                        *(['-a'] if kind == 'container' else []), '--filter',
                        f'label=com.docker.compose.project={project}'], text=True)
                    assert not found.strip(), ('Rejected launch created resources', kind, found)
            subprocess.run([*engine_command(), 'volume', 'create', '--label',
                            f'com.docker.compose.project={project}', project + '-override'], check=True, capture_output=True)
            override_created = True
            for arguments in (['scale', 'bind-absent=0'],
                              ['run', '--rm', '--no-deps', 'bind-dependent'],
                              ['run', '--rm', '-v', f'{present}:/probe:ro', 'bind-absent'],
                              ['run', '--rm', f'-Tv={present}:/probe:ro', 'bind-absent'],
                              ['run', '--rm', '-v', f'{project}-override:/probe', 'bind-absent'],
                              ['run', '--rm', '--no-deps', 'hermes-config', '--help']):
                subprocess.run([*command, *arguments], cwd=ROOT, check=True, capture_output=True)
            subprocess.run([*command, '--project-directory', str(root), 'run', '--rm',
                            f'-v{os.path.relpath(present, ROOT)}:/probe:ro', 'bind-absent', '-c',
                            "from pathlib import Path; assert Path('/probe/proof').read_text()=='bind proof'"],
                           cwd=ROOT, check=True, capture_output=True)
            # Read actual bytes from an allowed bind, not just a successful start.
            subprocess.run([*command, 'run', '--rm', 'bind-present', '-c',
                            "from pathlib import Path; assert Path('/probe/proof').read_text()=='bind proof'"],
                           cwd=ROOT, check=True, capture_output=True)
            assert not missing.exists()
            print(f'PASS: {engine()} missing required binds refuse before mutation; existing/overridden/offline paths work', flush=True)
        except subprocess.CalledProcessError as error:
            print(error.stdout or '', error.stderr or '', flush=True)
            raise
        finally:
            if override_created:
                subprocess.run([*engine_command(), 'volume', 'rm', project + '-override'], check=True, capture_output=True)
            subprocess.run([*command, 'down', '--volumes', '--remove-orphans'], cwd=ROOT, check=True, capture_output=True)


if __name__ == '__main__':
    main()
