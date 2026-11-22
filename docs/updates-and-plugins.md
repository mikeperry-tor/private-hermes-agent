# Updates, plugins, and privacy defaults

Private Hermes pins Hermes, Tor, HAProxy, and Tailscale by container image
digest, and pins Teep and `x402_treazury` by Git commit. Operator settings in
`.env` do not choose component versions. User plugins use Hermes's own plugin
manager and persist inside `hermes-data`.

## Check stack versions

With the stack running:

```sh
make check-updates
python3 scripts/check-updates.py --json
```

The checker runs as UID 10000 inside Hermes's Tor-routed namespace and makes
anonymous `GET` requests to Docker Hub and GitHub without using provider keys or
stored registry credentials (public pull tokens stay in memory). For each
pinned component, it reports:

- **`matches`:** The published manifest or commit matches the repository pin
  (including a pinned platform manifest inside a multi-platform index).
- **`different`:** The upstream image channel or default source branch differs
  from the pin. This signals a change to review, not proof of a newer or
  compatible release.
- **`error`:** Metadata could not be fetched (for example, anonymous rate
  limiting). The command exits nonzero rather than reporting the pin as current.

Hermes and Tor track `latest`, the desktop executor tracks `desktop` (following
`hermes-sandbox`), Tailscale tracks `stable`, and HAProxy tracks its pinned
release channel. Unpinned build-base tags are listed separately. The checker
modifies no pins, installs no packages, and pulls no image layers.

## Apply stack updates

Review repository pin updates and upstream release notes, back up your state
(see [backup scope](configuration.md#backup-scope)), and run:

```sh
make build
make down
make up
```

- **Pre-upgrade step from v0.23.1:** If upgrading from the v0.23.1 wrapper with
  Bot Desktop running, stop Bot Desktop from each profile's WebApp screen pane
  before shutting down so the old image clears its desktop owner record. If an
  upgrade already left a desktop stuck, temporarily revert to the v0.23.1
  wrapper with the same saved state, stop the desktop there, and retry the
  upgrade while keeping `data/executor/home/` and `hermes-data`.
- **Automatic builds:** `make up` runs cached builds for enabled services and
  `x402_treazury` before setup or container changes; `make x402_treazury-prepare`
  also runs a cached treasury build first. Running `make build` ahead of
  `make down` builds all images (including optional Funnel) while the stack
  stays up. Build failures abort before runtime state changes. Builds may need
  host Internet access and never search for newer commits or force base pulls.
- **State preservation:** `make down` waits for graceful treasury shutdown and
  preserves named volumes, bind directories, and `config/x402_treazury/research_desk.toml`.
  `make up` reruns offline setup, prints an advisory diff if your saved research
  policy differs from packaged defaults, and reconnects a prepared treasury.
  Invalid treasury policy blocks research activation without discarding
  preparation history.
- **In-place Hermes updates:** The official Hermes image disables in-place core
  updates, so its built-in core version check reports an unsupported install;
  use `make check-updates` instead.

## Manage persistent user plugins

```sh
make plugins
python3 scripts/plugins.py list
python3 scripts/plugins.py install OWNER/REPOSITORY
python3 scripts/plugins.py update PLUGIN_NAME
python3 scripts/plugins.py disable PLUGIN_NAME
```

`scripts/plugins.py` runs the Hermes CLI as UID/GID 10000 inside Hermes's Tor
namespace, keeping interactive dependency and capability consent prompts
intact. For non-interactive installs, pass `--enable --yes-deps` explicitly;
the wrapper never adds consent, scan-bypass, or force flags automatically.

- **Persistence:** Plugin code lives under `/opt/data/plugins`, and enablement,
  provenance, and Python virtual environments live under `/opt/data/installs/`
  inside `hermes-data`. They survive container recreation and `make down`
  without modifying the container image. Plugins that require OS packages or
  external services still need deployment-level changes.
- **Update cadence:** Hermes checks for plugin updates every 24 hours without
  auto-applying them. Apply updates explicitly and follow Hermes's reload or
  restart instructions.
- **Bundled vs. user plugins:** Bundled plugins ship inside the pinned Hermes
  image, with standalone add-ons disabled by default (`plugins.enabled: []`). A
  user plugin with the same name can override a bundled plugin, so keep
  overrides deliberate rather than shadowing bundled code unintentionally.
- **Authority:** Plugins run inside Hermes with full agent privileges—outside
  the SSH executor sandbox, though without access to the `x402_treazury` wallet
  volume.

`make plugins-test` tests installing, updating, and reloading a wheel-backed
plugin across container recreation in a temporary Compose project with no
inference or paid calls.

## Privacy defaults

- **Telemetry off:** Hermes shared-metrics collection is disabled with the
  consent prompt marked declined. OTLP diagnostics export, computer-use
  telemetry, and browser telemetry environment flags are disabled in Hermes and
  the executor. Update checks and plugin notifications stay enabled
  independently.
- **Font and style CSP:** HAProxy adds a `Content-Security-Policy` restricting
  fonts and styles to local resources and inline styles, which browsers
  intersect with Hermes's own CSP. This blocks Google Fonts on local, Funnel,
  and onion ingress while preserving bundled and system font fallbacks, model
  catalogs, and agent-side Tor requests.
- **Scope:** Because profile files are writable, these are explicit defaults
  rather than immutable controls against arbitrary agent or plugin code.

## Derived Hermes build and patch maintenance

The derived Hermes image (`private-hermes-agent:local`) builds from official
Hermes v0.23.3 (source commit `caafe5389ae585ef77387a962aee05b1bcf17029`). In a
separate frontend build stage, `components/hermes/verify-build.mjs` verifies
the base image's install stamp, source hash, and renderer receipt before
applying the ordered patch series under `components/hermes/patches/`.

That build stage installs a hash-verified `pnpm` pin for the frozen-lockfile
frontend build, clears stale renderer chunks, and copies patched Python files
plus the rebuilt WebApp (`HERMES_WEBAPP_DIST`) into the final runtime image.
The runtime image omits `pnpm`; its advisory warning about missing `pnpm` does
not affect Python plugin setup.

`0001-upstream-candidates.patch` is exported from the release replay recorded
in [v0.23.3 build provenance](plans/hermes-upstream-prep.md#v0233-build-provenance),
excluding upstream Python tests, website files, contributor metadata, and
Electron-only files. The Docker build uses only the tracked patches and pinned
official image, never local reference checkouts. See
[Hermes update workflow](update-workflow.md) and
[rebuilding the candidate patch](update-workflow.md#rebuild-the-candidate-patch-for-a-new-release)
for upgrade steps.

### Downstream responsibility inventory

| Patch | Responsibility | Checks and removal condition |
| --- | --- | --- |
| `0001-upstream-candidates` | Strict managed config reader and reload precedence, SSH trust and file error handling, executor desktop/browser transport, Code/Agent terminals, configurable URL context, and managed tool denial (PR1–PR6). | Drop adopted portions once the official Hermes release includes them and packaged tests pass. |
| `0002-managed-policy` | Generates root-owned `/etc/hermes/config.yaml` and `/etc/hermes/.env` at container startup before Hermes loads profiles. | Verify effective settings under conflicting profile input, reloads, and offline jobs. |
| `0003-desktop-and-terminal-policy` | Enforces explicit desktop enablement and recovery diagnostics, local Code/Agent terminal labels and startup acknowledgement, and safe absolute Code `cwd` handling. | Keep until upstream deployment controls satisfy the desktop and terminal checks. |
| `0004-deployment-policy` | Captures `WEBAPP_EXTERNAL_CONTENT` and `COMPUTER_USE_ENABLED` before profile dotenv loading and validates WebApp content policy. | Keep until upstream deployment config preserves the same authority. |
| `0008-private-image-routes` | Authenticated Tor image proxy and origin-consent APIs with bounded public IPv4 raster retrieval. | Verify with image endpoint, CDN consumer, and outage checks. |
| `0009-browser-response-policy` | Response CSP, trusted bootstrap headers, exact-origin WebSockets, and inert private previews. | Verify with browser response, WebSocket, and active-file checks. |
| `0010-browser-content` | Shared content rendering, image consent UI, and image Save/Copy through the Tor proxy. | Verify with renderer unit tests and cross-browser tests across all four content modes. |
| `0011-mcp-probe-redirects` | Leaves HTTP redirects to the MCP SDK and treats redirected `initialize` responses in Hermes's separate diagnostic probe as inconclusive. | Verify `HEAD`, `GET`, and `initialize` redirects in `tests/local_integration_smoke.py`; remove once upstream's diagnostic respects the SDK's redirect boundary. |

### Managed container config and executor packaging

At startup, the Hermes entrypoint writes `/etc/hermes/config.yaml` and
`/etc/hermes/.env` to pin:

- The SSH file backend, endpoint, and OpenSSH client config, plus executor-only
  desktop, Chromium sandbox, operator terminal mode, `context_references.fetch_urls: false`,
  and the `tools.disabled` list.
- Cleared `HTTP_PROXY`, `HTTPS_PROXY`, and `ALL_PROXY` values (applied on top
  of Compose defaults and reapplied across profile reloads) so the namespace
  firewall and `tor` gateway remain the single enforcement point for local
  grants and Tor routing.
- Derived `tools.disabled` entries:

| Deployment setting | Disabled tools |
| --- | --- |
| Every deployment | `browser_cdp`, `browser_dialog`, `browser_vault`, `read_window_below` |
| `COMPUTER_USE_ENABLED=false` | Add `computer_use`, `browser_exec` |
| `WEBAPP_EXTERNAL_CONTENT` is `tor_proxied`, `ask`, or `off` | Add `desktop_preview`, `drive_preview`, `annotate_preview` |

The desktop executor pairs the pinned `hermes-sandbox` image with OpenSSH and a
hash-locked browser harness under `/opt/browser-harness` (following Hermes's
Python lockfile plus the Pillow 13 `--no-deps` override). Hermes sends the
runner and screenshot helper over SSH, keeps the live browser profile excluded
from SSH sync archives, and provides an empty agent-side `/workspace` directory
(separate from the executor's `/workspace`) for session `cwd` validation.

Run `make hermes-ui-test` to execute TypeScript type-checking and focused
renderer tests in the build stage (using `tests/fixtures/session-resume-active-turn.json`,
which the official runtime omits). Run the
[packaged Hermes checks](development.md#packaged-hermes-qualification) on both
engines after modifying patches or base pins.

### Local preparation package dispositions

Upstream submission drafts for PR1–PR6 live under `upstream_work/submissions/`
and use `upstream-pr/*` branches in `upstream_work/hermes-agent/`, pushed to
the `fork` remote ([mikeperry-tor/hermes-agent](https://github.com/mikeperry-tor/hermes-agent))
alongside the `stack-patches/v0.23.3/*` release refs. Submissions target
`NousResearch/hermes-agent` (`origin`) under author identity
`Mike Perry <mikeperry-git@untrusted.systems>`. Follow the branch heads and
merge order in the
[submission plan](plans/hermes-upstream-prep.md#1-branches-to-submit) and
[merge-order checklist](plans/hermes-upstream-prep.md#2-upstream-submission-and-merge-order-checklist).

| Package | Scope in Private Hermes |
| --- | --- |
| PR1 | Strict managed config reads, dotenv bootstrap and reload precedence, and profile-specific interpolation. |
| PR2 | Browser-profile SSH sync exclusion, missing-path `ENOENT`/404 classification, and pinned SSH client options (required by PR3). |
| PR3 | Executor-only desktop/browser placement, SSH transport, and Chromium sandboxing. |
| PR4 | Native executor/gateway terminal selection backing the stack's Code and Agent modes (builds on PR1). |
| PR5 | Managed `context_references.fetch_urls: false` for normal and config-bypass turns (builds on PR1). |
| PR6 | Managed `tools.disabled` enforcement across discovery, prompt guidance, background review, CLI banners, and connectors without dropping registered MCP servers (builds on PR1). |
| PR7 | Deferred design only. Private Hermes retains its downstream content, raster-proxy, and consent patches (`0008`–`0010`). |

PR7 is not submission-ready: it still needs decisions on shared Ask/Always
renderer ownership and authenticated consent storage/API while preserving
upstream's CDN consumer and IPv6 support (private audio/video streaming and
interactive frames stay out of scope).

Related upstream issues and PRs tracked for conflict checks include `#156336`,
`#130878`, `#130946` (renderer/consent), `#130023` (provenance), `#156728`
(managed-policy readers), `#95247` (profile tool approvals), `#156598` (browser
module move), `#156368` (Chromium cleanup), `#128539` (CDN consumer), and
`#102667` (large gateway-local rasters). Recheck their status on GitHub before
submitting or adopting changes.

Remove a downstream patch only after a pinned official Hermes release ships the
equivalent behavior and both Docker and rootless Podman qualification passes.
Keep deployment choices, network grants, state preservation, and unsupported
tool exclusions intact; an upstream merge alone does not qualify a stack update.
See [local upstream candidate qualification](development.md#local-upstream-candidate-qualification)
for candidate-level test coverage.
