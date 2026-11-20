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
The desktop check follows the `hermes-sandbox` image stage.
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

The derived Hermes image uses the official v0.23.3 image, source
`caafe5389ae585ef77387a962aee05b1bcf17029`. The disposable frontend stage
compares the clean install stamp, packaged source hash and native renderer
receipt before applying the ordered patches. Upstream PM installs its
hash-verified pnpm pin for the native frozen-lockfile build. The final image
includes the patched Python components and rebuilt Webapp selected through
`HERMES_WEBAPP_DIST`. It clears old renderer chunks before copying the output.
The runtime omits pnpm. Its passive absence warning does not block Python plugin
setup. See the [Hermes update workflow](update-workflow.md).

The candidate patch is the packaged Python and renderer diff of release-based
replay recorded in the [release provenance](plans/hermes-upstream-prep.md#v0233-build-provenance).
The export excludes upstream Python tests, website, contributor and Electron-only
files. The local clone and reference checkouts are source references. The Docker build uses the
tracked patch and pinned official image. For the next Hermes release, see
[how to rebuild the candidate patch](update-workflow.md#rebuild-the-candidate-patch-for-a-new-release).

### Downstream responsibility inventory

| Patch | Responsibility | Checks and removal condition |
| --- | --- | --- |
| 0001 upstream candidates | Strict managed reader and reload authority, native SSH trust and file classification, executor desktop/browser, native terminal, configurable URL context and managed tool ceiling from PR1–PR6 | Remove adopted portions when the official pin provides them and the affected packaged checks pass |
| 0002 managed policy | Publish the serving container's root-owned managed YAML and dotenv before native bootstrap | Verify effective settings under conflicting profile input, repeat loading and offline operation |
| 0003 desktop and terminal policy | Keep explicit desktop enablement and recovery guidance, local Code/Agent labels and startup acknowledgement, and safe absolute Code cwd | Retain until equivalent native deployment controls meet the terminal and desktop checks |
| 0004 deployment policy | Capture content and desktop choices before profile dotenv loading, and validate WebApp content policy | Retain until native deployment policy preserves the same authority |
| 0008 private image routes | Authenticated content and consent APIs with bounded public IPv4 raster retrieval | Image endpoint, CDN consumer and outage checks |
| 0009 browser response policy | CSP, trusted bootstrap headers and inert private previews | Browser response, exact-origin socket and active-file checks |
| 0010 browser content | Shared rendering, consent and image Save/Copy | Renderer and real browser checks across all content modes |

The serving entrypoint generates `/etc/hermes/config.yaml` and `/etc/hermes/.env`.
The files pin the native file backend, SSH endpoint and client configuration,
executor-only desktop, Chromium sandbox, operator terminal mode, no-fetch URL
references and the tool denial list. The managed dotenv also pins terminal
selectors for the native launch bridge. Hermes retains those assignments during
profile reload. Offline jobs operate on the saved profile. Browser startup and reload checks use the built image.

The desktop executor uses the separately pinned Hermes sandbox image, OpenSSH
and a hash-locked harness under `/opt/browser-harness`. The candidate sends its
runner and the official screenshot helper over the existing SSH command stream.
The requirements follow the Hermes Python lock and retain the Pillow 13 override
with `--no-deps`. The live browser profile remains persistent and excluded from
the native bulk synchronization archive. The derived agent's empty
`/workspace` supports native cwd checks and is separate from the executor mount.

Run `make hermes-ui-test` for TypeScript and focused renderer tests in the
disposable build stage. The upstream session-resume JSON fixture, omitted from
the runtime image, is in `tests/fixtures/`. Run the [packaged checks](development.md#packaged-hermes-qualification)
against both engines when changing the adopted source or deployment patch series.

### Local preparation package dispositions

The PR1–PR6 drafts in `upstream_work/submissions/` use the
`upstream-pr/*` branches. The working clone `upstream_work/hermes-agent/`
uses the `fork` remote for those refs and the release refs. Submit one branch per
PR using the heads and merge order in the [submission plan](plans/hermes-upstream-prep.md#1-branches-to-submit).
See the [fork repository](https://github.com/mikeperry-tor/hermes-agent).
The `stack-patches/v0.23.3/*` refs preserve the
[v0.23.3 build provenance](plans/hermes-upstream-prep.md#v0233-build-provenance).

Human submissions target `NousResearch/hermes-agent`, which is the clone's
`origin` remote. PR1 supplies strict reads, validated snapshots and dotenv
precedence through reload. PR2 provides the SSH fixes that PR3 builds on.
PR4–PR6 each build directly on PR1.
Follow the [merge-order checklist](plans/hermes-upstream-prep.md#2-upstream-submission-and-merge-order-checklist)
for overlap and validation.

Candidate identities use `Mike Perry <mikeperry-git@untrusted.systems>`.
Exact local heads and qualification scope are recorded in the preparation plan.

| Package | Packaged use |
| --- | --- |
| PR1 | Strict managed reads, dotenv bootstrap and reload, and profile-specific interpolation |
| PR2 | Browser-profile sync exclusion, missing-path classification and pinned SSH client options |
| PR3 | Native executor placement, desktop/browser transport and Chromium sandboxing |
| PR4 | Native executor/gateway terminal selection with the stack's Code/Agent modes |
| PR5 | Managed `context_references.fetch_urls: false` for normal and config-bypass turns |
| PR6 | Managed `tools.disabled` derived from the deployment's desktop and external-content selections |
| PR7 | Deferred. The stack carries its private content, raster and consent patches |

The serving image derives `tools.disabled` from the deployment selections.

| Selection | Disabled tool names |
| --- | --- |
| Every deployment | `browser_cdp`, `browser_dialog`, `browser_vault`, `read_window_below` |
| `COMPUTER_USE_ENABLED=false` | Add `computer_use` and `browser_exec` |
| `WEBAPP_EXTERNAL_CONTENT` is `tor_proxied`, `ask` or `off` | Add `desktop_preview`, `drive_preview` and `annotate_preview` |

PR6 uses native managed filesystem authority, existing dispatch points and profile
narrowing without enabling the hosted allowlist. It refreshes tool schemas and
generated prompt guidance when the managed tool policy changes. Background review
lists tools from the fork's effective schemas and managed policy. Startup readiness
respects the tool selection, and warm CLI banners reuse only panels built under
the current policy. Model-facing connector and catalog results omit denied tools.
A registered MCP server stays selected when all its tools are temporarily denied.
Explicit Doctor inspection can still report deployment
dependencies. PR7 owns the content ceiling and content capture independently.
The local drafts list the topic commits and their validation.
The [preparation plan](plans/hermes-upstream-prep.md#2-upstream-submission-and-merge-order-checklist)
records overlaps and patch removal conditions. The
[candidate qualification](development.md#local-upstream-candidate-qualification)
records platform limits and candidate-only evidence.

PR7 is a reviewed deferred design, not runnable or submission-ready. Its next
steps are to resolve shared Ask/Always renderer ownership and native authenticated
consent authority/storage/API, then implement and qualify the combined passive-
raster package. Native UI preferences exclude permission grants. Preserve the
existing CDN consumer and legitimate upstream IPv6 behavior; fixed `/opt/data`
storage and Tor-only selection are downstream policy. Private audio/video
streaming and interactive frames remain outside this package.

The stack preserves the existing OpenSSH configuration file for both model
execution and the operator Code terminal. Verify fresh SSH and SCP with valid,
missing and mismatched known-host keys, desktop dependency loss and recovery,
and refusal of browser routes outside managed executor Chromium.

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
