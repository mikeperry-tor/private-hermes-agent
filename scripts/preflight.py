#!/usr/bin/env python3
"""Read-only checks for required engine features and conflicting address pools."""
import argparse
import errno
import ipaddress
import json
import socket
import subprocess
import sys
import textwrap
import deployment
from deployment import compose_base, compose_files, engine, engine_command
sys.path.insert(0, str(deployment.ROOT / 'components/network'))
from addressing import validate_network_prefix, validate_project_name
from integrations import grants

ADDRESS_PLAN_HELP = ('Set a distinct NETWORK_PREFIX in .env (for example, NETWORK_PREFIX=10.205) '
                     'to move all pinned subnets in the networks: block of compose.yaml.',
                     'Funnel networks (funnel-link and tailscale-uplink) live in compose.funnel.yaml.')


def diagnostic(*sentences):
    """One sentence per line, each wrapped to 80 columns."""
    return '\n'.join(textwrap.fill(sentence, width=80, break_long_words=False,
                                   break_on_hyphens=False) for sentence in sentences)


def fail(*paragraphs):
    """Raise a blank-line-separated diagnostic with space after the command."""
    raise SystemExit('\n' + '\n\n'.join(diagnostic(*paragraph) for paragraph in paragraphs))


def display_address(address, port):
    address = address or '0.0.0.0'
    return f'[{address}]:{port}' if ':' in address else f'{address}:{port}'


def output(*args):
    return subprocess.check_output(args, text=True).strip()


def check_engine():
    try:
        deployment.check_engine()
    except deployment.EngineError as error:
        raise SystemExit(str(error)) from None


def engine_pool_hint(verb='add or enlarge'):
    if engine() == 'podman':
        return (f'You can instead {verb} default_subnet_pools in containers.conf '
                'if another stack relies on automatic Podman network allocation.')
    return (f'You can instead {verb} "default-address-pools" under Docker Desktop > '
            'Settings > Docker Engine (~/.docker/daemon.json) and apply the change; '
            'that restarts Docker and all running containers.')


def inspect_resources(kind, identifiers):
    """Inspect existing engine objects, tolerating entries removed concurrently."""
    if not identifiers:
        return []
    command = [*engine_command(), *kind, 'inspect']
    try:
        return json.loads(output(*command, *identifiers))
    except subprocess.CalledProcessError:
        found = []
        for identifier in identifiers:
            try:
                found.extend(json.loads(output(*command, identifier)))
            except subprocess.CalledProcessError:
                continue
        return found


def parse_network(value, context):
    try:
        return ipaddress.ip_network(value, strict=False)
    except ValueError as error:
        fail(
            (f'Invalid subnet "{value}" for {context}: {error}.',),
            ('No network was changed.',),
            ADDRESS_PLAN_HELP,
        )


def check_security_options(config):
    # Compose reads a seccomp profile file and sends its content through the
    # Docker-compatible API. Podman's API treats that value as a file path, so
    # the container cannot be created. Normal Podman services use native defaults.
    if engine() != 'podman':
        return
    for name, service in sorted(config['services'].items()):
        for option in service.get('security_opt') or []:
            if option.startswith('seccomp=') and option != 'seccomp=unconfined':
                fail(
                    (f'Service {name} selects a custom seccomp profile ({option}).',
                     'The Compose provider sends inline JSON, but Podman expects a host filename.',
                     'Use the native Podman default without a seccomp override, or Docker for custom profiles.'),
                )


def subnets(network):
    # Docker reports IPAM.Config[].Subnet; native Podman inspect reports subnets[].subnet.
    entries = (network.get('IPAM') or {}).get('Config') or []
    found = [entry.get('Subnet') for entry in entries]
    found += [entry.get('subnet') for entry in network.get('subnets') or []]
    result = []
    for value in found:
        if not value:
            continue
        try:
            result.append(ipaddress.ip_network(value, strict=False))
        except ValueError:
            continue
    return result


def labels(network):
    return network.get('Labels') or network.get('labels') or {}


def name(network):
    return network.get('Name') or network.get('name')


def declared_subnets(config):
    return [(key, parse_network(entry['subnet'], f'network "{key}"'))
            for key, network in (config.get('networks') or {}).items()
            if not network.get('external')
            for entry in (network.get('ipam') or {}).get('config') or [] if 'subnet' in entry]


def check_pinned_networks(config):
    for key, network in (config.get('networks') or {}).items():
        if network.get('external'):
            continue
        entries = (network.get('ipam') or {}).get('config') or []
        if not any('subnet' in entry for entry in entries):
            fail(
                (f'Network "{key}" has no pinned subnet.',),
                ('No network was created.',),
                ('Set ipam.config[].subnet for it so the engine does not allocate from '
                 'its default address pools.', *ADDRESS_PLAN_HELP, engine_pool_hint('enlarge')),
            )


def check_address_conflicts(project, config, existing):
    declared = declared_subnets(config)
    declared_keys = {key for key, _ in declared}
    for index, (key, candidate) in enumerate(declared):
        for other_key, other in declared[index + 1:]:
            if candidate.version == other.version and candidate.overlaps(other):
                fail(
                    (f'Address conflict: networks "{key}" ({candidate}) and "{other_key}" '
                     f'({other}) declare overlapping subnets.',),
                    ('No network was changed.',),
                    ('Give each network a distinct, non-overlapping subnet.', *ADDRESS_PLAN_HELP),
                )
    for network in existing:
        network_labels, network_name = labels(network), name(network)
        occupied = subnets(network)
        if network_labels.get('com.docker.compose.project') == project:
            key = network_labels.get('com.docker.compose.network')
            if not key:
                continue
            if key in declared_keys:
                desired_networks = [value for declared_key, value in declared if declared_key == key]
                versions = {value.version for value in desired_networks}
                desired = sorted(str(value) for value in desired_networks)
                actual = sorted(str(value) for value in occupied if value.version in versions)
                if actual != desired:
                    fail(
                        (f'Address plan changed: network {network_name} ("{key}") already uses '
                         f'{", ".join(actual) or "no subnet"}, but the stack now declares '
                         f'{", ".join(desired)}.',),
                        ('No network was changed.',),
                        ('Run make down to remove the project networks.',
                         'Run make up to recreate them.',
                         'If you are starting a separate instance, set a distinct COMPOSE_PROJECT_NAME in .env instead.',
                         *ADDRESS_PLAN_HELP),
                    )
                continue
        for occupied_network in occupied:
            for key, candidate in declared:
                if candidate.version != occupied_network.version or not candidate.overlaps(occupied_network):
                    continue
                if network_labels.get('com.docker.compose.project') == project:
                    fail(
                        (f'Address conflict: subnet {candidate} for network "{key}" overlaps '
                         f'existing project network {network_name} ({occupied_network}).',),
                        ('No network was changed.',),
                        ('Run make down to remove stale project networks, then run make up.',
                         *ADDRESS_PLAN_HELP),
                    )
                fail(
                    (f'Address conflict: subnet {candidate} for network "{key}" overlaps existing '
                     f'network {network_name} ({occupied_network}).',),
                    ('No network was changed.',),
                    (f'Choose a different subnet for "{key}".', *ADDRESS_PLAN_HELP,
                     f'If {network_name} was allocated automatically from the engine\'s default address '
                     'pools: ' + engine_pool_hint()),
                )


def published_values(published):
    value = str(published or '')
    if value.isdigit():
        port = int(value)
        return [port] if 1 <= port <= 65535 else []
    start, separator, end = value.partition('-')
    if separator and start.isdigit() and end.isdigit():
        low, high = int(start), int(end)
        if 1 <= low <= high <= 65535:
            return list(range(low, high + 1))
    return []


def published_ports(config):
    declared = []
    for service, definition in (config.get('services') or {}).items():
        for entry in definition.get('ports') or []:
            if not isinstance(entry, dict):
                continue
            host_ip = entry.get('host_ip') or '0.0.0.0'
            protocol = (entry.get('protocol') or 'tcp').lower()
            declared += [(service, host_ip, port, protocol)
                         for port in published_values(entry.get('published'))]
    return declared


def bindings_overlap(first, second):
    first, second = first or '0.0.0.0', second or '0.0.0.0'
    # A wildcard host IP may bind dual-stack on Docker/macOS/Linux; check same
    # family or wildcard-to-wildcard/unspecified overlap conservatively.
    if (':' in first) != (':' in second):
        return first == '::' or second == '::'
    return first in ('0.0.0.0', '::') or second in ('0.0.0.0', '::') or first == second


def container_labels(container):
    return ((container.get('Config') or {}).get('Labels') or container.get('Labels')
            or container.get('labels') or {})


def _parse_port_key(port_key):
    _, _, protocol = str(port_key).partition('/')
    return (protocol or 'tcp').lower()


def port_bindings(container):
    # Docker populates NetworkSettings.Ports with live bindings; fall back to
    # HostConfig.PortBindings when NetworkSettings.Ports is absent or empty
    # (for example, some Podman inspect payloads).
    ports = (container.get('NetworkSettings') or {}).get('Ports') or {}
    has_live = any(bindings for bindings in ports.values())
    source = ports if has_live else ((container.get('HostConfig') or {}).get('PortBindings') or {})
    found = set()
    for port_key, bindings in source.items():
        protocol = _parse_port_key(port_key)
        for binding in bindings or []:
            port = binding.get('HostPort') or binding.get('host_port')
            if port and str(port).isdigit() and 1 <= int(port) <= 65535:
                address = binding.get('HostIp') or binding.get('host_ip') or ''
                found.add((address, int(port), protocol))
    return sorted(found)


def check_published_ports(project, config, containers):
    declared = published_ports(config)
    for index, (service, host_ip, port, protocol) in enumerate(declared):
        for other_service, other_host, other_port, other_protocol in declared[index + 1:]:
            if (port == other_port and protocol == other_protocol
                    and bindings_overlap(host_ip, other_host)):
                fail(
                    (f'Host port conflict: {service} publishes {display_address(host_ip, port)}/{protocol} and '
                     f'{other_service} publishes {display_address(other_host, other_port)}/{other_protocol}.',),
                    ('No container was started.',),
                    ('Set distinct host ports in .env before starting: TEEP_HOST_PORT for teep, or '
                     'WEBAPP_BIND/WEBAPP_PORT for the webapp (see docs/configuration.md).',),
                )
    own_bindings, foreign_bindings = [], []
    for container in containers:
        bindings = port_bindings(container)
        if not bindings:
            continue
        own = container_labels(container).get('com.docker.compose.project') == project
        container_name = (container.get('Name') or container.get('name') or 'container').lstrip('/')
        for address, port, protocol in bindings:
            if own:
                own_bindings.append((address, port, protocol))
            else:
                foreign_bindings.append((container_name, address, port, protocol))
    for service, host_ip, port, protocol in declared:
        if any(own_port == port and own_protocol == protocol and bindings_overlap(host_ip, own_address)
               for own_address, own_port, own_protocol in own_bindings):
            continue
        conflict = next(
            ((cname, faddr) for cname, faddr, fport, fproto in foreign_bindings
             if fport == port and fproto == protocol and bindings_overlap(host_ip, faddr)),
            None,
        )
        if conflict is None:
            family = socket.AF_INET6 if ':' in host_ip else socket.AF_INET
            kind = socket.SOCK_STREAM if protocol == 'tcp' else socket.SOCK_DGRAM
            with socket.socket(family, kind) as probe:
                try:
                    if kind == socket.SOCK_STREAM:
                        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    probe.bind((host_ip, port))
                    if kind == socket.SOCK_STREAM:
                        probe.listen(1)
                except OSError as error:
                    # A privileged or otherwise unbindable address is left to the engine.
                    if error.errno != errno.EADDRINUSE:
                        continue
                else:
                    continue
        owner = ''
        if conflict:
            owner = f' by container {conflict[0]} ({display_address(conflict[1], port)})'
        fail(
            (f'Host port conflict: service {service} publishes {display_address(host_ip, port)}/{protocol}, '
             f'but it is already in use{owner}.',),
            ('No container was started.',),
            ('Set an unused host port in .env before starting: TEEP_HOST_PORT for teep, or '
             'WEBAPP_BIND/WEBAPP_PORT for the webapp (see docs/configuration.md).',
             'Stopping the process or stack using the port also resolves it; '
             'the stack never changes a published port silently.'),
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('project', nargs='?')
    parser.add_argument('--funnel', action='store_true')
    parser.add_argument('--skip-ports', action='store_true')
    parser.add_argument('--services', nargs='+', help='Check the selected Compose services and their networks')
    arguments = parser.parse_args()
    check_engine()
    options = ['-p', arguments.project] if arguments.project else []
    command = [*compose_base(), *options, *compose_files(arguments.funnel)]
    try:
        rendered = output(*command, 'config', '--format', 'json',
                          *(['--', *arguments.services] if arguments.services else []))
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or error.stdout or '').strip()
        fail((detail or 'Compose could not render the deployment configuration.',),
             ('No network or container was changed.',))
    config = json.loads(rendered)
    project = arguments.project or config.get('name', 'private-hermes')
    try:
        validate_project_name(project)
        declared_project = (config.get('x-deployment') or {}).get('project_name')
        if declared_project is not None:
            validate_project_name(declared_project)
        declared_prefix = (config.get('x-deployment') or {}).get('network_prefix')
        if declared_prefix is not None:
            validate_network_prefix(declared_prefix)
    except ValueError as error:
        fail((str(error),), ('No network or container was changed.',))
    check_security_options(config)
    check_pinned_networks(config)
    identifiers = output(*engine_command(), 'network', 'ls', '-q').split()
    existing = inspect_resources(('network',), identifiers)
    check_address_conflicts(project, config, existing)
    try:
        grants(config.get('services', {}).get('tor', {}).get('environment') or {},
               (str(network) for entry in existing for network in subnets(entry) if network.version == 4))
    except ValueError as error:
        fail((str(error),), ('No container was started.',))
    if not arguments.skip_ports:
        identifiers = output(*engine_command(), 'ps', '-q').split()
        containers = inspect_resources((), identifiers)
        check_published_ports(project, config, containers)
    print('Engine features, address pools and published ports checked.'
          if not arguments.skip_ports else 'Engine features and address pools checked.')


if __name__ == '__main__':
    main()
