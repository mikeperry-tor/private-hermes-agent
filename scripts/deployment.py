"""Compose handles dotenv interpolation; this module validates feature settings."""
from functools import cache
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'components/webapp'))
from settings import Settings, proxy_config


def _output(*args):
    return subprocess.run(args, cwd=ROOT, text=True, capture_output=True, check=True).stdout


@cache
def engine():
    """Return 'podman' only when the engine positively identifies as Podman.

    Any other answer, including a failed query, selects Docker. On Docker the
    Docker files are then complete; on Podman netavark rejects their Docker
    bridge options, so startup stops instead of running with weaker isolation.
    """
    try:
        # podman-docker and docker shims run Podman as the `docker` command, and
        # `podman compose` points Compose at the Podman socket.
        if _output('docker', '--version').lower().startswith('podman version'):
            return 'podman'
        # The Docker CLI follows DOCKER_HOST and the current context, as Compose does.
        components = json.loads(_output('docker', 'version', '--format', '{{json .Server.Components}}'))
    except (OSError, subprocess.CalledProcessError, ValueError):
        return 'docker'
    names = [entry.get('Name') for entry in components or [] if isinstance(entry, dict)]
    return 'podman' if 'Podman Engine' in names else 'docker'


def compose_files(funnel, extra=()):
    """Return Compose file arguments. The Podman files must stay last."""
    files = ['compose.yaml', *(['compose.funnel.yaml'] if funnel else []), *extra]
    if engine() == 'podman':
        files += ['compose.podman.yaml', *(['compose.podman.funnel.yaml'] if funnel else [])]
    return [argument for name in files for argument in ('-f', name)]


def settings():
    result = subprocess.run(['docker', 'compose', *compose_files(False), 'config', '--format', 'json'],
                            cwd=ROOT, text=True, capture_output=True, check=True)
    return Settings.read(json.loads(result.stdout)['x-deployment'])


def compose(config, all_ingress=False):
    return ['docker', 'compose', *compose_files(config.funnel or all_ingress)]


def maintenance_compose(all_ingress=False, executor_build=False):
    # These operations must not start ingress, inference or the agent with
    # placeholders. Actual treasury policy remains in its mounted configuration.
    # Compose still interpolates unused services and publications.
    os.environ.update(TAILSCALE_FUNNEL_ENABLED='false', WEBAPP_EXTERNAL_CONTENT='off',
                      WEBAPP_BIND='127.0.0.1', WEBAPP_PORT='9120', WEBAPP_USERNAME='admin',
                      TAILSCALE_FUNNEL_HOST='', TAILSCALE_FUNNEL_PORT='443',
                      TAILSCALE_HOSTNAME='private-hermes', TEEP_HOST_PORT='8337', TEEP_SERVE_ARGS='')
    if not executor_build:
        # Saved-state inspection/shutdown do not select or build an executor.
        # An invalid optional desktop preference must not block those operations.
        os.environ['COMPUTER_USE_ENABLED'] = 'false'
    return ['docker', 'compose', *compose_files(all_ingress)]


def maintenance_command(arguments):
    if not arguments:
        return False
    if arguments[0] in ('build', 'logs', 'ps', 'top', 'port', 'exec', 'stop', 'down', 'rm', 'kill', 'pause', 'unpause'):
        return True
    # Explicit networkless maintenance jobs; do not normalize arbitrary launches.
    if arguments[0] != 'run' or '--no-deps' not in arguments:
        return False
    options = iter(arguments[1:])
    for value in options:
        if value in ('--rm', '--no-deps', '-T'):
            continue
        if value in ('--entrypoint', '--volume', '-v', '--env', '-e', '--user', '-u', '--name', '--workdir', '-w'):
            if next(options, None) is None:
                return False
            continue
        return value in ('hermes-config', 'setup-storage', 'mcp-config',
                         'x402_treazury-inspect', 'x402_treazury-admin')
    return False


def render(config):
    path = ROOT / 'config/webapp/proxy.cfg'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(proxy_config(config, loopback_forwarder=engine() == 'podman'))
