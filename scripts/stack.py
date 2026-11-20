#!/usr/bin/env python3
"""Apply validated deployment settings; Funnel is never enabled implicitly."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
from deployment import (ROOT, check_bind_sources, check_engine, compose, compose_base, compose_files, prepare_launch, remove_networks, render,
                        settings, maintenance_compose, maintenance_command, needs_networks, split_passthrough)
from auth import validate
from x402_treazury import Controller, operation_lock
from provisioning import initialize_setup, initialize_research_config, report_research_config_diff


def run(command, **kwargs):
    return subprocess.run(command, cwd=ROOT, check=True, **kwargs)


def capture(command):
    return run(command, text=True, capture_output=True).stdout.strip()


def run_preflight(command):
    # Preflight prints its own diagnostic and exits non-zero. Propagate the
    # status without a wrapper traceback.
    try:
        run(command)
    except subprocess.CalledProcessError as error:
        raise SystemExit(error.returncode) from None


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
        all_command = maintenance_compose(all_ingress=True) + ['--profile', '*']
        try:
            stop_funnel(all_command)
        finally:
            run(all_command + ['down', '--timeout', '-1'])
            remove_networks(all_command)
        return
    if args.action == 'compose':
        if not args.arguments:
            raise ValueError('Provide a Compose command after compose')
        # Global options come before the subcommand. Keep the user's files
        # before the engine files, and use the same project and profiles for
        # network preparation, the command and cleanup.
        files, options, dry_run, rest = split_passthrough(args.arguments)
        if not rest:
            raise ValueError('Provide a Compose command after the global options')
        if rest[0] == 'config':
            # Inspect the actual model, including invalid policy values, without
            # replacing them with maintenance placeholders or pre-validating policy.
            run([*compose_base(), *compose_files(True, files), *options, *rest])
            return
        if maintenance_command(rest):
            command = maintenance_compose(all_ingress=True, executor_build=rest[0] == 'build', extra=files) + options
            if rest[0] == 'run' and needs_networks(command, rest):
                raise ValueError('Offline maintenance jobs require network_mode: none for the job and its dependencies. '
                                 'Remove the networking/dependency override before running this job.')
            if rest[0] == 'down':
                command += ['--profile', '*']
            check_bind_sources(command, rest, dry_run=dry_run)
            run(command + rest)
            if rest[0] == 'down' and not dry_run:
                remove_networks(command)
            return
        config = settings(extra=files, options=options)
        command = compose(config, extra=files) + options
        check_bind_sources(command, rest, dry_run=dry_run)
        if not dry_run and needs_networks(command, rest):
            prepare_launch(command)
        run(command + rest)
        return
    config = settings()
    command = compose(config)
    all_command = compose(config, all_ingress=True)
    if args.action == 'config':
        run(command + ['config', '--quiet'])
    else:
        # Refuse a wrong engine or an endpoint override before setup writes anything.
        check_engine()
        run_preflight([sys.executable, 'scripts/preflight.py', *(['--funnel'] if config.funnel else [])])
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
        report_research_config_diff(command, ROOT)
        initialize_setup(command)
        infrastructure = ['tor', 'agent-net', 'executor-net', 'executor', 'teep']
        check_bind_sources(command, ['up', '--no-deps', *infrastructure])
        prepare_launch(command)
        run(command + ['up', '-d', '--wait', '--no-deps', *infrastructure])
        controller = Controller(command, ROOT)
        # Setup already removed research registrations. The recreated gateway
        # reads that configuration without needing an old gateway's control RPC.
        check_bind_sources(command, ['up', '--no-deps', 'webapp-proxy', 'hermes'])
        run(command + ['up', '-d', '--no-deps', '--force-recreate', 'webapp-proxy', 'hermes'])
        if config.funnel:
            check_bind_sources(command, ['up', '--no-deps', 'tailscale'])
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
