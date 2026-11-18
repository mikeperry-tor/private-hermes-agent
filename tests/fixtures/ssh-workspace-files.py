"""Native SSH filesystem command semantics, using a real shell in the image."""
from pathlib import Path
import subprocess
import tempfile
from hermes_cli.ssh_workspace_fs import SshWorkspaceFs, SshWorkspaceFsError


class ShellTarget:
    timeout = 10

    def __init__(self, root):
        self.cwd = self._remote_home = str(root)

    def execute(self, command, *, cwd, stdin_data, timeout):
        result = subprocess.run(['bash', '-c', command], cwd=cwd, input=stdin_data,
                                text=True, capture_output=True, timeout=timeout)
        return {'returncode': result.returncode, 'output': result.stdout + result.stderr}


with tempfile.TemporaryDirectory(prefix='ssh-file-inspection-') as directory:
    root = Path(directory)
    backend = SshWorkspaceFs(ShellTarget(root))
    regular = root / 'regular.txt'
    regular.write_bytes(b'bytes')
    (root / 'link').symlink_to(regular)
    for name in ('regular.txt', 'link'):
        assert backend.inspect_file(name) == (str(regular), 5)
        assert backend.read_bytes(name, max_bytes=100)[0] == b'bytes'
    for name, expected in (('absent', 'ENOENT'), ('absent-parent/leaf', 'ENOENT'),
                           (str(root), 'ENOTREG')):
        try:
            backend.inspect_file(name)
        except SshWorkspaceFsError as error:
            assert error.code == expected, (name, error.code, expected)
        else:
            raise AssertionError('Inspection accepted an absent/non-file path: ' + name)
print('PASS: native SSH inspection distinguishes absent files from directories and preserves regular/symlink reads')
