"""Offline setup using the stock Hermes image; no wallet creation or networking."""
import argparse
import json
import os
from pathlib import Path
import sys

COMPONENTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(COMPONENTS / 'network'))
sys.path.insert(0, str(COMPONENTS / 'webapp'))
sys.path.insert(0, str(COMPONENTS / 'x402_treazury'))
from storage import prepare, verify_filesystem
from bootstrap import initialize
from registration import configure

DATA = Path('/persistent-data')
HERMES = Path('/opt/data')
WALLET = Path('/var/lib/x402')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    commands.add_parser('init', help='Prepare storage, SSH, webapp auth and disconnected MCP configuration')
    commands.add_parser('storage', help='Prepare storage ownership and verify database locking only')
    mcp = commands.add_parser('mcp', help='Manage the research MCP token and registrations')
    mcp.add_argument('mode', choices=('token', 'connect', 'disconnect'))
    check = commands.add_parser('check-filesystem', help='Check locking using temporary probe files only')
    check.add_argument('path', type=Path)
    args = parser.parse_args()
    if args.action == 'check-filesystem':
        verify_filesystem(args.path)
        print('PASS: fresh-file flock and SQLite WAL writer exclusion enforced.')
        return
    if args.action == 'mcp':
        print(json.dumps(configure(args.mode, HERMES, DATA / 'x402_treazury-auth')))
        return
    prepare(DATA, HERMES, WALLET)
    if args.action == 'init':
        initialize(DATA, HERMES, COMPONENTS / 'hermes/config.example.yaml',
                   Path('/run/webapp/auth.json'), os.environ['WEBAPP_USERNAME'])
        configure('disconnect', HERMES, DATA / 'x402_treazury-auth')
        print('Offline setup complete; wallet creation and preparation remain explicit.')


if __name__ == '__main__':
    main()
