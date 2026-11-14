#!/bin/sh
set -eu
# /run and /tmp are fresh tmpfs mounts, hiding image-seeded directories.
mkdir -p /run/sshd /tmp/.X11-unix
chmod 0755 /run/sshd
chmod 1777 /tmp/.X11-unix
# Create the bus/runtime directory as runner; sshd's CHOWN is for PTY setup.
setpriv --reuid=10000 --regid=10000 --clear-groups \
    sh -c 'set -e
        mkdir -p /tmp/hermes-runtime
        chmod 0700 /tmp/hermes-runtime
        # No browser survives container startup. These links/port belong to its
        # old process namespace; retain all persistent profile data.
        profile=/home/runner/.hermes/bot-desktop/browser-profile
        rm -f "$profile/SingletonLock" "$profile/SingletonSocket" \
            "$profile/SingletonCookie" "$profile/DevToolsActivePort"'
exec /usr/sbin/sshd -D -e -f /etc/ssh/sshd_config
