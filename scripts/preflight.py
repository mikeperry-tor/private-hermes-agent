#!/usr/bin/env python3
"""Read-only checks for required engine features and conflicting address pools."""
import argparse
import ipaddress
import json
import subprocess
import sys
import deployment
from deployment import compose_base, compose_files, engine, engine_command

ADDRESS_PLAN_HELP = ('Pinned subnets live in the networks: block of compose.yaml '
                     '(compose.funnel.yaml for funnel-link and tailscale-uplink).')


def output(*args):
    return subprocess.check_output(args, text=True).strip()


def check_engine():
    try:
        deployment.check_engine()
    except deployment.EngineError as error:
        raise SystemExit(str(error)) from None


def check_security_options(config):
    # Compose reads a seccomp profile file and sends its content through the
    # Docker-compatible API. Podman's API treats that value as a file path, so
    # the container cannot be created. Normal Podman services use native defaults.
    if engine() != 'podman':
        return
    for name, service in sorted(config['services'].items()):
        for option in service.get('security_opt') or []:
            if option.startswith('seccomp=') and option != 'seccomp=unconfined':
                raise SystemExit(f'Service {name} selects a custom seccomp profile ({option}). '
                                 'The Compose provider sends inline JSON, but Podman expects a host filename. '
                                 'Use the native Podman default without a seccomp override, or Docker for custom profiles.')


def subnets(network):
    # Docker reports IPAM.Config[].Subnet; native Podman inspect reports subnets[].subnet.
    entries = (network.get('IPAM') or {}).get('Config') or []
    found = [entry.get('Subnet') for entry in entries]
    found += [entry.get('subnet') for entry in network.get('subnets') or []]
    return [ipaddress.ip_network(value) for value in found if value]


def labels(network):
    return network.get('Labels') or network.get('labels') or {}


def name(network):
    return network.get('Name') or network.get('name')


def declared_subnets(config):
    return [(key, ipaddress.ip_network(entry['subnet']))
            for key, network in (config.get('networks') or {}).items()
            if not network.get('external')
            for entry in (network.get('ipam') or {}).get('config') or [] if 'subnet' in entry]


def check_address_conflicts(project, config, existing):
    declared = declared_subnets(config)
    for index, (key, candidate) in enumerate(declared):
        for other_key, other in declared[index + 1:]:
            if candidate.version == other.version and candidate.overlaps(other):
                raise SystemExit(f'Address conflict: networks "{key}" ({candidate}) and "{other_key}" '
                                 f'({other}) declare overlapping subnets. No network was changed. '
                                 f'Give each network a distinct, non-overlapping subnet. {ADDRESS_PLAN_HELP}')
    for network in existing:
        network_labels, network_name = labels(network), name(network)
        occupied = subnets(network)
        if network_labels.get('com.docker.compose.project') == project:
            key = network_labels.get('com.docker.compose.network')
            desired = sorted(str(value) for declared_key, value in declared if declared_key == key)
            actual = sorted(str(value) for value in occupied)
            if key and desired and actual != desired:
                raise SystemExit(f'Address plan changed: network {network_name} ("{key}") already uses '
                                 f'{", ".join(actual) or "no subnet"}, but the stack now declares '
                                 f'{", ".join(desired)}. No network was changed. '
                                 f'Run make down so the project networks are removed, then make up to recreate them. '
                                 f'{ADDRESS_PLAN_HELP}')
            continue
        for occupied_network in occupied:
            for key, candidate in declared:
                if candidate.version != occupied_network.version or not candidate.overlaps(occupied_network):
                    continue
                raise SystemExit(f'Address conflict: subnet {candidate} for network "{key}" overlaps existing '
                                 f'network {network_name} ({occupied_network}). No network was changed. '
                                 f'Choose a different subnet for "{key}". {ADDRESS_PLAN_HELP} '
                                 f'If {network_name} was allocated automatically from Docker\'s default address '
                                 f'pools, you can instead add or enlarge "default-address-pools" under '
                                 f'Docker Desktop > Settings > Docker Engine (~/.docker/daemon.json) and apply '
                                 f'the change; that restarts Docker and all running containers.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('project', nargs='?', default='private-hermes')
    parser.add_argument('--funnel', action='store_true')
    arguments = parser.parse_args()
    project = arguments.project
    check_engine()
    command = [*compose_base(), '-p', project, *compose_files(arguments.funnel)]
    config = json.loads(output(*command, 'config', '--format', 'json'))
    check_security_options(config)
    identifiers = output(*engine_command(), 'network', 'ls', '-q').split()
    existing = json.loads(output(*engine_command(), 'network', 'inspect', *identifiers)) if identifiers else []
    check_address_conflicts(project, config, existing)
    print('Engine features and address pools checked.')


if __name__ == '__main__':
    main()
