#!/usr/bin/env python3
"""Initialize local operator configuration without replacing existing settings."""
from pathlib import Path
import argparse
import stat
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'components/webapp'))
from auth import initialize_credentials
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'components/provisioning'))
from storage import initialize as initialize_storage
from private_files import publish_default


def initialize(root, wallet_only=False):
    root = Path(root)
    env = root / '.env'
    if not env.exists():
        publish_default(env, (root / '.env.example').read_bytes(), 0o600)

    target = root / 'config/network/mcp-allowlist.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        source = root / 'components/network/mcp-allowlist.json'
        publish_default(target, source.read_bytes(), stat.S_IMODE(source.stat().st_mode))
    if not target.is_file():
        raise SystemExit('config/network/mcp-allowlist.json must be a file')
    initialize_storage(root / 'data', paths=('tor',) if wallet_only else None)
    if not wallet_only:
        initialize_credentials(root)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wallet', action='store_true', help='Prepare new-wallet Tor/network inputs without unrelated host paths')
    args = parser.parse_args()
    initialize(Path(__file__).resolve().parents[1], wallet_only=args.wallet)
    if not args.wallet:
        from deployment import render, settings
        config, _ = settings(allow_unused_teep=True)
        render(config)
    print('Initialized local configuration; existing settings and application volumes preserved.')
    if not args.wallet:
        print('Webapp password: config/webapp/password (0600); credentials were not printed.')
