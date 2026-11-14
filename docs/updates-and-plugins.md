# Updates, plugins, and privacy defaults

The stack manages Hermes, Tor, HAProxy and Tailscale through image digest pins,
and teep/x402_treazury through source commits. Operator preferences in `.env`
do not select image versions. User plugins use Hermes's native management and
persistent profile storage.

## Check stack versions

With the stack running:

```sh
make check-updates
python3 scripts/check-updates.py --json
```

Requests run as UID 10000 inside Hermes's existing Tor-routed namespace. They
fetch public Docker Hub manifests and GitHub commit metadata with anonymous,
GET-only requests. Provider keys and stored Docker registry credentials are not
used; public registry pull tokens stay anonymous and in memory.
The checker reads the repository pins and reports:

- `matches`: the advertised artifact matches the pin, including a pinned
  platform manifest present in an advertised multi-platform index.
- `different`: the configured image channel or default source branch differs.
  This is a review signal, not proof of a newer or compatible release.
- `error`: metadata could not be checked, including anonymous rate limits.
  The command exits nonzero and does not report the component as current.

Hermes/Tor use their `latest` image channels, the optional executor desktop uses
its `desktop` channel, Tailscale uses `stable`, and
HAProxy stays on the pinned reference's version channel. Unpinned build-base
tags are listed separately: there is no recorded digest to compare for those.
The command changes no pins, installs no packages, and pulls no image layers.
Checks are operator-invoked; plugin notifications have their own cadence below.

## Apply stack updates

Review updated wrapper repository pins and upstream release information, then:

```sh
make build
make down
make up
```

`make up` automatically runs cached builds for the selected deployment and treasury
before setup or service changes. `make x402_treazury-prepare` also runs a cached
treasury build before inspecting completion or changing research services. Changed
Dockerfiles, source pins and copied inputs rebuild their affected layers; unchanged
layers reuse the selected engine's cache. Build failure stops the operation before
those runtime changes. Builds may need Internet access; these commands do not search for newer
upstream commits or force base-image pulls. Status, backup and shutdown remain
independent of builds.

The explicit `make build` above builds all images, including optional Funnel, ahead
of shutdown and keeps the existing deployment available during the build. Image
construction does not run initialization or deployment-policy checks, so it remains
available when operator configuration needs repair. `make up` validates and applies
actual operator settings; use `make check` explicitly for development qualification.
`make down` waits for graceful financial shutdown and preserves named volumes
and bind data. `make up` reapplies offline setup and verifies research readiness.
Back up configuration, bind data, and the Hermes/treasury named volumes before
applying changes; see [backup scope](configuration.md#backup-scope).

The official Hermes image refuses in-place core updates. Its native passive
core version check currently reports an image-managed install as unsupported;
the stack checker supplies the useful version comparison. Treasury preparation
completion survives source/build updates. Startup checks the current deployment
policy and treasury identity; an invalid policy blocks research activation without
discarding completion or requiring another funding/warming run. Missing or
incomplete preparation still requires explicit `make x402_treazury-prepare`;
review native funding policy before that operation. The editable research TOML
is preserved across image builds; compare packaged defaults and apply desired
policy changes explicitly. Ordinary policy edits retain initial preparation
eligibility; see [research configuration](x402_treazury.md#edit-the-research-configuration).

## Manage persistent user plugins

```sh
make plugins
python3 scripts/plugins.py list
python3 scripts/plugins.py install OWNER/REPOSITORY
python3 scripts/plugins.py update PLUGIN_NAME
python3 scripts/plugins.py disable PLUGIN_NAME
```

The wrapper executes the native Hermes CLI as UID/GID 10000 in the running
agent's Tor namespace. Interactive terminals retain native dependency and
capability consent prompts. For deliberate non-interactive dependency consent,
the native installer accepts `--enable --yes-deps`; the wrapper does not add
consent, scan bypasses, or force flags automatically.

Plugin code is stored under `/opt/data/plugins`. Enablement, install provenance,
and prepared dependency environments under `/opt/data/installs/` share the
existing `hermes-data` volume. They survive container recreation and ordinary
`make down`. Native plugin installation prepares Python environments in profile
storage, rather than requiring edits to the image's Python environment. Some
plugins also require system binaries or external services; those requirements
still need component-specific deployment work.

Plugin update checks run every 24 hours; automatic application is disabled.
Catalog updates follow native reviewed pins and consent checks; custom Git
sources use their native update rules. Apply updates explicitly and follow the
native interface's reload/restart guidance.

Bundled plugins remain part of the pinned Hermes image. Optional standalone
add-ons start disabled (`plugins.enabled: []`); backend/platform registrations
are selected through their normal configuration. A matching user plugin can
override a bundled plugin where its native discovery rules support that
override. Keep overrides intentional instead of covering the entire bundled
directory with persistent old code. Plugins execute with agent privileges;
they are outside the SSH executor sandbox and have no treasury wallet mount.

`make plugins-test` uses a disposable project to install and update a harmless
plugin with a locally generated wheel dependency, then checks loading after
container recreation. It uses no inference or paid research calls.

## Privacy defaults

Shared-metrics collection and uploads are explicitly disabled, with the current
consent offer recorded as declined. OTLP diagnostics export and computer-use
telemetry are off. Browser telemetry environment overrides are applied to the
agent and executor. Native update checks and plugin notifications remain enabled
independently of those settings.

HAProxy adds a CSP restricting fonts/styles to local resources and inline styles;
browsers intersect it with Hermes's own CSP. Google Fonts requests are blocked
for both local and Funnel ingress, and bundled/system font fallbacks remain
available. This does not block functional model catalogs, tool downloads, or
content the operator deliberately accesses. Those agent-side requests retain
the existing Tor route. Profile settings are writable; these are explicit
defaults, not immutable enforcement against arbitrary plugin or agent code.

## Derived Hermes build and patch maintenance

For the review sequence and lessons from prior upgrades, see
[Hermes update workflow](update-workflow.md).

`components/hermes/Dockerfile` derives from the pinned official v0.23.1 image,
source `3b421578588243f920886e6fe79a6faa87ea026e`. A disposable build stage checks
the clean install stamp and the packaged Webapp source hash against its reviewed
native build receipt before applying explicit patches with `git apply --check`.
The image supplies the source and pinned Node. The disposable build stage uses
upstream PM to install its hash-verified pnpm 12.15.0 pin, then the native build
recipe installs frozen-lockfile dependencies and compiles the browser-hosted
Desktop. pnpm and frontend build dependencies do not enter the final image. It
retains upstream dispatch, bootstrap and UID handling and explicitly selects the
rebuilt `apps/desktop/dist-webapp` through `HERMES_WEBAPP_DIST`. It does not replace
the separate legacy dashboard assets in `hermes_cli/web_dist` or install build
dependencies at startup. Runtime, offline setup and qualification fixtures use the
same derived image. Build contexts still contain only tracked components.

Native plugin commands can report an advisory `pnpm: not installed or outdated`
from their passive runtime check. The official v0.23.1 runtime intentionally
omits this frontend build tool; the warning does not block Python plugin
environment preparation. Dependency download failures still fail the requested
operation visibly and require a successful retry.

`make check-updates` reads the official base pin from this Dockerfile. An upstream
change requires reviewing source and runtime contracts, refreshing explicit
patches and the source/hash checks, then rebuilding and rerunning affected build,
plugin, browser and network qualification. Never bypass a failed patch/hash check
or substitute a reference checkout revision. Remove a patch when the selected
upstream revision provides and qualifies its behavior; do not patch compiled
bundles or runtime startup. The first policy patch validates the deployment mode
at HTTP server assembly and captures it in the stdlib-only native bootstrap before
profile dotenv loads. The final image also copies that patched bootstrap. Its
removal requires equivalent upstream deployment
policy validation, not merely a UI preference.

The private-content patches also remove the CDN-first proxy, mount the narrow
public-raster/consent APIs, integrate shared renderer consumers, and cover main,
preview/plugin and active-file responses. Private preview shells display source
text; they never parse arbitrary HTML or run its scripts. Preserve main bootstrap
hashes and exact-origin WebSockets when updating these patches. Remove patches
only after equivalent upstream behavior passes the same backend/browser/network
qualification, including dependency loss and stale permissions. No runtime bundle
editing, fallback provider or compatibility reader is installed.

The disabled-desktop-tools patch omits the three unsupported executor browser
tools listed in the [webapp guide](webapp.md#local-content-previews-and-links),
along with the unsupported native-client `read_window_below` tool. The early
bootstrap captures `COMPUTER_USE_ENABLED` before profile dotenv loading;
`computer_use` and `browser_exec` are omitted when false and check actual remote
dependencies when true. The SSH-computer-use patch enforces executor-only placement, rejects local
CLI/embedded-daemon fallbacks and host installation, and preserves Chromium's
sandbox at the desktop dock launch. Standard driver permissions are supported;
other modes fail before a local daemon can be constructed. Native mutation
outcome-unknown/no-replay behavior remains intact.
The three separate in-browser preview tools instead follow the early captured
`WEBAPP_EXTERNAL_CONTENT` mode: available in `browser_native`, unavailable in all
private modes. Both policies apply to native registration, inline callback
dispatch and stale registry calls, without rewriting operator settings.
The final image copies the patched registry, inline-dispatch, desktop/driver,
display RPC and display WebSocket files from the build stage. Revisit remaining
executor exclusions only after each execution path is independently qualified;
an upstream browser dependency or desktop
image alone is not grounds to restore those tools. Remove the patch when an
equivalent native deployment-owned mechanism is selected and qualified.
After building Hermes, run `python3 tests/desktop_tools_smoke.py` to check
discovery, stale calls, native-mode preview callbacks and supported-tool
preservation in disposable networkless containers. This is not containment
against trusted plugins executing Python.

The URL-context patch filters URL references before native context expansion
and reference-count limits. It preserves message/chip text and all other native
reference handling, but does not fetch pages or add URL-extraction warnings.
The final image copies the patched `agent/context_references.py`; qualify it
after building with `python3 tests/context_refs_smoke.py`. Remove the patch if
upstream supplies an equivalent selected no-fetch policy, with URL-chip and
non-URL expansion behavior qualified against the packaged revision.

The optional desktop executor derives from the separately pinned
`nousresearch/hermes-sandbox:desktop` layers and adds OpenSSH and runner setup,
removing the candidate's passwordless sudo grant. Its tmpfs directory setup runs
at startup without adding CHOWN or other capabilities. It contains no Hermes
runtime to patch. The lean target retains Alpine; the root `.env` preference
selects the build and native Compose security fragment, not image versions.
The desktop-only syscall profile's source/license, maintenance and removal
conditions are in [development](development.md#executor-desktop-qualification).
The SSH-browser-use patch delegates execution, availability and schema generation
to the deployment helper before native gateway-local harness code can run. It
also restricts local session creation to executor Chromium, preserves Chromium's
sandbox in the automation launch path, and connects native session cleanup to the
SSH-owned harness. The final Hermes image copies all four patched browser modules
and the patched SSH environment module. Native SSH sync-back excludes exactly the
executor's `~/.hermes/bot-desktop/browser-profile` from its bulk archive: this
unmapped persistent browser state contains Chromium's absolute socket symlinks,
which otherwise fail native safe tar extraction and block intended cache/skill
sync-back. Other native mappings and safe extraction remain unchanged; the
profile stays in executor bind data and backups. Remove this exclusion when
native SSH archives only the required mapped state or handles this runtime
profile without breaking safe extraction and selected-file synchronization.
The desktop executor copies only the public screenshot helper and its MIT license
from the same official image and builds `/opt/browser-harness` from the minimal locked dependency
closure in `browser-requirements.txt`. Hashes and versions come from the packaged
Hermes lock, including its explicit Pillow 13 override; `--no-deps` preserves that
override instead of resolving the harness's older Pillow pin. Refresh both image
source pins and this closure together when updating Hermes. No full Hermes runtime
or profile is installed in the executor. Remove this patch/helper/launcher when
equivalent native SSH execution, ownership, screenshots and failure behavior pass
the browser qualification checks. Keep other browser tools excluded until their
own routes are qualified.
Remove the SSH patch when equivalent upstream executor-only behavior passes
these discovery, failure/restart, driver and authenticated-display checks. The
gateway still needs this project's derived Hermes image and rebuilt web assets;
switching to an unmodified official agent image would lose the deployment
policies. Engine build caching reuses unchanged upstream layers and dependencies even
when changing Python patches causes the shared webapp build stage to rerun.

The derived image also creates an empty agent-side `/workspace` for native
session-cwd validation; this is separate from the executor mount. Qualify actual
browser chat, rather than relying on login/terminal checks alone.

Follow the [webapp qualification evidence and current limits](webapp.md#qualification).

Run `make hermes-ui-test` for the patched renderer's full TypeScript check and
focused native media/preview tests. It uses the disposable build stage, without
runtime dependency installation or private mounts. The small upstream session
fixture omitted from the official runtime image is copied verbatim under
`tests/fixtures/` from the pinned source; refresh it when changing that source.
The compiler needs a larger heap than Node's observed 2 GiB default on this target;
that setting applies only to the qualification compiler, not runtime containers.
`make webapp-test` rebuilds Hermes and the proxy before fixture startup, and
`make images-test` rebuilds Hermes, preventing stale local tags from bypassing
changed startup or fetch behavior.

The code-terminal patch and `private_code_terminal` helper target the same pinned
v0.23.1 source. They select ordinary host-terminal preparation using early-captured
deployment inputs, preserving native saved gateways and the authenticated PTY
lifecycle. The helper owns remote cwd validation and shell/SSH argument construction;
the browser bootstrap carries the mode for labeling, stale-page refusal and local
tab restoration. No compiled bundles are edited. Remove them when the selected
upstream provides equivalent executor terminals with this connection policy,
authentication, cwd handling and lifecycle, qualified on both supported engines.
See [terminal qualification](development.md#code-terminal-qualification).
