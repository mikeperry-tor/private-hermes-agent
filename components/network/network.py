"""Own the agent/executor network namespaces and a separate transparent router.

Only this trusted service has NET_ADMIN during initialization. Application
containers share its namespace, but have neither network administration nor
raw-packet capability. Steady-state owners drop identity and all capability sets.
"""
import ipaddress
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from addressing import (Addresses, GRE_AGENT_INNER, GRE_AGENT_PEER,
                        GRE_EXECUTOR_INNER, GRE_EXECUTOR_PEER, HOST_ALIAS,
                        network_prefix)
from onion import require_secret, read_address
from integrations import RFC1918, grants

# Block non-public IPv4 destinations even when applications use literal IPs or
# public DNS returns a private answer. Explicit service grants precede this list.
DENIED = (
    '0.0.0.0/8', '10.0.0.0/8', '100.64.0.0/10', '127.0.0.0/8',
    '169.254.0.0/16', '172.16.0.0/12', '192.0.0.0/24', '192.0.2.0/24',
    '192.88.99.0/24', '192.168.0.0/16', '198.18.0.0/15',
    '198.51.100.0/24', '203.0.113.0/24', '224.0.0.0/3',
)


def run(*args, **kwargs):
    return subprocess.run(args, check=True, text=True, **kwargs)


def connected():
    routes = json.loads(run('ip', '-j', '-4', 'route', 'show', 'scope', 'link', capture_output=True).stdout)
    return [r['dst'] for r in routes if r.get('dst') and r['dst'] != 'default']


def apply(raw, nat, incoming, outgoing, early_output=(), forwarding=()):
    # The namespace is exclusively managed here. Restores are atomic per table.
    # Drop policies close any gaps across tables and on reinitialization.
    for binary in ('iptables', 'ip6tables'):
        for chain in ('INPUT', 'OUTPUT', 'FORWARD'):
            run(binary, '-P', chain, 'DROP')
    text = '\n'.join([
        '*raw', ':PREROUTING ACCEPT [0:0]', ':OUTPUT ACCEPT [0:0]', *raw, 'COMMIT',
        '*nat', ':PREROUTING ACCEPT [0:0]', ':INPUT ACCEPT [0:0]',
        ':OUTPUT ACCEPT [0:0]', ':POSTROUTING ACCEPT [0:0]', *nat, 'COMMIT',
        '*filter', ':INPUT DROP [0:0]', ':OUTPUT DROP [0:0]', ':FORWARD DROP [0:0]',
        '-A INPUT -i lo -j ACCEPT', '-A OUTPUT -o lo -j ACCEPT',
        *early_output, *forwarding,
        '-A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT',
        '-A OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT',
        *incoming, *outgoing, 'COMMIT', '',
    ])
    run('iptables-restore', input=text)
    run('ip6tables-restore', input='\n'.join([
        '*filter', ':INPUT DROP [0:0]', ':OUTPUT DROP [0:0]', ':FORWARD DROP [0:0]',
        '-A INPUT -i lo -j ACCEPT', '-A OUTPUT -o lo -j ACCEPT', 'COMMIT', '',
    ]))


def drop(uid, gid, *command):
    os.execv('/bin/setpriv', ['setpriv', f'--reuid={uid}', f'--regid={gid}',
                              '--clear-groups', '--bounding-set=-all', '--inh-caps=-all',
                              '--ambient-caps=-all', '--no-new-privs', *command])


def wait():
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    while True:
        signal.pause()


def deny(chain, networks):
    return [f'-A {chain} -d {network} -j DROP' for network in networks]


def mcp_grants(addresses=None):
    addresses = addresses or Addresses(network_prefix(os.environ))
    entries = json.loads(Path('/etc/private-hermes/mcp-allowlist.json').read_text())
    if not isinstance(entries, list):
        raise ValueError('MCP allowlist must be a list')
    rules = []
    subnet = ipaddress.IPv4Network(addresses.mcp_access_subnet)
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {'ip', 'port'}:
            raise ValueError('Each MCP grant must contain only ip and port')
        address = ipaddress.IPv4Address(entry['ip'])
        port = entry['port']
        if address not in subnet or int(address) & 255 in (0, 1, 2, 255):
            raise ValueError('MCP grants must target service addresses on mcp-access')
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError('MCP port must be an integer from 1 to 65535')
        rules.append(f'-A OUTPUT -d {address}/32 -p tcp --dport {port} -j ACCEPT')
    return rules


def tunnel(name, local, remote, address):
    present = subprocess.run(['ip', 'link', 'show', name], capture_output=True).returncode == 0
    if not present:
        # Netlink lets the kernel load ip_gre on demand; the ioctl path of
        # `ip tunnel add` cannot do that from a rootless container engine.
        run('ip', 'link', 'add', name, 'type', 'gre', 'local', local, 'remote', remote, 'ttl', '64')
    run('ip', 'addr', 'replace', address, 'dev', name)
    run('ip', 'link', 'set', name, 'mtu', '1400', 'up')


def endpoint(role):
    addresses = Addresses(network_prefix(os.environ))
    agent = role == 'agent'
    gateway = addresses.tor_agent_route if agent else addresses.tor_executor_route
    outer = addresses.agent_route if agent else addresses.executor_route
    inner = GRE_AGENT_INNER if agent else GRE_EXECUTOR_INNER
    peer = GRE_AGENT_PEER if agent else GRE_EXECUTOR_PEER
    tunnel('tor-route', outer, gateway, inner + '/30')
    outgoing = [f'-A OUTPUT -d {gateway}/32 -p udp --dport 53 -j ACCEPT',
                f'-A OUTPUT -d {gateway}/32 -p gre -j ACCEPT']
    incoming, early_output = [], []
    if agent:
        host, lan = grants(os.environ, connected())
        destinations = [(HOST_ALIAS, port) for port in host] + lan
        early_output += [
            f'-A OUTPUT -o tor-route -d {address}/32 -p tcp --dport {port} '
            '-m owner --uid-owner 10000 -j ACCEPT'
            for address, port in destinations
        ]
        # A preexisting connection cannot bypass the current owner/tuple policy.
        early_output += [f'-A OUTPUT -o tor-route -d {network} -j DROP' for network in DENIED]
        incoming += [f'-A INPUT -s {addresses.proxy_webapp_backend}/32 -d {addresses.agent_webapp_backend}/32 -p tcp --dport 9120 -j ACCEPT']
        outgoing += [
            f'-A OUTPUT -d {addresses.teep_inference}/32 -p tcp --dport 8337 -j ACCEPT',
            f'-A OUTPUT -d {addresses.executor_execution_control}/32 -p tcp --dport 2222 -j ACCEPT',
            *mcp_grants(addresses),
        ]
    else:
        incoming += [f'-A INPUT -s {addresses.agent_execution_control}/32 -d {addresses.executor_execution_control}/32 -p tcp --dport 2222 -j ACCEPT']
    outgoing += deny('OUTPUT', (*DENIED, *connected()))
    outgoing += ['-A OUTPUT -p tcp -j ACCEPT']
    # Drop embedded Docker DNS before its DNAT changes port 53. Also prevents
    # a loopback exception from admitting queries to Docker's resolver.
    apply(['-A OUTPUT -d 127.0.0.11/32 -j DROP'], [], incoming, outgoing, early_output)
    run('ip', 'route', 'replace', 'default', 'via', peer, 'dev', 'tor-route')
    Path('/tmp/network-ready').touch()
    print(f'{role}: firewall and default route installed; dropping privilege', flush=True)
    drop(65534, 65534, sys.executable, os.path.abspath(__file__), 'wait')


IP_FORWARD = Path('/proc/sys/net/ipv4/ip_forward')
LOCAL_GRANT_WARNINGS = Path('/tmp/local-grant-warnings')


def uplink_route(address, uplink, uplink_address):
    result = subprocess.run(['ip', '-j', '-4', 'route', 'get', address], text=True, capture_output=True)
    if result.returncode == 0:
        route, = json.loads(result.stdout)
        return (route.get('dev') == uplink and route.get('gateway')
                and route.get('prefsrc') == uplink_address)
    return False


def host_backend(podman, uplink, addresses=None):
    addresses = addresses or Addresses(network_prefix(os.environ))
    try:
        address = ipaddress.IPv4Address(os.environ.get('PRIVATE_HERMES_ENGINE_HOST_ADDRESS', ''))
    except ipaddress.AddressValueError:
        return None
    if any(address in network for network in addresses.reserved):
        return None
    # A link-local address is eligible only from Podman's native static
    # alias. Ordinary LAN rules never admit any link-local address.
    if (any(address in network for network in RFC1918)
            or (podman and address.is_link_local)):
        if uplink_route(str(address), uplink, addresses.tor_uplink):
            return str(address)
    return None


def local_forwarding(client, uplink, destinations, uplink_address):
    raw, nat, forwarding = [], [], []
    for original, backend, port in destinations:
        ingress = f'-i client-0 -s {client}/32 -p tcp'
        target = f'-d {original}/32 --dport {port}'
        connection = f'--ctorigsrc {client} --ctorigdst {original} --ctorigdstport {port}'
        actual = f'-d {backend}/32 --dport {port}'
        raw += [f'-A PREROUTING {ingress} {target} -j ACCEPT']
        if original == backend:
            nat += [f'-A PREROUTING {ingress} {target} -j ACCEPT']
        else:
            nat += [f'-A PREROUTING {ingress} {target} -j DNAT --to-destination {backend}']
        nat += [
            f'-A POSTROUTING -o {uplink} -s {client}/32 -p tcp {actual} '
            f'-m conntrack --ctdir ORIGINAL {connection} -j SNAT --to-source {uplink_address}'
        ]
        # Filter after DNAT and before SNAT, including established packets.
        # Check the original tuple so alias and literal rules cannot substitute.
        forwarding += [
            f'-A FORWARD {ingress} -o {uplink} {actual} '
            f'-m conntrack --ctdir ORIGINAL --ctstate NEW,ESTABLISHED {connection} -j ACCEPT',
            f'-A FORWARD -i {uplink} -o client-0 -s {backend}/32 -d {client}/32 -p tcp --sport {port} '
            f'-m conntrack --ctdir REPLY --ctstate ESTABLISHED {connection} -j ACCEPT',
            # Path MTU feedback can originate at an intermediate router.
            f'-A FORWARD -i {uplink} -o client-0 -d {client}/32 -p icmp --icmp-type fragmentation-needed '
            f'-m conntrack --ctdir REPLY --ctstate RELATED --ctproto tcp {connection} -j ACCEPT',
        ]
    return raw, nat, forwarding


def repair_gre_reply_checksums(client, destinations):
    # Docker Desktop can deliver replies whose TCP checksum is incomplete.
    # Recompute after reverse NAT and before the agent GRE encapsulation.
    # The firewall still controls which tuples can reach this interface.
    run('tc', 'qdisc', 'replace', 'dev', 'client-0', 'clsact')
    for address in sorted({original for original, _, _ in destinations}):
        run('tc', 'filter', 'replace', 'dev', 'client-0', 'egress', 'protocol', 'ip',
            'u32', 'match', 'ip', 'protocol', '6', '0xff',
            'match', 'ip', 'src', address + '/32', 'match', 'ip', 'dst', client + '/32',
            'action', 'csum', 'tcp')


def enable_local_forwarding():
    try:
        IP_FORWARD.write_text('1\n')
    except OSError as error:
        if IP_FORWARD.read_text().strip() != '0':
            raise
        return f'Could not enable IPv4 forwarding ({error.strerror or type(error).__name__}). Local grants closed.'
    return None


def router():
    addresses = Addresses(network_prefix(os.environ))
    # Also close a retained namespace before changing any existing rules.
    if IP_FORWARD.read_text().strip() != '0':
        IP_FORWARD.write_text('0\n')
    onion = os.environ.get('TOR_ONION_ENABLED', 'false')
    if onion not in ('true', 'false'):
        raise ValueError('TOR_ONION_ENABLED must be exactly true or false')
    if onion == 'true':
        require_secret()
        read_address()
    clients = [(addresses.agent_route, addresses.tor_agent_route, GRE_AGENT_INNER, GRE_AGENT_PEER),
               (addresses.executor_route, addresses.tor_executor_route, GRE_EXECUTOR_INNER, GRE_EXECUTOR_PEER)]
    for index, (client, gateway, inner, peer) in enumerate(clients):
        tunnel(f'client-{index}', gateway, client, peer + '/30')
    routes = connected()
    host, lan = grants(os.environ, routes)
    networks = (*DENIED, *routes)
    raw, nat, incoming, forwarding = [], [], [], []
    warnings = []
    if host or lan:
        interfaces = json.loads(run('ip', '-j', '-4', 'addr', 'show', capture_output=True).stdout)
        uplink, = [entry['ifname'] for entry in interfaces
                   if any(addr['local'] == addresses.tor_uplink for addr in entry['addr_info'])]
        platform = os.environ.get('PRIVATE_HERMES_NETWORK_PLATFORM', 'docker')
        if lan and platform == 'docker':
            warnings.append('Docker LAN grants require Docker Desktop. LAN grants closed.')
            lan = []
        destinations = [(address, address, port) for address, port in lan
                        if uplink_route(address, uplink, addresses.tor_uplink)]
        if len(destinations) != len(lan):
            warnings.append('LAN grants lacking a tor-uplink route were closed.')
        if host:
            backend = host_backend(platform == 'podman', uplink, addresses)
            if backend:
                destinations += [(HOST_ALIAS, backend, port) for port in host]
            else:
                warnings.append('Native host IPv4 mapping unavailable or unreachable through tor-uplink. Host grants closed.')
        if destinations and platform != 'podman':
            try:
                repair_gre_reply_checksums(clients[0][2], destinations)
            except subprocess.CalledProcessError:
                warnings.append('GRE TCP checksum repair unavailable. Local forwarding closed.')
                destinations = []
        raw, nat, forwarding = local_forwarding(clients[0][2], uplink, destinations, addresses.tor_uplink)
    for client, gateway, inner, peer in clients:
        # GRE carries the original public-destination packet inside an internal
        # IP packet. Docker's internal bridge drops public-destination Ethernet
        # frames even when their next hop is another container on that bridge.
        raw += [
            f'-A PREROUTING -s {client}/32 -d {gateway}/32 -p gre -j ACCEPT',
            f'-A PREROUTING -s {client}/32 -d {gateway}/32 -p udp --dport 53 -j ACCEPT',
        ]
        for source in (client, inner):
            raw += [f'-A PREROUTING -s {source}/32 -d {network} -j DROP' for network in networks]
        nat += [
            f'-A PREROUTING -s {client}/32 -d {gateway}/32 -p udp --dport 53 -j REDIRECT --to-ports 9053',
            f'-A PREROUTING -s {inner}/32 -p tcp -j REDIRECT --to-ports 9040',
        ]
        incoming += [
            f'-A INPUT -s {client}/32 -d {gateway}/32 -p gre -j ACCEPT',
            f'-A INPUT -s {inner}/32 -p tcp --dport 9040 -j ACCEPT',
            f'-A INPUT -s {client}/32 -p udp --dport 9053 -j ACCEPT',
        ]
    # The Tor process itself also cannot contact host, VM, or private networks.
    outgoing = [f'-A OUTPUT -d {client}/32 -p gre -j ACCEPT' for client, *_ in clients]
    if onion == 'true':
        outgoing += [f'-A OUTPUT -s {addresses.tor_onion_ingress}/32 -d {addresses.proxy_onion_ingress}/32 -p tcp --dport 8080 -m owner --uid-owner 101 -j ACCEPT']
    outgoing += deny('OUTPUT', networks)
    outgoing += ['-A OUTPUT -m owner --uid-owner 101 -p tcp -j ACCEPT']
    apply(raw, nat, incoming, outgoing, forwarding=forwarding)
    if forwarding:
        warning = enable_local_forwarding()
        if warning:
            warnings.append(warning)
    for warning in warnings:
        print(f'router: {warning}', file=sys.stderr, flush=True)
    # This advisory view is for make up. The gateway can serve if publication fails.
    try:
        LOCAL_GRANT_WARNINGS.write_text(''.join(f'{warning}\n' for warning in warnings))
    except OSError as error:
        print(f'router: Could not publish local grant warnings. {error.strerror}', file=sys.stderr, flush=True)
    state = Path('/var/lib/tor')
    state.mkdir(exist_ok=True)
    for base, dirs, files in os.walk(state):
        for path in [Path(base), *(Path(base) / p for p in dirs + files)]:
            os.chown(path, 101, 102, follow_symlinks=False)
    state.chmod(0o700)
    # Set the control directory owner here: Podman rejects tmpfs uid and gid options.
    os.chown('/run/tor-control', 101, 102)
    print('router: firewall installed; starting Tor without network capabilities', flush=True)
    original = Path('/etc/tor/torrc').read_text()
    if not original.endswith('\n'):
        original += '\n'
    original += f'DNSPort {addresses.tor_agent_route}:9053\nDNSPort {addresses.tor_executor_route}:9053\n'
    if os.environ.get('PRIVATE_HERMES_X402_TREAZURY_SOCKS', '0') == '1':
        socks = Path('/run/tor-x402_treazury')
        os.chown(socks, 101, 102)
        socks.chmod(0o750)
        if original.splitlines().count('SocksPort 0') != 1:
            raise ValueError('Expected one disabled SOCKS listener in the base Tor config')
        original = original.replace('SocksPort 0', 'SocksPort unix:/run/tor-x402_treazury/socks IsolateSOCKSAuth GroupWritable RelaxDirModeCheck')
    if onion == 'true':
        original += f'\nHiddenServiceDir /var/lib/tor/onion-service\nHiddenServiceVersion 3\nHiddenServicePort 80 {addresses.proxy_onion_ingress}:8080\n'
    config = '/tmp/private-hermes-torrc'
    Path(config).write_text(original)
    drop(101, 102, '/usr/bin/tor', '-f', config)


if __name__ == '__main__':
    role = sys.argv[1]
    if role == 'router':
        router()
    elif role in ('agent', 'executor'):
        endpoint(role)
    elif role == 'wait':
        wait()
    else:
        raise SystemExit('Expected router, agent, executor, or wait')
