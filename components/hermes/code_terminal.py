"""Stack-owned placement for ordinary WebApp terminals; native PTYs own lifecycle."""
import asyncio
import json
from pathlib import Path
import shlex

from hermes_bootstrap import PRIVATE_HERMES_TERMINAL_ENVIRONMENT, PRIVATE_HERMES_TERMINAL_SSH


class CodeTerminalError(RuntimeError):
    """A fixed, nonprivate message safe for the browser startup error."""


def environment():
    mode = PRIVATE_HERMES_TERMINAL_ENVIRONMENT
    if mode not in ('code', 'agent'):
        raise CodeTerminalError('WEBAPP_TERMINAL_ENVIRONMENT must be code or agent')
    return mode


def validate_path(path):
    if not isinstance(path, str) or not path.startswith('/') or any(ord(c) < 32 or ord(c) == 127 for c in path):
        raise CodeTerminalError('Code terminal cwd must be an absolute path without control characters')
    try:
        path.encode('utf-8')
    except UnicodeEncodeError:
        raise CodeTerminalError('Code terminal cwd must be valid UTF-8') from None
    return path


def ssh_argv():
    host, port, user, key = PRIVATE_HERMES_TERMINAL_SSH
    if not all((host, port, user, key)) or not port.isdecimal() or not 1 <= int(port) <= 65535:
        raise CodeTerminalError('Code terminal requires the stack TERMINAL_SSH connection settings')
    if not Path(key).is_file():
        raise CodeTerminalError('Code terminal SSH identity is missing; run make init and make up')
    # Command-line options cannot be relaxed by profile settings or client config.
    return ['/usr/bin/ssh', '-F', '/etc/ssh/ssh_config.d/99-private-hermes.conf',
            '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
            '-o', 'IdentitiesOnly=yes', '-o', 'ForwardAgent=no',
            '-o', 'ClearAllForwardings=yes', '-o', 'ConnectTimeout=10',
            '-o', 'EscapeChar=none', '-i', key, '-p', port, '-l', user, host]


# The probe changes directory too: is_dir alone does not prove search permission.
_PROBE = '''import json, os, shutil, sys
from pathlib import Path
if not shutil.which('bash'):
    sys.exit(3)
try:
    p = Path(sys.argv[1]).resolve(strict=True)
    if p.is_file(): p = p.parent
    os.chdir(p)
    print(json.dumps(os.getcwd()))
except (OSError, RuntimeError, ValueError):
    sys.exit(2)
'''

# bash --rcfile preserves system/user initialization and existing prompt hooks.
# OSC 7 encodes whitespace and metacharacters as URI data, never shell syntax.
_RC = r'''
if [ -f /etc/bash.bashrc ]; then source /etc/bash.bashrc; fi
if [ -f ~/.bashrc ]; then source ~/.bashrc; fi
_private_hermes_cwd() {
    python3 -c 'import os, urllib.parse; print("\033]7;file://executor" + urllib.parse.quote(os.getcwd(), safe="/") + "\007", end="", flush=True)'
}
if declare -p PROMPT_COMMAND 2>/dev/null | grep -q 'declare -a'; then
    PROMPT_COMMAND+=(_private_hermes_cwd)
else
    PROMPT_COMMAND="${PROMPT_COMMAND:+${PROMPT_COMMAND}; }_private_hermes_cwd"
fi
'''


async def prepare(home, requested_cwd=None):
    from hermes_cli.config_backend import ConfigBackendUnavailable
    from hermes_cli.web_host_terminal import resolve_argv

    mode = environment()
    # Keep native profile-scoped environment and the agent shell selection ladder.
    try:
        argv, local_cwd, env, shell = await asyncio.to_thread(
            resolve_argv, home=home, requested_cwd=requested_cwd if mode == 'agent' else None,
            use_profile_cwd=mode == 'agent')
    except ConfigBackendUnavailable:
        raise CodeTerminalError('Code terminal: configuration backend is unavailable') from None
    if mode == 'agent':
        return argv, local_cwd, env, 'Agent · ' + shell, local_cwd

    requested = validate_path('/workspace' if requested_cwd is None else requested_cwd)
    ssh = ssh_argv()
    probe = await asyncio.create_subprocess_exec(
        ssh[0], '-n', *ssh[1:], 'python3 -c ' + shlex.quote(_PROBE) + ' ' + shlex.quote(requested),
        env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    try:
        output, _ = await probe.communicate()
    except BaseException:
        if probe.returncode is None:
            probe.kill()
        await probe.wait()
        raise
    if probe.returncode:
        # Do not echo raw SSH diagnostics (paths, targets or startup-file output).
        if probe.returncode == 2:
            reason = 'cwd is missing or inaccessible'
        elif probe.returncode == 3:
            reason = 'Bash is unavailable on the executor'
        else:
            reason = 'SSH connection or remote Python failed; check executor availability, client identity and pinned host key'
        raise CodeTerminalError('Code terminal: ' + reason)
    try:
        remote_cwd = validate_path(json.loads(output))
    except (ValueError, RuntimeError):
        raise CodeTerminalError('Code terminal: executor returned an invalid cwd') from None
    command = 'cd -- ' + shlex.quote(remote_cwd) + ' && exec bash --rcfile <(printf %s ' + shlex.quote(_RC) + ') -i'
    remote = 'bash -c ' + shlex.quote(command)
    # -tt must precede destination. No local chdir to an executor-only path.
    return [ssh[0], '-tt', *ssh[1:], remote], str(home), env, 'Code · bash', remote_cwd
