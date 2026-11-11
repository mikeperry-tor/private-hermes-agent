#!/usr/bin/env python3
"""Read-only checks for required engine features and conflicting address pools."""
import argparse
import ipaddress
import json
import os
import re
import subprocess
import sys
from deployment import compose_files, engine


def output(*args):
    return subprocess.check_output(args, text=True).strip()


def version(value):
    match = re.search(r'(\d+)\.(\d+)\.(\d+)', value)
    if not match:
        raise SystemExit('Cannot recognize engine/Compose version: ' + value)
    return tuple(map(int, match.groups()))


def check_engine():
    if engine() == 'podman':
        # The stack creates its Podman networks with the podman command
        # (deployment.ensure_networks); netavark isolate=strict was qualified on 5.4.
        try:
            info = json.loads(output('podman', 'info', '--format', 'json'))
        except (OSError, subprocess.CalledProcessError) as error:
            raise SystemExit('The podman command is required with the Podman engine.') from error
        if version(info['version']['Version']) < (5, 4, 0):
            raise SystemExit('Podman 5.4+ is required for rootless network isolation.')
        if info['host']['security']['rootless'] is not True:
            raise SystemExit('Podman must run rootless: rootful bridge gateways are host addresses.')
        host = os.environ.get('DOCKER_HOST')
        socket_path = info['host'].get('remoteSocket', {}).get('path', '')
        if host and host.removeprefix('unix://') != socket_path.removeprefix('unix://'):
            raise SystemExit(f'DOCKER_HOST must name this user\'s Podman socket ({socket_path}) or be unset.')
    elif version(output('docker', 'version', '--format', '{{.Server.Version}}')) < (28, 0, 0):
        raise SystemExit('Docker Engine 28+ is required for isolated bridge gateway mode.')
    if version(output('docker', 'compose', 'version', '--short')) < (2, 36, 0):
        raise SystemExit('Docker Compose 2.36+ is required for this deployment.')


def subnets(network):
    # Docker reports IPAM.Config[].Subnet; native Podman inspect reports subnets[].subnet.
    entries = (network.get('IPAM') or {}).get('Config') or []
    found = [entry.get('Subnet') for entry in entries]
    found += [entry.get('subnet') for entry in network.get('subnets') or []]
    return [ipaddress.ip_network(value) for value in found if value]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('project', nargs='?', default='private-hermes')
    parser.add_argument('--funnel', action='store_true')
    arguments = parser.parse_args()
    project = arguments.project
    check_engine()
    command = ['docker', 'compose', '-p', project, *compose_files(arguments.funnel)]
    config = json.loads(output(*command, 'config', '--format', 'json'))
    selected = [ipaddress.ip_network(c['subnet']) for n in config['networks'].values()
                for c in n.get('ipam', {}).get('config', []) if 'subnet' in c]
    identifiers = output('docker', 'network', 'ls', '-q').split()
    existing = json.loads(output('docker', 'network', 'inspect', *identifiers)) if identifiers else []
    for network in existing:
        labels = network.get('Labels') or network.get('labels') or {}
        if labels.get('com.docker.compose.project') == project:
            continue
        name = network.get('Name') or network.get('name')
        for occupied in subnets(network):
            for candidate in selected:
                if candidate.version == occupied.version and candidate.overlaps(occupied):
                    raise SystemExit(f'Address conflict: {candidate} overlaps {name} ({occupied}). Stop the test/normal stack or coordinate a new address plan; no network was changed.')
    print('Engine features and address pools checked.')


if __name__ == '__main__':
    main()
