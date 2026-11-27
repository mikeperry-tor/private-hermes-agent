"""Install native webapp settings during the existing networkless bootstrap."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'network'))
from addressing import Addresses, DEFAULT_NETWORK_PREFIX
from auth import validate


def configure(config, credentials, username, prefix=DEFAULT_NETWORK_PREFIX):
    credentials = validate(credentials)
    webapp = config.get('webapp')
    if webapp is None:
        webapp = config['webapp'] = {}
    if not isinstance(webapp, dict):
        raise ValueError('Hermes webapp configuration must be a mapping')
    webapp.update({'enabled': True, 'host': '0.0.0.0', 'port': 9120, 'public_url': ''})
    dashboard = config.setdefault('dashboard', {})
    dashboard['trusted_proxies'] = [Addresses(prefix).proxy_webapp_backend]
    dashboard['public_url'] = ''
    dashboard['basic_auth'] = {'username': username, **credentials}
    dashboard['session_token_auth'] = {'enabled': False}
