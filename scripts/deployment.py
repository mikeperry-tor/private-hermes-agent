"""Compose handles dotenv interpolation; this module validates feature settings."""
from functools import cache
import io
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'components/webapp'))
sys.path.insert(0, str(ROOT / 'scripts/vendor/dotenv'))
from settings import Settings, proxy_config
from parser import parse_stream  # vendored python-dotenv parser, see scripts/vendor/dotenv/SOURCE.md


SELECTOR = 'CONTAINER_ENGINE'
ENGINES = ('docker', 'podman')
# Endpoint overrides that would point Podman, or the Compose provider that
# `podman compose` starts, at another engine. `podman compose` passes an
# inherited DOCKER_HOST to the provider even with --remote=false.
PODMAN_OVERRIDES = ('DOCKER_HOST', 'DOCKER_CONTEXT', 'CONTAINER_HOST', 'CONTAINER_CONNECTION')
_AMBIENT_OVERRIDES = []


class EngineError(RuntimeError):
    pass


def _output(*args):
    return subprocess.run(args, cwd=ROOT, text=True, capture_output=True, check=True).stdout


def read_selector(path=None):
    """Return the engine that CONTAINER_ENGINE selects: docker or podman.

    An exported value takes precedence over the root .env. Without either, the
    engine is Docker. A blank or other value is an error, never a fallback.
    Only this key is read from .env; nothing is exported or interpolated.
    """
    if SELECTOR in os.environ:
        value, source = os.environ[SELECTOR], 'the environment'
    else:
        path = Path(path or ROOT / '.env')
        try:
            text = path.read_text(encoding='utf-8')
        except FileNotFoundError:
            return 'docker'
        except (OSError, UnicodeDecodeError) as error:
            raise EngineError(f'Cannot read {path}: {getattr(error, "strerror", None) or error.__class__.__name__}') from None
        value, source = None, str(path)
        for binding in parse_stream(io.StringIO(text)):
            if binding.error:
                raise EngineError(f'{path}, line {binding.original.line}: not a valid assignment')
            if binding.key == SELECTOR:
                value = binding.value if binding.value is not None else ''
        if value is None:
            return 'docker'
    if value not in ENGINES:
        raise EngineError(f'{SELECTOR} in {source} must be docker or podman')
    return value


@cache
def engine():
    """Return the selected engine. With Podman, remove endpoint overrides.

    The overrides are removed from this process's environment, so every child
    command and the Compose provider use the local rootless Podman. They are
    recorded, and a networked launch refuses to start while they are set.
    """
    selected = read_selector()
    if selected == 'podman':
        for name in PODMAN_OVERRIDES:
            if name in os.environ:
                _AMBIENT_OVERRIDES.append(name)
                del os.environ[name]
    return selected


def engine_command():
    """The engine command: the Docker CLI, or local Podman."""
    return ['docker'] if engine() == 'docker' else ['podman', '--remote=false']


def compose_base():
    return [*engine_command(), 'compose']


def _version(text):
    parts = text.strip().lstrip('v').split('-')[0].split('.')
    try:
        return tuple(int(part) for part in parts[:3])
    except ValueError:
        return (0,)


@cache
def check_engine():
    """Check the selected engine before a networked launch.

    Docker: the endpoint is Docker Engine 28+ (not Podman behind a docker
    command), with Compose 2.36+. Podman: local and rootless, 5.4+, its user API
    socket exists, its Compose provider is Docker Compose 2.36+, and no endpoint
    override is set.
    """
    if engine() == 'podman':
        if _AMBIENT_OVERRIDES:
            raise EngineError('Unset ' + ', '.join(_AMBIENT_OVERRIDES) + ' before starting the stack with Podman: '
                              'the stack runs on the local rootless Podman only.')
        try:
            info = json.loads(_output(*engine_command(), 'info', '--format', 'json'))
        except (OSError, subprocess.CalledProcessError, ValueError) as error:
            raise EngineError('The podman command is required with CONTAINER_ENGINE=podman.') from error
        host = info.get('host') or {}
        if not (host.get('security') or {}).get('rootless'):
            raise EngineError('Podman must run rootless: rootful bridge gateways are host addresses.')
        if _version((info.get('version') or {}).get('Version', '')) < (5, 4, 0):
            raise EngineError('Podman 5.4 or later is required.')
        if not (host.get('remoteSocket') or {}).get('exists'):
            raise EngineError('Enable the user Podman API socket: systemctl --user enable --now podman.socket')
        try:
            provider = _output(*compose_base(), 'version')
        except (OSError, subprocess.CalledProcessError) as error:
            raise EngineError('podman compose needs Docker Compose 2.36 or later as its provider.') from error
        if 'Docker Compose' not in provider or _version(provider.rsplit(' ', 1)[-1]) < (2, 36, 0):
            raise EngineError('podman compose needs Docker Compose 2.36 or later as its provider '
                              '(PODMAN_COMPOSE_PROVIDER or compose_providers in containers.conf).')
        return
    reaches_podman = EngineError('The docker command reaches Podman. Set CONTAINER_ENGINE=podman to use Podman.')
    try:
        if _output('docker', '--version').lower().startswith('podman'):
            raise reaches_podman
        components = json.loads(_output('docker', 'version', '--format', '{{json .Server.Components}}'))
        server = _output('docker', 'version', '--format', '{{.Server.Version}}')
    except (OSError, subprocess.CalledProcessError, ValueError) as error:
        raise EngineError('Docker Engine is required with CONTAINER_ENGINE=docker.') from error
    names = [entry.get('Name') for entry in components or [] if isinstance(entry, dict)]
    if 'Podman Engine' in names:
        raise reaches_podman
    if _version(server) < (28, 0, 0):
        raise EngineError('Docker Engine 28 or later is required.')
    if _version(_output('docker', 'compose', 'version', '--short')) < (2, 36, 0):
        raise EngineError('Docker Compose 2.36 or later is required.')


def prepare_launch(command):
    """Check the engine, then create Podman networks, before a networked launch."""
    check_engine()
    ensure_networks(command)


def remove_networks(command):
    """On Podman, remove the project networks that Compose `down` left.

    ensure_networks() creates the networks of every profile; Compose `down`
    removes only those of the services it manages. Only networks with this
    project's Compose label are removed. A failure is reported and does not
    block shutdown.
    """
    if engine() != 'podman':
        return
    try:
        config = json.loads(_output(*command, '--profile', '*', 'config', '--format', 'json'))
    except (OSError, subprocess.CalledProcessError, ValueError) as error:
        print(f'Could not list the project networks to remove: {error}', file=sys.stderr, flush=True)
        return
    for network in (config.get('networks') or {}).values():
        if network.get('external'):
            continue
        name = network['name']
        found = subprocess.run([*engine_command(), 'network', 'inspect', name], cwd=ROOT, text=True, capture_output=True)
        if found.returncode != 0:
            continue
        labels = json.loads(found.stdout)[0].get('labels') or {}
        if labels.get('com.docker.compose.project') != config['name']:
            continue
        removed = subprocess.run([*engine_command(), 'network', 'rm', name], cwd=ROOT, text=True, capture_output=True)
        if removed.returncode:
            print(f'Could not remove Podman network {name}: {removed.stderr.strip()}', file=sys.stderr, flush=True)


def ensure_networks(command):
    """On Podman, create the project's networks with their declared options.

    Compose creates networks through Podman's Docker-compatible API, which sets
    only isolate=true and drops other bridge options such as isolate=strict and
    no_default_route. Networks created here carry Compose's labels, so Compose
    adopts them and `down` removes them. An existing network without the
    declared options stops startup.
    """
    if engine() != 'podman':
        return
    config = json.loads(_output(*command, '--profile', '*', 'config', '--format', 'json'))
    for key, network in (config.get('networks') or {}).items():
        if network.get('external'):
            continue
        name = network['name']
        options = {option: str(value) for option, value in (network.get('driver_opts') or {}).items()}
        subnets = sorted(entry['subnet'] for entry in (network.get('ipam') or {}).get('config') or []
                         if 'subnet' in entry)
        internal = bool(network.get('internal'))
        if options.get('isolate') != 'strict':
            # Without strict isolation, netavark forwards from other networks (F9).
            raise RuntimeError(f'Network {key} has no isolate: strict for Podman. Declare it in compose.podman.yaml.')
        found = subprocess.run([*engine_command(), 'network', 'inspect', name], cwd=ROOT, text=True, capture_output=True)
        if found.returncode == 0:
            actual = json.loads(found.stdout)[0]
            labels = actual.get('labels') or {}
            if (actual.get('driver') != 'bridge' or labels.get('com.docker.compose.project') != config['name']
                    or labels.get('com.docker.compose.network') != key):
                raise RuntimeError(f'Podman network {name} is not a bridge network of this project. '
                                   'Remove it or choose another project name.')
            actual_options = actual.get('options') or {}
            actual_subnets = sorted(entry['subnet'] for entry in actual.get('subnets') or [])
            if (any(actual_options.get(option) != value for option, value in options.items())
                    or bool(actual.get('internal')) != internal
                    or (subnets and actual_subnets != subnets)):
                raise RuntimeError(f'Podman network {name} does not have the options the stack declares. '
                                   'Run make down so that it is created again.')
            continue
        arguments = [*engine_command(), 'network', 'create',
                     '--label', f"com.docker.compose.project={config['name']}",
                     '--label', f'com.docker.compose.network={key}']
        if internal:
            arguments.append('--internal')
        for subnet in subnets:
            arguments += ['--subnet', subnet]
        for option, value in options.items():
            arguments += ['--opt', f'{option}={value}']
        subprocess.run([*arguments, name], cwd=ROOT, text=True, capture_output=True, check=True)


def compose_files(funnel, extra=()):
    """Return Compose file arguments. The Podman files must stay last."""
    files = ['compose.yaml', *(['compose.funnel.yaml'] if funnel else []), *extra]
    if engine() == 'podman':
        files += ['compose.podman.yaml', *(['compose.podman.funnel.yaml'] if funnel else [])]
    return [argument for name in files for argument in ('-f', name)]


def settings(extra=(), options=()):
    result = subprocess.run([*compose_base(), *compose_files(False, extra), *options, 'config', '--format', 'json'],
                            cwd=ROOT, text=True, capture_output=True, check=True)
    return Settings.read(json.loads(result.stdout)['x-deployment'])


def compose(config, all_ingress=False, extra=()):
    return [*compose_base(), *compose_files(config.funnel or all_ingress, extra)]


def maintenance_compose(all_ingress=False, executor_build=False, extra=()):
    # These operations must not start ingress, inference or the agent with
    # placeholders. Actual treasury policy remains in its mounted configuration.
    # Compose still interpolates unused services and publications.
    os.environ.update(WEBAPP_TERMINAL_ENVIRONMENT='code', TOR_ONION_ENABLED='false', TAILSCALE_FUNNEL_ENABLED='false', WEBAPP_EXTERNAL_CONTENT='off',
                      WEBAPP_BIND='127.0.0.1', WEBAPP_PORT='9120', WEBAPP_USERNAME='admin',
                      TAILSCALE_FUNNEL_HOST='', TAILSCALE_FUNNEL_PORT='443',
                      TAILSCALE_HOSTNAME='private-hermes', TEEP_HOST_PORT='8337', TEEP_SERVE_ARGS='')
    if not executor_build:
        # Saved-state inspection/shutdown do not select or build an executor.
        # An invalid optional desktop preference must not block those operations.
        os.environ['COMPUTER_USE_ENABLED'] = 'false'
    return [*compose_base(), *compose_files(all_ingress, extra)]


def maintenance_command(arguments):
    if not arguments:
        return False
    if arguments[0] in ('build', 'logs', 'ps', 'top', 'port', 'exec', 'stop', 'down', 'rm', 'kill', 'pause', 'unpause'):
        return True
    # Explicit networkless maintenance jobs; do not normalize arbitrary launches.
    if arguments[0] != 'run':
        return False
    service, no_deps, _ = _run_target(arguments)
    return no_deps and service in ('hermes-config', 'setup-storage', 'mcp-config',
                                  'onion-inspect', 'onion-init',
                                  'x402_treazury-inspect', 'x402_treazury-admin')


def render(config):
    onion_host = ''
    if config.onion:
        from onion_address import saved_address
        onion_host = saved_address()
    path = ROOT / 'config/webapp/proxy.cfg'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(proxy_config(config, loopback_forwarder=engine() == 'podman', onion_host=onion_host))


# Compose global options that the stack.py passthrough accepts before the subcommand.
GLOBAL_OPTIONS = {'-p': 'project', '--project-name': 'project', '--profile': 'profile', '-f': 'file',
                  '--file': 'file', '--env-file': 'env', '--project-directory': 'directory'}
# Compose subcommands that create no network. Every other subcommand, including
# an unknown one, is prepared as a launch (run only for a networked service).
NO_NETWORKS = ('config', 'ps', 'ls', 'logs', 'top', 'port', 'images', 'version', 'events', 'exec', 'stop',
               'down', 'rm', 'kill', 'pause', 'unpause', 'build', 'pull', 'push', 'cp', 'wait', 'attach',
               'stats', 'commit', 'export', 'volumes')
# `run` options that take a value, so that the service name can be found.
RUN_VALUE_OPTIONS = ('--entrypoint', '-v', '--volume', '-e', '--env', '--env-from-file', '-u', '--user', '--name',
                     '-w', '--workdir', '-p', '--publish', '-l', '--label', '--cap-add', '--cap-drop', '--pull')
# Only known zero-argument flags may be skipped while finding the service.
# A future option must never classify its value as an offline service. Reject
# unknown options before mutation; native Compose still validates their values.
RUN_FLAG_OPTIONS = ('--build', '-d', '--detach', '--dry-run', '-i', '--interactive', '--no-deps',
                    '--no-recreate', '-T', '--no-tty', '-q', '--quiet', '--quiet-build', '--quiet-pull',
                    '--remove-orphans', '--rm', '-P', '--service-ports', '--use-aliases')


def _run_target(rest, volumes=None):
    """Find the service and launch flags before a run's container command."""
    arguments, no_deps, dry_run = iter(rest[1:]), False, None
    for value in arguments:
        if value == '--':
            return next(arguments, None), no_deps, dry_run
        if not value.startswith('-'):
            return value, no_deps, dry_run
        name, equals, operand = value.partition('=')
        if name in RUN_VALUE_OPTIONS:
            value = operand if equals else next(arguments, None)
            if value is None:
                return None, no_deps, dry_run
            if name in ('-v', '--volume') and volumes is not None:
                volumes.append(value)
        elif name in RUN_FLAG_OPTIONS:
            if name == '--no-deps':
                no_deps = not equals or operand in ('true', '1', 't', 'T', 'TRUE', 'True')
            elif name == '--dry-run':
                dry_run = _dry_run_flag(value)
        elif not value.startswith('--'):
            # Native shorthand clusters, e.g. -Te NAME=value or -eNAME=value.
            # A value-taking option consumes the rest of the token or the next.
            for index, letter in enumerate(value[1:], start=1):
                short = '-' + letter
                if short in RUN_VALUE_OPTIONS:
                    attached = value[index + 1:]
                    operand = attached.removeprefix('=') if attached else next(arguments, None)
                    if operand is None:
                        return None, no_deps, dry_run
                    if short == '-v' and volumes is not None:
                        volumes.append(operand)
                    break
                if short not in RUN_FLAG_OPTIONS:
                    raise ValueError(f'Unsupported Compose run option {short}; use separate supported flags.')
        else:
            raise ValueError(f'Unsupported Compose run option {name}.')
    return None, no_deps, dry_run


def _dry_run_flag(value):
    # Go/pflag's accepted false spellings; malformed values fail in Compose.
    return value.partition('=')[2] not in ('false', 'False', 'FALSE', '0', 'f', 'F')


# These are creation options whose operands must not be mistaken for services.
CREATE_VALUES = ('--attach', '--no-attach', '--exit-code-from', '--pull', '--scale',
                 '-t', '--timeout', '--wait-timeout')
CREATE_FLAGS = ('--abort-on-container-exit', '--abort-on-container-failure',
                '--always-recreate-deps', '--attach-dependencies', '--build', '-d',
                '--detach', '--dry-run', '--force-recreate', '--menu', '--no-build',
                '--no-color', '--no-deps', '--no-log-prefix', '--no-recreate',
                '--no-start', '--quiet-build', '--quiet-pull', '--remove-orphans',
                '-V', '--renew-anon-volumes', '--timestamps', '--wait', '-y', '--yes')


def check_bind_sources(command, rest, *, dry_run=False):
    """Reject absent required sources before a supported container creation.

    Compose resolves paths, profiles and dependency selection. This is a host
    preflight, not atomic enforcement against concurrent host filesystem changes.
    """
    if not rest or rest[0] in NO_NETWORKS or rest[0] in ('start', 'restart'):
        return
    action, volumes, targets, no_deps = rest[0], [], [], False
    scales = {}
    if action == 'run':
        target, no_deps, _ = _run_target(rest, volumes)
        if target is None:
            raise ValueError('Compose run requires a service')
        targets = [target]
    elif action in ('up', 'create'):
        arguments = iter(rest[1:])
        for value in arguments:
            if value == '--':
                targets.extend(arguments)
                break
            if not value.startswith('-'):
                targets.append(value)
                continue
            name, equals, operand = value.partition('=')
            if name in CREATE_VALUES:
                operand = operand if equals else next(arguments, None)
                if operand is None:
                    raise ValueError(f'{name} needs a value')
                if name == '--scale':
                    service, separator, count = operand.partition('=')
                    if not separator or not count.isdigit():
                        raise ValueError('Use --scale SERVICE=COUNT')
                    scales[service] = int(count)
            elif name in CREATE_FLAGS:
                if name == '--no-deps':
                    no_deps = _dry_run_flag(value)
            else:
                raise ValueError(f'Unsupported Compose creation option {name}; use separate supported flags.')
        if no_deps and any(x.split('=')[0] == '--always-recreate-deps' for x in rest[1:]):
            raise ValueError('Do not combine --no-deps and --always-recreate-deps')
    elif action == 'scale':
        for value in rest[1:]:
            name, separator, count = value.partition('=')
            if not separator or not count.isdigit() or name.startswith('-'):
                raise ValueError('Use Compose scale SERVICE=COUNT with explicit services')
            targets.append(name)
            scales[name] = int(count)
        if not targets:
            raise ValueError('Compose scale requires SERVICE=COUNT')
    else:
        raise ValueError(f'Unsupported Compose creation command {action}; use up, create or run.')
    if dry_run:
        return
    model = json.loads(_output(*command, 'config', '--format', 'json',
                               *(['--', *targets] if targets else [])))
    services = model.get('services') or {}
    # A run override supersedes the target mount, never a dependency's mount.
    overrides = {}
    for volume in volumes:
        parts = volume.split(':')
        if len(parts) == 1:
            overrides[parts[0]] = None  # anonymous volume
        elif len(parts) in (2, 3):
            source, destination = parts[:2]
            if source.startswith(('/', '.', '~')) or '/' in source:
                path = Path(source).expanduser()
                if not path.is_absolute():
                    # CLI run-volume sources use the invocation cwd, independently
                    # of --project-directory (verified with actual mounts).
                    path = ROOT / path
                overrides[destination] = str(path)
            else:
                overrides[destination] = None  # named volume
        else:
            raise ValueError('Unsupported Compose run volume syntax')
    for name, service in services.items():
        if action != 'run' and scales.get(name, service.get('scale', service.get('deploy', {}).get('replicas', 1))) == 0:
            continue
        if no_deps and targets and name not in targets:
            continue
        mounts = {mount['target']: mount for mount in service.get('volumes', [])}
        if action == 'run' and name == targets[0]:
            for destination, source in overrides.items():
                mounts[destination] = {'type': 'bind', 'source': source,
                                       'bind': {'create_host_path': False}} if source else {'type': 'volume'}
        for mount in mounts.values():
            if mount['type'] != 'bind' or mount.get('bind', {}).get('create_host_path', True):
                continue
            source = mount.get('source')
            if not source or not Path(source).exists():
                raise RuntimeError(f'Required bind source missing for service {name}: {source}. '
                                   'Restore the source or run its documented initialization before launching.')


def needs_networks(command, rest):
    """Only a none-mode run whose dependencies are also none-mode is offline.

    Compose can create a namespace owner's networks for service:/container:
    runs, or dependency networks for none-mode jobs, even with --no-deps.
    Unknown services are treated as networked.
    """
    if not rest or rest[0] in NO_NETWORKS:
        return False
    if rest[0] != 'run':
        return True
    service, _, _ = _run_target(rest)
    if service is None:
        return True
    config = json.loads(_output(*command, '--profile', '*', 'config', '--format', 'json'))
    # Compose validates the dependency graph (including cycles) when rendering.
    # --no-deps suppresses startup, but not dependency network creation.
    def networked(name):
        definition = (config.get('services') or {}).get(name) or {}
        return definition.get('network_mode') != 'none' or any(
            networked(dependency) for dependency in definition.get('depends_on') or {})
    return networked(service)


def split_passthrough(arguments):
    """Split `compose` passthrough arguments into (files, global options, dry run, rest).

    The rest starts with the Compose subcommand. Files are returned apart so that
    the engine files stay last. An unsupported global option is an error: the
    wrapper must know the project and model a launch uses.
    """
    files, options, dry_run = [], [], False
    rest = list(arguments)
    while rest and rest[0].startswith('-'):
        argument = rest.pop(0)
        if argument == '--dry-run' or argument.startswith('--dry-run='):
            dry_run = _dry_run_flag(argument)
            options.append(argument)
            continue
        name, value = argument, None
        if argument.startswith('--') and '=' in argument:
            name, value = argument.split('=', 1)
        elif not argument.startswith('--') and len(argument) > 2:
            name, value = argument[:2], argument[2:].removeprefix('=')
        if name not in GLOBAL_OPTIONS:
            raise ValueError(f'Unsupported Compose global option {name}. Supported before the subcommand: '
                             + ', '.join(sorted(GLOBAL_OPTIONS)) + ', --dry-run.')
        if value is None:
            if not rest:
                raise ValueError(f'{name} needs a value')
            value = rest.pop(0)
        if GLOBAL_OPTIONS[name] == 'file':
            files.append(value)
        else:
            options += [name, value]
    if rest and rest[0] == 'run':
        _, _, command_dry_run = _run_target(rest)
        if command_dry_run is not None:
            dry_run = command_dry_run
    else:
        arguments = iter(rest[1:])
        for argument in arguments:
            if argument == '--':
                break
            name, equals, _ = argument.partition('=')
            if name in CREATE_VALUES:
                # A value spelled --dry-run is still an operand. Native pflag
                # consumes it, so it must neither skip real launch preparation
                # nor override an actual global dry-run flag.
                if not equals:
                    next(arguments, None)
                continue
            if argument == '--dry-run' or argument.startswith('--dry-run='):
                dry_run = _dry_run_flag(argument)
    return files, options, dry_run, rest


if __name__ == '__main__':
    # For the Makefile: print the selected Compose command.
    if sys.argv[1:] == ['compose-command']:
        try:
            # Make runs this command with its own environment: drop the
            # endpoint overrides there too, as engine() does for this process.
            prefix = ['env', *(f'--unset={name}' for name in PODMAN_OVERRIDES)] if engine() == 'podman' else []
            print(' '.join([*prefix, *compose_base()]))
        except EngineError as error:
            raise SystemExit(str(error)) from None
    else:
        raise SystemExit('usage: deployment.py compose-command')
