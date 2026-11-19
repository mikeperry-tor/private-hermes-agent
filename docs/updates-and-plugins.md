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
The desktop check follows the `hermes-sandbox` image stage even when the executor
also copies helpers from a pinned Hermes stage.
The command changes no pins, installs no packages, and pulls no image layers.
Checks are operator-invoked; plugin notifications have their own cadence below.

## Apply stack updates

When upgrading this wrapper from v0.23.1, stop Bot Desktop from each profile's
WebApp screen pane while the old deployment still shows it running. The old
image can clear its desktop owner record. If an upgrade already left a desktop that
cannot start or stop, return to the v0.23.1 wrapper and deployment settings
with compatible saved state, stop the affected screens there, then retry the
upgrade. Keep the executor home and Hermes volume so browser data and profile
state survive. See [backup scope](configuration.md#backup-scope).

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

For integration review and qualification requirements, see
[Hermes update workflow](update-workflow.md).

`components/hermes/Dockerfile` derives from the pinned official v0.23.2 image,
source `ae2a81ccc00e9b7c06301523e5bb09608397149c`. A disposable build stage checks
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
same derived image. The final stage removes inherited Webapp output before
copying the rebuilt directory, so obsolete upstream chunks cannot remain in the
served artifact. `tests/hermes_build.py` verifies the final output with the native
build receipt. Build contexts still contain only tracked components.

Native plugin commands can report an advisory `pnpm: not installed or outdated`
from their passive runtime check. The official v0.23.2 runtime intentionally
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
The final image copies the patched registry, inline-dispatch, approval, background-review, desktop/driver,
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
removing the base image's passwordless sudo grant. Its tmpfs directory setup runs
at startup without adding CHOWN or other capabilities. It contains no Hermes
runtime to patch. The lean target retains Alpine; the root `.env` preference
selects the build and native Compose security fragment, not image versions.
The desktop-only syscall profile's source/license, maintenance and removal
conditions are in [development](development.md#executor-desktop-qualification).
The SSH-browser-use patch delegates execution, availability and schema generation
to the deployment helper before native gateway-local harness code can run. It
also restricts local session creation to executor Chromium, preserves Chromium's
sandbox in the automation launch path, and connects native session cleanup to the
SSH-owned harness. The final Hermes image copies the patched browser modules and gateway handlers
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
v0.23.2 source. They select ordinary host-terminal preparation using early-captured
deployment inputs, preserving native saved gateways and the authenticated PTY
lifecycle. The helper owns remote cwd validation and shell/SSH argument construction;
the browser bootstrap carries the mode for labeling, stale-page refusal and local
tab restoration. No compiled bundles are edited. Remove them when the selected
upstream provides equivalent executor terminals with this connection policy,
authentication, cwd handling and lifecycle, qualified on both supported engines.
See [terminal qualification](development.md#code-terminal-qualification).


### Downstream responsibility inventory

The packaged build has thirteen ordered patches. The complete series defines the
runnable deployment; individual intermediate patches need not establish every
boundary. Keep purpose, consumers, helper delivery and removal conditions together.

| Patch | Current responsibility / owning consumers | Checks and removal condition |
| --- | --- | --- |
| 0001 desktop dependency probe | Failed/unavailable inspection is distinct from missing commands; startup/status/UI/RPC diagnostics | Native probe/rendering controls and `computer-use-test`; remove when the packaged upstream handles every caller equivalently |
| 0002 SSH sync browser profile | Native bulk archive excludes only the unmapped live browser profile; safe extraction/mappings remain native | Browser sync fixture; remove for equivalent mapped-state archiving or safe live-profile handling |
| 0003 no URL context expansion | Filter URL refs before expansion/count limits; preserve text/chips and other reference kinds | `context_refs_smoke.py`; adopt managed `context_references.fetch_urls: false` after verifying normal and config-bypass entrypoints in the packaged stack |
| 0004 deployment policy | Capture mode/enablement before dotenv; validate server selections; `external_content.py` owns content modes and grants | Native image/policy checks; replace only with an immutable deployment ceiling that preserves writable profiles |
| 0005 disabled desktop tools | Discovery, registry/stale dispatch and inline restrictions across CLI/gateway/RPC/children | `desktop_tools_smoke.py`; remove for equivalent native shared discovery/execution enforcement |
| 0006 SSH computer use | Executor-only placement, dependency status, driver permission/transport, sandboxed dock and display RPC/socket; `computer_use.py` | `computer-use-test`; adopted generic mechanics must retain deployment SSH selection, image policy and no local fallback |
| 0007 SSH browser use | Remote harness/schema/session cleanup, strict named-tab setup and sandboxed launch; `browser_use.py` and executor `browser-session.py` | `browser-use-test`; remove equivalent mechanics only after remote execution, exact transport/session ownership, inherited-pipe cleanup, fencing, cancellation and no replay are qualified |
| 0008 private image routes | Authenticated content/consent APIs in `external_content.py`; bounded public IPv4 raster retrieval in `public_images.py` | `images-test`; equivalent native consumers must retain checked connections, TLS/credential isolation, redirects, limits and consent |
| 0009 browser response policy | `browser_policy.py` owns CSP, trusted bootstrap headers and inert private previews | Browser/endpoint tests; equivalent response, origin/socket and active-file handling required |
| 0010 browser content | Shared rendering/consent, external resource consumers and image Save/Copy through `ui/private-content.tsx` | Native UI and browser matrix; all consumers must honor private modes and automatic `tor_proxied` retrieval |
| 0011 code terminal | Launch mode, async native PTY preparation, truthful metadata, stale mode and cwd persistence; `code_terminal.py` | Adopt native terminal placement with strict provisioning, fixed SSH identity and `/workspace` as the code default. Check exact paths, saved gateways, auth and lifecycle on both engines |
| 0012 SSH file inspection | Native missing-path classification before canonicalization; directory/symlink/sensitive-path guards retained | Real-shell build and browser controls; remove for equivalent native ENOENT/404 behavior |
| 0013 SSH pinned host key | Model SSH and SCP explicitly select the existing pinned OpenSSH configuration and require a known matching key | Check valid, missing and changed host keys with fresh authentication. Remove when native `terminal.ssh_config` preserves the same behavior for shell, streams, workspace and sync |

Dependencies: 0004 precedes policy consumers 0005–0011; 0006 supplies executor
placement used by 0007; 0008 routes and 0009 response policy support 0010 rendering.
0011 captures terminal selection at the existing bootstrap attachment point.
0001–0003 do not depend on the deployment-specific patches. Filename glob order
is the Dockerfile's actual `git apply --check` / `git apply` order; no resolver exists.

The Dockerfile delivers patched bootstrap, the owning `hermes_cli` tree, registry,
inline dispatch, approval, background review, context refs,
desktop/display/browser/SSH modules, six Python helpers and rebuilt dist-webapp. Setup and runtime use the same image. Executor
images deliver OpenSSH, the hash-locked harness closure, screenshot helper and
upstream MIT license. Preserve the deliberate Pillow 13 override and `--no-deps`
installation. The native session-resume JSON fixture and TypeScript compiler heap
setting are qualification-only. Reference checkouts are not build inputs.

Native ARM64 Chromium discovery, per-hop CDN redirect host checks and no-follow
named-tab marker publication are supplied upstream; do not reintroduce redundant
hunks. The hosted sandbox allowlist excludes required MCP/browser/memory/delegation
features and cannot replace this deployment ceiling. Preserve native placement,
session ownership and PTY lifecycle rather than adding parallel policy/state.
The stack's private raster/consent contract and fixed SSH selection remain distinct
from generic upstream defaults.

### Local preparation package dispositions

The preparation clone is `upstream_work/hermes-agent/`; submission drafts are
`upstream_work/submissions/PR1.md` through `PR5.md`. These ignored local artifacts
are retained for human submission and are not production build inputs. The
[retained preparation plan](plans/hermes-upstream-prep.md) records execution and
review details for PR creation and merge.

`origin` is `https://github.com/nousresearch/hermes-agent`. Human submissions target
`https://github.com/mikeperry-tor/hermes-agent/` by fork URL or an optional fork
remote. Local preparation has no push, PR, issue, merge or maintainer-message
authority. No upstream submission is recorded in these local packages.

| Package / purpose | Local branch | Exact head | Base / prerequisites | Disposition |
| --- | --- | --- | --- | --- |
| PR1: executor desktop/browser correctness | `candidate/executor-desktop-browser` | `53043aeb9d0dc1f90528504e4b88c66bb8bb6398` | `caafe5389ae585ef77387a962aee05b1bcf17029`; shared strict-reader commit `15de33f3a` | Rebased, qualified and independently reviewed locally |
| PR2: operator terminals and exact cwd | `candidate/executor-terminals` | `f7f0b244545b2943a58b8f915c14066463262cec` | `caafe5389ae585ef77387a962aee05b1bcf17029`; shared strict-reader commit `15de33f3a` | Rebased, qualified and independently reviewed locally |
| PR3: selectable URL context | `candidate/url-reference-fetching` | `50ab0a4cfe9dc08f85b62ed5991d10f3bc39cec1` | `caafe5389ae585ef77387a962aee05b1bcf17029`; shared strict-reader commit `15de33f3a` | Rebased, qualified and independently reviewed locally |
| PR4: managed tool denial | `candidate/deployment-restrictions` | `7495b47bc25f8b8ac8cfb8c939ffd6c5eec3fa35` | `caafe5389ae585ef77387a962aee05b1bcf17029`; shared strict-reader commit `15de33f3a` | Rebased, qualified and independently reviewed locally |
| PR5: Webapp content privacy | `candidate/webapp-content-privacy` | `caafe5389ae585ef77387a962aee05b1bcf17029` (base only) | head is its base; no implementation prerequisites yet | Independently reviewed deferred design; not submission-ready |

The four implemented branches contain ten, four, two and four topical
commits, respectively. Each has problem, approach and validation notes and
applies independently on `origin/main` `caafe5389ae585ef77387a962aee05b1bcf17029`.
Recheck the target revision, overlapping PRs and affected qualification before
submission. PR1 and PR4 both touch `tools/browser_use_cli.py`: keep PR1's
executor result helpers and PR4's shared `tool_refusal` gate when combining
them. PR1–PR4 include the same strict managed-reader commit `15de33f3a`; PR2
and PR3 also share the effective reader's validated-snapshot option. PR4's
final prompt-refresh commit also merges upstream's
`_refresh_name_dependent_defs` with the managed `permitted` filter in
`tools/mcp_tool_agent.py`.

Candidate identities use `Mike Perry <mikeperry-git@untrusted.systems>`.
Exact identity/history translations and qualification logs remain in ignored
local evidence. History-only consolidation does not change the qualified trees.

| Package | Production mapping / retained deployment policy |
| --- | --- |
| PR1 | 0001/0002/0006/0007/0012/0013: adopt native probes, sync, permissions, executor Python, sandboxing, file absence and SSH trust. Provision managed executor-only mode and the settings below |
| PR2 | 0011: map `code` to native `executor` and `agent` to `gateway`. Select `webapp.executor_ssh_config` pointing to the existing pinned OpenSSH configuration, and pin the executor's endpoint, identity and `/workspace` cwd through native managed terminal settings |
| PR3 | 0003: set `context_references.fetch_urls: false` in deployment-owned native managed configuration. This reaches safe/config-bypass sessions as well as profile-scoped turns |
| PR4 | Tool selection in 0004/0005: derive native managed `tools.disabled` from the deployment's desktop and content modes. Retain the production matrix for the resulting name set and actual dispatch |
| PR5 | Content capture in 0004 plus 0008/0009/0010 and helpers: keep the qualified automatic Tor raster, consent, Save/Copy and inert-preview implementation pending a native replacement |

For the PR4 cutover, derive `tools.disabled` from the same mode matrix as the
current deployment:

| Selection | Disabled tool names |
| --- | --- |
| Every deployment | `browser_cdp`, `browser_dialog`, `browser_vault`, `read_window_below` |
| `COMPUTER_USE_ENABLED=false` | Add `computer_use` and `browser_exec` |
| `WEBAPP_EXTERNAL_CONTENT` is `tor_proxied`, `ask` or `off` | Add `desktop_preview`, `drive_preview` and `annotate_preview` |

PR4 uses native managed filesystem authority, existing dispatch points and profile
narrowing without enabling the hosted allowlist. It refreshes tool schemas and
generated prompt guidance when the managed tool policy changes. Background review
lists tools from the fork's effective schemas and managed policy. Startup readiness
respects the tool selection, and warm CLI banners reuse only panels built under
the current policy. Model-facing connector and catalog results omit denied tools.
A registered MCP server stays selected when all its tools are temporarily denied.
Explicit Doctor inspection can still report deployment
dependencies. PR5 owns the content ceiling and content capture independently.
Each draft identifies focused commits, validation, platform/type limits, overlap
and removal conditions. [Candidate qualification](development.md#local-upstream-candidate-qualification)
records current evidence without treating the candidates as adopted production code.

PR5 is a reviewed deferred design, not runnable or submission-ready. Its next
steps are to resolve shared Ask/Always renderer ownership and native authenticated
consent authority/storage/API, then implement and qualify the combined passive-
raster package. Native UI preferences exclude permission grants. Preserve the
existing CDN consumer and legitimate upstream IPv6 behavior; fixed `/opt/data`
storage and Tor-only selection are downstream policy. Private audio/video
streaming and interactive frames remain outside this package.

For PR1 adoption, use the existing managed file authority to pin the SSH
endpoint and executor/browser settings:

```yaml
terminal:
  backend: ssh
  ssh_host: 10.203.82.3
  ssh_user: runner
  ssh_port: 2222
  ssh_key: /run/agent-ssh/id_ed25519
  ssh_config: /etc/ssh/ssh_config.d/99-private-hermes.conf
  cwd: /workspace
webapp:
  terminal_environment: executor
  executor_ssh_config: /etc/ssh/ssh_config.d/99-private-hermes.conf
bot_desktop:
  executor_only: true
computer_use:
  backend: cua
browser:
  require_sandbox: true
  executor_python: /opt/browser-harness/bin/python
  executor_workspace: /workspace/browser-use
```

Select `webapp.terminal_environment: gateway` for deployments configured with
`WEBAPP_TERMINAL_ENVIRONMENT=agent`.

The native runner uses the Python and harness already built into the executor
image. Verify the pinned key on fresh model SSH and SCP connections, and retain
the independent operator-terminal setting from PR2. Verify that eligible browser
work reaches executor Chromium and that ambient override settings never select
gateway, cloud, real-profile, alternate-engine or external CDP routes. Keep the
deployment tool selection covered by PR4 and the private-content patch series
while PR5 is deferred.
Qualify cold desktop and harness discovery with real SSH, missing dependencies
and recovery. Verify a warm CUA driver refuses a replaced screen even when the
new screen uses the same display number.

Also supply the launcher's SSH selections in the deployment-owned managed dotenv.
Scoped turns read the managed YAML above, while the native launch bridge can
otherwise preserve an existing profile dotenv value for a key its profile YAML
omits. Use these values through normal launch and profile reload:

```dotenv
HERMES_CONFIG_BACKEND=file
TERMINAL_ENV=ssh
TERMINAL_SSH_HOST=10.203.82.3
TERMINAL_SSH_USER=runner
TERMINAL_SSH_PORT=2222
TERMINAL_SSH_KEY=/run/agent-ssh/id_ed25519
TERMINAL_SSH_CONFIG=/etc/ssh/ssh_config.d/99-private-hermes.conf
```

For PR1–PR4, provision the selected configuration backend and its managed
inputs together as deployment authority. The native defaults are
`/etc/hermes/config.yaml` and `/etc/hermes/.env`. The file backend honors managed YAML.
A different backend can supply configuration elsewhere, and the launch
profile's dotenv can otherwise affect backend selection. Pin file selection
in the deployment-owned managed dotenv and verify the effective backend after
native bootstrap, profile loading and reload. Supply a YAML mapping as the
managed document. An intentionally empty policy uses `{}`. Native Hermes permits
these files to be absent for installations without managed settings. For stack
adoption, the deployment must supply readable, deployment-owned managed YAML and
dotenv before starting Hermes and prevent profiles from writing either file.
Verify that the deployment refuses startup if a required managed file is missing
or unreadable. Test that profile settings cannot change the selected backend or
replace the managed SSH endpoint, URL-fetch policy or tool ceiling.

PR2 changes the saved local Code layout's mode identifier from `code` to
`executor`. Adopting the native layout drops those prerelease local tabs and
their remembered directories and scrollback. Record important working
directories before changing the image. Saved remote gateway tabs keep their
own layout, and executor workspace files stay on the existing mount.

The retained plan and local comparison records include renderer/consent work #156336,
#130878 and #130946, adjacent provenance #130023, managed-policy readers #156728,
profile tool approvals #95247, browser module movement #156598 and Chromium cleanup
#156368. The CDN consumer from #128539 must remain supported; #102667 concerns
large gateway-local rasters. These are comparison references, not live tracker
status or prerequisites. Recheck actual disposition before submission or adoption.

Remove downstream mechanics only after the selected packaged upstream revision
provides equivalent behavior and affected Docker/rootless-Podman qualification
passes. Keep deployment choices, approved network grants, state preservation and
unsupported-surface exclusions. A maintainer merge alone does not establish
runtime qualification or authorize a production update.
