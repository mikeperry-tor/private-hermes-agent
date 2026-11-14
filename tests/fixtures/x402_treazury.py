"""Start all real MCP listeners without treasury state, funding, or paid APIs."""
import json
import os
from pathlib import Path
import secrets
import socket
from endpoints import ADDRESS, ENDPOINTS

flags = Path(os.environ.get('RESEARCH_TEST_FLAGS', '/tmp/unused-test-flags'))
if (flags / 'gate').exists():
    # Accept TCP before native startup, but leave HTTP pending so cancellation
    # exercises an outstanding protocol request rather than a quick refusal.
    pending = socket.socket()
    pending.bind((ADDRESS, ENDPOINTS['toolbox']))
    pending.listen()
    os.mkfifo('/tmp/research-start-gate')
    print('Fixture waiting for start release.', flush=True)
    with open('/tmp/research-start-gate') as gate:
        gate.read()
    pending.close()
broken = (flags / 'broken').read_text().strip() if (flags / 'broken').exists() else None
spec = {
    'openapi': '3.0.3', 'info': {'title': 'Free Tor check', 'version': '1'},
    'paths': {'/api/ip': {'get': {'operationId': 'check_tor_exit',
              'responses': {'200': {'description': 'Tor exit status'}}}}},
}
Path('/tmp/tor-check.json').write_text(json.dumps(spec))
config = '''version=1
[network]
mode="tor"
socks_endpoint="unix:/run/tor-x402_treazury/socks"
socks_auth="tor_extended"
[wallets.fixture]
mode="static"
private_key_env="RESEARCH_TEST_KEY"
max_api_payment_usdc="0.50"
[sources.torcheck]
spec="/tmp/tor-check.json"
base_url="https://check.torproject.org"
prefix="torcheck"
allow_http1=true
'''
if broken:
    # This branch runs only in the networkless endpoint fixture. A required
    # remote acquisition failure disables its endpoint after deferred loading;
    # local malformed files now stop the entire process before it can serve.
    with socket.socket() as unused:
        unused.bind((ADDRESS, 0))
        port = unused.getsockname()[1]
    config = config.replace('mode="tor"', 'mode="direct"')
    config = '\n'.join(line for line in config.splitlines() if not line.startswith('socks_')) + '\n'
    config += f'''\n[sources.failure]
spec="https://{ADDRESS}:{port}/catalog.json"
base_url="https://{ADDRESS}:{port}"
allow_http1=true
'''
for name, port in ENDPOINTS.items():
    config += f'''\n[servers.{name}]
listen="{ADDRESS}:{port}"
allowed_hosts=["{ADDRESS}"]
bearer_token_env="X402_TREAZURY_MCP_TOKEN"
wallet="fixture"
sources=["{'failure' if name == broken else 'torcheck'}"]
'''
    if (flags / 'empty').exists() and name == 'web':
        config += 'include_tools=["torcheck_missing_operation"]\n'
Path('/tmp/x402_treazury-test.toml').write_text(config)
os.environ['X402_TREAZURY_MCP_TOKEN'] = Path('/run/x402_treazury-auth/token').read_text().strip()
os.environ['RESEARCH_TEST_KEY'] = secrets.token_hex(32)
os.environ['X402_TREAZURY_CONFIG'] = '/tmp/x402_treazury-test.toml'
os.execvp('x402_treazury', ['x402_treazury', 'serve'])
