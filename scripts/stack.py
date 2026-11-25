#!/usr/bin/env python3
"""Apply validated deployment settings; Funnel is never enabled implicitly."""
import argparse
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
from deployment import (ROOT, check_bind_sources, check_engine, compose, compose_base, compose_files,
                        engine, engine_command, inspect_launch, maintenance_command, maintenance_compose, prepare_launch,
                        parse_launch, remove_networks, render, settings, split_passthrough)
from auth import validate
from x402_treazury import Controller, operation_lock
from provisioning import initialize_setup, initialize_research_config, report_research_config_diff
from project_mounts import (PROJECTS, SETTING, bind_sources, check_project_model, engine_views, parse_mounts,
                            overlaps, project_override, source_ids, valid_destination, validate_sources)


EXECUTOR_ROOTS = 'PRIVATE_HERMES_EXECUTOR_ROOTS'
CHAT_SETTINGS = ('WEBAPP_TERMINAL_ENVIRONMENT', 'WEBAPP_EXTERNAL_CONTENT', 'COMPUTER_USE_ENABLED')
RECOVERY = 'Close open chats and run make down, then make up.'


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


def require_same_project_mounts(command, mounts):
    expected = {str(target): str(source) for target, source in mounts.items()}
    for executor in capture(command + ['ps', '-a', '-q', 'executor']).splitlines():
        attached = attached_project_mounts(executor)
        if attached != expected:
            raise ValueError(f'Run make down before applying changes to {SETTING}.')


def attached_project_mounts(executor):
    unavailable = f'Could not verify the executor mounts. {RECOVERY}'
    try:
        volumes = json.loads(capture([*engine_command(), 'inspect', '--format', '{{json .Mounts}}', executor]))
    except (subprocess.CalledProcessError, ValueError) as error:
        raise RuntimeError(unavailable) from error
    if not isinstance(volumes, list):
        raise RuntimeError(unavailable)
    attached = {}
    workspace = False
    for volume in volumes:
        target = volume.get('Destination') if isinstance(volume, dict) else None
        if not isinstance(target, str) or not target.startswith('/'):
            raise RuntimeError(unavailable)
        path = PurePosixPath(target)
        if path != PurePosixPath('/workspace') and not path.is_relative_to(PROJECTS):
            continue
        source = volume.get('Source')
        if volume.get('Type') != 'bind' or volume.get('RW') is not True or not isinstance(source, str) or not source.startswith('/'):
            raise RuntimeError(unavailable)
        if target == '/workspace' and not workspace:
            workspace = True
        elif not valid_destination(target) or any(overlaps(path, PurePosixPath(other)) for other in attached):
            raise RuntimeError(unavailable)
        else:
            attached[target] = source
    if not workspace:
        raise RuntimeError(unavailable)
    return attached


def running_service(command, service):
    unavailable = f'Could not identify the running {service} service. {RECOVERY}'
    try:
        # Compose includes one-off chats when ps receives --all or --status.
        containers = capture(command + ['ps', '-q', service]).splitlines()
        if len(containers) == 1:
            container = containers[0]
            if capture([*engine_command(), 'inspect', '--format', '{{.State.Status}}', container]) == 'running':
                return container
    except subprocess.CalledProcessError as error:
        raise RuntimeError(unavailable) from error
    raise RuntimeError(unavailable)


def executor_roots(mounts):
    return ['/workspace', *sorted(map(str, mounts))]


def start_chat():
    command = maintenance_compose()
    check_engine()
    gateway = running_service(command, 'hermes')
    executor = running_service(command, 'executor')
    mounted = executor_roots(attached_project_mounts(executor))
    unavailable = f'Could not verify the applied chat settings. {RECOVERY}'
    try:
        entries = json.loads(capture([*engine_command(), 'inspect', '--format', '{{json .Config.Env}}', gateway]))
        if not isinstance(entries, list):
            raise ValueError('container environment is not a list')
        applied = dict(entry.split('=', 1) for entry in entries)
        recorded = json.loads(applied[EXECUTOR_ROOTS])
        mode, content, desktop = (applied[name] for name in CHAT_SETTINGS)
    except (subprocess.CalledProcessError, ValueError, AttributeError, KeyError, TypeError) as error:
        raise RuntimeError(unavailable) from error
    if (recorded != mounted or mode not in ('code', 'agent') or desktop not in ('true', 'false')
            or content not in ('tor_proxied', 'ask', 'off', 'browser_native')):
        raise RuntimeError(unavailable)
    command = ['env', *(f'{name}={applied[name]}' for name in CHAT_SETTINGS),
               f'{EXECUTOR_ROOTS}={json.dumps(mounted)}', *command]
    arguments = ['run', '--rm', '--no-deps', 'hermes', 'chat']
    model, networked = inspect_launch(command, parse_launch(arguments))
    if networked:
        prepare_launch(command, model)
    run(command + arguments)


def main_unlocked():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('build', 'up', 'down', 'config', 'chat', 'compose'))
    parser.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.action == 'chat':
        start_chat()
        return
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
        files, options, dry_run, rest, launch = split_passthrough(args.arguments)
        if not rest:
            raise ValueError('Provide a Compose command after the global options')
        if rest[0] == 'config':
            # Inspect the actual model, including invalid policy values, without
            # replacing them with maintenance placeholders or pre-validating policy.
            run([*compose_base(), *compose_files(True, files), *options, *rest])
            return
        if maintenance_command(launch):
            command = maintenance_compose(all_ingress=True, executor_build=rest[0] == 'build', extra=files) + options
            if rest[0] == 'down':
                command += ['--profile', '*']
            inspect_launch(command, launch, dry_run=dry_run, require_offline=True)
            run(command + rest)
            if rest[0] == 'down' and not dry_run:
                remove_networks(command)
            return
        standalone = (launch.action == 'run' and launch.no_deps
                      and launch.targets[0] in ('hermes', 'x402_treazury'))
        config, prefix = settings(extra=files, options=options, allow_unused_teep=standalone)
        command = prefix + compose(config, extra=files) + options
        model, networked = inspect_launch(command, launch, dry_run=dry_run)
        if not dry_run and networked:
            prepare_launch(command, model, build_missing=launch.build)
        run(command + rest)
        return
    config, prefix = settings(allow_unused_teep=args.action == 'up')
    mounts = parse_mounts(config.executor_bind_mounts)
    original_sources = {}
    if args.action == 'up':
        # Validate project sources before any build or container creation.
        if mounts:
            views, protected, mac_mounts = engine_views(engine(), Path.home().resolve())
            base_command = prefix + compose(config, all_ingress=True)
            model = json.loads(capture(base_command + ['--profile', '*', 'config', '--format', 'json']))
            mounts, original_sources = validate_sources(mounts, ROOT, views,
                                                         (*protected, *bind_sources(model)), mac_mounts)
        check_engine()
    with project_override(mounts, ROOT) as extra:
        command = prefix + compose(config, extra=extra)
        if mounts:
            check_project_model(json.loads(capture(command + ['config', '--format', 'json'])), mounts)
        if args.action == 'config':
            if not mounts:
                run(command + ['config', '--quiet'])
        else:
            start_stack(config, prefix, command, mounts, original_sources)


def start_stack(config, prefix, command, mounts, original_sources):
    if mounts:
        require_same_project_mounts(command, mounts)
    inference = ['teep'] if config.teep else []
    funnel = ['tailscale'] if config.funnel else []
    network_endpoints = ['agent-net', 'executor-net']
    infrastructure = ['tor', *network_endpoints, 'executor', *inference]
    application = ['webapp-proxy', 'hermes']
    selected = [*infrastructure, *application, *funnel]
    run_preflight([*prefix, sys.executable, 'scripts/preflight.py', *(['--funnel'] if funnel else []),
                   '--services', *selected])
    path = ROOT / 'config/webapp/auth.json'
    if not path.is_file():
        raise RuntimeError('Run make init before starting the stack.')
    validate(json.loads(path.read_text()))
    if inference:
        require_inference_key(command)
    # Build shared images before setup consumes them or services are changed.
    # Include treasury even before preparation: setup/config seeding need it.
    build = [service for service in selected if service not in network_endpoints] + ['x402_treazury']
    run(command + ['build', *build])
    render(config)
    if not funnel:
        stop_funnel(prefix + compose(config, all_ingress=True))
    # A changed bind-mounted credential file does not itself recreate a
    # completed container. Always apply current settings before startup.
    initialize_research_config(command, ROOT)
    report_research_config_diff(command, ROOT)
    initialize_setup(command)
    model = check_bind_sources(command, ['up', '--no-deps', *selected])
    prepare_launch(command, model)
    if mounts:
        check_project_model(model, mounts)
        for source, identity in source_ids(mounts).items():
            if identity != original_sources[source]:
                raise ValueError(f'{SETTING} source changed before creation: {source}.')
    run(command + ['up', '-d', '--wait', '--no-deps', *infrastructure])
    executor = running_service(command, 'executor')
    attached = attached_project_mounts(executor)
    if attached != {str(target): str(source) for target, source in mounts.items()}:
        raise RuntimeError(f'Executor mounts differ from the validated configuration. {RECOVERY}')
    try:
        run(command + ['exec', '-T', '--user', '65534:65534', 'tor', 'cat', '/tmp/local-grant-warnings'])
    except subprocess.CalledProcessError:
        print('Could not read local grant warnings. Check the tor service logs.', file=sys.stderr)
    controller = Controller(command, ROOT)
    # Setup already removed research registrations. The recreated gateway
    # reads that configuration without needing an old gateway's control RPC.
    run(command + ['up', '-d', '--no-deps', '--force-recreate', *application],
        env={**os.environ, EXECUTOR_ROOTS: json.dumps(executor_roots(attached))})
    if funnel:
        run(command + ['up', '-d', '--no-deps', *funnel])
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
    except (OSError, ValueError, RuntimeError) as error:
        raise SystemExit(str(error))
