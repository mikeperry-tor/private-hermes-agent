# Development and qualification

For operator setup, see [the README](../README.md). For network design and
execution boundaries, see [architecture and isolation](architecture.md). Read
[AGENTS.md](../AGENTS.md) before changing the stack, and follow the
[planning workflow](planning-workflow.md) for substantial staged work.

## Repository layout and build behavior

- `components/`: tracked Dockerfiles, container scripts, and component defaults.
- `.env`: private operator settings, explicitly mapped per service (add new
  settings to `.env.example`; keep image and source pins in Compose and
  Dockerfiles).
- `config/`: private editable bind-mount configuration, initialized from
  defaults.
- `data/`: persistent bind directories for identities and executor work.
- `scripts/`: host-side initialization, lifecycle, and check helpers.
- `tests/fixtures/`: test servers and fixtures.

### Build and policy-diff behavior

- `make init` creates missing local configuration while preserving existing
  files.
- `make up` runs `make init`, builds images (using engine caching) for enabled
  services and `x402_treazury`, runs offline `setup`, and starts services.
  `x402_treazury` is always built because its image supplies the default
  research policy.
- `make x402_treazury-prepare` builds only the `x402_treazury` image before
  checking preparation history or stopping services.
- Build failures abort before runtime state changes. The container engine owns
  build caching; no extra freshness markers are stored.
- `make build` builds images only (no state initialization or policy
  validation). Inspection, backup, and shutdown never trigger builds.
- `make up` and `make x402_treazury-prepare` print an advisory diff comparing
  saved `config/x402_treazury/research_desk.toml` against the built image's
  rendered default (using a networkless container with no private mounts).
  `make x402_treazury-config-diff` runs the same comparison standalone without
  building or seeding and exits nonzero on inspection failure. See
  [editing research configuration](x402_treazury.md#edit-the-research-configuration).

Hermes and wallet databases use named volumes (`hermes-data` and
`x402_treazury-data`), while Tor socket IPC uses a runtime named volume. See
[configuration and backups](configuration.md) for the full storage layout.

## Qualification and maintenance

```sh
make check
make test
```

Stop any running deployment before running live test targets: tests reuse the
pinned stack subnets, and preflight rejects overlapping subnets before creating
resources.

### Preflight checks

Every network subnet is pinned in `compose.yaml` (and `compose.funnel.yaml` for
Funnel), and preflight rejects networks that omit a subnet. If a subnet overlaps
another stack or an existing network has a mismatched subnet, preflight exits
with instructions, including configuring Docker's `default-address-pools`
(`~/.docker/daemon.json` or Docker Desktop Engine settings) or Podman's
`default_subnet_pools` (`containers.conf`) when the overlap came from automatic
allocation.

During `make up`, preflight also checks `TEEP_HOST_PORT`, `WEBAPP_BIND`, and
`WEBAPP_PORT` for duplicate stack bindings or host port conflicts. Test targets
pass `--skip-ports` so they check fixed subnets without probing operator `.env`
ports that test overlays do not bind.

### Core unit and smoke suites

Run tests against each engine by setting `CONTAINER_ENGINE=docker` or
`CONTAINER_ENGINE=podman` (no `.env` edit needed). Tests always use isolated
project volumes and temporary bind directories, never operator data.

- **`make check`:** Validates Docker and Podman Compose models, Python syntax,
  and unit tests without requiring initialized operator state (`tests/test_bind_sources.py`
  covers bind-source checks; `tests/test_engine.py` covers engine selection,
  version floors, `stack.py compose` flag parsing, Podman network creation, and
  proxy firewall rules without a running engine).
- **`make test`:** Runs the full live stack in a temporary project using the
  pinned Hermes image, SSH executor, Tor, Teep (dummy key), and `x402_treazury`
  (unfunded fixture wallet). Covers SSH terminal and Python execution, secret
  separation in the executor, Tor vs. Teep egress, blocked host, VM, RPC, and
  private targets, Streamable HTTP MCP with SSE, blocked unselected ports, and
  Tor outage behavior.
- **`python3 tests/bind_mount_smoke.py`:** Networkless check confirming missing
  required bind sources fail before creating directories, containers, or
  networks while valid, overridden, and unrelated offline jobs still run. Run on
  each engine before core and browser suites.
- **`python3 tests/launch_smoke.py`:** After building Hermes, verifies cold
  passthrough runs, dependency and owner network creation, truly offline runs,
  rejected maintenance overrides, `--dry-run` handling, Podman `isolate=strict`
  inspection, and network cleanup. Serialize with fixed-subnet tests.
- **`make podman-paths-test`:** On Podman only, verifies allowed and forbidden
  paths of a running stack, including isolation from a client on a non-isolated
  Podman network, with positive controls for DNS, TCP, and host loopback.
- **`tests/capability_bootstrap.py`:** Networkless Hermes privilege probe in a
  temporary volume testing s6 supervision, profile registration, warm permission
  repair, CLI, and clean stop. Supports `--omit GRANT`, `--probe-path`,
  `--expect-closed`, and `--path` to verify required capabilities and `PATH`
  ordering; cleans up its container and volume on exit.
- **`make webapp-test` and `make webapp-live-test`:** Run serially.
  `make webapp-test` covers UI, auth, terminals, and content containment;
  `make webapp-live-test` verifies live Tor image retrieval, outage, and
  recovery. See [webapp verification and qualification](webapp.md#verification-and-qualification).

### Handling shared-namespace interruptions in tests

Keep `agent-net` and `executor-net` running while their application containers
exist. Restarting only a namespace owner leaves attached containers stranded on
Docker and is unsupported on Podman (see
[failure behavior and shared-namespace restarts](architecture.md#failure-behavior-and-shared-namespace-restarts)).
If a test run interrupts a namespace owner, collect diagnostics and tear down
and recreate the whole test project rather than restarting the owner alone.
Tor runs in its own namespace, so Tor-only outage and restart tests remain
valid.

References:
[Hermes backends](https://hermes-agent.nousresearch.com/docs/user-guide/configuration/#terminal-backend-configuration),
[Hermes security](https://hermes-agent.nousresearch.com/docs/user-guide/security/),
[Dockurr Tor](https://github.com/dockur/tor),
[Docker isolated networks](https://docs.docker.com/engine/network/port-publishing/#gateway-modes),
and [Teep](https://github.com/13rac1/teep).

## Qualification status

Docker Desktop Linux ARM64 and Debian 13 ARM64 rootless Podman are the stack's
qualified targets. Compose model checks cover both engines but do not qualify
untested Linux Docker hosts, AMD64 runtimes, other distributions, or third-party
Compose providers.

| Qualified target | Engine and Compose provider | Filesystem and browser matrix |
| --- | --- | --- |
| macOS 26.7.1 ARM64, Linux `7.0.14-linuxkit` VM | Docker Desktop 29.9.3 and Compose 5.7.0 | Named volumes for Hermes and wallet databases; Playwright 1.64.1 (Chromium 156.0.8078.4, Firefox 157.0, WebKit 27.2) |
| Debian 13 ARM64, kernel `6.12.116+deb13-arm64` | Rootless Podman 5.4.2 (netavark, overlay) and official Docker Compose 5.7.1 | ext4 binds and named volumes; same Playwright browser matrix |

### Native Linux Docker checks

On Debian 13 ARM64:

- **Docker Engine 26.1.5** passes unit and Compose model checks, is rejected by
  preflight (minimum Engine 28), and leaves an internal bridge with a host-side
  IPv4 address even under `gateway_mode_ipv4=isolated`.
- **Docker Engine 29.10.0** passes `make check` and preflight, leaves isolated
  bridges without a host-side IPv4 address, and enforces default denial,
  executor denial, and literal LAN denial. Its default AppArmor profile blocks
  the `tor` gateway from enabling IPv4 forwarding for host-port grants. With the
  [gateway-scoped AppArmor profile](configuration.md#native-linux-docker-with-apparmor)
  under AppArmor 4.1, exact TLS host grants, ungranted socket and executor
  denial, gateway restart, and grant removal all pass while neighboring sysctls
  remain denied.

### Coverage boundaries

Outside this qualification: live Tailscale Funnel enrollment, live provider
attestation, paid inference or research calls, funded wallet settlement,
Electron browser privacy, and untested platforms and architectures. Building Tor
or Teep images does not verify live provider compatibility or attestation. For
treasury financial gaps, see
[pending live qualification](x402_treazury.md#pending-live-qualification).

- **HAProxy checks** cover authentication, exact-host enforcement, capability
  drops, fixed-backend egress, separate local, Funnel, and onion listeners, and
  proxy restart.
- **Offline Tailscale checks** cover missing enrollment keys, userspace daemon
  startup (`NeedsLogin`), and refusal to publish without an enrolled node map;
  they do not test live Funnel enrollment.
- **Browser vs. transport checks:** Controlled browser fixtures prove rendered
  bytes, consent, and request placement; socket and live Tor fixtures separately
  prove network destinations and Tor routing. Keep those proofs distinct when
  reusing evidence.

### Local inference and HTTP MCP

`tests/local_integration_smoke.py HOST_BIND LAN_ADDRESS` tests host-port and
literal LAN grants with temporary inference and MCP listeners while the pinned
subnets are free:

- On a rootless Podman VM, bind host listeners to the VM's reachable interface.
  Pass `--lan-ports ALLOWED DENIED` with a separate LAN peer when the engine
  cannot route to the VM's own literal LAN address.
- The script builds network and Hermes test tags unless `--no-build` is passed.
- Pass `--expect-lan-closed` on native Linux Docker to test default denial,
  host-port grants, and LAN denial using only the network image.

Qualified coverage on Docker Desktop 4.99.0 (Engine 29.9.3 / Compose 5.7.0) and
Debian 13 ARM64 rootless Podman 5.4.2 (Compose 5.7.1) includes:

- Original TLS SNI and HTTP `Host` preservation, independent positive controls,
  exact port and UID checks, executor denial, and denial of retained connections
  after grant removal.
- Clearing inherited and profile `HTTP_PROXY`, `HTTPS_PROXY`, and `ALL_PROXY`
  across profile reload, model discovery, streamed inference, MCP `initialize`,
  `list`, and `call`, and redirected `HEAD`, `GET`, and `POST` diagnostic
  boundaries.
- IPv4 path-MTU feedback for 64 KiB bidirectional transfers through a 630-byte
  bottleneck, LAN-only startup without a host mapping, gateway health when
  forwarding enablement is denied, local forwarding while Tor is suspended
  (Docker Desktop), and authenticated WebApp switching between Teep and a local
  provider (plus blank-`TEEP_INSTALL_MODEL` discovery in **Settings -> Model**).
- Lifecycle checks for `TEEP_ENABLED=false` (including malformed unused Teep
  settings and an occupied Teep uplink subnet), port and subnet conflict
  rejection when Teep is enabled, and preserving running containers during
  treasury init with a pending grant edit.

## Packaged Hermes qualification

The derived Hermes image builds from official Hermes v0.23.3
(`caafe5389ae585ef77387a962aee05b1bcf17029`, multiarch index
`sha256:3e9fe4c6ef36490f43aa0d0d80f9df64e9c92a576eee3042f1a97c8813c05355`). The
build verifies the ARM64 source stamp and renderer receipt against official
source hash `03efd94d420bfdd70ea477a985c14fc56574e265e6e1a0f6cf601a33d07ec8af`
and writes patched renderer receipt hash
`de3582b39cdfa7b69fb5dbf4958d3ee718ae0ed29198c7108af27df6e7e5834f`. See
[downstream responsibility inventory](updates-and-plugins.md#downstream-responsibility-inventory)
for the applied patches.

| Check or contract | Docker Desktop ARM64 | Rootless Podman ARM64 |
| --- | --- | --- |
| 197 wrapper unit checks, 4 Compose models, and compilation | Passed | Passed |
| Image build, source verification, and renderer receipt | Passed | Passed |
| Renderer TypeScript check and 218 targeted renderer tests | Passed | Passed |
| Managed URL-context and tool-denial matrix (including dotenv reload) | Passed | Passed |
| Populated official v0.23.2 profile loaded twice by v0.23.3 (schema 53 -> 54) | Passed | Passed |
| Full lean WebApp (Code and Agent terminals, auth, cross-browser content, MCP) | Passed | Passed |
| Desktop Code and Agent terminals over local and simulated HTTPS | Passed | Passed |
| Networkless desktop startup and Chromium lock-file cleanup | Passed | Passed |
| Executor browser, named tabs, ownership, cancellation, harness recovery | Passed | Passed |
| CUA display, takeover leases, sandbox, dependency loss, variant switching | Passed | Passed |
| Dependency-bearing user plugin install, update, and persistence | Passed | Passed |
| Authenticated image proxy, destination checks, and DNS controls | Passed | Passed |
| Repeated setup, offline CLI edits, SSH key repair, named-volume persistence | Passed | Passed |
| Live SSH execution, Teep and MCP grants, forbidden paths, Tor outage and recovery | Passed | Passed |
| Cold launch, maintenance scope, and namespace cleanup | Passed | Passed |
| Dedicated cross-browser image Save and Copy, and desktop viewer and download | Passed | Prior v0.23.2 evidence |

The v0.23.2 -> v0.23.3 migration check verifies preserved model and terminal
settings, preferences, transcript, and `.env`, auth, and plugin files in a
temporary named volume. Clipboard checks use a test sink, authenticated HTTPS
checks use simulated TLS, and Tor routing is verified separately. Live public
ingress, provider attestation, funded treasury actions, and AMD64 runtimes are
outside this table.

## Onion ingress qualification

- **`make onion-test`:** Runs with `DisableNetwork=1` and a test-only byte
  proxy into Tor's namespace (no descriptor published). Covers identity
  creation, retry, and repair, malformed-secret refusal, backup restore, exact
  host routing, login, refresh, and logout, WebSockets, origin-scoped image
  consent, forbidden paths, restart and outage recovery, and withdrawal. Passes
  on both qualified engines.
- **`make onion-live-test`:** Publishes a temporary authenticated onion service
  and connects through a separate Tor client for live rendezvous, login, and
  API access. Requires explicit public-network test authority and is excluded
  from `make check`. Recorded live rendezvous passes on both engines with Tor
  0.4.9.16 clients (reverify if Tor pin changes; bootstrap health alone does not
  prove reachability).
- **Browser testing:** Set `WEBAPP_BROWSER_PYTHON` (installed from
  `tests/requirements-browser.txt`) and optional `PLAYWRIGHT_BROWSERS_PATH`.
  Chromium consent checks supply Fetch Metadata explicitly for the fixture's
  HTTP onion origin. Local Tor Browser 15.0.26 (Gecko 140.17.0) checks against
  Docker cover native private-cookie partitioning and Fetch Metadata using
  explicit `TOR_BROWSER_PYTHON` (with Selenium), `TOR_BROWSER_BINARY`, and
  `GECKODRIVER` (no Selenium Manager auto-download; the test profile disables
  the bundled Tor launcher and inspects only cookie flags, never session
  values).

## Executor desktop qualification

For daemon capabilities and runner restrictions, see
[executor capability requirements](architecture.md#executor-capability-requirements).
Always test OpenSSH, PTY, or Chromium changes on both engines rather than
inferring behavior from Compose models.

Compose tags the lean and desktop executors separately
(`private-hermes-executor-false:local` and `private-hermes-executor-true:local`)
so both coexist cleanly. Direct `tests/*_smoke.py` scripts expect the matching
image to be built already; `make *-test` targets build first:

- `python3 tests/desktop_tools_smoke.py`: checks the `WEBAPP_EXTERNAL_CONTENT`
  x `COMPUTER_USE_ENABLED` tool-denial matrix.
- `make computer-use-test`: builds selected images and verifies desktop actions
  over SSH alongside Tor and forbidden-path checks (`tests/computer_use_smoke.py --desktop-only`
  isolates GUI checks while debugging).
- `python3 tests/desktop_startup_smoke.py`: runs the desktop startup script in
  a networkless read-only container with the SSH bounding set to verify
  non-recursive removal of stale Chromium lock files (`SingletonLock`,
  `SingletonSocket`, `SingletonCookie`, `DevToolsActivePort`), preservation of
  cookies, identities, and symlink targets, and refusal on unexpected
  directories.

### Docker seccomp baseline

Docker's desktop executor uses a checked-in Moby seccomp baseline (commit
`7b5ccfab2d6b4e0aa64c6cce401a2705788eafeb`,
[default.json](https://github.com/moby/profiles/blob/7b5ccfab2d6b4e0aa64c6cce401a2705788eafeb/seccomp/default.json),
license in `components/executor/seccomp-LICENSE`) with one added rule allowing
`clone`, `setns`, and `unshare`, keeping `clone3` returning `ENOSYS` and
blocking `io_uring`. Compose selects it via `compose.executor.yaml`; Podman's
overlay replaces it with Podman's default seccomp policy. Review the baseline on
engine upgrades and drop the custom file once Docker's default policy supports
Chromium's namespace sandbox without weakening other restrictions.

Desktop runtime support is qualified on ARM64; the pinned base image ships
AMD64 and ARM64 binaries, but AMD64 runtime remains untested.

### Browser harness and results

`make browser-use-test` verifies the executor browser harness: remote Python
and child-process execution (with the executor's clean launch environment and
per-task workspace), DOM interaction, navigation, typing, and downloads, named
and unnamed tabs (strict setup before model code, repinning after daemon
restart, preserved tracebacks and `__main__` globals), concurrent startup,
screenshots and vision, SSH cache sync excluding the live browser profile,
takeover refusal, cancellation, owner and daemon death, and missing-harness
recovery.

- Run manual probes as UID 10000; running `exec` as root can create install
  locks owned by root and break restart checks.
- Chromium diagnostics confirm user, PID, and network namespaces plus
  seccomp-BPF; root inside a nested user namespace cannot join the parent
  network namespace or open raw sockets there.
- Switching between lean and desktop executors preserves SSH identity,
  `/workspace`, cookies, and `localStorage` on both engines.
- Coverage is limited to one default-profile screen and programmatic display
  transport; concurrent profile screens, interactive noVNC pane testing, and
  `browser_cdp`, `browser_dialog`, and `browser_vault` are unsupported.

## Native Podman desktop support

Podman uses its default seccomp policy for both lean and desktop executors,
whereas Docker uses the pinned Moby-derived desktop profile. Both enforce
seccomp, `no-new-privileges`, Chromium sandboxing, and parent-namespace
isolation, but their syscall filters are not identical:

| Invalid-operation control | Docker desktop profile | Podman 5.4.2 native default |
| --- | --- | --- |
| `keyctl` | `EPERM` (filter) | `EOPNOTSUPP` (kernel) |
| `clone3` | `ENOSYS` | `EINVAL` (kernel) |
| `io_uring_setup` | `EPERM` | `ENOSYS` |
| `bpf` | `EPERM` | `EPERM` |

- `compose.podman.yaml` mounts empty `/tmp` and `/run` tmpfs directories with
  `notmpcopyup` so upstream UID-1000 files do not block runner UID 10000.
- Custom seccomp files are unsupported via Compose on Podman because Compose
  sends inline JSON while Podman expects a file path; preflight reports such
  overrides.
- Retain `SYS_CHROOT` on the desktop executor: removing it breaks Chromium's
  namespace chroot under Podman's default filter even though runner capability
  sets stay empty.

Run the desktop qualification commands on Podman (with Playwright installed and
other fixed-network stacks stopped):

```sh
CONTAINER_ENGINE=podman make computer-use-test
CONTAINER_ENGINE=podman make browser-use-test
CONTAINER_ENGINE=podman python3 tests/desktop_startup_smoke.py
CONTAINER_ENGINE=podman COMPUTER_USE_ENABLED=true WEBAPP_BROWSER_PYTHON=/path/to/browser-test/python python3 tests/webapp_smoke.py --browser-only
```

## Code terminal qualification

- **`make check`** verifies managed terminal settings and Hermes-only Compose
  mappings across Docker and Podman overlays.
- **`make hermes-ui-test`** runs terminal transport, saved-gateway,
  mode-specific tab restoration, exact `cwd` persistence, session tests, and
  TypeScript checks.
- **`make webapp-test`** tests Code -> Agent -> Code across local and simulated
  HTTPS on lean and desktop executors: placement parity, mount separation, `cwd`
  and file-parent validation (including Unicode, quotes, shell metacharacters,
  and trailing spaces), replay and reattach, resize, Ctrl-C, explicit close,
  mid-handshake tab close reaping the local SSH process, SSH key and host-key
  failures, executor outage, and fresh-shell recovery.
- For targeted terminal reruns, use
  `python3 tests/webapp_smoke.py --terminal-only` (lean executor) or with
  `COMPUTER_USE_ENABLED=true` (desktop executor).

When exporting repository archives to a test VM, use
`git -c tar.umask=0022 archive` so tracked SSH configuration keeps mode `0644`
as OpenSSH requires.

## Diagnostic messages

Error and status messages should name the operation or capability, its impact,
the cause or uncertainty, and a concrete next step in plain language without
forcing readers to decode internal stage names. Never include secrets, raw
protocol dumps, or credential-bearing upstream text.

Choose log severity at the layer that knows the final outcome after retries:

- **`ERROR`:** Required service or endpoint functionality is unavailable.
- **`WARN`:** A requested operation failed terminally or functionality degraded
  unexpectedly.
- **`INFO`:** Lifecycle, progress, or recovery milestones.
- **`DEBUG` / `TRACE`:** Routine retry attempts and diagnostic detail.

An intermediate retryable failure is not a terminal error, and elapsed time or
repetition alone does not raise severity. Scope errors to the failing capability
rather than declaring whole-stack failure, and when a financial outcome is
uncertain, state that clearly instead of implying a payment is safe to repeat.

### `x402_treazury` endpoint readiness observer

Because the pinned `x402_treazury` commit exposes no typed endpoint-readiness
event, activation follows container logs from `StartedAt` and recognizes only
the two exact terminal endpoint diagnostics from `deployment.rs` and
`deployment/deferred.rs` (recoverable `ERROR` log lines do not fail activation).
Reverify those messages with `tests/endpoint_readiness_smoke.py` whenever
updating the treasury commit, and replace log matching once upstream adds a
typed readiness signal. Closing the controller's input pipe cancels remote
probes immediately with no extra startup deadline.

## Local upstream candidate qualification

The `fork` remote ([mikeperry-tor/hermes-agent](https://github.com/mikeperry-tor/hermes-agent))
hosts the `stack-patches/v0.23.3/*` release refs, the original `upstream-pr/*`
qualification refs, and the active `fix/*` and `feat/*` submission branches. See
[local preparation package dispositions](updates-and-plugins.md#local-preparation-package-dispositions)
and [hermes-upstream-prep.md](plans/hermes-upstream-prep.md).

Candidate tests run inside temporary Docker Desktop Linux ARM64 containers
with isolated homes, `--init`, no engine socket, and no private mounts (using
`scripts/check` and containerized Python and Node toolchains). The release
replay targets Hermes v0.23.3 (`caafe5389ae585ef77387a962aee05b1bcf17029`), while
the active submission branches target `main`
(`88a1c1f4b19d1bc2b9fe8db870dee9ba0803fad5`, with the earlier `25a1302eacb563c59eb3b7454c1a53f8c89f274c`
base preserved for PR7).

| Candidate | Recorded passing checks | Scope |
| --- | --- | --- |
| PR1: managed configuration | Config and profile unit tests, and Docker and Podman managed-policy image fixtures | Strict reads, dotenv bootstrap and reload precedence, routed interpolation, secret ownership |
| PR2a: SSH workspace fixes | Sync and workspace tests, and packaged shell and HTTP checks | Browser-profile sync exclusion and missing-file `ENOENT` and 404 |
| PR2b: explicit SSH client config | SSH environment and config tests, and packaged shell checks | Pinned SSH client options across terminal, workspace, streams, and Doctor |
| PR3: executor desktop and browser | 224 Python tests, 6 desktop renderer tests, browser and SSH suites, live SSH Chromium checks | Cold executor discovery, viewer identity, warm CUA driver, named-profile RFB, raw CDP refusal, vault lease, scratch, screenshots, sandboxing |
| PR4: operator terminals and exact `cwd` | 80 Python tests, 95 terminal renderer tests, live SSH checks | Placement pinning, rollback refusal, Bash and `cwd` setup, startup wait, terminal ID acknowledgement, relay close, pinned trust |
| PR5: selectable URL context | 74 reference, gateway-turn, and config tests | Managed no-fetch in normal and bypass sessions, validated snapshots, malformed config handling |
| PR6: managed tool denial | 87 policy, MCP, and discovery tests plus prompt and worker persistence tests | CLI readiness, catalogs, prompt guidance, connectors, background review, direct and deferred schemas, dispatch enforcement |
| PR7: WebApp content privacy | Design review only | Shared renderer ownership and authenticated consent storage and API remain open |

### Limits and test ownership

- Native upstream suites cover duplicate dependency checks, browser ownership
  internals, and queued-action, lease, and cancellation regressions. Private
  Hermes keeps packaged stack checks for live SSH file `ENOENT` and 404, allowed
  and forbidden actions, takeover denial, HTTP file delivery, sandboxing,
  startup cleanup, terminal deployment modes, auth, and pinned keys, gateway
  URL no-fetch, the `desktop_tools_smoke.py` matrix, and all private raster and
  browser containment tests while PR7 is deferred.
- On the pristine `main` submission base in Linux ARM64 Docker, the full
  upstream suite has pre-existing container-environment failures (file modes,
  service management, Doctor checks, and two gateway profile copy tests
  outside this stack's executor-only contract). Focused candidate suites cover
  the changed code directly, and `tests/fixtures/session-resume-active-turn.json`
  supplies the fixture omitted from the runtime image (clearing inherited
  frontend output first avoids overlay `EXDEV` rename errors).
- PR4 Windows encoding tests do not qualify native Windows shell behavior.
  Native macOS and Windows runtimes, live providers, public ingress, OS
  clipboard integration, and financial operations are outside candidate
  evidence.
- Detailed follow-up logs and commit translations are stored locally in ignored
  `upstream_work/follow-up-review/`.
