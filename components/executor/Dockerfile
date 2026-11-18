# Public screenshot helper from the exact packaged Hermes revision, not its runtime.
FROM nousresearch/hermes-agent@sha256:d6746a084e9341baada483e3d6210444d3c1aeb7c130f0915150065fb2851459 AS browser-source

FROM alpine:3.24 AS executor-false
RUN apk add --no-cache bash python3 py3-pip py3-yaml git curl openssh-server openssh-client nodejs npm tar coreutils \
    && addgroup -g 10000 runner \
    && adduser -D -u 10000 -G runner -s /bin/bash runner \
    && passwd -u runner \
    && mkdir -p /workspace /run/sshd \
    && chown runner:runner /workspace
COPY components/executor/sshd_config /etc/ssh/sshd_config
WORKDIR /workspace
CMD ["/usr/sbin/sshd", "-D", "-e", "-f", "/etc/ssh/sshd_config"]

# Independently published desktop sandbox; qualify separately from Hermes source.
FROM nousresearch/hermes-sandbox@sha256:c7d8607d076f26a64e0bd6828f74e1764af43fe3281368188459bb693bfa7567 AS executor-true
USER root
RUN apt-get update && apt-get install -y --no-install-recommends openssh-server openssh-client \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir PyYAML \
    && groupmod -g 10000 -n runner pn \
    && usermod -u 10000 -g 10000 -l runner -d /home/runner -s /bin/bash pn \
    && passwd -d runner \
    && rm -f /etc/sudoers.d/pn \
    && mkdir -p /workspace /home/runner \
    && chown runner:runner /workspace /home/runner
COPY components/executor/sshd_config /etc/ssh/sshd_config
COPY components/executor/start-desktop.sh /usr/local/bin/executor-start
COPY components/executor/browser-requirements.txt /opt/private-hermes/browser-requirements.txt
RUN python3 -m venv /opt/browser-harness \
    && /opt/browser-harness/bin/pip install --no-deps --require-hashes -r /opt/private-hermes/browser-requirements.txt
COPY --from=browser-source /opt/hermes/tools/browser_use_shot.py /opt/private-hermes/browser_use_shot.py
COPY --from=browser-source /opt/hermes/LICENSE /opt/private-hermes/hermes-LICENSE
COPY components/executor/browser-session.py /opt/private-hermes/browser-session.py
RUN chmod 0755 /usr/local/bin/executor-start \
    && printf '\nSetEnv PLAYWRIGHT_BROWSERS_PATH=/opt/playwright XDG_RUNTIME_DIR=/tmp/hermes-runtime CUA_DRIVER_RS_TELEMETRY_ENABLED=0\n' >> /etc/ssh/sshd_config
WORKDIR /workspace
CMD ["/usr/local/bin/executor-start"]
