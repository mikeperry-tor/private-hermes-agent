"""Install native webapp settings during the existing networkless bootstrap."""
from auth import validate


def configure(config, credentials, username):
    credentials = validate(credentials)
    config.setdefault('webapp', {}).update({'enabled': True, 'host': '0.0.0.0', 'port': 9120, 'public_url': ''})
    dashboard = config.setdefault('dashboard', {})
    dashboard['trusted_proxies'] = ['10.203.85.3']
    dashboard['public_url'] = ''
    dashboard['basic_auth'] = {'username': username, **credentials}
    dashboard['session_token_auth'] = {'enabled': False}
