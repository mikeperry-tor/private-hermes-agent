# Official v0.23.3, source caafe5389ae585ef77387a962aee05b1bcf17029.
FROM nousresearch/hermes-agent@sha256:3e9fe4c6ef36490f43aa0d0d80f9df64e9c92a576eee3042f1a97c8813c05355 AS upstream

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

# Native browser session creation validates its agent-side cwd exists. This
# empty local directory is separate from the executor mount and contains no
# executor files; model terminal/code execution still uses SSH.
FROM upstream
# COPY overlays inherited directories. Remove the old output so obsolete chunks
# cannot survive alongside the qualified rebuilt frontend.
RUN install -d -m 0755 -o 10000 -g 10000 /workspace && \
    rm -rf /opt/hermes/apps/desktop/dist-webapp
COPY --from=webapp-build /opt/hermes/hermes_bootstrap.py /opt/hermes/hermes_bootstrap.py
COPY --from=webapp-build /opt/hermes/hermes_cli/ /opt/hermes/hermes_cli/
COPY --from=webapp-build /opt/hermes/docker/entrypoint-dispatch.sh /opt/hermes/docker/entrypoint-dispatch.sh
COPY --from=webapp-build /opt/hermes/agent/ /opt/hermes/agent/
COPY --from=webapp-build /opt/hermes/gateway/ /opt/hermes/gateway/
COPY --from=webapp-build /opt/hermes/persistence/ /opt/hermes/persistence/
COPY --from=webapp-build /opt/hermes/plugins/computer_use/ /opt/hermes/plugins/computer_use/
COPY --from=webapp-build /opt/hermes/tools/ /opt/hermes/tools/
COPY --from=webapp-build /opt/hermes/tui_gateway/ /opt/hermes/tui_gateway/
COPY --from=webapp-build /opt/hermes/model_tools.py /opt/hermes/run_agent.py /opt/hermes/toolsets.py /opt/hermes/
COPY --from=webapp-build /opt/hermes/apps/desktop/dist-webapp/ /opt/hermes/apps/desktop/dist-webapp/
COPY components/hermes/managed_policy.py /opt/hermes/docker/private-managed-policy.py
COPY components/hermes/external_content.py /opt/hermes/hermes_cli/private_external_content.py
COPY components/hermes/public_images.py /opt/hermes/hermes_cli/private_public_images.py
COPY components/hermes/browser_policy.py /opt/hermes/hermes_cli/private_browser_policy.py
# Keep the user-writable profile wrapper directory last so root s6, cont-init
# and wrapper command lookup cannot execute profile content. Unique profile
# wrapper names still resolve for the unprivileged application.
ENV PATH=/opt/hermes/bin:/opt/hermes/.venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/opt/data/.local/bin
ENV HERMES_WEBAPP_DIST=/opt/hermes/apps/desktop/dist-webapp
