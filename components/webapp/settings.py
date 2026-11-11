"""Strict deployment settings shared by the host workflow and config renderer."""
from dataclasses import dataclass
import ipaddress
import re


def boolean(value, name):
    if value not in ('true', 'false'):
        raise ValueError(f'{name} must be exactly true or false')
    return value == 'true'


def port(value, name):
    if not re.fullmatch(r'[0-9]+', value) or not 1 <= int(value) <= 65535:
        raise ValueError(f'{name} must be an integer port from 1 to 65535')
    return int(value)


@dataclass(frozen=True)
class Settings:
    funnel: bool
    bind: str
    port: int
    username: str
    funnel_host: str
    funnel_port: int
    node: str
    external_content: str

    @classmethod
    def read(cls, values):
        external_content = values['external_content']
        if external_content not in ('tor_proxied', 'ask', 'off', 'browser_native'):
            raise ValueError('WEBAPP_EXTERNAL_CONTENT must be tor_proxied, ask, off or browser_native')
        funnel = boolean(values['funnel_enabled'], 'TAILSCALE_FUNNEL_ENABLED')
        bind = values['webapp_bind']
        if not ipaddress.IPv4Address(bind).is_loopback:
            raise ValueError('WEBAPP_BIND must be an IPv4 loopback address')
        local_port = port(values['webapp_port'], 'WEBAPP_PORT')
        username = values['webapp_username']
        if not re.fullmatch(r'[A-Za-z0-9_.@-]+', username):
            raise ValueError('WEBAPP_USERNAME must contain only letters, digits, _, ., @ or -')
        node = values['tailscale_hostname']
        if not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', node):
            raise ValueError('TAILSCALE_HOSTNAME must be a lowercase DNS label')
        host = values['funnel_host']
        if host and (len(host) > 253 or not host.endswith('.ts.net') or
                     any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label)
                         for label in host.split('.'))):
            raise ValueError('TAILSCALE_FUNNEL_HOST must be one exact lowercase .ts.net hostname')
        if funnel and not host:
            raise ValueError('TAILSCALE_FUNNEL_HOST is required when Funnel is enabled')
        if funnel and local_port == 8443:
            raise ValueError('WEBAPP_PORT must not be 8443 when Funnel is enabled: the Funnel frontend uses 8443')
        public_port = port(values['funnel_port'], 'TAILSCALE_FUNNEL_PORT')
        if public_port not in (443, 8443, 10000):
            raise ValueError('TAILSCALE_FUNNEL_PORT must be 443, 8443 or 10000')
        return cls(funnel, bind, local_port, username, host, public_port, node, external_content)


def authorities(host, port_number, default_port):
    result = [f'{host}:{port_number}']
    if port_number == default_port:
        result.append(host)
    return result


def proxy_config(settings, loopback_forwarder=False):
    """Render HAProxy's configuration.

    Docker delivers published connections on the publication interface.
    Rootless Podman's port forwarder runs inside the proxy namespace and
    connects over loopback to one of the proxy's addresses, so with
    loopback_forwarder the local frontend listens on all proxy addresses and
    the proxy firewall admits new loopback connections only.
    """
    local_hosts = sorted({authority for host in ('localhost', settings.bind)
                          for authority in authorities(host, settings.port, 80)})
    forwarder = 'loopback' if loopback_forwarder else 'interface'
    text = (f'# WEBAPP_EXTERNAL_CONTENT={settings.external_content}\n'
            f'# PORT_FORWARDER={forwarder}\n') + '''global
    log stdout format raw local0 notice

defaults
    mode http
    timeout connect 10s
    timeout client 0
    timeout server 0
    timeout tunnel 0

backend hermes
    # Add a second policy: browsers intersect it with Hermes's own CSP, so its
    # script/connect restrictions remain intact while third-party fonts stop.
    http-response add-header Content-Security-Policy "font-src 'self' data:; style-src 'self' 'unsafe-inline'"
    server agent 10.203.85.2:9120
'''
    def frontend(name, listen, hosts, scheme, peer=None):
        source_rule = f"    http-request deny deny_status 403 unless {{ src {peer} }}\n" if peer else ""
        return f'''
frontend {name}
    bind {listen}
{source_rule}
    http-request deny deny_status 400 unless {{ req.hdr_cnt(host) eq 1 }}
    acl allowed_host req.hdr(host),lower -m str {' '.join(hosts)}
    http-request deny deny_status 421 unless allowed_host
    http-request del-header Forwarded
    http-request del-header x-forwarded- -m beg
    http-request set-header X-Private-Hermes-Content-Mode {settings.external_content}
    http-request set-header X-Forwarded-Proto {scheme}
    http-request set-header X-Forwarded-For %[src]
    default_backend hermes
'''
    listen = f':{settings.port}' if loopback_forwarder else f'${{PRIVATE_HERMES_EDGE_IP}}:{settings.port}'
    text += frontend('localhost', listen, local_hosts, 'http')
    if settings.funnel:
        text += frontend('funnel', '10.203.87.3:8443',
                         authorities(settings.funnel_host, settings.funnel_port, 443), 'https', '10.203.87.2')
    return text
