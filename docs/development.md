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
- `make up` prepares host configuration, validates startup settings, builds
  images for enabled services and `x402_treazury`, runs offline `setup`, and
  starts services.
  `x402_treazury` is always built because its image supplies the default
  research policy.
- `make x402_treazury-prepare` builds only the `x402_treazury` image before
  checking preparation history or stopping services.
- Build failures abort before runtime state changes. The container engine owns
  build caching; no extra freshness markers are stored.
- `make build` builds images only (no state initialization or policy
  validation). Inspection, backup, and shutdown never trigger builds.
- `x402_treazury` uses its packaged image default unless an operator opts in to
  a local override with `make x402_treazury-config` (which creates
  `config/x402_treazury/research_desk.toml` and `.research_desk.toml.base`).
  When a local override exists and differs from an updated packaged default (or
  lacks a base snapshot), `make up` and `make x402_treazury-prepare` print an
  advisory notice at the end of startup (after `Research services prepared and
  connected to Hermes.`, or after pending-preparation and activation-error
  messages) using a networkless container with no private mounts.
  `make x402_treazury-config-diff`, `make x402_treazury-config-merge`, and
  `make x402_treazury-config-reset` run standalone offline without building and
  exit nonzero on inspection, merge, or validation failure. See
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

### Makefile test targets

`make help` (the default goal) lists user-facing commands plus the baseline
`make check`, `make test`, and `make webapp-test` targets. All development and
qualification `make` targets are indexed below; pass `CONTAINER_ENGINE=docker`
or `CONTAINER_ENGINE=podman` to select the engine without editing `.env`.

| Target | Scope | Owning details |
| --- | --- | --- |
| `make check` | Unit tests, `make help`, Docker and Podman Compose models, and Python compilation | [Core unit and smoke suites](#core-unit-and-smoke-suites) |
| `make test` | Isolated live stack (SSH executor, secret separation, Tor, Teep, and MCP) | [Core unit and smoke suites](#core-unit-and-smoke-suites) |
| `make webapp-test` | Isolated WebApp auth, Code and Agent terminals, and browser content containment | [WebApp verification](webapp.md#verification-and-qualification) |
| `make webapp-live-test` | Live public-network Tor image retrieval, outage, and recovery | [WebApp verification](webapp.md#verification-and-qualification) |
| `make onion-test` | Offline (`DisableNetwork=1`) onion identity, routing, auth, WebSockets, and recovery | [Onion ingress qualification](#onion-ingress-qualification) |
| `make onion-live-test` | Temporary live authenticated onion service and separate Tor client rendezvous | [Onion ingress qualification](#onion-ingress-qualification) |
| `make computer-use-test` | Desktop executor GUI actions over SSH, Tor routing, and forbidden-path checks | [Executor desktop qualification](#executor-desktop-qualification) |
| `make browser-use-test` | Executor browser harness, Chromium namespace sandboxing, named tabs, and recovery | [Browser harness and results](#browser-harness-and-results) |
| `make storage-test` | Named-volume and bind-mount persistence across `make down` and container restarts | [Persistent data layout](configuration.md#why-databases-stay-in-named-volumes) |
| `make x402_treazury-test` | Treasury image build, bearer-token auth, and MCP integration on an unfunded fixture | [Shutdown and testing](x402_treazury.md#shutdown-and-testing) |
| `make plugins-test` | Wheel-backed user plugin install, update, reload, and persistence | [Manage persistent user plugins](updates-and-plugins.md#manage-persistent-user-plugins) |
| `make images-test` | Isolated HTTP and TLS canaries for authenticated image proxy destination and DNS checks | [WebApp qualification](webapp.md#qualification) |
| `make hermes-ui-test` | Frontend TypeScript type-checking and renderer terminal, gateway, and session tests | [Code terminal qualification](#code-terminal-qualification) |
| `make podman-paths-test` | Allowed and forbidden network paths of a running stack on rootless Podman | [Core unit and smoke suites](#core-unit-and-smoke-suites) |

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

- **`make check`:** Validates Docker and Podman Compose models, `make help`,
  Python syntax, and unit tests without requiring initialized operator state
  (`tests/test_bind_sources.py` covers bind-source checks; `tests/test_engine.py`
  covers engine selection, version floors, `stack.py compose` flag parsing,
  Podman network creation, and proxy firewall rules without a running engine;
  `tests/test_makefile.py` checks default `make help` execution and target
  consistency).
- **`make test`:** Runs the full live stack in a temporary project using the
  pinned Hermes image, SSH executor, Tor, Teep (dummy key), and `x402_treazury`
  (unfunded fixture wallet). Covers SSH terminal and Python execution, secret
  separation in the executor, Tor vs. Teep egress, blocked host, VM, RPC, and
  private targets, Streamable HTTP MCP with SSE, blocked unselected ports, and
  Tor outage behavior.
- **`python3 tests/multi_instance_smoke.py`:** Launches two isolated checkouts
  concurrently with distinct `COMPOSE_PROJECT_NAME`, `NETWORK_PREFIX`
  (`10.205` and `10.206`), and host ports. Verifies independent SSH execution,
  Tor DNS configuration, Teep reachability, and WebApp authentication; verifies
  cross-instance bridge, proxy, executor, and Teep denial; verifies preflight
  rejection of overlapping `NETWORK_PREFIX`, host ports, cross-instance LAN
  grants, and reused project names; confirms stopping one instance leaves the
  other instance's containers, networks, volumes, and `<project>-*:local` images
  intact; and verifies offline onion identity creation, `NETWORK_PREFIX`
  migration (`10.205` to `10.207`) with onion ingress, host-port integration
  grants (allowed on engines permitting `ip_forward`, fail-closed otherwise),
  `stack.py chat`, and `x402_treazury` status, prefix detection, and private
  Tor SOCKS namespace isolation alongside the running second instance.
  Qualified on Docker (Docker Desktop and native Linux Docker 29.10.0) and
  rootless Podman 5.4.2.
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

### Project mount tests

The two-way sharing fixture covers both executor images on ARM64 macOS with
Docker Desktop (Docker Engine 29.9.3) and on ARM64 Debian 13 with native Docker
29.10.0 and rootless Podman 5.4.2. It passes with Docker Compose 2.36.0 and
5.7.1. Docker Desktop shares directories from APFS, and the Linux fixtures use
ext4 with POSIX ACLs. Creating a device node requires host permission, which
was unavailable on the test hosts. See
[native Linux Docker checks](#native-linux-docker-checks) for
the scope of the other native Docker checks. Project mounts on Docker Desktop
through WSL are unqualified.

Run `make check` for mount list and admission checks. To test read-write
sharing on your engine, build the executor images and run the scratch
projects:

```sh
COMPUTER_USE_ENABLED=false make build
COMPUTER_USE_ENABLED=true make build
python3 tests/project_mount_smoke.py
```

For rootless Podman, set `CONTAINER_ENGINE=podman` for the builds and the
test. Use `--variant lean` or `--variant desktop` for one image,
or `--compose-binary /path/to/docker-compose` to test another Compose
version. Linux requires `libacl.so.1` and a local filesystem with POSIX
ACLs. The test uses temporary projects and covers Compose path handling,
source checks, Git operations, two-way edits, and behavior after source
deletion. It prints the engine and Compose version and reports what the
engine does if the source disappears just before creation.

The managed startup test covers model file edits and instruction approvals
through CLI and WebApp chat, host access after WebApp editor saves, and
authenticated Code terminal writes. It also checks executor recovery
through `make up` and clearing all shares without shutting down the stack.
Stop stacks that use the fixed subnets before running the test.

```sh
python3 tests/project_mount_lifecycle.py --variant lean
python3 tests/project_mount_lifecycle.py --variant desktop
```

Use the Playwright environment from [WebApp verification](webapp.md#verification-and-qualification)
for chat, editor, and Code terminal checks. With `--skip-browser`, the test
skips those checks and still exercises chat through `make chat`. Pass `--prior-ref <local-git-revision>` to populate the
disposable checkout using an older wrapper before testing the in-place
upgrade. The scratch checkout uses the committed source at `HEAD` for the
new wrapper. The recorded upgrade fixtures cover the lean image on Docker
Desktop from `5131b69` and on ARM64 Debian 13 (native Docker 29.10.0 and
rootless Podman 5.4.2, ext4 with POSIX ACLs) from `a6a6f642` to `5605078`.

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

The derived Hermes image builds from official Hermes v0.23.4
(`8fc0374447313e276f6b9a2764bfc750190c966a`, multiarch index
`sha256:ef0650d523ee1b5ab32c779acabc446d9936869a9932591553688a62bcf0c42f`). The
build verifies the ARM64 source stamp and renderer receipt against official
source hash `b70656c6a129f5b4172aa6b388e1e8991a5301eeff8b4d0a3bf8d09aeff04801`
before applying the [downstream patches](updates-and-plugins.md#downstream-responsibility-inventory).
The packaged candidate patch (`0001-upstream-candidates.patch`, SHA-256
`a00e7af5e12012b242d61ac43dd8f2b53499d9f1971f861f42285f672461f1f4`) is exported
from `stack-patches/v0.23.4/combined` (`1cdcf6a54338c0f02b2a09f280a688ff20ad5ad7`).
Downstream patches `0002` through `0011` apply unchanged. See
[packaged release provenance](plans/hermes-upstream-prep.md#5-packaged-release-provenance)
for the local topic and replay record.

The table records the v0.23.4 cross-engine qualification matrix across macOS
Docker Desktop 29.9.3 ARM64, Debian 13 ARM64 native Docker 29.10.0, and Debian
13 ARM64 rootless Podman 5.4.2.

| Check or contract | Docker Desktop ARM64 | Native Linux Docker ARM64 | Rootless Podman ARM64 |
| --- | --- | --- | --- |
| `make check` (242 unit tests, 4 Compose models, compilation) | Passed | Passed | Passed |
| Lean and desktop image builds, source verification, and delivered renderer receipt (`tests/hermes_build.py`) | Passed | Passed (builds; receipt via shared image) | Passed |
| `make hermes-ui-test` (TypeScript and 296 Vitest renderer tests across 16 files) | Passed | Covered by shared build | Covered by shared build |
| `make test` (SSH execution, remote Python, Teep and MCP, forbidden paths, Tor outage) | Passed | Passed | Passed |
| `make webapp-test` (4 content modes across Chromium, Firefox, WebKit, Code and Agent terminals, stale-document restart, logout, and off, DNS canary, 12-endpoint MCP) | Passed | Passed | Passed |
| `make computer-use-test` (SSH desktop CUA, takeover leases, Chromium sandbox, idle stop, variant switching) | Passed | Passed | Passed |
| `make browser-use-test` (executor browser harness, Chromium namespace and seccomp layers, named tabs, recovery) | Passed | Passed | Passed |
| `make onion-test` (offline onion identity, corruption refusal, Chromium onion login, localhost and HTTPS, restart) | Passed | Passed | Passed |
| `make storage-test`, `make images-test`, `make plugins-test` | Passed | Passed | Passed |
| `tests/bind_mount_smoke.py`, `desktop_startup_smoke.py`, `desktop_tools_smoke.py`, `capability_bootstrap.py`, `project_mount_smoke.py` | Passed | Passed | Passed |
| `tests/project_mount_lifecycle.py --variant lean --prior-ref 4ce3e35` (populated v0.23.3 to v0.23.4 upgrade, classic, TUI, and WebApp browser) | Passed | Passed | Passed |
| `make podman-paths-test` (39 allowed and forbidden path checks on live stack) | n/a | n/a | Passed (39/39) |

Simulated TLS covers authenticated HTTPS checks, Tor routing is verified
separately from browser containment, and `make onion-test` runs offline with
`DisableNetwork=1`. Live public ingress, provider attestation, funded treasury
actions, and AMD64 runtimes are outside this table.

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
(`<COMPOSE_PROJECT_NAME>-executor-false:local` and
`<COMPOSE_PROJECT_NAME>-executor-true:local`, defaulting to
`private-hermes-executor-false:local` and `private-hermes-executor-true:local`)
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
- At local ingress, Chromium verifies that model reads follow the selected
  Code tab, checks the visible output and bounded scrollback, and confirms that
  requesting Agent output is refused. It also sends selected Agent output
  through **Add to chat**.
- For targeted terminal reruns, use
  `python3 tests/webapp_smoke.py --terminal-only` (lean executor) or with
  `COMPUTER_USE_ENABLED=true` (desktop executor).

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
hosts the `stack-patches/<release>/*` release refs, the original `upstream-pr/*`
qualification refs, and the active `fix/*` and `feat/*` submission branches. See
[local preparation package dispositions](updates-and-plugins.md#local-preparation-package-dispositions)
and [hermes-upstream-prep.md](plans/hermes-upstream-prep.md).

Candidate tests run inside temporary Docker Desktop Linux ARM64 containers
with isolated homes, `--init`, no engine socket, and no private mounts (using
`scripts/check` and containerized Python and Node toolchains). The active
release replay targets Hermes v0.23.4 (`8fc0374447313e276f6b9a2764bfc750190c966a`),
and the 11 upstream submission branches target `origin/main` at
`04be1bc06ba9fb3a7326679b0036bb65daaeda85`.
The [submission plan](plans/hermes-upstream-prep.md#1-branches-to-submit) records
the local submission branches and bases for all upstream candidate topics.

| Candidate | Recorded passing checks (`origin/main` `04be1bc06`) | Scope |
| --- | --- | --- |
| `W1-1`: managed configuration (`fix/managed-config`) | 22/22 `scripts/check`, 678 tests across 60/61 config and managed-scope files (1 pre-existing Docker mode failure), plus Docker and Podman managed-policy fixtures | Strict reads, dotenv bootstrap and reload precedence, routed interpolation, secret ownership |
| `W1-2`: SSH workspace fixes (`fix/ssh-workspace`) | 22/22 `scripts/check`, 904 Python tests across 24 files, `ui-tui` `tsc` and 27 Vitest tests | Browser-profile sync exclusion, missing-file `ENOENT` and 404, checkpoint host refusal, read baselines, search filtering, executor version and path checks before edits |
| `W1-3`: desktop and browser fixes (`fix/executor-desktop-browser`) | 22/22 `scripts/check`, 203 Python tests across 16 files, Desktop `tsc` and 6 Vitest tests | Dependency probe vs. screen liveness, active desktop and permission-mode pinning, Chromium ownership and restart recovery |
| `W1-4`: literal SSH and OSC 7 `cwd` (`fix/terminal-ssh-cwd`) | 22/22 `scripts/check`, 6 Python tests across 3 files, Desktop `tsc`, 25 UI and 117 Electron Vitest tests | Literal working-directory preservation across OSC 7, shell quoting, and SSH terminal launches |
| `W1-5`: speech output placement (`fix/tts-output-placement`) | 22/22 `scripts/check`, 16 TTS and CI tests, and Docker controlled audio probe | Profile cache placement, gateway audio attachments, and explicit internal playback destinations |
| `W2-1`: explicit SSH client config (`feat/ssh-client-config`) | 22/22 `scripts/check`, 45 tests across 5 files plus 6/6 Doctor `ssh_port` tests | Pinned `terminal.ssh_config` options across terminal, workspace, streams, and Doctor |
| `W2-2`: selectable URL context (`feat/url-reference-fetching`) | 22/22 `scripts/check`, 72 reference, gateway-turn, and CI tests | Managed `context_references.fetch_urls: false` in normal and bypass sessions, validated snapshots, fail-closed malformed config handling |
| `W2-3`: managed tool denials (`feat/managed-tool-denials`) | 22/22 `scripts/check`, 1,099 policy, prompt-refresh, fork, and MCP tests across 17/18 files (3 pre-existing Docker `test_doctor.py` failures) | CLI readiness, catalogs, prompt guidance, connectors, background review, direct and deferred schemas, dispatch enforcement |
| `W3-1`: executor desktop and browser (`feat/executor-desktop-placement`) | 22/22 `scripts/check`, 332 Python tests across 20 files, plus v0.23.4 live SSH desktop and Chromium E2E across all 3 engines | `browser.require_sandbox`, executor browser harness, managed `bot_desktop.executor_only`, owner binding, raw CDP refusal, vault lease checks |
| `W3-2`: operator shells and terminals (`feat/webapp-executor-terminals`) | 22/22 `scripts/check`, 180 Python tests across 14 files, Desktop `tsc` and 332 Vitest tests, `ui-tui` `tsc` and 7 Vitest tests | Placement pinning, viewer ownership, relayed `terminal.read` scoping, managed `!` shell and `shell.cwd` routing, TUI paste/queue/cancel, CLI reconnects |
| `W3-3`: managed SSH isolation (`feat/ssh-executor-isolation`) | 22/22 `scripts/check`, 391 Python tests across 35 files, 1,825 `tests/cron/` tests across 201/202 files (1 pre-existing Docker mode test), Desktop `tsc` and 46 Vitest tests, `ui-tui` `tsc` and 9 Vitest tests | Applied SSH write roots, project selection, context files, `@` references, `/init`, `/diff`, WebApp files and Git, delegation, Kanban, gateway media, remote Python `cwd`, project skills and inline shells, and managed cron execution |
| Combined 11-branch merge on `04be1bc06` | 22/22 `scripts/check` (448 files, 0 blocking), 534 cross-topic Python tests across 35 files, Desktop `tsc`, 384 UI and 117 Electron Vitest tests, `ui-tui` `tsc` and 43 Vitest tests | Full cross-wave compatibility check before upstream submission |
| Deferred: WebApp content privacy (`upstream-pr/webapp-content-privacy`) | Design review only | Shared renderer ownership and authenticated consent storage and API remain open |

### Limits and test ownership

- Native upstream suites cover duplicate dependency checks, browser ownership
  internals, and queued-action, lease, and cancellation regressions. Private
  Hermes keeps packaged stack checks for live SSH file `ENOENT` and 404, allowed
  and forbidden actions, takeover denial, HTTP file delivery, sandboxing,
  startup cleanup, terminal deployment modes, auth, and pinned keys, gateway
  URL no-fetch, the `desktop_tools_smoke.py` matrix, and all private raster and
  browser containment tests while WebApp content privacy remains deferred.
- On the pristine `main` submission base in Linux ARM64 Docker, the full
  upstream suite has pre-existing container-environment failures (file modes,
  service management, Doctor checks, and two gateway profile copy tests
  outside this stack's executor-only contract). Focused candidate suites cover
  the changed code directly, and `tests/fixtures/session-resume-active-turn.json`
  supplies the fixture omitted from the runtime image (clearing inherited
  frontend output first avoids overlay `EXDEV` rename errors).
- `W1-4` and `W3-2` Windows encoding tests do not qualify native Windows shell
  behavior. Native macOS and Windows runtimes, live providers, public ingress,
  OS clipboard integration, and financial operations are outside candidate
  evidence.
- Detailed Phase 5 verification logs are stored locally in ignored
  `upstream_work/wave-rebase-evidence/main/` (with prior `v0.23.4` logs in
  `upstream_work/wave-rebase-evidence/`).
