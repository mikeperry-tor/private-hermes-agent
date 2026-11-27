"""Enable one fixed Funnel only after verifying the enrolled node's exact DNS name."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

try:
    from addressing import Addresses, DEFAULT_NETWORK_PREFIX, network_prefix
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'network'))
    from addressing import Addresses, DEFAULT_NETWORK_PREFIX, network_prefix

SOCKET = '/tmp/tailscaled.sock'
CONFIG = Path('/tmp/serve/config.json')


def serve_config(host, port, prefix=DEFAULT_NETWORK_PREFIX):
    addresses = Addresses(prefix)
    authority = f'{host}:{port}'
    return {'TCP': {str(port): {'HTTPS': True}},
            'Web': {authority: {'Handlers': {'/': {'Proxy': f'http://{addresses.proxy_funnel_link}:8443'}}}},
            'AllowFunnel': {authority: True}}


def publish(value):
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    temporary = CONFIG.with_suffix('.tmp')
    temporary.write_text(json.dumps(value))
    os.replace(temporary, CONFIG)


def cli(*arguments, check=True):
    return subprocess.run(['tailscale', '--socket=' + SOCKET, *arguments],
                          check=check, text=True, capture_output=True)


def main():
    if os.environ.get('TAILSCALE_FUNNEL_ENABLED') != 'true':
        raise SystemExit('Funnel is disabled; refusing to enroll or publish.')
    prefix = network_prefix(os.environ)
    host = os.environ['TAILSCALE_FUNNEL_HOST']
    port = int(os.environ['TAILSCALE_FUNNEL_PORT'])
    if not os.environ.get('TS_AUTHKEY') and not Path('/var/lib/tailscale/tailscaled.state').exists():
        raise SystemExit('Initial Tailscale enrollment requires TS_AUTHKEY.')
    publish({})  # never restore public forwarding implicitly on startup
    environment = dict(os.environ, TS_SERVE_CONFIG=str(CONFIG), TS_SOCKET=SOCKET,
                       TS_USERSPACE='true', TS_AUTH_ONCE='true', TS_STATE_DIR='/var/lib/tailscale')
    child = subprocess.Popen(['/usr/local/bin/containerboot'], env=environment)
    stopping = False
    def stop(*_):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        enabled = False
        while child.poll() is None and not stopping:
            if not enabled:
                result = cli('status', '--json', check=False)
                if result.returncode == 0:
                    status = json.loads(result.stdout)
                    if status.get('BackendState') == 'Running':
                        actual = status.get('Self', {}).get('DNSName', '').rstrip('.')
                        if actual != host:
                            raise RuntimeError('Enrolled Tailscale DNS name differs from TAILSCALE_FUNNEL_HOST; public forwarding remains disabled.')
                        publish(serve_config(host, port, prefix))
                        enabled = True
                        print('Configured authenticated webapp Funnel for the verified node name.', flush=True)
            time.sleep(1)
        if not stopping:
            raise RuntimeError('Tailscale containerboot exited before shutdown')
    finally:
        publish({})
        if child.poll() is None:
            result = cli('funnel', 'reset', check=False)
            if result.returncode:
                print('Funnel reset failed; stopping the node. Next startup begins with empty forwarding configuration.', file=sys.stderr, flush=True)
            child.terminate()
            child.wait()


if __name__ == '__main__':
    main()
