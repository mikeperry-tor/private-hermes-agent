#!/usr/bin/env python3
"""Exercise cached executor images against the local engine with scratch projects."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import shlex
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from deployment import compose_base, compose_files, engine, engine_command
from project_mounts import (SETTING, check_project_model, engine_views, parse_mounts,
                            project_override, validate_sources)

TARGET = '/mnt/projects/my project $example$$'


def run(*command, **kwargs):
    return subprocess.run(command, check=True, text=True, **kwargs)


def grant_fixture_access(source, runner_uid):
    """Set ACLs on the scratch tree using the host Linux distribution's libacl."""
    acl = ctypes.CDLL('libacl.so.1', use_errno=True)
    acl.acl_from_text.argtypes = [ctypes.c_char_p]
    acl.acl_from_text.restype = ctypes.c_void_p
    acl.acl_set_file.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p]
    acl.acl_free.argtypes = [ctypes.c_void_p]

    def set_acl(path, kind, text):
        handle = acl.acl_from_text(text.encode())
        if not handle:
            raise OSError(ctypes.get_errno(), 'acl_from_text')
        try:
            if acl.acl_set_file(os.fsencode(path), kind, handle) != 0:
                number = ctypes.get_errno()
                raise OSError(number, os.strerror(number), path)
        finally:
            acl.acl_free(handle)

    for path in (source, *source.rglob('*')):
        if path.is_dir():
            set_acl(path, 0x8000, f'u::rwx,u:{runner_uid}:rwx,g::r-x,m::rwx,o::r-x')
            set_acl(path, 0x4000, f'u::rwx,u:{os.getuid()}:rwx,u:{runner_uid}:rwx,g::r-x,m::rwx,o::r-x')
        elif path.is_file():
            execute = 'x' if path.stat().st_mode & 0o111 else '-'
            set_acl(path, 0x8000, f'u::rw{execute},u:{runner_uid}:rw{execute},g::r--,m::rw{execute},o::r--')


def runner_host_uid(backend):
    if backend == 'podman':
        command = [*engine_command(), 'unshare', 'cat', '/proc/self/uid_map']
        for row in subprocess.check_output(command, text=True).splitlines():
            inner, outer, size = map(int, row.split())
            if inner <= 10000 < inner + size:
                return outer + 10000 - inner
        raise RuntimeError('Podman cannot map executor UID 10000.')
    return 10000 if sys.platform == 'linux' else os.getuid()


def prepare_fixture(source, runner_uid):
    source.mkdir(mode=0o755)
    run('git', 'init', '-q', str(source))
    (source / 'host.txt').write_text('host\n')
    (source / 'remove-by-runner').touch()
    if sys.platform == 'linux':
        grant_fixture_access(source, runner_uid)


def two_way_writes(source, runner_uid, execute, target=TARGET):
    git = shlex.join(['git', '-c', f'safe.directory={target}'])
    cd = shlex.join(['cd', target])
    execute(f'''
        {cd}
        test "$(id -u)" = 10000
        printf 'runner\n' >> host.txt
        {git} add host.txt
        rm remove-by-runner
        mkdir runner
        printf 'runner\n' > runner/file
        touch runner/remove-by-host
        touch runner/private
        chmod 0600 runner/private
        swap=$(mktemp .swap.XXXXXX)
        printf 'runner atomic\n' > "$swap"
        chmod 0664 "$swap"
        mv "$swap" host.txt
    ''')
    assert not (source / 'remove-by-runner').exists()
    assert (source / 'host.txt').read_text() == 'runner atomic\n'
    assert subprocess.check_output(['git', '-C', str(source), 'show', ':host.txt'], text=True) == 'host\nrunner\n'
    created = source / 'runner/file'
    assert created.stat().st_uid == runner_uid
    if sys.platform == 'linux':
        try:
            (source / 'runner/private').read_text()
        except PermissionError:
            pass
        else:
            raise AssertionError('Mode 0600 gave the host access to a runner-owned file.')
    with created.open('r+') as stream:
        assert stream.read() == 'runner\n'
        stream.write('host edit\n')
    (source / 'runner/remove-by-host').unlink()
    swap = source / 'runner/host.swap'
    swap.write_text('host atomic\n')
    swap.replace(created)
    execute(f'''
        {cd}
        test "$(cat runner/file)" = 'host atomic'
        test ! -e runner/remove-by-host
        printf 'runner edit\n' >> runner/file
    ''')
    assert created.read_text() == 'host atomic\nrunner edit\n'
    run('git', '-C', str(source), 'add', 'runner/file')


def engine_probe(root, source, uid, views, backend, base, image, project, binary, variant):
    root.mkdir()
    manifest = root / 'compose.json'
    manifest.write_text(json.dumps({
        'x-deployment': {'code_executor_bind_mounts': '${CODE_EXECUTOR_BIND_MOUNTS-}'},
        'services': {'executor': {
            'image': image, 'network_mode': 'none', 'user': '10000:10000',
            'read_only': True, 'cap_drop': ['ALL'], 'security_opt': ['no-new-privileges:true'],
            'entrypoint': ['/bin/sh', '-eu', '-c'],
        }},
    }))
    (root / '.env').write_text(f"{SETTING}='{source}:{TARGET}'\n")
    env = os.environ.copy()
    env.pop(SETTING, None)
    if binary and backend == 'podman':
        env['PODMAN_COMPOSE_PROVIDER'] = str(binary)
    if binary and backend == 'docker':
        base = [str(binary)]
    command = [*base, '-p', project, '--project-directory', str(root), '-f', str(manifest)]
    render = ['config', '--format', 'json']
    def setting(environment):
        model = json.loads(subprocess.check_output([*command, *render], env=environment))
        return parse_mounts(model['x-deployment']['code_executor_bind_mounts'])
    mounts, _ = validate_sources(setting(env), ROOT, *views)
    assert mounts == {Path(TARGET): source}
    assert setting({**env, SETTING: f'{source}:/mnt/projects/exported'}) == {Path('/mnt/projects/exported'): source}
    with project_override(mounts, root) as extra:
        merged = [*command, '-f', extra[0]]
        check_project_model(json.loads(subprocess.check_output([*merged, *render], env=env)), mounts)
        real_model = [*base, '--env-file', '/dev/null', *compose_files(False, extra), *render]
        rendered = subprocess.check_output(real_model, cwd=ROOT, env={**env, 'COMPUTER_USE_ENABLED': variant})
        check_project_model(json.loads(rendered), mounts)
        launch = [*merged, 'run', '--rm', '--no-deps', '-T', '--pull', 'never', 'executor']
        two_way_writes(source, uid, lambda script: run(*launch, script, env=env))
        moved = source.rename(source.with_name('moved'))
        try:
            result = subprocess.run([*launch, 'true'], env=env, capture_output=True)
            print(f'{backend} after final check: return code {result.returncode}, '
                  f'missing source created={source.exists()}', flush=True)
        finally:
            if source.exists():
                source.rmdir()
            moved.rename(source)


def refusal_probes(source, views):
    target = Path(TARGET)
    for path in (ROOT, ROOT.parent, source / 'missing'):
        try:
            validate_sources({target: path}, ROOT, *views)
        except ValueError:
            continue
        raise AssertionError(f'Unsafe source accepted: {path}')
    with socket.socket(socket.AF_UNIX) as server:
        path = source / 'host.sock'
        server.bind(str(path))
        try:
            validate_sources({target: source}, ROOT, *views)
        except ValueError as error:
            assert 'special file' in str(error)
        else:
            raise AssertionError('Host socket was accepted as part of a project.')
        finally:
            path.unlink()
    node = source / 'test-device'
    try:
        os.mknod(node, stat.S_IFCHR | 0o600, os.makedev(1, 3))
    except PermissionError:
        print('SKIP: creating a device node requires host permission.', flush=True)
    else:
        try:
            validate_sources({target: source}, ROOT, *views)
        except ValueError as error:
            assert 'special file' in str(error)
        else:
            raise AssertionError('Device node was accepted as part of a project.')
        finally:
            node.unlink()


def alias_probes(scratch, views):
    protected = scratch / 'Protected'
    protected.mkdir()
    alternate = scratch / 'alternate'
    alternate.mkdir()
    if sys.platform == 'darwin':
        case_alias = scratch / 'protected'
        if case_alias.exists():
            try:
                validate_sources({Path(TARGET): case_alias}, protected, *views)
            except ValueError as error:
                assert 'overlaps a protected' in str(error)
            else:
                raise AssertionError('A case alias exposed the protected directory.')
        else:
            print('SKIP: the scratch volume is case-sensitive.', flush=True)
        return

    if not shutil.which('unshare') or not shutil.which('mount'):
        print('SKIP: Linux bind aliases require unshare and mount.', flush=True)
        return
    script = """
import sys, subprocess
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from project_mounts import linux_mounts, validate_sources
scratch = Path(sys.argv[2])
protected, alternate = scratch / 'Protected', scratch / 'alternate'
subtree = protected / 'keys'
subtree.mkdir()
(subtree / 'child').mkdir()
(alternate / 'nested').mkdir()
subprocess.run(['mount', '--bind', str(subtree), str(alternate / 'nested')], check=True)
mounts = linux_mounts(Path('/proc/self/mountinfo').read_text())
for source in (alternate, alternate / 'nested/child'):
    try:
        validate_sources({Path('/mnt/projects/p'): source}, protected, (mounts,), (), ())
    except ValueError:
        pass
    else:
        raise AssertionError(f'Protected bind alias accepted: {source}')
"""
    result = subprocess.run(['unshare', '--user', '--map-root-user', '--mount', '--propagation', 'private',
                             sys.executable, '-c', script, str(ROOT / 'scripts'), str(scratch)],
                            text=True, capture_output=True)
    if result.returncode and ('unshare failed: Operation not permitted' in result.stderr or
                              'mount: ' in result.stderr and 'permission denied' in result.stderr.lower()):
        print('SKIP: host denies private bind-mount namespace fixtures.', flush=True)
    elif result.returncode:
        raise RuntimeError(result.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compose-binary', type=Path, help='Use an alternate Docker Compose executable.')
    parser.add_argument('--variant', choices=('lean', 'desktop', 'both'), default='both')
    args = parser.parse_args()
    backend = engine()
    views = engine_views(backend, Path.home().resolve())
    uid = runner_host_uid(backend)
    base = compose_base()
    binary = args.compose_binary.resolve() if args.compose_binary else None
    run(*engine_command(), '--version')
    run(*([str(binary)] if binary else base), 'version')
    parent = Path('/private/tmp') if sys.platform == 'darwin' else Path.home()
    with tempfile.TemporaryDirectory(prefix='hermes-share-', dir=parent) as directory:
        scratch = Path(directory).resolve()
        alias_probes(scratch, views)
        variants = {'lean': ('false',), 'desktop': ('true',), 'both': ('false', 'true')}[args.variant]
        for variant in variants:
            image = f'private-hermes-executor-{variant}:local'
            image_check = subprocess.run([*engine_command(), 'image', 'inspect', image], capture_output=True)
            if image_check.returncode:
                image = 'localhost/' + image
                run(*engine_command(), 'image', 'inspect', image, stdout=subprocess.DEVNULL)
            run(*engine_command(), 'run', '--rm', '--pull=never', '--network=none',
                '--read-only', '--cap-drop=ALL', '--entrypoint', '/bin/sh', image, '-eu', '-c',
                'for dir in /mnt /mnt/projects; do test ! -L "$dir"; test ! -e "$dir" || test -d "$dir"; done')
            source = scratch / ('host path $example$$' + '{other}-' + variant)
            prepare_fixture(source, uid)
            refusal_probes(source, views)
            engine_probe(scratch / f'compose-{variant}', source, uid, views, backend, base,
                         image, 'hermes-shares-' + uuid.uuid4().hex[:10], binary, variant)
            print(f'PASS: {backend} {variant} two-way writes and source checks', flush=True)


if __name__ == '__main__':
    main()
