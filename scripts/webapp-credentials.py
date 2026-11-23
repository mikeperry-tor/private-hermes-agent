#!/usr/bin/env python3
"""Explicit operator workflow: show, create, or rotate webapp login credentials."""
import argparse
import io
import os
from pathlib import Path
import re
from deployment import ROOT, parse_stream
from auth import initialize_credentials

USERNAME_PATTERN = re.compile(r'[A-Za-z0-9_.@-]+')


def read_webapp_username(root):
    """Read WEBAPP_USERNAME from the environment or .env without validating unrelated settings."""
    if 'WEBAPP_USERNAME' in os.environ:
        value, source = os.environ['WEBAPP_USERNAME'] or 'admin', 'the environment'
    else:
        path = Path(root) / '.env'
        source = '.env'
        try:
            text = path.read_text(encoding='utf-8')
        except FileNotFoundError:
            value = 'admin'
        except (OSError, UnicodeDecodeError):
            return None, 'WEBAPP_USERNAME could not be read from .env'
        else:
            found = None
            for binding in parse_stream(io.StringIO(text)):
                if binding.error:
                    return None, 'WEBAPP_USERNAME could not be read from .env'
                if binding.key == 'WEBAPP_USERNAME' and binding.value is not None:
                    found = binding.value
            value = found or 'admin'
    if not USERNAME_PATTERN.fullmatch(value):
        return None, f'WEBAPP_USERNAME in {source} is invalid'
    return value, None


def has_saved_password(root):
    password_path = Path(root) / 'config/webapp/password'
    return password_path.is_file() and bool(password_path.read_text(encoding='utf-8').strip())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--rotate', action='store_true', help='Replace password and signing key, invalidating all sessions')
    args = parser.parse_args()
    changed = initialize_credentials(ROOT, rotate=args.rotate)
    username, note = read_webapp_username(ROOT)
    subject = f' for {username}' if username else ''
    detail = f'; {note}' if note else ''
    if changed:
        verb = 'Rotated' if args.rotate else 'Generated'
        print(f'{verb} webapp credentials{subject} in config/webapp/password (0600); password was not printed{detail}.')
        if args.rotate:
            print('Apply rotation with make up to reprovision and recreate Hermes.')
    elif has_saved_password(ROOT):
        if username:
            print(f'Existing webapp credentials preserved; credentials for {username} are in config/webapp/password (not printed).')
        else:
            print(f'Existing webapp credentials preserved; password is in config/webapp/password (not printed{detail}).')
    else:
        print(f'Existing webapp credentials{subject} preserved, but config/webapp/password is missing or empty{detail}.')


if __name__ == '__main__':
    main()
