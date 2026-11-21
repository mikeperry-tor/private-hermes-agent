"""Exact IPv4 TCP exceptions shared by the agent and its trusted gateway."""
import ipaddress
import re

HOST_PORTS = 'HERMES_INTEGRATIONS_ALLOWED_HOST_PORTS'
LAN_ENDPOINTS = 'HERMES_INTEGRATIONS_LAN_ENDPOINTS'
HOST_ALIAS = '198.18.255.254'
RFC1918 = tuple(map(ipaddress.IPv4Network, ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')))
# Include the networks that neither namespace sees in its connected routes.
RESERVED = tuple(map(ipaddress.IPv4Network, (
    *(f'10.203.{subnet}.0/24' for subnet in range(80, 92)),
    '10.204.80.0/30', '10.204.81.0/30',
)))


def entries(environment, name):
    value = environment.get(name, 'none').strip()
    return [] if value == 'none' else [entry.strip() for entry in value.split(',')]


def port(value, name):
    if not re.fullmatch(r'[0-9]{1,5}', value) or not 1 <= int(value) <= 65535:
        raise ValueError(f'{name} must contain exact numeric TCP ports from 1 to 65535, or none')
    return int(value)


def grants(environment, connected=()):
    host = sorted({port(value, HOST_PORTS) for value in entries(environment, HOST_PORTS)})
    excluded = (*RESERVED, *map(ipaddress.IPv4Network, connected))
    lan = set()
    for entry in entries(environment, LAN_ENDPOINTS):
        address, _, number = entry.partition(':')
        try:
            address = ipaddress.IPv4Address(address)
        except ValueError:
            raise ValueError(f'{LAN_ENDPOINTS} must contain literal RFC1918 IPv4 address:port pairs, or none') from None
        if not any(address in network for network in RFC1918) or any(address in network for network in excluded):
            raise ValueError(f'{LAN_ENDPOINTS} targets must be RFC1918 addresses outside container networks')
        lan.add((str(address), port(number, LAN_ENDPOINTS)))
    return host, sorted(lan)
