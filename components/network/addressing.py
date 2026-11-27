"""Shared validation and IPv4 address derivation for multi-instance deployments."""
from dataclasses import dataclass
import ipaddress
import os
import re

DEFAULT_PROJECT_NAME = 'private-hermes'
DEFAULT_NETWORK_PREFIX = '10.203'

# Namespace-local GRE inner tunnel addresses and host alias never collide across instances.
GRE_AGENT_INNER = '10.204.80.2'
GRE_AGENT_PEER = '10.204.80.1'
GRE_EXECUTOR_INNER = '10.204.81.2'
GRE_EXECUTOR_PEER = '10.204.81.1'
GRE_SUBNETS = ('10.204.80.0/30', '10.204.81.0/30')
HOST_ALIAS = '198.18.255.254'

_PROJECT_RE = re.compile(r'^[a-z0-9]+(?:[-_][a-z0-9]+)*$')
_OCTET_0_255 = r'(?:0|[1-9][0-9]?|1[0-9]{2}|2[0-4][0-9]|25[0-5])'
_PREFIX_RE = re.compile(
    rf'^(?:10\.{_OCTET_0_255}|172\.(?:1[6-9]|2[0-9]|3[01])|192\.168)$'
)


def validate_project_name(value):
    """Validate COMPOSE_PROJECT_NAME for Compose projects and OCI image tags."""
    if not isinstance(value, str) or not (1 <= len(value) <= 63) or not _PROJECT_RE.fullmatch(value):
        raise ValueError(
            'COMPOSE_PROJECT_NAME must be 1 to 63 lowercase letters or digits '
            'separated by single hyphens or underscores (for example, private-hermes-2)'
        )
    return value


def validate_network_prefix(value):
    """Validate a two-octet RFC1918 IPv4 prefix (excluding 10.204 for GRE)."""
    if not isinstance(value, str) or not _PREFIX_RE.fullmatch(value) or value == '10.204':
        raise ValueError(
            'NETWORK_PREFIX must be a two-octet RFC1918 IPv4 prefix '
            '(10.<0-255> except 10.204, 172.<16-31>, or 192.168) without leading zeros'
        )
    return value


def network_prefix(environment=None):
    """Read and validate NETWORK_PREFIX from environment (defaulting when unset or empty)."""
    env = os.environ if environment is None else environment
    raw = env.get('NETWORK_PREFIX')
    if raw is None or raw == '':
        return DEFAULT_NETWORK_PREFIX
    return validate_network_prefix(raw)


def reserved_subnets(prefix=DEFAULT_NETWORK_PREFIX):
    """Return all internal IPv4 subnets reserved by one instance."""
    prefix = validate_network_prefix(prefix)
    return tuple(
        ipaddress.IPv4Network(cidr)
        for cidr in (*(f'{prefix}.{octet}.0/24' for octet in range(80, 92)), *GRE_SUBNETS)
    )


@dataclass(frozen=True)
class Addresses:
    """Deterministic IPv4 addresses and subnets derived from NETWORK_PREFIX."""

    prefix: str = DEFAULT_NETWORK_PREFIX

    def __post_init__(self):
        validate_network_prefix(self.prefix)

    def ip(self, subnet_octet, host_octet):
        return f'{self.prefix}.{subnet_octet}.{host_octet}'

    def subnet(self, subnet_octet):
        return f'{self.prefix}.{subnet_octet}.0/24'

    @property
    def tor_agent_route(self):
        return self.ip(80, 3)

    @property
    def tor_executor_route(self):
        return self.ip(81, 3)

    @property
    def tor_onion_ingress(self):
        return self.ip(86, 2)

    @property
    def tor_uplink(self):
        return self.ip(88, 2)

    @property
    def agent_route(self):
        return self.ip(80, 2)

    @property
    def agent_execution_control(self):
        return self.ip(82, 2)

    @property
    def agent_inference(self):
        return self.ip(83, 2)

    @property
    def agent_mcp_access(self):
        return self.ip(84, 2)

    @property
    def agent_webapp_backend(self):
        return self.ip(85, 2)

    @property
    def executor_route(self):
        return self.ip(81, 2)

    @property
    def executor_execution_control(self):
        return self.ip(82, 3)

    @property
    def teep_inference(self):
        return self.ip(83, 3)

    @property
    def proxy_webapp_backend(self):
        return self.ip(85, 3)

    @property
    def proxy_onion_ingress(self):
        return self.ip(86, 3)

    @property
    def proxy_funnel_link(self):
        return self.ip(87, 3)

    @property
    def tailscale_funnel_link(self):
        return self.ip(87, 2)

    @property
    def mcp_access_subnet(self):
        return self.subnet(84)

    @property
    def reserved(self):
        return reserved_subnets(self.prefix)
