#!/usr/bin/env python3
"""Select a mounted research_desk.toml override when present, else the image default."""
import os
import sys

BINARY = '/opt/x402/bin/x402_treazury'
OVERRIDE = '/opt/x402/examples/deployments/research_desk.toml'
DEFAULT = '/opt/x402/defaults/deployments/research_desk.toml'
CONFLICT_FLAGS = ('--config', '--provider', '--state-dir', '--key-file', '--treasury-id')
SKIP_FLAGS = ('-h', '--help', '-V', '--version')


def needs_default_config(argv):
    if 'X402_TREAZURY_CONFIG' in os.environ:
        return False
    if argv and argv[0] == 'build-info':
        return False
    for arg in argv:
        if arg == '--':
            break
        if (arg in SKIP_FLAGS or arg in CONFLICT_FLAGS
                or any(arg.startswith(flag + '=') for flag in CONFLICT_FLAGS)):
            return False
    return True


def resolve_config():
    try:
        os.lstat(OVERRIDE)
    except FileNotFoundError:
        return DEFAULT
    except OSError as error:
        raise SystemExit(f'Cannot inspect research configuration override {OVERRIDE}: {error}') from error
    return OVERRIDE


def main():
    if needs_default_config(sys.argv[1:]):
        os.environ['X402_TREAZURY_CONFIG'] = resolve_config()
    os.execv(BINARY, [BINARY, *sys.argv[1:]])


if __name__ == '__main__':
    main()
