"""Validate operator-selected project binds before starting the executor."""
from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import site
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import unicodedata
from deployment import check_engine

SETTING = 'CODE_EXECUTOR_BIND_MOUNTS'
PROJECTS = PurePosixPath('/mnt/projects')


def valid_path_characters(path):
    return all(char not in ',:"' and unicodedata.category(char) != 'Cc' for char in path)


def parse_mounts(value):
    mounts = {}
    if not value:
        return mounts
    for index, pair in enumerate(value.split(','), 1):
        # Compose's interpolated JSON output escapes every literal dollar.
        source, separator, target = pair.replace('$$', '$').partition(':')
        if not separator or not source.startswith('/') or not valid_path_characters(source + target):
            raise ValueError(f'{SETTING} entry {index} must be an absolute host:executor path pair.')
        destination = PurePosixPath(target)
        if not valid_destination(target):
            raise ValueError(f'{SETTING} entry {index} must use a normalized path below {PROJECTS}/.')
        if any(overlaps(destination, other) for other in mounts):
            raise ValueError(f'{SETTING} entry {index} overlaps another executor destination.')
        mounts[destination] = Path(source)
    return mounts


def valid_destination(path):
    destination = PurePosixPath(path)
    return (str(destination) == path and '..' not in destination.parts
            and destination != PROJECTS and destination.is_relative_to(PROJECTS)
            and valid_path_characters(path))


def overlaps(first, second):
    return first.is_relative_to(second) or second.is_relative_to(first)


def output(*args, trim=True):
    try:
        stdout = subprocess.run(args, check=True, text=True, capture_output=True).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        raise RuntimeError(f'{SETTING} could not verify the local engine with {args[0]}.') from error
    return stdout.strip() if trim else stdout


def docker_socket(home, platform):
    address = output('docker', 'context', 'inspect', '--format', '{{.Endpoints.docker.Host}}')
    prefix = 'unix://'
    if not address.startswith(prefix + '/'):
        raise RuntimeError(f'{SETTING} requires a local Docker Unix socket.')
    address_path = Path(address[len(prefix):]).resolve()
    expected = home / '.docker/run/docker.sock' if platform == 'darwin' else Path('/run/docker.sock')
    if address_path != expected.resolve():
        raise RuntimeError(f'{SETTING} requires the standard local Docker socket at {expected}.')
    return address_path


def linux_socket_peer(path, process, uid):
    with socket.socket(socket.AF_UNIX) as connection:
        connection.connect(str(path))
        pid, owner, _ = struct.unpack('3i', connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
    if owner != uid:
        raise RuntimeError(f'{SETTING} found an unexpected owner on the local {process} socket.')
    return pid


def linux_service_pid(path, process, uid, *, user=False, unit=None):
    pid = linux_socket_peer(path, process, uid)
    if unit and Path(f'/proc/{pid}/comm').read_text().strip() == 'systemd':
        systemctl = ['systemctl', *(['--user'] if user else [])]
        listens = output(*systemctl, 'show', unit + '.socket', '-p', 'Listen', '--value')
        triggers = output(*systemctl, 'show', unit + '.socket', '-p', 'Triggers', '--value')
        if listens != f'{path} (Stream)' or triggers != unit + '.service':
            raise RuntimeError(f'{SETTING} could not verify the local {unit} socket service.')
        pid = int(output(*systemctl, 'show', unit + '.service', '-p', 'MainPID', '--value'))
    return pid


def process_mounts(pid, process):
    if not pid or Path(f'/proc/{pid}/comm').read_text().strip() != process:
        raise RuntimeError(f'{SETTING} could not identify the local {process} process.')
    return linux_mounts(Path(f'/proc/{pid}/mountinfo').read_text())


def podman_compose_provider(stderr):
    _, marker, warning = stderr.partition('Executing external compose provider ')
    if not marker:
        raise RuntimeError(f'{SETTING} could not identify the local Podman Compose provider.')
    name, _ = json.JSONDecoder().raw_decode(warning)
    executable = shutil.which(name)
    if not executable:
        raise RuntimeError(f'{SETTING} could not locate the local Podman Compose provider.')
    provider = Path(executable).absolute()
    os.environ['PODMAN_COMPOSE_PROVIDER'] = str(provider)
    missing = []
    for line in stderr.splitlines():
        _, marker, message = line.partition(' msg=')
        if not marker or not message.startswith('"Error looking up compose provider '):
            continue
        diagnostic, _ = json.JSONDecoder().raw_decode(message)
        _, found, failure = diagnostic.partition(': exec: ')
        if not found:
            raise RuntimeError(f'{SETTING} could not resolve a configured Podman Compose provider.')
        # The exec error contains the candidate after Podman expands variables.
        candidate, _ = json.JSONDecoder().raw_decode(failure)
        if '/' in candidate:
            missing.append(Path(candidate))
    return (provider, *missing)


def docker_config_paths(home):
    config = Path(os.environ.get('DOCKER_CONFIG') or home / '.docker') / 'config.json'
    try:
        values = json.loads(config.read_text()) or {}
    except FileNotFoundError:
        return (config,)
    return (config, *(Path(path) for name, paths in values.items() if name.lower() == 'clipluginsextradirs'
                      for path in paths or ()))


def podman_control_paths(info):
    store = info['store']
    for key in ('graphRoot', 'runRoot', 'volumePath', 'configFile'):
        if store.get(key):
            yield Path(store[key])
    for key, value in (store.get('graphOptions') or {}).items():
        if key.endswith('.additionalImageStores'):
            yield from map(Path, value)
        if key.endswith('.mount_program') and value.get('Executable'):
            yield Path(value['Executable'])
    host = info['host']
    network = host.get('networkBackendInfo') or {}
    for component in (host.get('conmon'), host.get('ociRuntime'), network, network.get('dns')):
        if component and component.get('path'):
            yield Path(component['path'])
    for name in ('pasta', 'slirp4netns'):
        executable = (host.get(name) or {}).get('executable')
        if executable:
            yield Path(executable)


def docker_desktop_storage(home):
    directory = home / 'Library/Group Containers/group.com.docker'
    for filename in ('settings-store.json', 'settings.json'):
        try:
            settings = json.loads((directory / filename).read_text())
        except FileNotFoundError:
            continue
        for key, value in settings.items():
            if key.lower() == 'datafolder' and value:
                yield Path(value).expanduser()


def engine_views(engine, home):
    """Pin the Docker endpoint and identify the host views used for bind sources."""
    if engine == 'docker':
        path = docker_socket(home, sys.platform)
        if sys.platform == 'darwin':
            with socket.socket(socket.AF_UNIX) as connection:
                connection.connect(str(path))
                # Darwin SOL_LOCAL / LOCAL_PEERPID.
                pid = struct.unpack('i', connection.getsockopt(0, 2, 4))[0]
            backend = Path(output('/bin/ps', '-p', str(pid), '-o', 'comm='))
            if backend.parts[-4:] != ('Docker.app', 'Contents', 'MacOS', 'com.docker.backend'):
                raise RuntimeError(f'{SETTING} requires the local Docker Desktop backend.')
        elif sys.platform == 'linux':
            linux_socket_peer(path, 'Docker', 0)
        else:
            raise RuntimeError(f'{SETTING} requires Docker Desktop on macOS or native Docker on Linux.')
        # Compose, preflight, and built-in engine helpers inherit the same endpoint.
        os.environ.pop('DOCKER_CONTEXT', None)
        os.environ['DOCKER_HOST'] = 'unix://' + str(path)
        info = json.loads(output('docker', 'info', '--format', '{{json .}}'))
        client_plugins = (info.get('ClientInfo') or {}).get('Plugins') or ()
        plugins = (*docker_config_paths(home),
                   *(Path(plugin['Path']) for plugin in client_plugins if plugin.get('Path')))
        if sys.platform == 'darwin':
            if info.get('OperatingSystem') != 'Docker Desktop':
                raise RuntimeError(f'{SETTING} requires local Docker Desktop on macOS.')
            return (), (path, *plugins, *docker_desktop_storage(home)), darwin_mounts()
        if any(option.startswith(('name=rootless', 'name=userns')) for option in info['SecurityOptions'] or ()):
            raise RuntimeError(f'{SETTING} requires direct UID mapping on native Docker.')
        runtimes = (Path(runtime['path']) for runtime in (info.get('Runtimes') or {}).values()
                    if runtime.get('path', '').startswith('/'))
        views = ()
        protected = (path, Path(info['DockerRootDir']), Path('/var/lib/containerd'),
                     Path('/run/containerd'), *runtimes, *plugins)
    else:
        if sys.platform != 'linux':
            raise RuntimeError(f'{SETTING} requires rootless Podman on Linux.')
        info, provider_log = check_engine()
        path = Path(info['host']['remoteSocket']['path'])
        expected = Path(f'/run/user/{os.getuid()}/podman/podman.sock')
        if path.resolve() != expected or not info['host']['security']['rootless']:
            raise RuntimeError(f'{SETTING} requires the standard local rootless Podman socket at {expected}.')
        # A read-only API operation activates the service before its PID is inspected.
        api = json.loads(output('podman', '--remote', '--url', 'unix://' + str(expected),
                                'info', '--format', 'json'))
        if not api['host']['security']['rootless']:
            raise RuntimeError(f'{SETTING} requires a rootless local Podman API service.')
        pid = linux_service_pid(expected, 'podman', os.getuid(), user=True, unit='podman')
        views = (process_mounts(pid, 'podman'),)
        protected = (path, *podman_compose_provider(provider_log),
                     *podman_control_paths(info), *podman_control_paths(api))
    return (linux_mounts(Path('/proc/self/mountinfo').read_text()), *views), protected, ()


@dataclass(frozen=True)
class Mount:
    device: str
    root: Path
    point: Path
    filesystem: str


def linux_mounts(text):
    def path(field):
        return Path(re.sub(r'\\([0-7]{3})', lambda match: chr(int(match[1], 8)), field))

    mounts = []
    for line in text.splitlines():
        left, right = line.split(' - ', 1)
        fields = left.split()
        mounts.append(Mount(fields[2], path(fields[3]), path(fields[4]), right.split()[0]))
    return mounts


def mount_at(path, mounts):
    candidates = sorted((mount for mount in mounts if path.is_relative_to(mount.point)),
                        key=lambda mount: len(mount.point.parts), reverse=True)
    if not candidates or len(candidates) > 1 and candidates[0].point == candidates[1].point:
        raise ValueError(f'{SETTING} cannot establish the mounted filesystem for {path}.')
    return candidates[0]


def backing_path(path, mounts):
    mount = mount_at(path, mounts)
    return mount.device, mount.root / path.relative_to(mount.point)


def darwin_mounts():
    points = []
    for line in output('/sbin/mount').splitlines():
        _, has_separator, mount = line.partition(' on ')
        target, has_options, _ = mount.rpartition(' (')
        if not has_separator or not has_options or not target.startswith('/'):
            raise RuntimeError(f'{SETTING} could not read the macOS mount table.')
        points.append(Path(target))
    return points


def identities(path):
    result = []
    for entry in (path, *path.parents):
        try:
            info = entry.stat()
        except (FileNotFoundError, PermissionError):
            continue
        result.append((info.st_dev, info.st_ino))
    return result


def git_config_paths(root):
    git = shutil.which('git')
    if not git:
        return ()
    configuration = output(git, '-C', str(root), 'config', '--null', '--show-origin', '--includes', '--list')
    records = iter(configuration.split('\0'))
    paths = []
    for origin, record in zip(records, records):
        key, _, value = record.partition('\n')
        if key == 'core.fsmonitor' and '/' in value:
            paths.append(root / Path(value).expanduser())
        if not origin.startswith('file:'):
            continue
        path = root / origin.removeprefix('file:')
        paths.append(path)
        if key == 'include.path' or key.startswith('includeif.') and key.endswith('.path'):
            paths.append(path.parent / Path(value).expanduser())
    return paths


def protected_paths(root, home, extra):
    paths = [root, root / '.env', root / '.env.example', root / '.operation.lock',
             root / 'config', root / 'data',
             root / 'config/webapp/auth.json', root / 'config/webapp/password',
             root / 'config/x402_treazury/research_desk.toml', *extra,
             *map(Path, ('/etc', '/usr', '/bin', '/sbin', '/boot', '/lib', '/lib64',
                                      '/dev', '/proc', '/sys', '/run', '/var', '/root', '/opt',
                                      '/srv', '/nix', '/snap', '/System', '/Library', '/Applications'))]
    paths.extend(home / part for part in ('.ssh', '.ssh/config', '.ssh/authorized_keys',
                                           '.gnupg', '.docker', '.config', '.aws', '.kube',
                                           '.codex', '.local/bin', '.local/state', '.local/share/containers',
                                           '.gitconfig', '.git-credentials', '.netrc', '.profile',
                                           '.bash_profile', '.bash_login', '.bashrc', '.zshenv',
                                           '.zprofile', '.zshrc', '.zlogin', 'Library'))
    config_root = Path(os.environ.get('XDG_CONFIG_HOME') or home / '.config')
    paths.extend(config_root / file for file in (
        'git/config', 'git/credentials', 'containers/auth.json', 'containers/containers.conf',
        'containers/storage.conf', 'containers/registries.conf'))
    for name in ('containers.conf.d', 'registries.conf.d'):
        directory = config_root / 'containers' / name
        paths.append(directory)
        paths.extend(directory.glob('*.conf'))
    runtime = Path(os.environ.get('XDG_RUNTIME_DIR') or f'/run/user/{os.getuid()}')
    paths.append(runtime / 'containers/auth.json')
    if os.environ.get('ZDOTDIR'):
        zsh_root = Path(os.environ['ZDOTDIR'])
        paths.extend(zsh_root / name for name in ('.zshenv', '.zprofile', '.zshrc', '.zlogin'))
    for key in ('PATH', 'LD_LIBRARY_PATH', 'DYLD_LIBRARY_PATH'):
        paths.extend(Path(part) for part in os.environ.get(key, '').split(os.pathsep) if part)
    paths.extend(Path(part) for part in sys.path if part)
    paths.extend((Path(site.getusersitepackages()), Path(sys.executable)))
    paths.extend(Path(found) for name in ('docker', 'podman', 'make', 'python3', 'env', 'systemctl', 'git')
                 if (found := shutil.which(name)))
    if (root / '.git').exists() or os.environ.get('GIT_DIR'):
        metadata = output('git', '-C', str(root), 'rev-parse', '--path-format=absolute',
                          '--git-dir', '--git-common-dir', '--git-path', 'hooks', trim=False).splitlines()
        if len(metadata) != 3 or any(not Path(path).is_absolute() for path in metadata):
            raise ValueError(f'{SETTING} could not establish the deployment Git paths.')
        git_dir, common_dir, hooks_dir = map(Path, metadata)
        paths.extend((git_dir, common_dir, hooks_dir))
        if hooks_dir.is_dir():
            paths.extend(hook for hook in hooks_dir.iterdir() if hook.is_symlink())
    paths.extend(git_config_paths(root))
    paths.extend(Path(os.environ[key]).expanduser() for key in (
        'DOCKER_CONFIG', 'XDG_CONFIG_HOME', 'XDG_RUNTIME_DIR', 'SSH_AUTH_SOCK',
        'CONTAINERS_CONF', 'CONTAINERS_CONF_OVERRIDE', 'CONTAINERS_STORAGE_CONF',
        'CONTAINERS_REGISTRIES_CONF', 'REGISTRY_AUTH_FILE', 'PODMAN_COMPOSE_PROVIDER',
        'GIT_CONFIG_GLOBAL', 'GIT_CONFIG_SYSTEM', 'BASH_ENV', 'ENV', 'ZDOTDIR') if os.environ.get(key))
    paths.extend(Path(path) for path in os.environ.get('COMPOSE_ENV_FILES', '').split(',') if path)
    return {location for path in paths for location in control_locations(path)}


def control_locations(path):
    # Protect the links themselves as well as the resolved control file.
    absolute = path.absolute()
    locations = {absolute, absolute.resolve()}
    current = Path(absolute.anchor)
    pending = list(absolute.parts[1:])
    redirects = 0
    while pending:
        part = pending.pop(0)
        current = current.parent if part == '..' else current / part
        if current.is_symlink():
            redirects += 1
            if redirects > 40:
                raise ValueError(f'{SETTING} cannot resolve a host control path: {absolute}.')
            locations.add(current)
            target = current.readlink()
            if target.is_absolute():
                current = Path(target.anchor)
                pending[:0] = target.parts[1:]
            else:
                current = current.parent
                pending[:0] = target.parts
    return locations


def bind_sources(model):
    return tuple(Path(volume['source'].replace('$$', '$')) for service in model['services'].values()
                 for volume in service.get('volumes', ()) if volume['type'] == 'bind')


def source_directory(path):
    try:
        source = path.resolve(strict=True)
        if not source.is_dir():
            raise ValueError(f'{SETTING} source must be a directory: {path}.')
        if not valid_path_characters(str(source)):
            raise ValueError(f'{SETTING} resolved source contains an unsupported character: {path}.')
        return source
    except (OSError, RuntimeError) as error:
        raise ValueError(f'{SETTING} source is missing or inaccessible: {path}.') from error


def source_ids(mounts):
    result = {}
    for source in mounts.values():
        if source_directory(source) != source:
            raise ValueError(f'{SETTING} source changed before creation: {source}.')
        info = source.stat()
        result[source] = (info.st_dev, info.st_ino)
    return result


def validate_sources(mounts, root, views, engine_paths, mac_mounts):
    home = Path.home().resolve()
    protected = protected_paths(root, home, engine_paths)
    broad = [home, Path('/')]
    chosen = {}
    source_identities = {}
    if views:
        host = views[0]
        protected_backing = {backing_path(path, view) for view in views for path in protected}
        protected_backing.update((mount.device, mount.root) for view in views for mount in view
                                 if any(mount.point.is_relative_to(path) for path in protected))
        broad_backing = [backing_path(path, host) for path in broad]
    for destination, path in mounts.items():
        source = source_directory(path)
        info = source.stat()
        identity = (info.st_dev, info.st_ino)
        source_chain = [identity, *identities(source.parent)]
        for control in protected | set(chosen.values()):
            if overlaps(source, control) or aliases(source_chain, control):
                raise ValueError(f'{SETTING} source overlaps a protected or already shared path: {source}.')
        if any(home_path.is_relative_to(source) or source_chain[0] in identities(home_path)
               for home_path in broad):
            raise ValueError(f'{SETTING} requires a project directory, not a parent directory: {source}.')
        if views:
            location = backing_path(source, host)
            selected = mount_at(source, host)
            if selected.filesystem not in ('ext4', 'xfs', 'btrfs') or selected.root != Path('/'):
                raise ValueError(f'{SETTING} source requires a local filesystem without a bind alias: {source}.')
            if any(backing_path(source, view) != location for view in views[1:]):
                raise ValueError(f'{SETTING} source has a different filesystem view in the engine: {source}.')
            device, file_path = location
            if (any(dev == device and overlaps(file_path, path) for dev, path in protected_backing) or
                    any(dev == device and path.is_relative_to(file_path) for dev, path in broad_backing)):
                raise ValueError(f'{SETTING} source aliases a protected host path: {source}.')
            mountpoints = (mount.point for view in views for mount in view)
        else:
            if source_chain[0][0] != home.stat().st_dev:
                raise ValueError(f'{SETTING} source must be on the macOS home volume: {source}.')
            mountpoints = iter(mac_mounts)
        reject_nested_mounts(source, source_chain[0], mountpoints)
        check_project_entries(source)
        chosen[destination] = source
        source_identities[source] = identity
    return chosen, source_identities


def reject_nested_mounts(source, identity, mountpoints):
    for point in mountpoints:
        if point != source and (point.is_relative_to(source) or identity in identities(point.parent)):
            raise ValueError(f'{SETTING} source contains a nested mount: {source}.')


def aliases(source_chain, control):
    if source_chain[0] in identities(control):
        return True
    try:
        info = control.stat()
    except (FileNotFoundError, PermissionError):
        return False
    return (info.st_dev, info.st_ino) in source_chain


def check_project_entries(source):
    device = source.stat().st_dev

    def fail(error):
        raise error

    try:
        for directory, dirs, files in os.walk(source, onerror=fail, followlinks=False):
            for name in dirs + files:
                info = (Path(directory) / name).lstat()
                if (info.st_dev != device or not (stat.S_ISREG(info.st_mode) or
                                                  stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode))):
                    raise ValueError(f'{SETTING} project contains a mounted or special file: {Path(directory) / name}.')
    except OSError as error:
        raise ValueError(f'{SETTING} could not read the complete project directory: {source}.') from error


@contextmanager
def project_override(mounts, root):
    if not mounts:
        yield ()
        return
    volumes = [{'type': 'bind', 'source': str(source).replace('$', '$$'),
                'target': str(target).replace('$', '$$'),
                'bind': {'create_host_path': False, 'recursive': 'disabled'}} for target, source in mounts.items()]
    with tempfile.TemporaryDirectory(prefix='.executor-projects-', dir=root) as directory:
        path = Path(directory) / 'projects.json'
        # Compose parses the overlay as YAML, which rejects JSON surrogate pairs.
        model = {'services': {'executor': {'restart': 'no', 'volumes': volumes}}}
        escapes = {ord(char): f'\\u{ord(char):04x}' for char in '\u2028\u2029\ufffe\uffff'}
        path.write_text(json.dumps(model, ensure_ascii=False).translate(escapes), encoding='utf-8')
        yield (str(path),)


def check_project_model(model, mounts):
    found = {}
    if mounts and model['services'].get('executor', {}).get('restart') != 'no':
        raise RuntimeError(f'{SETTING} requires automatic executor restart to be disabled.')
    for name, service in model['services'].items():
        for volume in service.get('volumes', ()):
            target = PurePosixPath(volume['target'].replace('$$', '$'))
            if not target.is_relative_to(PROJECTS):
                continue
            # Compose 2.36 omits false bind flags from its rendered model.
            bind = volume.get('bind', {})
            if (name != 'executor' or target in found or volume['type'] != 'bind' or
                    volume.get('read_only') or bind.get('create_host_path', False) or
                    bind.get('recursive') != 'disabled'):
                raise RuntimeError(f'{SETTING} produced an unexpected project mount in {name}.')
            found[target] = Path(volume['source'].replace('$$', '$'))
    if found != mounts:
        raise RuntimeError(f'{SETTING} does not match the effective executor mount list.')
