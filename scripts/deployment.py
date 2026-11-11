"""Compose handles dotenv interpolation; this module validates feature settings."""
from functools import cache
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'components/webapp'))
from settings import Settings, proxy_config


def _output(*args):
    return subprocess.run(args, cwd=ROOT, text=True, capture_output=True, check=True).stdout


def _endpoint_components(url):
    """Return the component names that the engine API at a unix:// URL reports."""
    if not url.startswith('unix://'):
        raise ValueError('Only unix:// engine endpoints can be identified')
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(10)
        connection.connect(url[len('unix://'):])
        connection.sendall(b'GET /version HTTP/1.0\r\nHost: engine\r\n\r\n')
        response = b''
        while chunk := connection.recv(65536):
            response += chunk
    body = response.partition(b'\r\n\r\n')[2]
    return [entry.get('Name') for entry in json.loads(body).get('Components') or [] if isinstance(entry, dict)]


@cache
def engine():
    """Return 'podman' only when the endpoint Compose uses identifies as Podman.

    Any other answer, including a failed query, selects Docker, whose files are
    complete on Docker. With the Docker files, Podman refuses to start the stack:
    Compose rejects healthcheck.start_interval for Podman's API version.
    """
    try:
        if _output('docker', '--version').lower().startswith('podman version'):
            # podman-docker or a shim: `podman compose` passes DOCKER_HOST to
            # Compose when it is set, so identify that endpoint; otherwise
            # Compose uses the user's Podman socket.
            host = os.environ.get('DOCKER_HOST')
            names = _endpoint_components(host) if host else ['Podman Engine']
        else:
            # The Docker CLI follows DOCKER_HOST and the current context, as Compose does.
            components = json.loads(_output('docker', 'version', '--format', '{{json .Server.Components}}'))
            names = [entry.get('Name') for entry in components or [] if isinstance(entry, dict)]
    except (OSError, subprocess.CalledProcessError, ValueError, AttributeError):
        return 'docker'
    return 'podman' if 'Podman Engine' in names else 'docker'


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
        found = subprocess.run(['podman', 'network', 'inspect', name], cwd=ROOT, text=True, capture_output=True)
        if found.returncode == 0:
            actual = json.loads(found.stdout)[0]
            actual_options = actual.get('options') or {}
            actual_subnets = sorted(entry['subnet'] for entry in actual.get('subnets') or [])
            if (any(actual_options.get(option) != value for option, value in options.items())
                    or bool(actual.get('internal')) != internal
                    or (subnets and actual_subnets != subnets)):
                raise RuntimeError(f'Podman network {name} does not have the options the stack declares. '
                                   'Run make down so that it is created again.')
            continue
        arguments = ['podman', 'network', 'create',
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
