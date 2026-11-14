"""Treasury-local preparation and serving gate; never imported by Hermes."""
from contextlib import contextmanager
from collections import deque
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
from endpoints import ADDRESS, ENDPOINTS

HOME = Path('/var/lib/x402')
RECORD = HOME / 'onboarding' / 'preparation.json'
BINARY = '/usr/local/bin/x402_treazury'


class PhaseError(RuntimeError):
    def __init__(self, phase, code, tail):
        self.phase, self.code, self.tail = phase, code, tail
        super().__init__(f'{phase} failed (exit {code}). Recent output:\n{tail}')


def sanitize(value):
    for key, secret in os.environ.items():
        if secret and any(word in key for word in ('TOKEN', 'SECRET', 'KEY')):
            value = value.replace(secret, '[redacted]')
    return value


def native(arguments, phase, structured=False, quiet=False, offline=False):
    """Stream output, preserve a diagnostic tail, and forward graceful signals."""
    environment = os.environ.copy()
    if offline:
        # Saved-wallet inspection must not load serving or funding configuration.
        environment.pop('X402_TREAZURY_CONFIG', None)
        arguments = [*arguments, '--state-dir', str(HOME / 'state'),
                     '--key-file', str(HOME / 'state/wallet.key')]
    child = subprocess.Popen([BINARY, *arguments], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, env=environment)
    tail, output = deque(maxlen=80), []
    cancelled = []
    def forward(signum, _frame):
        cancelled.append(signum)
        if child.poll() is None:
            child.send_signal(signum)
    previous = {sig: signal.signal(sig, forward) for sig in (signal.SIGINT, signal.SIGTERM)}
    def drain(stream, stdout):
        for line in stream:
            if stdout and structured:
                output.append(line)
            safe = sanitize(line)
            tail.append(safe)
            if not quiet:
                print(safe, end='', file=sys.stdout if stdout else sys.stderr, flush=True)
        stream.close()
    threads = [threading.Thread(target=drain, args=(child.stdout, True)),
               threading.Thread(target=drain, args=(child.stderr, False))]
    try:
        for thread in threads:
            thread.start()
        code = child.wait()
        for thread in threads:
            thread.join()
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    if cancelled:
        code = 128 + cancelled[0]
    if code:
        raise PhaseError(phase, code, ''.join(tail))
    if structured:
        try:
            return json.loads(''.join(output))
        except ValueError as error:
            raise PhaseError(phase, 1, 'Successful command returned invalid JSON') from error


@contextmanager
def owner():
    """The same guard covers preparation and the full serving lifetime."""
    with (HOME / 'onboarding.lock').open('a') as lock:
        os.chmod(lock.name, 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError('Another preparation or serving process owns this treasury; stop it gracefully first.') from error
        yield


def write_record(record):
    RECORD.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    record['updated_at'] = datetime.now(timezone.utc).isoformat()
    with tempfile.NamedTemporaryFile(mode='w', dir=RECORD.parent, delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(record, stream)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    try:
        temporary.chmod(0o600)
        temporary.replace(RECORD)
    finally:
        temporary.unlink(missing_ok=True)


def context():
    config = native(['config', 'show'], 'configuration', structured=True, quiet=True)
    if config.get('network', {}).get('mode') != 'tor' or config['network'].get('socks_endpoint') != 'unix:/run/tor-x402_treazury/socks':
        raise RuntimeError('Onboarding requires the configured private Tor Unix socket; direct transport is refused')
    if config['network'].get('socks_auth') != 'tor_extended':
        raise RuntimeError('Deployment requires Tor extended SOCKS authentication for wallet isolation')
    treasury = config.get('treasury') or {}
    state = HOME / 'state'
    if treasury.get('state_dir') != str(state) or treasury.get('key_file', str(state / 'wallet.key')) != str(state / 'wallet.key'):
        raise RuntimeError('Deployment treasury state/key must remain at /var/lib/x402/state and /var/lib/x402/state/wallet.key')
    servers = config.get('servers', {})
    if set(servers) != set(ENDPOINTS):
        raise RuntimeError('Deployment requires its twelve managed MCP listeners')
    for name, port in ENDPOINTS.items():
        server = servers[name]
        if (server.get('listen') != f'{ADDRESS}:{port}'
                or server.get('allowed_hosts') != [ADDRESS]
                or server.get('disable_host_check') is not False
                or server.get('auth') is not True
                or server.get('bearer_token_env') != 'X402_TREAZURY_MCP_TOKEN'):
            raise RuntimeError(f'Deployment listener {name} must retain its authenticated loopback address and Host checks')
    return config


def wallet():
    state = HOME / 'state'
    key = state / 'wallet.key'
    if not os.path.lexists(state) and not os.path.lexists(key):
        return None
    if not state.is_dir() or not key.is_file():
        raise RuntimeError('Existing treasury state/key is incomplete; initialization refused. Inspect or restore it.')
    status = native(['wallet', 'status', '--json'], 'wallet inspection', structured=True, quiet=True, offline=True)
    # Metadata-only status cannot establish that the encrypted snapshot is readable.
    addresses = native(['wallet', 'addresses'], 'wallet addresses', structured=True, quiet=True, offline=True)
    if not status.get('treasury_id') or not addresses.get('receive_addresses'):
        raise RuntimeError('Existing wallet has no readable identity/address snapshot')
    return status['treasury_id']


def inspect():
    try:
        treasury_id = wallet()
        result = {'prepared': False, 'wallet_absent': treasury_id is None,
                  'wallet_valid': treasury_id is not None, 'record': {},
                  'reason': 'Wallet has not been initialized.' if treasury_id is None else 'Initial preparation has not completed for this wallet.'}
        try:
            record = json.loads(RECORD.read_text()) if RECORD.exists() else {}
            if not isinstance(record, dict):
                raise ValueError('Preparation record must be an object')
        except (OSError, ValueError) as error:
            return {**result, 'reason': 'Preparation record is unreadable: ' + sanitize(str(error))}
        valid = (treasury_id is not None and record.get('schema') == 1
                 and record.get('treasury_id') == treasury_id
                 and record.get('completed') == ['bootstrap', 'catalogs'])
        return {**result, 'prepared': valid, 'record': record,
                'reason': 'prepared' if valid else result['reason']}
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        return {'prepared': False, 'wallet_absent': False, 'wallet_valid': False,
                'reason': sanitize(str(error)), 'record': {}}


def initialize():
    with owner():
        context()
        if wallet() is None:
            previous = json.loads(RECORD.read_text()) if RECORD.exists() else {}
            if not isinstance(previous, dict) or previous.get('treasury_id'):
                raise RuntimeError('Onboarding records an existing treasury but its wallet is absent; inspect or restore state instead of replacing it.')
            record = {'schema': 1, 'phase': 'wallet-init', 'completed': [],
                      'activation': 'disconnected'}
            write_record(record)
            try:
                native(['wallet', 'init'], 'wallet creation')
                record['treasury_id'] = wallet()
                if not record['treasury_id']:
                    raise RuntimeError('Wallet creation exited successfully without readable state')
                record['phase'] = 'wallet-created'
                write_record(record)
            except Exception as cause:
                error = cause if isinstance(cause, PhaseError) else PhaseError('wallet creation', 1, sanitize(str(cause)))
                record['failure'] = {'phase': error.phase, 'exit_code': error.code, 'recent_output': error.tail}
                write_record(record)
                raise error
        else:
            print('Wallet already initialized; displaying saved wallet state.', flush=True)
            native(['wallet', 'status'], 'wallet status', offline=True)
        print('Back up the wallet with the native wallet backup command before depositing ZEC.\n'
              'Deposit when ready, then run make x402_treazury-prepare. Hermes remains available.')


def prepare():
    with owner():
        context()
        treasury_id = wallet()
        if treasury_id is None:
            raise RuntimeError('Create the wallet first with make x402_treazury-init')
        record = {'schema': 1, 'treasury_id': treasury_id,
                  'completed': [], 'activation': 'disconnected'}
        for phase, arguments in (
                ('bootstrap', ['wallet', 'bootstrap', '--json']),
                ('catalogs', ['catalog', 'warm'])):
            record['phase'] = phase
            write_record(record)
            print(f'Starting {phase}; native network/funding policy applies.', flush=True)
            try:
                # Warming zero-exit includes degraded coverage, even total
                # remote loss. Stream native output; do not gate on inventory.
                native(arguments, phase)
                record['completed'].append(phase)
                write_record(record)
            except Exception as cause:
                error = cause if isinstance(cause, PhaseError) else PhaseError(phase, 1, sanitize(str(cause)))
                record['failure'] = {'phase': phase, 'exit_code': error.code, 'recent_output': error.tail}
                write_record(record)
                raise error
        record['phase'] = 'prepared'
        write_record(record)
        print('Bootstrap and catalog warming completed. Serving and MCP activation are separate checks.', flush=True)


def serve():
    with owner():
        context()
        result = inspect()
        if not result['prepared']:
            raise RuntimeError('Serving refused: ' + result['reason'] + ' Run make x402_treazury-prepare.')
        native(['serve'], 'serving')


def main():
    action = sys.argv[1]
    if action == 'inspect':
        print(json.dumps(inspect()))
    elif action == 'validate':
        context()
    elif action == 'init':
        initialize()
    elif action == 'prepare':
        prepare()
    elif action == 'status':
        result = inspect()
        print(json.dumps(result, indent=2))
        if result['wallet_absent']:
            print('Wallet has not been initialized. Run make x402_treazury-init to create it.')
        elif not result['wallet_valid']:
            raise RuntimeError(result['reason'])
        else:
            print('Saved wallet state (offline; balances are not refreshed):', flush=True)
            native(['wallet', 'status'], 'wallet status', offline=True)
    elif action in ('connected', 'disconnected', 'activation-failed'):
        record = json.loads(RECORD.read_text()) if RECORD.exists() else {}
        if record:
            record['activation'] = action
            write_record(record)
    else:
        raise RuntimeError('Unknown onboarding action')


if __name__ == '__main__':
    try:
        main()
    except PhaseError as error:
        print(error, file=sys.stderr)
        sys.exit(error.code if 0 < error.code < 256 else 1)
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        print(sanitize(str(error)), file=sys.stderr)
        sys.exit(1)
