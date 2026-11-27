# Official v0.23.4, source 8fc0374447313e276f6b9a2764bfc750190c966a.
FROM nousresearch/hermes-agent@sha256:ef0650d523ee1b5ab32c779acabc446d9936869a9932591553688a62bcf0c42f AS upstream

FROM upstream AS webapp-build
COPY components/hermes/verify-build.mjs /tmp/verify-build.mjs
RUN node /tmp/verify-build.mjs
# Upstream's runtime omits pnpm. Use its own hash-verified PM pin, only in
# this disposable frontend stage, matching the upstream frontend build.
RUN python3 -c 'from pathlib import Path; from pm import ensure, installed_package; ensure("pnpm", explicit=True); Path("/usr/local/bin/pnpm").symlink_to(installed_package("pnpm").binary)'
RUN node apps/desktop/scripts/build-webapp.mjs --deps-only
COPY components/hermes/ui/private-content.tsx /opt/hermes/apps/desktop/src/components/ui/private-content.tsx
COPY components/hermes/patches/ /tmp/private-hermes-patches/
RUN set -e; for patch in /tmp/private-hermes-patches/*.patch; do git apply "$patch"; done
# The inherited output is an overlay lower-layer directory; replacing it by
# rename fails EXDEV. Remove only this disposable build output before compiling.
RUN rm -rf apps/desktop/dist-webapp && \
    node apps/desktop/scripts/build-webapp.mjs --no-install
# Replace the upstream layer's TUI workspace links before pnpm installs them.
RUN rm -rf node_modules ui-tui/node_modules ui-tui/packages/*/node_modules apps/shared/node_modules && \
    pnpm install --frozen-lockfile --filter hermes-tui... && \
    node scripts/build/tui.mjs --source /opt/hermes --out /tmp/private-hermes-tui && \
    rm -rf /opt/hermes/hermes_cli/tui_dist && \
    cp -a /tmp/private-hermes-tui/dist /opt/hermes/hermes_cli/tui_dist && \
    cp /tmp/private-hermes-tui/package.json /opt/hermes/hermes_cli/tui_dist/package.json

FROM upstream
# COPY overlays inherited directories. Remove the old output so obsolete chunks
# cannot survive alongside the qualified rebuilt frontend.
RUN rm -rf /opt/hermes/apps/desktop/dist-webapp /opt/hermes/ui-tui/dist /opt/hermes/hermes_cli/tui_dist
COPY --from=webapp-build /opt/hermes/hermes_bootstrap.py /opt/hermes/hermes_bootstrap.py
COPY --from=webapp-build /opt/hermes/hermes_cli/ /opt/hermes/hermes_cli/
COPY --from=webapp-build /opt/hermes/docker/entrypoint-dispatch.sh /opt/hermes/docker/entrypoint-dispatch.sh
COPY --from=webapp-build /opt/hermes/agent/ /opt/hermes/agent/
COPY --from=webapp-build /opt/hermes/cron/ /opt/hermes/cron/
COPY --from=webapp-build /opt/hermes/gateway/ /opt/hermes/gateway/
COPY --from=webapp-build /opt/hermes/persistence/ /opt/hermes/persistence/
COPY --from=webapp-build /opt/hermes/plugins/computer_use/ /opt/hermes/plugins/computer_use/
COPY --from=webapp-build /opt/hermes/plugins/kanban/ /opt/hermes/plugins/kanban/
COPY --from=webapp-build /opt/hermes/session_rules/ /opt/hermes/session_rules/
COPY --from=webapp-build /opt/hermes/tools/ /opt/hermes/tools/
COPY --from=webapp-build /opt/hermes/tui_gateway/ /opt/hermes/tui_gateway/
COPY --from=webapp-build /opt/hermes/cli.py /opt/hermes/model_tools.py /opt/hermes/run_agent.py /opt/hermes/toolsets.py /opt/hermes/
COPY --from=webapp-build /opt/hermes/apps/desktop/dist-webapp/ /opt/hermes/apps/desktop/dist-webapp/
COPY --from=webapp-build /tmp/private-hermes-tui/dist/ /opt/hermes/ui-tui/dist/
COPY components/network/addressing.py /opt/hermes/hermes_cli/private_addressing.py
COPY components/hermes/managed_policy.py /opt/hermes/docker/private-managed-policy.py
COPY components/hermes/external_content.py /opt/hermes/hermes_cli/private_external_content.py
COPY components/hermes/public_images.py /opt/hermes/hermes_cli/private_public_images.py
COPY components/hermes/browser_policy.py /opt/hermes/hermes_cli/private_browser_policy.py
COPY --chown=0:0 --chmod=0644 components/hermes/ssh-client.conf /etc/ssh/private-hermes-ssh.conf
# Keep the user-writable profile wrapper directory last so root s6, cont-init
# and wrapper command lookup cannot execute profile content. Unique profile
# wrapper names still resolve for the unprivileged application.
ENV PATH=/opt/hermes/bin:/opt/hermes/.venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/opt/data/.local/bin
ENV HERMES_MANAGED_DIR=/etc/hermes
ENV HERMES_WEBAPP_DIST=/opt/hermes/apps/desktop/dist-webapp
