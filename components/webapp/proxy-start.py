"""Install a fixed-backend firewall before dropping privilege and starting HAProxy."""
import json
import os
from pathlib import Path
import subprocess
import sys


def run(*args, **kwargs):
    return subprocess.run(args, check=True, text=True, **kwargs)


def firewall(forwarder, edge, edge_ip, port, funnel):
    """Return the IPv4 iptables-restore input for HAProxy's namespace."""
    if forwarder == 'interface':
        # Docker delivers published connections on the publication interface.
        rules = [f'-A INPUT -i {edge} -d {edge_ip}/32 -p tcp --dport {port} -m conntrack --ctstate NEW -j ACCEPT']
    else:
        # The rootless Podman port forwarder runs in this namespace and connects
        # over loopback. Only processes in this namespace can send on lo; traffic
        # from the connected networks arrives on other interfaces and stays dropped.
        rules = [f'-A INPUT -i lo -p tcp --dport {port} -m conntrack --ctstate NEW -j ACCEPT',
                 f'-A OUTPUT -o lo -p tcp --dport {port} -m conntrack --ctstate NEW -j ACCEPT']
    if funnel:
        rules += ['-A INPUT -s 10.203.87.2/32 -d 10.203.87.3/32 -p tcp --dport 8443 -m conntrack --ctstate NEW -j ACCEPT']
    return '\n'.join([
        '*filter', ':INPUT DROP [0:0]', ':OUTPUT DROP [0:0]', ':FORWARD DROP [0:0]',
        '-A INPUT -m conntrack --ctstate ESTABLISHED -j ACCEPT',
        '-A OUTPUT -m conntrack --ctstate ESTABLISHED -j ACCEPT',
        *rules,
        '-A OUTPUT -d 10.203.85.2/32 -p tcp --dport 9120 -m conntrack --ctstate NEW -j ACCEPT',
        'COMMIT', '',
    ])


def main():
    # Fail closed on any error, including restarts with existing interfaces.
    for binary in ('iptables', 'ip6tables'):
        for chain in ('INPUT', 'OUTPUT', 'FORWARD'):
            run(binary, '-P', chain, 'DROP')
    policy = os.environ.get('WEBAPP_EXTERNAL_CONTENT')
    if policy not in ('tor_proxied', 'ask', 'off', 'browser_native'):
        raise ValueError('Invalid external-content policy')
    config = Path('/usr/local/etc/haproxy/haproxy.cfg').read_text()
    if config.splitlines()[0] != f'# WEBAPP_EXTERNAL_CONTENT={policy}':
        raise ValueError('External-content policy mismatch: regenerate ingress and recreate services')
    # compose.podman.yaml selects the loopback mode; see firewall().
    forwarder = os.environ.get('PRIVATE_HERMES_PORT_FORWARDER', 'interface')
    if forwarder not in ('interface', 'loopback'):
        raise ValueError('Invalid port forwarder mode')
    if config.splitlines()[1:2] != [f'# PORT_FORWARDER={forwarder}']:
        raise ValueError('Port forwarder mismatch: regenerate ingress and recreate services')
    port = int(os.environ['WEBAPP_PORT'])
    if not 1 <= port <= 65535:
        raise ValueError('Invalid webapp port')
    enabled = os.environ.get('TAILSCALE_FUNNEL_ENABLED', 'false')
    if enabled not in ('true', 'false'):
        raise ValueError('Invalid Funnel enablement')
    addresses = json.loads(run('ip', '-j', '-4', 'addr', capture_output=True).stdout)
    edge = [entry['ifname'] for entry in addresses if entry['ifname'] != 'lo'
            and any(info['scope'] == 'global' for info in entry['addr_info'])
            and not any(info['local'] in ('10.203.85.3', '10.203.87.3')
                        for info in entry['addr_info'])]
    if len(edge) != 1:
        raise ValueError('Expected exactly one host publication interface')
    edge_ip = next(info['local'] for entry in addresses if entry['ifname'] == edge[0]
                   for info in entry['addr_info'] if info['scope'] == 'global')
    os.environ['PRIVATE_HERMES_EDGE_IP'] = edge_ip
    run('iptables-restore', input=firewall(forwarder, edge[0], edge_ip, port, enabled == 'true'))
    run('ip6tables-restore', input='\n'.join([
        '*filter', ':INPUT DROP [0:0]', ':OUTPUT DROP [0:0]', ':FORWARD DROP [0:0]',
        'COMMIT', '',
    ]))
    # Capability bounding-set removal is irreversible for HAProxy and children.
    # Docker exec remains an operator-controlled privileged debugging interface.
    os.execvp('setpriv', ['setpriv', '--reuid=10005', '--regid=10005', '--clear-groups',
                         '--bounding-set=-all', '--inh-caps=-all', '--ambient-caps=-all',
                         '--no-new-privs', 'haproxy', *sys.argv[1:]])


if __name__ == '__main__':
    main()
