# Official v0.23.2, source ae2a81ccc00e9b7c06301523e5bb09608397149c.
FROM nousresearch/hermes-agent@sha256:d6746a084e9341baada483e3d6210444d3c1aeb7c130f0915150065fb2851459 AS upstream

FROM upstream AS webapp-build
COPY components/hermes/verify-build.mjs /tmp/verify-build.mjs
RUN node /tmp/verify-build.mjs
# Upstream's runtime omits pnpm. Use its own hash-verified PM pin, only in
# this disposable frontend stage, matching the upstream frontend build.
RUN python3 -c 'from pathlib import Path; from pm import ensure, installed_package; ensure("pnpm", explicit=True); Path("/usr/local/bin/pnpm").symlink_to(installed_package("pnpm").binary)'
RUN node apps/desktop/scripts/build-webapp.mjs --deps-only
COPY components/hermes/ui/private-content.tsx /opt/hermes/apps/desktop/src/components/ui/private-content.tsx
COPY components/hermes/patches/ /tmp/private-hermes-patches/
RUN git apply --check /tmp/private-hermes-patches/*.patch && \
    git apply /tmp/private-hermes-patches/*.patch
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
COPY --from=webapp-build /opt/hermes/tools/approval.py /opt/hermes/tools/approval.py
COPY --from=webapp-build /opt/hermes/tools/registry.py /opt/hermes/tools/registry.py
COPY --from=webapp-build /opt/hermes/tools/browser_use_cli.py /opt/hermes/tools/browser_use_cli.py
COPY --from=webapp-build /opt/hermes/tools/browser_url_policy.py /opt/hermes/tools/browser_url_policy.py
COPY --from=webapp-build /opt/hermes/tools/browser_session_real_profile.py /opt/hermes/tools/browser_session_real_profile.py
COPY --from=webapp-build /opt/hermes/tools/browser_session.py /opt/hermes/tools/browser_session.py
COPY --from=webapp-build /opt/hermes/tools/browser_session_lifecycle.py /opt/hermes/tools/browser_session_lifecycle.py
COPY --from=webapp-build /opt/hermes/tools/browser_session_sandbox.py /opt/hermes/tools/browser_session_sandbox.py
COPY --from=webapp-build /opt/hermes/tools/browser_supervisor.py /opt/hermes/tools/browser_supervisor.py
COPY --from=webapp-build /opt/hermes/tools/environments/ssh.py /opt/hermes/tools/environments/ssh.py
COPY --from=webapp-build /opt/hermes/agent/background_review.py /opt/hermes/agent/background_review.py
COPY --from=webapp-build /opt/hermes/agent/inline_tool_executors.py /opt/hermes/agent/inline_tool_executors.py
COPY --from=webapp-build /opt/hermes/agent/context_references.py /opt/hermes/agent/context_references.py
COPY --from=webapp-build /opt/hermes/tools/bot_desktop/ /opt/hermes/tools/bot_desktop/
COPY --from=webapp-build /opt/hermes/tools/computer_use/ /opt/hermes/tools/computer_use/
COPY --from=webapp-build /opt/hermes/tui_gateway/methods_browser.py /opt/hermes/tui_gateway/methods_browser.py
COPY --from=webapp-build /opt/hermes/tui_gateway/methods_display.py /opt/hermes/tui_gateway/methods_display.py
COPY --from=webapp-build /opt/hermes/apps/desktop/dist-webapp/ /opt/hermes/apps/desktop/dist-webapp/
COPY components/hermes/code_terminal.py /opt/hermes/hermes_cli/private_code_terminal.py
COPY components/hermes/external_content.py /opt/hermes/hermes_cli/private_external_content.py
COPY components/hermes/public_images.py /opt/hermes/hermes_cli/private_public_images.py
COPY components/hermes/browser_policy.py /opt/hermes/hermes_cli/private_browser_policy.py
COPY components/hermes/computer_use.py /opt/hermes/hermes_cli/private_computer_use.py
COPY components/hermes/browser_use.py /opt/hermes/hermes_cli/private_browser_use.py
# Keep the user-writable profile wrapper directory last so root s6, cont-init
# and wrapper command lookup cannot execute profile content. Unique profile
# wrapper names still resolve for the unprivileged application.
ENV PATH=/opt/hermes/bin:/opt/hermes/.venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/opt/data/.local/bin
ENV HERMES_WEBAPP_DIST=/opt/hermes/apps/desktop/dist-webapp
