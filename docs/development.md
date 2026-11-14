# Development and qualification

For operator setup, see [the README](../README.md). For network design and
execution boundaries, see [architecture and isolation](architecture.md).
Read [AGENTS.md](../AGENTS.md) before changing the stack and follow the
[planning workflow](planning-workflow.md) for substantial staged work.

## Repository layout and local configuration

- `components/`: tracked Dockerfiles, container scripts, and component defaults.
- `.env`: private operator settings, selected explicitly for each service.
- `config/`: private editable bind-mount configuration; initialized from defaults.
- `data/`: persistent bind directories for identities and executor work.
- `scripts/`: host-side initialization and checks.
- `tests/fixtures/`: disposable test servers and configuration.

`make init` creates missing local configuration and preserves existing files.
`make up` runs it automatically, then runs cached Compose builds for the selected
base/Funnel deployment and the treasury profile before offline setup or service
changes. Treasury is included even before preparation because its image supplies
the initial policy. `make x402_treazury-prepare` builds only the owning treasury
service before inspecting preparation history or disconnecting/stopping services.
The shared setup/admin image aliases need no separate build definitions.
Build failure aborts the requested operation before those runtime changes.
The selected engine owns build-input detection and caching; no freshness records
are stored.
Inspection, backup and shutdown do not invoke builds. `make build` constructs images only: it does not
initialize operator state or validate deployment policy. Run `make check`
explicitly for source/configuration qualification.

Research policy is seeded from the built image by `make x402_treazury-config`,
managed startup or new-wallet creation; see
[research configuration](x402_treazury.md#edit-the-research-configuration).
Startup and explicit preparation compare saved policy with the rendered default
after building/seeding, before setup or activation. Comparison uses a networkless
image container without private mounts; failures are reported as advisory.
The standalone `make x402_treazury-config-diff` performs the same comparison
without builds or seeding, and reports inspection failures with a nonzero exit.
Saved-wallet commands do not initialize unrelated state. New-wallet creation
prepares only its Tor/network host inputs. Add new settings explicitly using
`.env.example`; image/source pins remain in Compose and Dockerfiles.

Hermes and wallet state use native named volumes; other persistent files live
in `data/`. Runtime Tor socket IPC also uses a named volume. See
[configuration and backups](configuration.md) before starting.

## Onion ingress qualification

`make onion-test` uses disposable Tor state and the actual host address target,
native Tor, HAProxy and pinned Hermes. It disables Tor networking and uses a
test-only byte proxy from the browser into Tor's namespace; no descriptor is
published. It covers identity retry/recovery, malformed-secret refusal, backup
restore, exact ingress, browser-origin login/refresh/logout and WebSockets,
origin-scoped image consent, forbidden paths, restart/outage and withdrawal.
Use the existing browser environment via `WEBAPP_BROWSER_PYTHON` and the pinned
`tests/requirements-browser.txt`. `PLAYWRIGHT_BROWSERS_PATH` may select an
explicit disposable browser installation.

`make onion-live-test` additionally publishes a disposable authenticated service
and uses a separate native Tor client for real rendezvous, login and protected
API access. This is explicit public-network qualification, not part of routine
`make check` or the nonpublishing onion suite. The client has a test deadline;
deployment work receives no new runtime deadline or direct transport fallback.
Stop other fixed-network projects first; cleanup removes only test resources.

For actual Tor Browser semantics, set `TOR_BROWSER_PYTHON` to an environment
with Selenium, `TOR_BROWSER_BINARY` to the installed browser, and `GECKODRIVER`
to an existing local driver. The test creates a disposable profile, disables the
bundled Tor launcher and uses the controlled SOCKS fixture. It retains Tor
Browser's private cookie partitioning and reads only cookie flags through its
private-origin cookie API; it never prints session values. The direct driver
path bypasses Selenium Manager entirely, with its statistics opt-out set too.
Do not use automatic driver discovery: Selenium Manager has default Plausible
analytics. Browser fixture results are separate from live Tor rendezvous.

Qualification on 2026-11-13 used Docker 29.9.3 / Compose 5.7.0 on macOS 26.7.1
ARM64, and rootless Podman 5.4.2 / Compose provider 5.7.1 on Debian 13 ARM64,
kernel `6.12.116+deb13-arm64` via `debvm23`. Both engines passed the source/model
checks (167 tests), including all four onion/Funnel flag combinations. The full
deterministic onion fixture passed both engines with native recovery/backup,
public-key-only startup repair, consent, WebSockets, forged forwarding headers,
restart-loop writer refusal and disable/re-enable. Chromium 156.0.8078.4 was
exercised on both engines; actual Tor Browser 15.0.26 (Gecko 140.17.0) was
exercised locally against Docker. The existing routing/SSH/Tor-outage regression
fixture passed both engines, preserving public Tor egress, private-path denial,
executor isolation and outage/restart behavior.
Separate Tor 0.4.9.16 clients passed live onion rendezvous, authentication and
protected API access on both engines. Publication took several minutes; bootstrap
health alone did not establish reachability. Existing localhost/simulated HTTPS
cookie/auth/streaming regression checks passed both engines while onion ingress
was enabled. Lifecycle outage probes use localhost; HTTPS is exercised before
outage, with its unchanged isolated outage path assessed by source inspection.

The Chromium onion fixture supplies Fetch Metadata explicitly for the consent
endpoint; stock Chromium does not attach it to this HTTP origin. Actual Tor
Browser generated the required metadata and passed consent without that fixture
header. The test-only proxy supports HTTP/CONNECT and SOCKS into Tor's namespace;
it is neither a production listener nor live rendezvous evidence.

The first host Selenium Manager driver-discovery attempt emitted an unsolicited
Plausible analytics request. This did not originate in a stack image. The retained
Tor Browser harness now requires a direct local driver and bypasses the manager;
do not restore automatic discovery as a test dependency fallback.
Unchanged browser-content evidence remains in its existing sections; this change
does not requalify every renderer. Live Funnel enrollment, provider attestation,
financial settlement and untested platforms remain outside these checks.

Fresh independent read-only design and final combined reviews accepted onion
ingress, including production revision `8ae5e57` and the qualified test/doc
follow-up, with no remaining material findings. The implementation review's
writer-race finding was resolved by requiring runtime-container removal before
offline writes; recovery documentation was corrected to distinguish address
inspection from native derived-file repair. The final reviewer assessed recorded
evidence without rerunning suites. The completed implementation plan was retired
under the planning workflow; its history remains in Git.

## Qualification and maintenance

```sh
make check
make test
```

The live test uses a separate disposable Compose project with the actual pinned
Hermes image, the real SSH executor, real Tor, teep with a dummy provider
key, and the x402_treazury server with an unfunded fixture wallet. It performs no
inference or paid research calls. Stop a normal deployment before running it:
projects use the same fixed subnets, and preflight refuses overlaps.

Tests cover actual Hermes terminal and Python execution over SSH, absence of
agent keys/environment in the executor, Tor versus direct inference egress,
forbidden host/VM/RPC/private destinations, actual Streamable HTTP MCP
initialize/list/call with SSE responses, unselected ports, and Tor failure.
Tests use separate project volumes and private temporary bind directories, never
the operator's volumes or `data/` tree. Only disposable test resources are deleted.

Keep `agent-net` and `executor-net` alive while their application containers
exist. Docker can leave namespace-sharing applications disconnected after an
owner restart/recreation; automatic reattachment is also unqualified on Podman.
See the [shared-namespace lifecycle limitation](architecture.md#network-and-execution-boundaries)
and upstream reports there. If a qualification run interrupts an owner, retain
diagnostics and tear down/recreate the whole disposable project through its
normal fixture lifecycle before continuing. Restarting only the owner or
retrying requests does not establish recovery. Keep cleanup scoped to that test
project; operator recovery uses `make down` followed by `make up`, preserving data.
Do not diagnose this known lifecycle failure as a capability regression without
checking namespace attachment. Tor-only outage/restart tests remain valid because
applications do not share Tor's namespace. Any future recovery qualification
must distinguish independent reattachment from whole-project recreation; neither
fresh startup nor Tor recovery proves independent reattachment.

References: [Hermes backends](https://hermes-agent.nousresearch.com/docs/user-guide/configuration/#terminal-backend-configuration),
[Hermes security](https://hermes-agent.nousresearch.com/docs/user-guide/security/),
[Dockurr Tor](https://github.com/dockur/tor),
[Docker isolated networks](https://docs.docker.com/engine/network/port-publishing/#gateway-modes),
[teep](https://github.com/13rac1/teep).

`make check` validates the Docker and Podman Compose models with the selected
engine's Compose and runs without initialized operator state. Startup-ordering
unit tests isolate bind-source validation; `tests/test_bind_sources.py` covers
that validation separately. `tests/test_engine.py` covers the `CONTAINER_ENGINE` selector,
the engine checks, the `stack.py compose` option parsing, Podman network creation,
the proxy firewall rules and the engine floors, without a running engine. The
live tests use the same Compose files and engine commands as the stack. Run
`python3 tests/launch_smoke.py` after building Hermes to check cold passthrough
runs, dependency/namespace-owner network creation, truly offline runs, rejected
maintenance overrides and disposable network cleanup. It uses no private mounts,
Tor or wallets; serialize it with the other fixed-subnet fixtures. The same check
uses native strict-network inspection when Podman is selected. It also checks
native dry-run placement and preserves an unused network during simulated down.
Run `make test` on each engine after changing network, ingress or overlay code;
`CONTAINER_ENGINE=docker` or `CONTAINER_ENGINE=podman` selects the target without
editing `.env`. Also run affected focused fixtures; model checks alone do not
qualify native behavior. Reuse unchanged evidence and report unavailable targets. On
Podman, `make podman-paths-test` checks the paths of a running stack, including a
client on a network without isolation, with positive controls for its DNS, TCP
and host-loopback probes; it refuses to run unless Podman is selected.

`tests/capability_bootstrap.py` is a focused Hermes privilege/lifecycle probe. It
runs the production entrypoint in a disposable networkless named volume, with no
operator mounts, credentials or deployment, and checks native profile supervision,
profile registration, warm permission repair, CLI and clean stop. `--omit GRANT`
diagnoses a required capability; `--probe-path` restarts the root static service
with a harmless marker executable in the writable profile wrapper directory;
`--expect-closed` asserts the reordered image `PATH` resolves the service from a
trusted directory and writes no marker; `--path` overrides the container `PATH`
for that experiment before the image change is built. Do not treat a successful boot or a
capability snapshot as qualification: use the probe to diagnose a specific
change, then run the affected full checks on each engine. The probe removes its
container and named volume.

Before the current-main rebase, on 2026-11-13, Docker Desktop ARM64
(Engine 29.9.3, Compose 5.7.0) passed
139 unit tests, all four effective models, compilation, the cold-launch/dry-run
fixture, main SSH/MCP/Tor outage/recovery and storage suites, both standalone
policy scripts (including 12 tool-policy combinations), unfunded editable research
configuration and endpoint-readiness/cancellation checks. A fresh independent
combined review accepted `817fd3d` for the source/current Docker correction scope,
with no significant findings or compelling premerge simplifications. The model
tests exercise both engine paths through the selected provider; they do not prove
Podman runtime behavior. The subsequent native lifecycle, ingress and
corrected-launch qualification is recorded below.

The subsequent rebase onto `main` `b46e050` retained v0.23.1's pnpm layout,
relay guards and schema migration alongside native engine selection. Through
`454ce72`, the same Docker platform passed 143 unit tests, four effective models,
all image builds, native image and packaged policy checks, full TypeScript/70
renderer tests, main isolation/Tor/recovery, storage/migration, cold/dry-run,
unfunded research comparison and the full 24-case browser content/relay matrix
plus ingress failure/recovery and staged MCP activation. New comparison and
renderer-command tests cover both engine paths. The first webapp run hit a
transient post-restart Tor DNS failure; positive image checks now retry only that
exact failure, while Tor-stopped denial stays unchanged. The complete rerun passed.
Fresh independent reviews accepted combined source `e28fbde` and that focused
fixture correction with no material findings or compelling simplifications.
The native follow-up and final combined review acceptance are recorded below.

On 2026-11-13, unchanged source `a94ff16` was copied to Debian 13 ARM64
(kernel 6.12.116), rootless Podman 5.4.2 with netavark/overlay, and
the official Docker Compose 5.1.4 binary. The provider works without a PATH
change when `PODMAN_COMPOSE_PROVIDER=$HOME/.docker/cli-plugins/docker-compose`
and `CONTAINER_ENGINE=podman` are exported. No provider patch was used.
The 143 unit tests, four models, compilation, all selected lean/Funnel/treasury
image builds, full storage/migration/locking suite, packaged image/tool-policy
and URL-reference checks, full TypeScript/70 UI tests, endpoint cancellation,
readiness/errors/restart, and complete main SSH/MCP/Tor outage/recovery suite
passed. Managed `make up` and ordinary `make down` passed with dummy inference
credentials and no wallet initialization. The dedicated Podman path suite passed
38/38, including non-isolated-client denial, positive probe controls, strict
network inspection and HAProxy's absent default route. The deployment was left
stopped, its generated state preserved, and leftover disposable fixture volumes
removed explicitly by their exact project labels.
A networkless signal-handler probe completed 12-second cleanup both
with the configured unlimited timeout and explicit Compose `--timeout -1`.
Podman's native inspection stores the configured timeout as unsigned maximum.

That initial qualification exposed an API limitation. Compose preserves
`bind.create_host_path:
false` in its effective model, but the compatibility API starts a container and
creates the missing source anyway. Native `podman run --mount` refuses it.
The operation-scoped host preflight now rejects missing required sources for
managed creation, including offline jobs and supported passthrough launches; raw
Compose still bypasses it and concurrent host deletion remains an upstream gap.
The original reliability defect had no demonstrated credential or network
boundary bypass. A subsequent side-by-side comparison with the checksum-verified
official [Compose 5.7.1](https://github.com/docker/compose/releases/tag/v5.7.1)
binary reproduced both missing-bind creation and inline-seccomp filename failure
on Podman 5.4.2. The installed provider was not replaced; upgrading Compose alone
does not fix either observed issue.

The subsequent qualification corrections address the fixture failures:

- Cold-launch health checks use a simple executable HTTP probe, avoiding API
  splitting of a multiword Python argument.
- Research's missing-scratch negative control explicitly mounts read-only
  scratch on both engines; it no longer depends on Podman's automatic tmpfs.
- The disposable TLS fixture directory is traversable by container UID 10000.
- Both relay and local-file PNG fixtures have valid chunk checksums.
- The CONNECT observer uses unbuffered HTTP input before transferring socket
  ownership to its raw tunnel loop. A controlled coalesced-write probe reproduced
  lost early tunnel bytes with the old buffered parser. Real TCP tests cover
  preserved bytes and forbidden-target refusal without an upstream connection.
- The simulated TLS bridge closes both sockets and cancels residual copying
  when either peer closes. A real loopback probe reproduced the original
  orphaned bridge; two TCP tests verify full byte delivery, closure from either
  side and visible upstream-connection refusal. No active-stream deadline was
  added. A fresh independent review accepted this lifecycle correction.
- Ownership cleanup uses a networkless helper with only the disposable bind,
  preserving the nonce check and scoped capabilities. It no longer recreates
  named application volumes through `setup`; storage asserts their absence.
  Both engines also removed the helper's inherited anonymous volume with `--rm`.

Fresh independent review accepted the initial six-file fixture correction.
The expanded 147-test unit suite/model/compile checks and complete cold-launch/
dry-run, image-canary, research-policy and storage suites passed on both engines.
Subsequent browser testing exposed a product portability defect: Linux WebKit renders attachment
HTML inline despite its disposition. Standalone HTTP probes reproduced this
without containers; the sandbox blocked scripts, while binary MIME delivery
restored downloads. The existing untrusted HTML/XHTML/SVG branch now serves
binary attachments with unchanged bytes, nosniff and sandbox policy, preserving
trusted-document, raster and media behavior in every mode. Fresh independent
design review accepted this narrow fix. Browser tests retain actual click and
new-tab plugin download requirements and compare plugin/relay clicked-download
bytes with the authenticated response. Direct relay navigation still requires
403 under its native same-origin Fetch Metadata guard. Full rebuilt-image
Docker browser qualification passed before the focused-matrix refactor; native
Podman completed the controlled matrix but failed the separate live Tor control.
The corrected qualification and final controlled-browser/cleanup results are
recorded below.
Browser assertions wait for the exact consent-mutation response rather than
polling potentially stale state. Extra-tab exercises follow content/media checks;
chat streaming is qualified separately for each ingress.
Logout checks use a fresh page in the same cleared cookie context, avoiding a
race with the old SPA's own redirect while retaining unauthorized API assertions.

Earlier live checks also encountered a three-second Tor DNS timeout, an unfunded treasury
Tor-check TLS EOF, and a plugin environment GitHub-wheel download timeout; the
treasury and plugin suites did not pass. No weaker transport was selected.
The VM's checkout umask produced a group-writable public SSH configuration;
setting `components/hermes/ssh-client.conf` to `0644` was required by OpenSSH
before the successful core rerun. Source content was unchanged during that
initial qualification. Host browser
prerequisites were installed separately. At that initial stage, executor
desktop/browser use was explicitly refused with Podman; no inference, funds or live Funnel was tested.

Component-specific checks and limits are documented in the
[webapp](webapp.md#verification-and-current-limits),
[x402_treazury](x402_treazury.md#stop-and-test), and
[updates and plugins](updates-and-plugins.md) guides.

On 2026-11-13, the implemented capability reductions passed `make test`
(including `make check` and all effective models), `make computer-use-test`,
`make browser-use-test`, `python3 tests/launch_smoke.py` and `make storage-test`
on Docker Desktop ARM64 and rootless Podman ARM64. The focused native Hermes
probe passed with the trusted `PATH`; steady-state inspection found Tor at UID
101/GID 102 and both namespace endpoints at UID/GID 65534 with empty effective,
permitted, inheritable, ambient and bounding sets. Tests used disposable projects
and did not touch operator volumes. AMD64, live public ingress/Funnel and live
settlement/providers remain unqualified.

Follow-up capability review at `a998dda` restored the native webapp fixture's
production grants after the core fixture clears them. Effective-model regression
coverage compares native startup privileges for lean and desktop on both engines;
the namespace-owner assertion now checks every UID/GID field, empty supplementary
groups, all capability sets and no-new-privileges, with positive/negative procfs
regression cases. The 44 engine tests and two identity tests passed; the new model
test also passed through the actual Podman provider, and the corrected assertions
passed against all three live namespace owners on both engines.

The full native `tests/webapp_smoke.py` passed with the lean executor on Docker
Desktop ARM64 (Engine 29.9.3, Compose 5.7.0) and Debian 13 ARM64 rootless Podman
5.4.2 (Compose 5.7.1). It covered local/simulated HTTPS authentication, interactive
terminal and SSH file access, gateway restart, credential rotation, repeated
native recreation, content/consent controls and staged MCP activation. No live
Funnel enrollment, inference or funded research was used. The first Podman run
reproduced the documented group-writable SSH-config rejection in the disposable
archive; the successful run used mode `0644`. Logs are
`/tmp/capability-review-fix-webapp-{docker,podman}.log` on the Docker host;
the initial failure remains on the VM as
`/tmp/capability-review-fix-webapp-podman-archive-permissions.log`. New fixture
resources were removed; unrelated existing state was preserved.

Independent endpoint namespace-owner restart/recreation with attached
applications was not qualified and is unsupported on both engines. Fresh-stack
startup and Tor outage/restart checks do not establish namespace reattachment.
Use the [whole-stack recovery procedure](architecture.md#network-and-execution-boundaries)
instead; no automatic reattachment or recovery mechanism is provided.

## Executor desktop qualification

The [architecture guide](architecture.md#executor-capability-requirements) records
OpenSSH capability-removal experiments and their exact failure reasons. The
three existing listener grants are demonstrated requirements for that tested
configuration, not desktop grants. Repeat the affected evidence when replacing
OpenSSH, its account model or privilege-separation setup; do not repeat this
investigation merely because another GUI package is added. The Alpine lean
listener retains the same grants by conservative inference; P5/lean SSH
qualification exercises it on both engines.

Both-engine lifecycle qualification measured authenticated runner sessions at
UID 10000 with empty effective, permitted, inheritable and ambient sets and
bounding set `0x400c0`. That bounding set is not original-namespace authority
under `NoNewPrivs=1` and absent file capabilities; `SYS_CHROOT` is also a
functional desktop/Podman Chromium sandbox requirement, so do not clear it as a
security-only cleanup.

The optional desktop build uses Debian rather than Alpine. Run the packaged
policy checks with `python3 tests/desktop_tools_smoke.py`. Run
`make computer-use-test` to build the selected images and test real desktop
actions over SSH together with the existing Tor/forbidden-path checks.
`python3 tests/computer_use_smoke.py --desktop-only` runs the GUI portion
while diagnosing an affected failure. These fixtures use disposable state,
ephemeral Teep host ports, dummy credentials and no inference or payments.
Serialize them with other fixed-subnet tests and keep the normal stack down.

After building the desktop image, `python3 tests/desktop_startup_smoke.py` runs
its actual startup script in a networkless read-only fixture with the existing
SSH bounding set. It verifies stale Chromium coordination unlinking, cookie-like
and identity data preservation, retained symlink targets and visible refusal of
an unexpected coordination directory. The same command uses the normal executor
tag on Podman. The fixture supplies no host keys, so native sshd must refuse after preparation; normal real SSH and
browser lifecycle checks remain separate.

The Docker desktop executor uses a checked-in Moby seccomp baseline from commit
`7b5ccfab2d6b4e0aa64c6cce401a2705788eafeb`, with one added allow rule for
`clone`, `setns`, and `unshare`. Source:
[default.json](https://github.com/moby/profiles/blob/7b5ccfab2d6b4e0aa64c6cce401a2705788eafeb/seccomp/default.json);
license: `components/executor/seccomp-LICENSE`. The profile is selected for
Docker's desktop variant by native Compose inheritance in `compose.executor.yaml`;
the Podman overlay replaces it with the native engine policy.
It retains the baseline's `clone3` ENOSYS behavior and does not allow io_uring.
Playwright's older published full profile was rejected because it changed those
unrelated syscall contracts. Reconcile the baseline with engine updates. Remove
Docker's custom profile when its native engine policy permits the qualified
Chromium sandbox without weakening unrelated syscall restrictions.

Enabling user namespaces exposes additional kernel paths to executor code; it
must not grant control of the parent network namespace or bypass Tor. Verify
those forbidden paths and the actual Chromium sandbox layers, alongside runner
capabilities, SSH failure/restart behavior and persistent state. Each engine and
CPU target requires native evidence; source/manifest inspection is insufficient.
See [current native Podman evidence](#native-podman-desktop-support).
The optional desktop implementation is complete for the qualified scope below.
The stack has only been runtime-qualified on ARM64; AMD64 qualification is not a
completion prerequisite. The pinned desktop image includes Linux AMD64 and ARM64,
Compose imposes no ARM64 restriction, and Chromium discovery retains its AMD64
paths alongside the added ARM64 path. This preserves the ability to qualify AMD64
without claiming that it has passed. The [rootless engine differences](architecture.md#rootless-podman)
record the engine-specific desktop policies; native operator
webapp/browser qualification is recorded separately above and below.

The image choice avoids a substantial download and disk footprint when desktop
tools are unused. On 2026-11-11, the pinned desktop index reported compressed
downloads of 1,192,327,731 bytes (ARM64) and 1,203,999,297 bytes (AMD64).
Local ARM64 unpacked images measured 229,682,455 bytes for lean,
4,380,500,982 bytes for the desktop base and 4,429,795,686 bytes for the adapted
desktop executor. Download and unpacked sizes are different measurements; these
local build observations do not establish AMD64 disk or runtime requirements.
Adding the isolated browser harness brought the local ARM64 adapted executor to
4,508,949,695 unpacked bytes; the desktop base and lean target are unchanged.

On 2026-11-11, Docker Desktop ARM64 (Engine 29.9.3) passed 92 unit tests,
effective base/Funnel models, compilation, 12 packaged tool-policy combinations,
lean and desktop SSH/network checks, UID-101 Tor routing/outage/recovery and
desktop capture/click/type/key/scroll. Focused checks also passed native idle
eligibility/stop, human takeover preservation, display restart, lost derived
publication repair, enabled-gateway/lean-executor dependency refusal, SSH outage
and restart, actual root-write rejection on the system/identity mounts, and
on/off/on preservation of SSH identity, workspace, Chromium localStorage and an
HTTP-only fixture cookie. These use no real accounts or funds.

The combined webapp run passed the existing 24 content cases (Chromium, Firefox,
WebKit; four modes; local and simulated HTTPS), plus Chromium screen capture/RFB
pixels on both ingress fixtures in all four modes. Screen checks exercised
wrong-origin, one-use and expired tickets, watch/stale-viewer input denial,
positive takeover input, stop/restart, native cookie-logout lifetimes and no
external HTTP requests from viewing. The existing logout test now observes its
browser response without awaiting a fetch across SPA navigation. DNS/preconnect,
stale consent, Tor retrieval and credential/ingress failure checks also passed.
The GUI tests cover one active default-profile screen and programmatic native
display transport; full visual interaction with the native noVNC pane and other
profile arrangements are not independently qualified. At that revision, AMD64
and rootless Podman were unqualified; later Podman evidence appears in
[native Podman desktop support](#native-podman-desktop-support). Simulated HTTPS
does not prove live Funnel ingress, and these checks do not establish provider
attestation or funded settlement.

A fresh independent read-only review accepted combined revision
`4f003190e91358d9908dda87390f8254dbce2ee0` for the implemented and qualified
Docker Desktop ARM64 scope with no material findings. The computer-use plan was
completed after the operator clarified that untested architectures do not block
completion. Full visual noVNC-pane interaction and additional profile arrangements
remain outside the qualified scope; concurrent profile screens remain unsupported.

### Browser harness and results

Browser automation reuses this desktop substrate and adds the pinned harness in
an isolated executor environment. Run `make browser-use-test` for its focused
disposable placement, sessions, cancellation and result checks. Runtime browser
qualification passed remote stdlib/child execution, DOM/navigation/type/download,
named/unnamed tabs, concurrent startup, screenshot staging/native vision, native
selected-cache round-trip with the browser profile excluded, takeover denial,
active/startup cancellation, timeout/retry, daemon crash, owner death and actual
missing-harness refusal/recovery. These fixtures execute the tool as Hermes UID
10000, matching the gateway: root engine `exec` can create native install locks
owned by the wrong account and invalidate restart tests. The complete desktop/
network run also passed image switching and harness Tor outage/recovery. The
actual automation-launched Chromium's `chrome://sandbox` page reported namespace,
PID/network-namespace and seccomp-BPF sandbox layers enabled.
The implementation adds no capability, syscall rule,
published port or internal network grant. The existing three OpenSSH grants and
desktop-only Chromium user-namespace profile remain the owning requirements.

On 2026-11-12, the combined Docker Desktop ARM64 webapp regression passed the
existing 24 content cases across Chromium, Firefox and WebKit, eight screen
mode/ingress cases, and eight browser screenshot/download mode/ingress cases
plus initial authenticated result checks. Actual generated screenshots rendered,
executor downloads transferred, logout denied subsequent file requests, and the
viewing browser made no external requests. Restart, credential rotation, stale
consent, DNS/preconnect, ingress mismatch and Tor failure/recovery checks passed.
The profile archive exclusion also passed actual selected-cache round-trip
without socket/symlink extraction failures. That qualification covered the single
default-profile desktop and tested engine/architecture above; AMD64,
rootless Podman and full visual noVNC-pane interaction were unqualified at that
revision. See [later Podman qualification](#native-podman-desktop-support).
CDP/dialog/vault tools remain excluded; raw CDP through executor Python does not
qualify their separate native routes.

A fresh independent read-only combined review accepted BU-1 and BU-FINAL at
`db84bcfb8ea879a51db5ab59c0ac6b1a244874b3` for this documented scope, with no
material findings. Final patch-context whitespace cleanup was checked against
the exact packaged source: all seven patches apply and produce identical source
bytes. The completed browser-use plan has been removed; its history remains in Git.

## Hermes v0.23.1 integration qualification

The upgrade review covered upstream
`2bd378ed1b8d6bf2192cb26e0a55ff3091e6bd19..3b421578588243f920886e6fe79a6faa87ea026e`.
The official multiarch base index is
`sha256:276d44685c65c0cb2a25f190b63c65c8906f9dc76486fb1c05ae71b5826bda08`.
The downloaded ARM64 image's clean install stamp matched the selected commit;
its native renderer receipt and calculated source hash both matched
`d962149f7c279801f68eb629e8939592105e0d49ddb97d01a549b85748335717`.
All seven deployment patches remain necessary. Only the disabled-tool patch's
import context needed refreshing. The browser harness dependency closure,
screenshot helper and copied upstream session fixture are unchanged.

The principal integration changes are the upstream switch to pnpm builds,
native saved-gateway HTTP/WebSocket relays and SSH connections, threaded tool
availability probes, a new browser-vault inline dispatcher, and schema 53.
The [derived build](updates-and-plugins.md#derived-hermes-build-and-patch-maintenance)
uses upstream's pinned pnpm in its disposable frontend stage. Existing registry
and inline exclusions also cover the new vault dispatcher. Native availability
budgets remain upstream-owned. Saved connections retain authenticated operator
authority and the namespace's existing network grants; no firewall exceptions
were added. The relay cannot pass a remote trusted-page marker through its
header allowlist, so the existing global response policy makes relayed HTML/SVG
inert attachments. The content matrix now exercises that actual route with
hostile documents, a valid raster, anonymous requests and credential/header
canaries. Configuration qualification includes a populated schema-52 migration
and preservation of operator settings and SSH identities.

On 2026-11-12, Docker Desktop ARM64 (Engine 29.9.3) passed 92 unit tests,
effective base/Funnel Compose models, compilation, native image dispatch and
policy capture, 12 packaged tool-policy combinations, URL-context refusal,
full renderer TypeScript and 70 focused renderer tests. Runtime checks passed
configuration migration/repair/retry and native-volume locking; actual SSH
terminal/code execution; allowed and forbidden network paths; Tor outage and
restart; desktop actions, sandbox layers and on/off/on state preservation;
browser placement, cancellation, daemon/owner death and missing-harness recovery;
image retrieval canaries; and dependency-bearing native plugin install/update
and recreation persistence. The successful UID-101 public Tor probe now uses
the same existing retry helper as other allowed Tor probes; forbidden-path and
Tor-stopped assertions retain their original failure behavior.

The webapp passed 24 content/relay cases across Chromium, Firefox and WebKit,
four content modes and local/simulated HTTPS ingress, plus eight screen and
eight browser screenshot/download mode/ingress cases. Native auth, credential
rotation, gateway restart, terminal/file placement and viewer-request checks
also passed. Initial transient Tor/DNS failures were retried without changing
transport. One Firefox popup observation timed out; a diagnostic repeat and the
complete matrix passed the same deliberate-link assertion with read-only click
diagnostics. Existing single-profile, platform and visual-surface limitations
above still apply. These checks use dummy credentials and establish neither live
Funnel ingress, provider attestation nor funded settlement.

The complete webapp run also passed stale-consent revocation across restart and
policy changes, direct DNS/TCP/preconnect observation, gateway/ingress mismatch
refusal and repair, real Tor raster retrieval and outage/recovery, and staged
activation/reload/disconnection of twelve unfunded fixture MCP endpoints.

A fresh independent read-only review accepted U2/U-FINAL at
`594bc0c92f87cbe3694f54afbb64e82b63275a4c` with no material findings for the
documented Docker Desktop ARM64 scope. The completed upgrade plan was removed
after acceptance; Git history retains its baseline and review evidence.

## Diagnostic messages

Explain the affected operation or capability, its impact, the known cause or
uncertainty, and a useful next action when established. Messages must make sense
without decoding implementation stage names or error categories; structured
fields supplement that explanation. Include safe causes and status information,
never credentials, raw protocol responses or credential-bearing upstream prose.

Choose severity at the owner that knows the outcome after applicable recovery:
ERROR for unavailable required service/endpoint functionality, WARN for a terminal
requested-operation failure or unexpected loss of functionality, INFO for useful
lifecycle/progress/recovery messages, and DEBUG/TRACE for routine attempts and
diagnostic detail. An intermediate failure with retry remaining is not a terminal
operation failure. Elapsed time or repetition alone does not promote severity.
Scope errors to the affected capability rather than announcing whole-stack failure.
When outcome is uncertain, say so; do not imply that a payment is safe to repeat.

Endpoint activation follows container logs from the serving container's `StartedAt`.
The pinned x402_treazury revision has no public typed endpoint-readiness signal;
the wrapper recognizes its two exact terminal endpoint diagnostic messages from
`deployment.rs` and `deployment/deferred.rs`. This is not a general log-severity
failure policy: recoverable native ERROR events do not fail activation. Recheck
those native messages and their semantics when changing the treasury pin, using
`tests/endpoint_readiness_smoke.py`. Replace this recognition when a native typed
signal provides equivalent behavior; do not add historical-message compatibility
parsers. The observer and read-only authenticated probes add no treasury state.
Closing the controller's input pipe cancels the remote probe, including when the
controller exits unexpectedly. Protocol waits remain cancellable without an
additional startup deadline. Reporting cadence is independent of failure policy.

The focused qualification workflow runs `python3 tests/bind_mount_smoke.py` on
each engine before the core and browser suites. It uses only networkless,
disposable project containers and public fixtures, proving missing required
sources are refused without directory/container/network creation while existing,
overridden and unrelated offline jobs remain usable. Run `make webapp-test` and
`make webapp-live-test` serially: the former concentrates UI/ingress boundaries,
the latter retains public Tor image/outage/recovery evidence. See the
[webapp test matrix](webapp.md) for retained cross-browser coverage.

Native Podman controlled browser assertions passed after the matrix reduction.
Teardown exposed a stopped profiled treasury container omitted by default Compose
`down`; Podman then refused its namespace owner's removal. Managed/wrapper down
and disposable teardown now include all profiles. The fixture helper reports
cleanup errors and fails otherwise successful tests while preserving an original
exception. A real stopped-profile/shared-namespace regression case is included in
`tests/launch_smoke.py`. Operator shutdown preserves volumes unless requested.


On 2026-11-13, corrections through `897f91a` passed qualification on
Docker Desktop ARM64 (Engine 29.9.3, Compose 5.7.0) and Debian 13 ARM64 rootless
Podman 5.4.2 (netavark/overlay, official Compose 5.1.4). The installed VM provider
was retained. Results on both engines include:

- Effective models/compilation, packaged-image checks, full TypeScript and 70 UI
  tests, and artifact-only builds under invalid disposable deployment settings.
- Cold/dry-run and profiled namespace cleanup; real SSH/Python placement,
  forbidden paths, selected MCP grants and Tor outage/recovery.
- Named-volume storage, locks, migration and cleanup; authenticated image/socket
  policy; editable research policy; endpoint errors/readiness/cancellation;
  context-reference and twelve desktop/browser policy combinations.
- Separate live authenticated Tor raster retrieval, exit-control and redirect
  counter evidence, outage/recovery; unfunded twelve-listener treasury/free API
  checks and catalog warming; native plugin install/update/dependency persistence.

All 159 unit tests, four effective models and compilation passed on both engines.
Final controlled three-browser content/ingress suites and cleanup passed on both,
including stale consent, policy mismatch, credential/ingress failures and staged
MCP activation. The corrected profiled-namespace cleanup has an actual-engine
regression test on both engines.
No blanket browser retries, increased browser deadlines, direct transport or
weaker TLS verification were added.

On 2026-11-13, a fresh independent final combined review accepted `1d46ce9`
against `main` `b46e050`, including corrections through `897f91a`, with no material
security or reliability findings. The reviewer traced engine selection/endpoint
normalization, network preparation, dry-run operands, bind checks, maintenance
and treasury consumers, shutdown, browser containment and qualification fixtures.
It independently passed 54 focused tests (8 bind, 42 engine, 2 TLS bridge and
2 CONNECT), passed `git diff --check`, and inspected the successful Docker and
native Podman qualification logs and matching VM checkout. Full runtime suites
were not repeated for the unchanged reviewed snapshot. G2 is accepted for the
qualified lean deployments on Docker Desktop ARM64 and Debian 13 ARM64 rootless
Podman. The completed plan was removed under the planning workflow; Git history
retains its design and review evidence.

At that reviewed revision, Podman executor computer/browser tools were refused
because of seccomp profile delivery; operator webapp/browser qualification is a separate capability. Live
Funnel, provider attestation, funded settlement and other platforms remain
unqualified. Existing Docker optional-executor evidence remains historical and
was not rerun for this host-helper/fixture correction.

Final self-review also reproduced a native dry-run parsing ambiguity:
`up --no-attach --dry-run -d SERVICE` launches for real because the apparent flag
is an option value. The wrapper now consumes value options before interpreting
flags; dry-run still validates supported creation commands, and service names are
forwarded after `--`. Unit tests exercise both engines' preparation/refusal, and
actual-engine probes verify missing-bind refusal plus genuine global dry-run
preservation with flag-like operands. This correction was included in the final
independent combined review.

The final resource audit found no current-run qualification containers, networks
or volumes on either engine. Two older Docker webapp fixture volumes dated
2026-11-09 were preserved; they predate this run and are absent from the current
model. Normal deployment state and unrelated resources were preserved.

Qualification does not extend to Linux Docker, AMD64, other distributions/kernels,
Compose 2.36–2.39 or arbitrary provider/engine combinations. Additional targets
need native allowed/forbidden-path and lifecycle evidence. The earlier
custom-profile Podman desktop model required a delivery mechanism
preserving its selected policy; neither native bind enforcement nor seccomp
delivery was fixed by upgrading the stock Compose provider. The current desktop
instead uses the native Podman policy as described below.


## Seccomp delivery investigation

On 2026-11-13, source `dd2d30d` was investigated on the same Debian 13 ARM64
rootless Podman 5.4.2 VM. This tests delivery, not desktop/browser support. The
existing `components/executor/seccomp-desktop.json` loaded successfully through:

- Native `podman run --security-opt seccomp=/absolute/host/path/profile.json`.
- Direct Docker-compatible API creation with
  `HostConfig.SecurityOpt: ["seccomp=/absolute/host/path/profile.json"]`.
- Native Libpod API creation with `seccomp_profile_path` set to that host path.

All three routes ran a networkless, read-only executor-image probe as UID 10000,
with all capabilities dropped, no-new-privileges enabled and seccomp mode 2.
A separate copy of the required policy denied an otherwise permitted syscall
with errno 77; every route enforced that canary. Every route also refused a
missing profile rather than using a default. No application state or engine
socket was mounted into a container.

The incompatibility is specifically stock Compose's encoding, not Podman's
ability to apply the policy. Official Compose 5.1.4 still failed with both
`seccomp=path` and `seccomp:path`: it inlines JSON for both forms, which Podman
interprets as a filename. The
[Compose implementation](https://github.com/docker/compose/blob/v5.1.4/pkg/compose/create.go#L433-L465)
and [Podman path field](https://github.com/containers/podman/blob/v5.4.2/pkg/specgen/specgen.go#L396-L408)
explain the difference.

An isolated `podman-compose` 1.6.0 installation successfully delivered the exact
policy and enforced the denial canary; it also refused a missing profile.
It is not a drop-in provider for this stack: `config --format json` is unsupported,
and a disposable service declaring `stop_grace_period: -1s` received a stored
10-second timeout. A correct Docker-compatible API control with `StopTimeout: -1`
stored unsigned maximum, matching the previously qualified unlimited setting.
The alternate provider's broader lifecycle, namespace and isolation behavior was
not qualified. The configured official Compose provider was left unchanged.

These results establish working primitives for a native executor-creation helper
or a narrow API translation helper that turns Compose's inline policy into a
server-readable filename. Neither integration is implemented. The latter could
retain Compose lifecycle ownership, but would need correct HTTP streaming/upgrade
handling and policy-file lifetime; native creation must preserve dependency,
health, recreation and shutdown behavior. Patching/upstreaming one side's policy
encoding is another option. Global default-policy changes were not tested or
applied, since the desktop policy must not become the default for other services.
Podman's [experimental image-label policy selection](https://docs.podman.io/en/v5.4.2/markdown/podman-run.1.html)
also requires a native policy-selection option; it was not qualified as a stock
Compose solution.

All probe containers/projects were removed, and existing deployment state was
preserved. The probes do not establish Chromium's nested sandbox, desktop
operation, SSH lifecycle or Tor/forbidden-path behavior for the desktop image.
At that investigation stage, the Podman computer/browser refusal remained in place.

A subsequent comparison used the VM's selected default profile at
`/usr/share/containers/seccomp.json`, not `seccomp=unconfined`. Both default and
custom profiles ran with seccomp mode 2, UID 10000, no capabilities and
no-new-privileges. Both permitted an isolated child to create a user namespace,
and both let an invalid-FD `setns` call reach kernel validation. The policies are
nevertheless different:

| Harmless probe | Desktop profile | VM Podman default |
| --- | --- | --- |
| Invalid `keyctl` operation | EPERM from the syscall filter | EOPNOTSUPP from kernel validation |
| Invalid `clone3` arguments | ENOSYS, preserving the selected fallback contract | EINVAL from kernel validation |
| Invalid `io_uring_setup` arguments | EPERM | ENOSYS |
| Invalid `bpf` operation | EPERM | EPERM |

The profile files confirm that the custom policy blocks `keyctl` and `clone3`,
while the VM default permits them at the syscall-filter layer. Both block
io_uring and retain capability/kernel restrictions. Dropping only the custom
profile therefore retains container seccomp but changes its allowed kernel attack
surface; it does not establish equivalent security. Podman's default is already
the lean executor's policy. The subsequent qualification below demonstrates Chromium's namespace sandbox
and the accepted native engine policy without a translator.
Disabling seccomp or Chromium's sandbox is not that alternative.

A separate lifetime probe created a container through the compatible API with a
filename-based denial canary, deleted that file after successful creation, and
started the same container twice. Both starts retained the enforced canary. This
supports temporary profile files on the tested Podman 5.4.2; it does not qualify
other versions or an API proxy implementation.


## Native Podman desktop support

Rootless Podman uses its native default seccomp policy for both lean and desktop
executors. Docker retains the pinned Moby-derived desktop profile described
above. The operator accepted the engine-specific native baseline after the
experiment at `c7eabe9`; policy equivalence is not claimed. Both retain active
seccomp, no-new-privileges, Chromium's namespace/seccomp sandbox, the existing
SSH bounding set, zero-capability runner children and the same Tor/private-state
boundaries. No translator, provider patch, extra capability or operator setting
was added.

The normal Podman overlay replaces the executor's inherited custom security
options with no-new-privileges and disables tmpfs copy-up for /tmp and /run.
This keeps their modes/destinations and matches Docker's empty mounts: Podman's
image copy-up otherwise exposes upstream's UID-1000 runtime directory to runner
UID 10000 and prevents SSH startup. See Podman's
[tmpfs mount options](https://docs.podman.io/en/v5.4.2/markdown/podman-run.1.html).
Preflight accepts the normal Podman desktop model; unsupported custom file
profiles supplied through Compose still receive a targeted delivery diagnostic.

Use the standard fixtures with either engine. Stop a normal deployment first;
fixed-subnet qualification projects must not overlap. On Podman select the user
socket and official Compose provider described in the README, then run:

```sh
CONTAINER_ENGINE=podman make computer-use-test
CONTAINER_ENGINE=podman make browser-use-test
CONTAINER_ENGINE=podman python3 tests/desktop_startup_smoke.py
CONTAINER_ENGINE=podman COMPUTER_USE_ENABLED=true WEBAPP_BROWSER_PYTHON=/path/to/browser-test/python python3 tests/webapp_smoke.py --browser-only
```

The Make targets build the normal desktop image and preflight the same enabled
model their runtime fixtures use. No experimental security overlay or trial tag
is involved. The webapp phase needs installed Playwright browsers/dependencies;
it covers local and simulated HTTPS desktop/browser results, without enrolling
Funnel, calling inference or performing paid research. Core checks also verify
the Compose-created runner's zero process capabilities, NNP 1 and seccomp 2.
Serialize core, browser, webapp and lean runtime fixtures on each host.

The earlier experiment on Debian 13 ARM64 rootless Podman 5.4.2, stock Compose
5.1.4 and Chromium 156.0.8078.4 passed actual Chromium namespace/PID/network/
seccomp-BPF diagnostics and nested-root parent-network setns/raw-socket denial.
The inherited SETUID/SETGID/SYS_CHROOT bounding set matters: removing SYS_CHROOT
at container creation makes Podman's default filter deny Chromium's namespace
chroot even after user-namespace setup; runner effective/permitted/inheritable/
ambient capabilities remain zero. The experiment also passed actual SSH GUI
capture/click/type/key/scroll, leases/idle/reconnect, main browser interaction,
cancellation/owner death, Tor/forbidden-path/MCP checks, outage/recovery and
local/simulated HTTPS authenticated transport/results on the qualified engines.

Recreation qualification exposed stale Chromium coordination tied to the previous
container hostname/PID. Startup now unlinks only SingletonLock, SingletonSocket,
SingletonCookie and DevToolsActivePort as runner before SSH accepts sessions.
Profile/cookies/credentials and unrelated data persist; removal is nonrecursive,
does not follow symlink targets, and unexpected errors fail visibly. No lock
removal occurs during ordinary browser launch. Both engines passed networkless
preservation/error controls, main browser/sandbox/missing-harness restoration and
on/off/on real cookie/localStorage/SSH-identity/workspace persistence. The retained
failed Podman profile also recovered. Fresh design and final independent reviews
accepted that correction and experiment through `c7eabe9`. Earlier logs remain
under `/tmp/private-hermes-podman-default-desktop-*` and
`/tmp/private-hermes-desktop-startup-{podman,docker}*` on their respective hosts.

Qualification exposed a short positive-control connection budget: 3s truncated
DNS/circuit/TLS establishment (one measured native request needed 4.049s for TLS),
while DNS allowed two 5s attempts. Positive public curl controls now use 30s
establishment/90s total, retaining the envelope used by the earlier browser probes. Forbidden
and outage probes keep their 3s/35s budgets, transport and exact assertions.
Original DNS/timeout/TLS-EOF failures are retained in qualification logs.

Browser and webapp fixtures avoid duplicating public Tor HTTPS requests: the
model process must share the independently observed executor network namespace,
reach its existing localhost HTTP fixture, and fail the unchanged private-peer
probes. Core independently proves public IsTor for that namespace, UID 101 and
Tor outage/restart. Its browser worker must observe the real outage and recover
in that same namespace. This retains unique network/placement evidence without
retrying browser actions or adding a DNS/TLS retry framework. Authenticated local
and simulated HTTPS display/results remain separately qualified.

Normal-path adoption qualification passed on both actual providers: 160 unit
tests, all effective models and compilation; normal desktop-enabled preflight,
full computer/core checks including Tor/UID-101/outage/restart, main browser,
namespace/sandbox/cancellation/recreation, networkless startup preservation and
local/simulated HTTPS authenticated desktop/browser results. Podman also passed
full lean core after restoring the normal lean tag, qualifying its newly explicit
empty tmpfs behavior. Docker's custom profile remains selected and its lean tag
was restored. No experimental overlay or trial image tag was used.

Final logs on each respective host are
`/tmp/private-hermes-podman-adoption-{docker,podman}-computer-final.log`,
`-browser-final.log`, `-webapp-final.log` and `-startup.log` (native final startup
uses `-startup-final.log`). The VM also retains
`/tmp/private-hermes-podman-adoption-podman-lean.log` and its successful qualified
batch exit status. Original DNS/connection/TLS failures remain as diagnostic
logs; an obsolete run was stopped and its disposable state cleaned when the
final fixture snapshot changed. Successful final runs supply acceptance evidence.
Final resource audit found no current qualification containers, networks or
volumes on either engine. Operator state, the stopped normal Docker treasury
container, the unrelated VM network and two older Docker fixture volumes were
preserved. A fresh independent final combined review accepted the identified implementation,
fixtures and documentation snapshot on `288c769`, with no material findings or
compelling simplifications. It independently inspected both engines' normal-path
runtime logs, provider/unit/model evidence and matching VM source hashes, and
passed 43 focused engine tests, local-link inspection and `git diff --check`.
The completed adoption plan was removed under the planning workflow; Git history
retains its design. Native Podman desktop support is accepted for the qualified
scope below.
Qualification remains limited to the tested Docker Desktop ARM64 and Debian 13
ARM64 rootless Podman setup. Other kernels/distributions/architectures, live
Funnel, provider attestation and funded settlement remain outside this evidence.

## Code terminal qualification

The ordinary WebApp terminal defaults to the SSH executor; `agent` retains the
native local shell. Implementation is the pinned `0008-code-terminal.patch` plus
`components/hermes/code_terminal.py`. The shared native `resolve_argv` remains
unchanged because saved gateway terminals use it for their local environment.
Remote cwd preparation runs before the registry spawn lock; it does not serialize
unrelated lifecycle work behind an SSH probe. No native session limits change.

`make check` includes strict mode parsing, Hermes-only effective Compose mappings
for Docker/Podman overlays, remote cwd path data and agent preparation without SSH
readiness. `make hermes-ui-test` includes terminal transport, saved gateways,
mode-specific local-tab restoration, cwd whitespace persistence and native terminal
session tests, plus the renderer TypeScript check.

`make webapp-test` uses production images and the native entrypoint with disposable
identities. Its terminal checks cover both modes over local and simulated HTTPS,
placement and backend-file parity, identity/mount separation, remote cwd/file
parents and shell metacharacters, replay/reattach, resize, Ctrl-C, explicit close,
SSH identity/host-key failures, executor outage and fresh-shell recovery. Mode
changes use ordinary Compose reconciliation to demonstrate serving recreation.
For focused reruns, use the same browser environment with
`python3 tests/webapp_smoke.py --terminal-only`. Repeat with
`COMPUTER_USE_ENABLED=true` after building that executor to cover desktop SSH shell
behavior; this focused option avoids unrelated desktop/browser/content suites.

On 2026-11-14, qualification covered Linux ARM64 images on these targets:

| Runtime | Lean executor | Desktop executor |
| --- | --- | --- |
| Docker Desktop 29.9.3 / Compose 5.7.0 on macOS ARM64 | Full `make webapp-test` passed | Six focused terminal cases passed |
| Debian 13 ARM64 rootless Podman 5.4.2 / Compose 5.7.1 | Full `make webapp-test` passed | Six focused terminal cases passed |

Each terminal lane exercises Code→Agent→Code over local and simulated HTTPS,
including ordinary environment-change recreation. `make check` passes 172 tests,
four effective models and compilation on both engines. Renderer TypeScript and
147 tests passed in the disposable Docker build stage; both engines built the
same pinned patched frontend/runtime. A final networkless native-image probe
checks captured profile-home ownership across a remap and unchanged saved-gateway
metadata. Nine relevant public source/test hashes match the native Podman checkout.
A fresh independent combined review accepted implementation `86d4a81` and
corrections through `2d2b5bd` against baseline `3fb1881`, with the maintained
evidence above and no remaining material findings. Review inspected source and
recorded results without rerunning suites. All current fixture containers,
networks and volumes were removed on both engines; two unrelated Docker fixture
volumes created on 2026-11-09 were preserved.

The native PTY requirements are demonstrated daemon grants: shared CHOWN for PTY
ownership, and desktop-only AUDIT_WRITE for Debian OpenSSH audit submission.
Networkless probes and both engines’ production desktop fixtures confirm
the latter; no AUDIT_CONTROL or new network grant is supplied. Interactive and
model runner commands retain empty effective/permitted/inheritable/ambient sets
under no-new-privileges. Existing network/Tor and GUI sandbox evidence above is
reused where its implementation is unchanged; these terminal checks additionally
exercise denial of agent inference, MCP, ingress and private destinations.

Disposable VM source exports use `git -c tar.umask=0022 archive` so tracked SSH
config retains normal 0644 permissions; default archive group-write modes are
correctly rejected by native OpenSSH system-include checks.
Identity-failure fixtures use the networkless setup mount, preserving private key
bytes without printing them and respecting rootless bind ownership. Model-tool
probes run as UID 10000, matching the serving Hermes process. Explicit close
checks ordinary shell/foreground-child cleanup; intentionally detached jobs and
survival across backend/executor restart are not promised. Scope remains the
qualified ARM64 targets and Chromium terminal checks; unrelated GUI and browser
harness suites were not repeated for shell placement.
No live Funnel enrollment, paid research, funded-wallet operations or inference
provider attestation is part of these terminal fixtures.
