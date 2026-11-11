#!/usr/bin/env python3
"""Deployment-side staged onboarding; no wallet secrets leave its container."""
import argparse
from contextlib import contextmanager
from datetime import datetime
import fcntl
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
import time
from deployment import ROOT, ensure_networks, maintenance_compose
from provisioning import initialize_research_config


# Native diagnostic contract at pinned 39fb372; generic ERROR logs can recover.
ENDPOINT_FAILURES = (
    'MCP endpoint unavailable; catalog startup failed; correct the reported cause and restart',
    'MCP endpoint tools are unavailable because its tool selection is invalid; correct the configuration and restart',
)


def log_since(started_at):
    """Return a container start time as a Unix timestamp for `logs --since`.

    Docker reports RFC 3339 (`2026-11-11T22:32:02.496429564Z`); Podman reports
    `2026-11-11 22:32:02.496429564 +0000 UTC`. Both engines accept a Unix
    timestamp for --since.
    """
    match = re.fullmatch(r'(\d{4}-\d\d-\d\d)[T ](\d\d:\d\d:\d\d)(?:\.(\d+))?'
                         r'\s*(Z|[+-]\d\d:?\d\d)?(?: \S+)?', started_at.strip())
    if not match:
        raise ValueError(f'Cannot read the container start time: {started_at!r}')
    day, clock, fraction, zone = match.groups()
    zone = '+00:00' if zone in (None, 'Z') else f'{zone[:3]}:{zone[-2:]}'
    instant = datetime.fromisoformat(f'{day}T{clock}{zone}')
    return f'{instant.timestamp():.0f}.{(fraction or "0")[:6].ljust(6, "0")}'


@contextmanager
def serving_diagnostics(identifier, started_at, root):
    """Display this serving lifetime's diagnostics without storing another record."""
    stopped, failures = threading.Event(), []
    logs = subprocess.Popen(['docker', 'logs', '--follow', '--since', started_at, identifier],
                            cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    def drain():
        try:
            for line in logs.stdout:
                print(line, end='', file=sys.stderr, flush=True)
                if not failures and any(message in line for message in ENDPOINT_FAILURES):
                    failures.append('x402_treazury reported unavailable endpoint functionality; see its native diagnostic above.')
        finally:
            if not stopped.is_set() and not failures:
                failures.append('The research startup log observer stopped; endpoint failure diagnostics are unavailable.')
    reader = threading.Thread(target=drain)
    reader.start()
    try:
        yield failures
    finally:
        stopped.set()
        if logs.poll() is None:
            logs.terminate()
        logs.wait()
        reader.join()
        logs.stdout.close()


@contextmanager
def operation_lock(root):
    with (Path(root) / '.operation.lock').open('a') as lock:
        os.chmod(lock.name, 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError('Another deployment/onboarding operation is running.') from error
        yield


class Controller:
    def __init__(self, command, root=ROOT):
        self.command, self.root = command, Path(root)

    def call(self, *arguments, **kwargs):
        if arguments[:1] == ('up',):
            ensure_networks(self.command)
        return subprocess.run([*self.command, *arguments], cwd=self.root, text=True, check=True, **kwargs)

    def admin(self, action, capture=False):
        saved_state = ('inspect', 'status', 'connected', 'disconnected', 'activation-failed')
        service = 'x402_treazury-inspect' if action in saved_state else 'x402_treazury-admin'
        return self.call('run', '--rm', '-T', '--no-deps', service, action,
                         capture_output=capture)

    def inspect(self):
        return json.loads(self.admin('inspect', capture=True).stdout)

    def running(self, service):
        return self.call('ps', '-q', '--status', 'running', service, capture_output=True).stdout.strip()

    def configure(self, mode):
        arguments = ['run', '--rm', '-T', '--no-deps']
        if mode == 'disconnect':
            # Removing profile registrations needs neither root nor treasury auth.
            arguments += ['--entrypoint', '/opt/hermes/.venv/bin/python', '--volume',
                          f'{self.root / "components"}:/opt/private-hermes:ro', 'hermes-config',
                          '/opt/private-hermes/provisioning/setup.py', 'mcp', mode]
        else:
            arguments += ['mcp-config', mode]
        result = self.call(*arguments, capture_output=True)
        return json.loads(result.stdout)['changed']

    def client_arguments(self, action):
        script = (self.root / 'components/x402_treazury/mcp-client.py').read_text()
        return [*self.command, 'exec', '-T', '--user', '10000:10000', 'hermes',
                '/opt/hermes/.venv/bin/python', '-c', script, action]

    def client(self, action, check=True):
        return subprocess.run(self.client_arguments(action),
                              cwd=self.root, text=True, capture_output=True, check=check)

    def serving_instance(self):
        identifier = self.running('x402_treazury')
        if not identifier:
            # A quick native startup failure may precede the live observer.
            stopped = self.call('ps', '-a', '-q', 'x402_treazury', capture_output=True).stdout.strip()
            if stopped:
                started = subprocess.check_output(['docker', 'inspect', stopped, '--format',
                                                   '{{.State.StartedAt}}'], text=True)
                subprocess.run(['docker', 'logs', '--since', log_since(started), stopped], cwd=self.root, check=True)
            raise RuntimeError('Research service stopped before MCP activation completed; see its startup diagnostics.')
        # Podman's start time contains spaces, so the restart count comes first.
        restarts, started = subprocess.check_output(['docker', 'inspect', identifier, '--format',
                                                     '{{.RestartCount}}|{{.State.StartedAt}}'],
                                                    text=True).strip().split('|', 1)
        return identifier, log_since(started), restarts

    def require_instance(self, expected):
        if self.serving_instance() != expected:
            raise RuntimeError('Research service restarted or was replaced before MCP activation completed; inspect its logs and retry activation.')

    def wait_for_endpoints(self):
        instance = self.serving_instance()
        print('Waiting for all twelve authenticated research MCP endpoints (Ctrl-C leaves Hermes available).', flush=True)
        next_report = time.monotonic() + 30
        probe = None
        with serving_diagnostics(instance[0], instance[1], self.root) as failures:
            try:
                while True:
                    self.require_instance(instance)
                    if failures:
                        raise RuntimeError(failures[0])
                    if probe is None:
                        # Probe only initialize/list, never research/payment tools.
                        # Polling keeps native failures observable during protocol waits.
                        probe = subprocess.Popen([*self.client_arguments('probe'), '--watch-stdin'], cwd=self.root,
                                                 stdin=subprocess.PIPE,
                                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    code = probe.poll()
                    if code == 0:
                        self.require_instance(instance)
                        if failures:
                            raise RuntimeError(failures[0])
                        return instance
                    if code is not None:
                        if code != 75:
                            raise RuntimeError('Authenticated research MCP initialization/listing failed; endpoints were not connected. See the native startup diagnostics above.')
                        probe.communicate()
                        probe = None
                    now = time.monotonic()
                    if now >= next_report:
                        print('Still waiting for all twelve research MCP endpoints (Ctrl-C leaves Hermes available).', flush=True)
                        next_report = now + 30
                    time.sleep(1)
            finally:
                if probe is not None:
                    # EOF cancels the remote Python probe too, rather than merely
                    # killing Docker's local CLI and orphaning its exec process.
                    probe.communicate()

    def disconnect(self):
        if self.configure('disconnect') and self.running('hermes'):
            self.reload()

    def reload(self):
        while self.running('hermes'):
            result = self.client('reload', check=False)
            if result.returncode == 0:
                return
            if result.returncode != 75:
                raise RuntimeError('Hermes MCP reload failed; research remains disconnected. ' + (result.stderr or '').strip())
            time.sleep(1)
        raise RuntimeError('Hermes stopped before its MCP configuration could reload')

    def wallet_command(self, action):
        # Detached execution keeps Compose's interrupt handler from escalating
        # to SIGKILL after its ordinary shutdown timeout. We own graceful stop.
        project = json.loads(self.call('config', '--format', 'json', capture_output=True).stdout)['name']
        name = project + '-x402-onboarding'
        interrupted = []
        previous = {}
        logs = None
        started = finished = False
        def cancel(signum, _frame):
            interrupted.append(signum)
            subprocess.run(['docker', 'stop', '--timeout', '-1', name], cwd=self.root, check=False)
        try:
            # A retained container signals a prior interrupted/failed cleanup;
            # never remove or overwrite it implicitly.
            previous = {sig: signal.signal(sig, cancel) for sig in (signal.SIGINT, signal.SIGTERM)}
            self.call('run', '-d', '-T', '--no-deps', '--name', name, '--entrypoint', 'python3',
                      'x402_treazury-setup', '/opt/onboarding.py', action, capture_output=True)
            started = True
            if interrupted:
                cancel(interrupted[0], None)
            logs = subprocess.Popen(['docker', 'logs', '--follow', name], cwd=self.root)
            result = subprocess.run(['docker', 'wait', name], cwd=self.root, text=True,
                                    capture_output=True, check=True)
            code = int(result.stdout.strip())
            finished = True
            logs.wait()
            if interrupted or code:
                raise RuntimeError(f'x402_treazury {action} stopped (exit {code}); inspect status before retrying.')
        finally:
            if started and not finished:
                subprocess.run(['docker', 'stop', '--timeout', '-1', name], cwd=self.root, check=False)
            for sig, handler in previous.items():
                signal.signal(sig, handler)
            if logs and logs.poll() is None:
                logs.terminate()
                logs.wait()
            # Non-forced removal refuses a still-running financial operation.
            if started:
                subprocess.run(['docker', 'rm', name], cwd=self.root, check=False, capture_output=True)

    def initialize(self):
        state = self.inspect()
        if not state['wallet_absent'] and not state['wallet_valid']:
            raise RuntimeError(state['reason'])
        if state['wallet_valid']:
            print('Wallet already initialized; displaying saved wallet state.', flush=True)
            self.admin('status')
            return
        subprocess.run([sys.executable, str(self.root / 'scripts/init-config.py'), '--wallet'],
                       cwd=self.root, check=True)
        initialize_research_config(self.command, self.root)
        self.call('up', '-d', '--wait', '--no-deps', 'tor', 'agent-net')
        self.wallet_command('init')

    def prepare(self):
        if not self.running('hermes'):
            raise RuntimeError('Start Hermes with make up before preparing research services.')
        # The setup/admin jobs share this image but have no build definition.
        # Finish the cached build before inspection, disconnection or wallet work.
        self.call('build', 'x402_treazury')
        initialize_research_config(self.command, self.root)
        if self.inspect()['prepared']:
            self.activate()
            return
        self.admin('validate')
        self.disconnect()
        self.call('stop', '--timeout', '-1', 'x402_treazury')
        self.admin('disconnected')
        self.wallet_command('prepare')
        self.activate()

    def activate(self):
        if not self.running('hermes'):
            raise RuntimeError('Start Hermes with make up before connecting research services.')
        self.admin('validate')
        state = self.inspect()
        if not state['prepared']:
            raise RuntimeError(state['reason'] + ' Run make x402_treazury-prepare when ready.')
        try:
            self.configure('token')
            self.call('up', '-d', '--no-deps', 'x402_treazury')
            instance = self.wait_for_endpoints()
            self.require_instance(instance)
            self.configure('connect')
            self.require_instance(instance)
            self.reload()
            self.admin('connected')
            print('Research services prepared and connected to Hermes.', flush=True)
        except (Exception, KeyboardInterrupt):
            self.configure('disconnect')
            if self.running('hermes'):
                self.client('reload', check=False)
            self.admin('activation-failed')
            raise

    def startup(self):
        try:
            state = self.inspect()
            if state['prepared']:
                self.activate()
            else:
                if self.running('x402_treazury'):
                    self.call('stop', '--timeout', '-1', 'x402_treazury')
                print('Research preparation pending: ' + state['reason'] + '\n'
                      'Use make x402_treazury-init, then make x402_treazury-prepare. Hermes is available.')
        except Exception as error:
            print('Hermes is available; research activation failed: ' + str(error), file=sys.stderr)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('init', 'status', 'prepare', 'config'))
    args = parser.parse_args()
    # Only treasury and existing Hermes control RPC are used here. Actual treasury
    # policy is validated by its own admin/job, not unrelated ingress settings.
    controller = Controller(maintenance_compose())
    if args.action == 'config':
        initialize_research_config(controller.command, ROOT)
        print('Research policy is available at config/x402_treazury/research_desk.toml; existing policy was preserved.')
        return
    if args.action == 'status':
        controller.admin('status')
    else:
        with operation_lock(ROOT):
            if args.action == 'init':
                controller.initialize()
            else:
                controller.prepare()


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError, KeyboardInterrupt) as error:
        print(str(error) or 'Interrupted; wallet journals were retained.', file=sys.stderr)
        sys.exit(1)
