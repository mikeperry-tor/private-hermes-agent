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

## Qualification and maintenance

```sh
make check
make test
```

The live test uses a separate disposable Compose project with the actual pinned
Hermes image, the real SSH executor, real Tor, teep with a dummy provider
key, and the x402_treazury server with an unfunded fixture wallet. It performs no
inference or paid research calls. Stop a normal deployment before running it:
projects use the same fixed subnets, and preflight refuses overlaps. Every network
subnet is pinned in the `networks:` block of `compose.yaml` (`compose.funnel.yaml`
for the Funnel networks), and preflight rejects a network that omits one. If a
pinned subnet overlaps another stack's network, or a project network already exists
with a different subnet, preflight stops before changing anything and reports where
to edit the plan. When an overlapping network was allocated automatically, it also
points to Docker's `default-address-pools` (Docker Desktop > Settings > Docker
Engine, `~/.docker/daemon.json`) or Podman's `default_subnet_pools` in
`containers.conf`. Preflight also checks the declared host
publications (`TEEP_HOST_PORT`, `WEBAPP_BIND` and `WEBAPP_PORT`) during `make up`,
including duplicate or overlapping publications within the stack, and reports a
conflicting process or container before startup. Disposable test targets invoke
preflight with `--skip-ports` so they check the fixed subnets without probing
`.env` host ports that test overlays do not bind.

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

The focused qualification workflow runs `python3 tests/bind_mount_smoke.py` on
each engine before the core and browser suites. It uses only networkless,
disposable project containers and public fixtures, proving missing required
sources are refused without directory/container/network creation while existing,
overridden and unrelated offline jobs remain usable. Run `make webapp-test` and
`make webapp-live-test` serially: the former concentrates UI/ingress boundaries,
the latter retains public Tor image/outage/recovery evidence. See the
[webapp test matrix](webapp.md) for retained cross-browser coverage.

## Qualification status

Docker Desktop Linux ARM64 and Debian 13 ARM64 rootless Podman are the
stack's native qualification targets. See the packaged Hermes section for the
current release's coverage on each target. Effective Compose
models and source tests cover both engine paths; they do not qualify another
engine/provider/kernel/architecture combination. Linux Docker hosts, AMD64,
other distributions and arbitrary Compose providers need native evidence.

| Qualified target | Engine / provider | Filesystem / browser scope |
| --- | --- | --- |
| macOS 26.7.1 ARM64, Linux `7.0.14-linuxkit` containers | Docker Desktop 29.9.3 / Compose 5.7.0 | Native named volumes for Hermes/wallet databases; Playwright 1.64.1, Chromium 156.0.8078.4, Firefox 157.0, WebKit 27.2 |
| Debian 13 ARM64, kernel `6.12.116+deb13-arm64` | Rootless Podman 5.4.2, netavark/overlay / official Docker Compose 5.7.1 | ext4 binds and native named volumes; the same controlled browser matrix |

Live Funnel enrollment, provider attestation, paid research/inference, funded
settlement, Electron-wide browser privacy and untested platforms are outside
this qualification. Tor/Teep image build success does not establish live provider
compatibility. The Tor/Teep pin selection has no separate full compatibility or
attestation qualification. Treasury financial coverage is described in the
[treasury guide](x402_treazury.md#pending-live-qualification).

HAProxy ingress checks cover authentication, exact-host rejection, capability
handling, fixed-backend egress, separate local/Funnel listeners and proxy restart.
Offline Tailscale checks cover disabled/missing enrollment authority, userspace
daemon startup with `NeedsLogin`, and refusal to publish/reset forwarding without
an enrolled network map. They do not establish real enrollment or live Funnel.

Security and browser fixtures use public code, generated identities, disposable
state and controlled responses. Raster render/download checks establish bytes,
consent and request placement; socket and live Tor tests separately establish
destination and transport behavior. Preserve that distinction when reusing
results. The packaged integration has independent source and combined review within
these coverage limits.

## Packaged Hermes qualification

The packaged build derives from official Hermes v0.23.3 source
`caafe5389ae585ef77387a962aee05b1bcf17029`, multiarch index
`sha256:3e9fe4c6ef36490f43aa0d0d80f9df64e9c92a576eee3042f1a97c8813c05355`.
The build checks the official ARM64 source stamp and renderer receipt against
the official source hash
`03efd94d420bfdd70ea477a985c14fc56574e265e6e1a0f6cf601a33d07ec8af`.
The patched renderer's receipt records source hash
`de3582b39cdfa7b69fb5dbf4958d3ee718ae0ed29198c7108af27df6e7e5834f`.
The build incorporates four upstream candidates, their managed and SSH
prerequisites, and the remaining
[deployment patches](updates-and-plugins.md#downstream-responsibility-inventory).

| Check / contract | Docker Desktop ARM64 | Rootless Podman ARM64 |
| --- | --- | --- |
| 197 wrapper unit checks, four effective Compose models and compilation | Passed | Passed |
| Build, source delivery and native renderer receipt | Passed | Passed |
| Native TypeScript and 218 targeted renderer tests | Passed | Passed |
| Managed URL-context and tool-denial matrix with disposable profiles, including native dotenv reload | Passed | Passed |
| Populated official v0.23.2 profile opened twice by v0.23.3 | Passed | Passed |
| Full lean WebApp, including Code/Agent terminals, authentication, cross-browser content and native MCP activation | Passed | Passed |
| Desktop Code and Agent terminals over local and simulated HTTPS | Passed | Passed |
| Networkless desktop startup and coordination-file recovery | Passed | Passed |
| Executor browser, named tabs, ownership, cancellation, harness loss and recovery | Passed | Passed |
| CUA display, lease, sandbox, dependency loss and persistent executor switching | Passed | Passed |
| Native dependency-bearing plugin install, update and persistence | Passed | Passed |
| Authenticated image endpoint and connection destination controls | Passed | Passed |
| Repeated setup, native CLI edits, identity repair and named-volume persistence | Passed | Passed |
| Real SSH terminal and code execution, Teep/MCP grants, forbidden paths, Tor outage and recovery | Passed | Passed |
| Cold launch, maintenance scope and namespace cleanup | Passed | Passed |
| Dedicated cross-browser image Save/Copy and authenticated desktop viewer/download | Passed | Prior v0.23.2 evidence |

The migration check preserves model and terminal settings, selected operator
preferences, a stored transcript and saved env/auth/plugin files in a disposable
named volume. It establishes native schema 53 to 54 loading. The current
desktop and terminal fixtures use the same procedure on both engines.
Dedicated Save/Copy and desktop viewer fixtures cover exact downloaded bytes,
consent and request placement. Clipboard checks use a test sink.
The authenticated WebApp checks use simulated HTTPS, and Tor routing uses
a separate live network fixture. Live public ingress, provider attestation,
funded activity and AMD64 runtime remain outside these checks.

## Onion ingress qualification

`make onion-test` uses disposable Tor state, native HAProxy/Hermes and the actual
host-address target. Tor networking is disabled and a test-only byte proxy gives
the browser access into Tor's namespace; no descriptor is published. The fixture
covers identity retry/recovery, malformed-secret refusal, backup restore, exact
ingress, login/refresh/logout, WebSockets, origin-scoped image consent, forbidden
paths, restart/outage and withdrawal. It passes on both qualified engines.

`make onion-live-test` publishes a disposable authenticated service and uses a
separate native Tor client for real rendezvous, login and protected API access.
This requires explicit public-network qualification authority and is not part of
routine `make check` or the nonpublishing suite. Recorded live rendezvous coverage
uses Tor 0.4.9.16 clients on both engines; it does not establish live publication
for every later Tor pin. Bootstrap health alone does not establish reachability.
The client has a fixture deadline, not a deployment work deadline or fallback.

Select the explicit browser environment with `WEBAPP_BROWSER_PYTHON` and
`tests/requirements-browser.txt`; `PLAYWRIGHT_BROWSERS_PATH` may select a disposable
browser installation. Chromium consent tests supply Fetch Metadata explicitly
because stock Chromium does not send it for the fixture's HTTP onion origin.
Actual Tor Browser 15.0.26 (Gecko 140.17.0) coverage is local against Docker and
includes its native private-cookie partitioning and consent Fetch Metadata.

For Tor Browser, set `TOR_BROWSER_PYTHON` with Selenium, `TOR_BROWSER_BINARY` and
`GECKODRIVER` to explicitly installed local tools. The disposable profile disables
the bundled Tor launcher and uses the controlled SOCKS fixture; only cookie flags
are inspected, never session values. Direct driver selection bypasses Selenium
Manager and its default analytics; do not add automatic discovery as a fallback.
Browser semantics through this proxy are separate from live rendezvous evidence.

## Executor desktop qualification

The [architecture guide](architecture.md#executor-capability-requirements) owns
listener/PTY capability requirements and runner restrictions. Qualify changed
OpenSSH, account, PTY or Chromium requirements on each engine rather than inferring
runtime behavior from effective models. Runner effective, permitted, inheritable
and ambient capability sets remain empty under no-new-privileges.

The optional desktop build uses Debian rather than Alpine. Compose tags the
lean and desktop executor variants separately
(`private-hermes-executor-false:local` and `private-hermes-executor-true:local`),
so both images can coexist without a `--no-build` smoke run booting one variant
under the other's capability/seccomp profile. Direct `tests/*_smoke.py` runs
skip building and expect the executor image for the active
`COMPUTER_USE_ENABLED` value to be built already (or use the `make *-test`
targets, which build first). Run the packaged
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
an unexpected coordination directory. The same command uses the desktop executor
tag (`private-hermes-executor-true:local`) on both engines. The fixture supplies
no host keys, so native sshd must refuse after preparation; normal real SSH and
browser lifecycle checks remain separate.

The Docker desktop executor uses a checked-in Moby seccomp baseline from commit
`7b5ccfab2d6b4e0aa64c6cce401a2705788eafeb`, with one added allow rule for
`clone`, `setns`, and `unshare`. Source:
[default.json](https://github.com/moby/profiles/blob/7b5ccfab2d6b4e0aa64c6cce401a2705788eafeb/seccomp/default.json);
license: `components/executor/seccomp-LICENSE`. The profile is selected for
Docker's desktop variant by native Compose inheritance in `compose.executor.yaml`;
the Podman overlay replaces it with the native engine policy.
It retains the baseline's `clone3` ENOSYS behavior and does not allow io_uring.
Keep those unrelated syscall contracts intact when considering another profile.
Reconcile the baseline with engine updates. Remove Docker's custom profile when its native engine policy permits the qualified
Chromium sandbox without weakening unrelated syscall restrictions.

Enabling user namespaces exposes additional kernel paths to executor code; it
must not grant control of the parent network namespace or bypass Tor. Verify
those forbidden paths and the actual Chromium sandbox layers, alongside runner
capabilities, SSH failure/restart behavior and persistent state. Each engine and
CPU target requires native evidence; source/manifest inspection is insufficient.
See [native Podman desktop support](#native-podman-desktop-support).
Desktop runtime support is qualified on ARM64. The pinned image includes Linux
AMD64 and ARM64, and Chromium discovery supports both; AMD64 runtime remains
unqualified. The [rootless engine differences](architecture.md#rootless-podman)
record the engine-specific desktop policies; native operator
webapp/browser coverage is described in [packaged qualification](#packaged-hermes-qualification).


### Browser harness and results

`make browser-use-test` qualifies the pinned harness inside the executor. Its
native checks cover remote Python/child execution, DOM/navigation/type/download,
named/unnamed tabs, concurrent startup, screenshots/native vision, selected-cache
round-trip excluding the live browser profile, human takeover refusal,
active/startup cancellation, daemon/owner death and missing-harness recovery.
Strict named-tab setup precedes model code, preserves intentional selection,
repins after daemon restart, and retains traceback lines and `__main__` globals.

Run tool probes as Hermes/runner UID 10000. Root engine exec can create install
locks with the wrong owner and invalidate restart checks. Real Chromium diagnostics
confirm namespace, PID/network-namespace and seccomp-BPF layers. Nested namespace
root cannot rejoin the parent network namespace or create a raw socket there.
The harness adds no container capabilities, ports or network grants.

Executor switching preserves SSH identity, workspace, cookies and localStorage
on both qualified engines. Current authenticated local and simulated HTTPS
screenshot and download coverage is recorded in the [packaged qualification table](#packaged-hermes-qualification). Coverage is one active
default-profile screen and programmatic native display transport. Concurrent
profile screens are unsupported; full visual noVNC-pane interaction and other
profile arrangements remain unqualified. CDP/dialog/vault routes are excluded;
raw CDP through executor Python does not qualify those native tools.

## Native Podman desktop support

Podman uses its native default seccomp policy for lean and desktop executors;
Docker uses the pinned desktop profile above. Their policies are intentionally
different: both retain seccomp, no-new-privileges, Chromium sandboxing and parent-
namespace restrictions, but their allowed kernel syscall surfaces are not equal.
No translator, provider patch or unconfined mode is used.

The qualified Podman 5.4.2 default and Docker desktop profiles have these
syscall-level differences; active seccomp does not imply policy equivalence:

| Invalid-operation control | Docker desktop profile | Podman native default |
| --- | --- | --- |
| `keyctl` | EPERM from filter | EOPNOTSUPP from kernel validation |
| `clone3` | ENOSYS fallback contract | EINVAL from kernel validation |
| `io_uring_setup` | EPERM | ENOSYS |
| `bpf` | EPERM | EPERM |

The Podman overlay uses empty `/tmp` and `/run` tmpfs mounts via `notmpcopyup`,
preventing upstream UID-1000 files from blocking runner UID 10000. Custom file
seccomp profiles through the configured Compose API remain unsupported: Compose
inlines JSON while Podman expects a filename. Preflight reports those overrides.
Native Podman/API filename delivery can enforce a profile, but no custom-profile
creation helper or API translator is implemented or qualified for this stack.

Select the user socket and official Compose provider, stop other fixed-network
projects, and use the shared fixtures:

```sh
CONTAINER_ENGINE=podman make computer-use-test
CONTAINER_ENGINE=podman make browser-use-test
CONTAINER_ENGINE=podman python3 tests/desktop_startup_smoke.py
CONTAINER_ENGINE=podman COMPUTER_USE_ENABLED=true WEBAPP_BROWSER_PYTHON=/path/to/browser-test/python python3 tests/webapp_smoke.py --browser-only
```

The desktop test environment needs installed Playwright browsers/dependencies.
Native allowed/forbidden paths, actual Chromium sandbox layers, zero-capability
runner sessions, SSH GUI actions, leases, cancellation, owner death and recovery
are qualified on the targets in the status table. Removing SYS_CHROOT can break
Chromium's namespace chroot under Podman's native filter despite empty runner
capability sets; retain its demonstrated functional requirement.

Startup removes only SingletonLock, SingletonSocket, SingletonCookie and
DevToolsActivePort as runner before accepting SSH sessions. Unlinking is
nonrecursive, does not follow symlink targets, preserves profile/credential data,
and refuses unexpected errors. It does not run during ordinary browser launch.
Both engines' startup controls qualify preservation, refusal and real browser
state through container recreation.

Browser workers prove namespace placement, localhost fixture access, private-peer
denial and actual Tor outage/recovery. Core tests independently prove public Tor
routing for that namespace and UID 101. This avoids duplicate public requests
without retrying uncertain browser actions. Authenticated display/results need
separate browser assertions.

## Code terminal qualification

The ordinary WebApp terminal defaults to the SSH executor; `agent` retains the
native local shell. The candidate implements the native executor/gateway modes.
The stack maps its operator selections through managed WebApp settings and retains
local startup acknowledgement, labels and executor cwd validation. Native shell resolution supplies the
profile environment and resolves exact local paths. Saved SSH connections keep
their launch route.
Remote cwd preparation runs before the registry spawn lock; it does not serialize
unrelated lifecycle work behind an SSH probe. No native session limits change.
The startup socket owns its pending Code probe. After the browser acknowledges
the reattach token for a negotiated Code terminal, native retention owns the shell. An ordinary
transport loss still permits retry in the same tab.

`make check` covers the stack's managed terminal selections, tool matrix and
Hermes-only effective Compose mappings for Docker/Podman overlays. `make hermes-ui-test` includes terminal transport, saved gateways,
mode-specific local-tab restoration, exact cwd persistence and native terminal
session tests, plus the renderer TypeScript check.

`make webapp-test` uses production images and the native entrypoint with disposable
identities. Its terminal checks cover both modes over local and simulated HTTPS,
placement and backend-file parity, identity/mount separation, remote cwd/file
parents, shell metacharacters and literal local cwd, replay/reattach, resize, Ctrl-C, explicit close,
SSH identity/host-key failures, executor outage and fresh-shell recovery. The
connected-probe case holds the real remote cwd check and verifies local SSH
client reaping after closing the tab before metadata publication. Mode
changes use ordinary Compose reconciliation to demonstrate serving recreation.
For focused reruns, use the same browser environment with
`python3 tests/webapp_smoke.py --terminal-only` (after building the lean
executor) or with `COMPUTER_USE_ENABLED=true` (after building the desktop
executor) to cover lean and desktop SSH shell behavior; this focused option
avoids unrelated desktop/browser/content suites.


The terminal matrix runs Code→Agent→Code over local and simulated HTTPS,
including normal serving recreation, lean and desktop executors. See the
[packaged qualification table](#packaged-hermes-qualification) for current
engine results. Exact cwd/path
handling includes Unicode, quotes, shell metacharacters and trailing spaces.
Runner commands retain empty effective/permitted/inheritable/ambient capabilities
under no-new-privileges. Listener CHOWN owns PTY setup; desktop AUDIT_WRITE owns
Debian OpenSSH audit submission, without AUDIT_CONTROL or new network grants.

VM source exports use `git -c tar.umask=0022 archive` so tracked SSH configuration
retains mode 0644, as native OpenSSH requires. Identity-failure fixtures use the
networkless setup mount and preserve private key bytes without printing them.
Explicit close covers shell/foreground-child cleanup; intentionally detached jobs
and remote shell survival across executor restart are not promised. No live
Funnel, provider attestation, inference or financial outcomes are established.

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

## Local upstream candidate qualification

The `fork` remote holds the `stack-patches/v0.23.3/*` release refs and
`upstream-pr/*` submission branches once they are pushed. The tracked release
patch carries the reviewed v0.23.3 replay. See the [fork repository](https://github.com/mikeperry-tor/hermes-agent),
[candidate inventory](updates-and-plugins.md#local-preparation-package-dispositions)
and [retained preparation plan](plans/hermes-upstream-prep.md).

Qualification uses native pytest and renderer suites in disposable Docker
Desktop Linux ARM64 containers with isolated homes and `--init`, without an engine socket or
private mounts. Python/Node/development dependencies stay in containers; host
stdlib code may orchestrate fixtures. No host npm installation is required.
Native source checks use `scripts/check` with the declared base or a previously
qualified tree for focused follow-up changes.

| Candidate | Recorded passing checks | Behavioral scope |
| --- | --- | --- |
| PR1: executor desktop/browser | 224 focused native Python tests, 6 desktop status renderer tests, combined browser/SSH suites, and real SSH Chromium qualification | Desktop probes and cold executor discovery, viewer owner identity, warm CUA driver ownership, named-profile RFB, raw CDP refusal, browser attachment and retirement, named vault lease, scratch, screenshots, sandboxing and no replay |
| PR2: operator terminals and exact cwd | 80 focused native Python tests, 95 terminal renderer tests, and real SSH coverage | Gateway, profile and placement pinning, direct rollback refusal, Bash and cwd preparation, startup metadata wait, terminal ID acknowledgement and retention, relay close, pinned trust and repair |
| PR3: selectable URL context | 74 reference, gateway-turn and configuration tests | Managed no-fetch across normal and bypass sessions, one validated snapshot, inaccessible and malformed configuration, safe defaults, filter order and recovery |
| PR4: managed tool denial | 87 focused policy, MCP and discovery tests, plus combined prompt and worker persistence coverage | CLI readiness, tool catalog and generated guidance, connector results and policy relaxation, background review, coherent direct and deferred schemas, worker and prompt snapshots, and dispatch authority |
| PR5: Webapp content privacy | Design review only | Shared renderer ownership and authenticated consent authority/storage/API remain unresolved |

Baseline regressions confirm the affected failure paths at native entrypoints.
PR2 Windows command encoding tests leave native Windows shell lifecycle unqualified. Current qualification
covers Linux ARM64; native macOS/Windows runtime, live providers, public ingress,
OS clipboard integration and financial actions are outside this evidence.

Native suites own duplicate dependency and browser ownership mechanism tests.
Keep the packaged missing-file ENOENT/404 controls, which also cover real-shell
and HTTP delivery. PR1 also owns the
queued-action, lease, permission and cancellation regressions. Keep allowed
actions, takeover denial and recovery through real SSH, along with HTTP file
controls, image delivery, sandbox placement and startup on both engines.
PR2's deployment mode, stale-page, identity, authentication, pinned-key
and cross-engine tests remain until those paths are covered at stack entrypoints.
Keep packaged URL no-fetch checks for normal and bypass turns at the gateway
entrypoint, with a conflicting writable profile preference. The deployment
mode × desktop tool matrix is in `desktop_tools_smoke.py`. Retain all private raster and browser containment coverage while PR5 is
deferred. Separate candidate qualification from the stack's Tor, storage and
engine behavior.

The native webapp mirror needs the public `session-resume-active-turn.json` fixture.
Disposable inherited frontend output may need clearing before native publication
to avoid an overlay-filesystem EXDEV rename. These are build/test inputs, not
production repair steps. The Linux sandbox stop tests cover both original and
rewritten command lines and an unrelated process on a reused PID.

The [pinned release replay](plans/hermes-upstream-prep.md#v0233-build-provenance)
uses Hermes v0.23.3 source `caafe5389ae585ef77387a962aee05b1bcf17029`. The
[submission branches](plans/hermes-upstream-prep.md#1-branches-to-submit)
use the separate main revision `2de9f51b8008a7d49a49221c184f2f11cbfc4af1`.
Deployments and upstream submissions share strict managed configuration,
including reload precedence, ordered recovery from managed dotenv read errors
and routed subprocess interpolation.
Focused native checks exercise prompt and worker persistence, deferred review
tools, SSH trust and terminal ID acknowledgement, executor probes and warm
recovery, and URL settings in gateway and configuration-bypass turns.
The packaged runtime checks use the release replay.

The disposable native image has baseline failures in three Doctor checks
for Vercel, Chromium repair advice and the GitHub CLI. They reproduce on the
corresponding pristine bases. Managed tool availability in Doctor is covered.

The two broader real-profile copy-permission cases fail on the pristine native
base in the test image. They cover gateway real-profile behavior, outside the
stack's executor-only contract. The fixture covers ordinary native
real-profile selection and managed refusal of gateway browser launch.

Follow-up logs and exact commit translations are retained under ignored
`upstream_work/follow-up-review/`. Earlier evidence remains applicable to
unchanged inputs. Candidate dispositions and submission drafts are recorded in
the [maintained package inventory](updates-and-plugins.md#local-preparation-package-dispositions).
