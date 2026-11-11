#!/usr/bin/env python3
"""Apply validated deployment settings; Funnel is never enabled implicitly."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
from deployment import ROOT, compose, compose_files, ensure_networks, remove_networks, render, settings, maintenance_compose, maintenance_command
from auth import validate
from x402_treazury import Controller, operation_lock
from provisioning import initialize_setup, initialize_research_config


def run(command, **kwargs):
    return subprocess.run(command, cwd=ROOT, check=True, **kwargs)


def capture(command):
    return run(command, text=True, capture_output=True).stdout.strip()


def require_inference_key(command):
    # Teep exits at once without a provider key. Rootless Podman restarts it
    # without backoff and `up --wait` would wait without end, so stop here.
    environment = json.loads(capture(command + ['config', '--format', 'json']))['services']['teep']['environment']
    if not any(value for name, value in environment.items() if name.endswith('_API_KEY')):
        raise RuntimeError('Set at least one inference provider API key in .env, for example NEARAI_API_KEY. '
                           'Teep does not start without one.')


def stop_funnel(all_command):
    identifier = capture(all_command + ['ps', '-q', '--status', 'running', 'tailscale'])
    if identifier:
        result = subprocess.run(all_command + ['exec', '-T', 'tailscale', 'tailscale',
                               '--socket=/tmp/tailscaled.sock', 'funnel', 'reset'],
                                cwd=ROOT, text=True, capture_output=True)
        run(all_command + ['stop', 'tailscale'])
        if result.returncode:
            raise RuntimeError('Stopped Tailscale, but could not confirm persistent Funnel reset. Inspect the node before re-enabling.')
    run(all_command + ['stop', 'tailscale'])
    run(all_command + ['rm', '-f', 'tailscale'])


def main_unlocked():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('build', 'up', 'down', 'config', 'compose'))
    parser.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.action == 'build':
        run(maintenance_compose(all_ingress=True, executor_build=True) + ['--profile', '*', 'build'])
        return
    if args.action == 'down':
        all_command = maintenance_compose(all_ingress=True)
        try:
            stop_funnel(all_command)
        finally:
            run(all_command + ['down', '--timeout', '-1'])
            remove_networks(all_command)
        return
    if args.action == 'compose' and args.arguments[:1] == ['config']:
        # Inspect the actual model, including invalid policy values, without
        # replacing them with maintenance placeholders or pre-validating policy.
        run(['docker', 'compose', *compose_files(True), *args.arguments])
        return
    if args.action == 'compose' and maintenance_command(args.arguments):
        run(maintenance_compose(all_ingress=True, executor_build=args.arguments[:1] == ['build']) + args.arguments)
        return
    config = settings()
    command = compose(config)
    all_command = compose(config, all_ingress=True)
    if args.action == 'compose':
        if not args.arguments:
            raise ValueError('Provide a Compose command after compose')
        if args.arguments[0] in ('up', 'create', 'run', 'start'):
            ensure_networks(command)
        run(command + args.arguments)
        if args.arguments[0] == 'down':
            remove_networks(command)
    elif args.action == 'config':
        run(command + ['config', '--quiet'])
    else:
        run([sys.executable, 'scripts/preflight.py', *(['--funnel'] if config.funnel else [])])
        path = ROOT / 'config/webapp/auth.json'
        if not path.is_file():
            raise RuntimeError('Run make init before starting the stack.')
        validate(json.loads(path.read_text()))
        require_inference_key(command)
        # Build shared images before setup consumes them or services are changed.
        # Include treasury even before preparation: setup/config seeding need it.
        run(command + ['--profile', 'x402_treazury', 'build'])
        render(config)
        if not config.funnel:
            stop_funnel(all_command)
        # A changed bind-mounted credential file does not itself recreate a
        # completed container. Always apply current settings before startup.
        initialize_research_config(command, ROOT)
        initialize_setup(command)
        infrastructure = ['tor', 'agent-net', 'executor-net', 'executor', 'teep']
        ensure_networks(command)
        run(command + ['up', '-d', '--wait', '--no-deps', *infrastructure])
        controller = Controller(command, ROOT)
        # Setup already removed research registrations. The recreated gateway
        # reads that configuration without needing an old gateway's control RPC.
        run(command + ['up', '-d', '--no-deps', '--force-recreate', 'webapp-proxy', 'hermes'])
        if config.funnel:
            run(command + ['up', '-d', '--no-deps', 'tailscale'])
        controller.startup()


def main():
    if len(sys.argv) > 1 and sys.argv[1] in ('up', 'down'):
        with operation_lock(ROOT):
            main_unlocked()
    else:
        main_unlocked()


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError) as error:
        raise SystemExit(str(error))
