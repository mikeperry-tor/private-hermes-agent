# Multi-instance deployment support

Status: proposed; independent design review and implementation are pending.
Working branch: `multi-instance-support`.
Starting commit: `66bd17fa0ce6fe32433e51ef7b9987703190a028`.
Plan path: `docs/plans/multi-instance-support.md`.
Follow [AGENTS.md](../../AGENTS.md) and [docs/planning-workflow.md](../planning-workflow.md).

## Agent handoff protocol

Before making changes, run these read-only checks to reconcile the checkout with
this plan:

```sh
git status --short
git rev-parse --abbrev-ref HEAD
git log --oneline 66bd17fa0ce6fe32433e51ef7b9987703190a028..HEAD
```

Skip any row in `### Execution checkpoints` already marked `Done` whose recorded
commit and validation summary match the checkout. Do not re-run passing checks
unless a later change invalidates them.

Primary validation commands for this plan:

```sh
make check
make test
make webapp-test
make onion-test
CONTAINER_ENGINE=podman make check
CONTAINER_ENGINE=podman make test
CONTAINER_ENGINE=podman make webapp-test
CONTAINER_ENGINE=podman make onion-test
git diff --check
```

### Execution checkpoints

| Phase or item | Target | Commit or ref | Validation | Review | Status |
| --- | --- | --- | --- | --- | --- |
| Plan creation | `docs/plans/multi-instance-support.md` | Initial plan commit | Link check and `git diff --check` passed | N/A | Done |
| Gate G1: Design review | Proposed design in this plan | Pending | N/A (read-only design review) | Pending | Pending |
| P1: Addressing, Compose, and image namespacing | `compose*.yaml`, `.env.example`, `components/network/`, `components/webapp/`, `components/tailscale/`, `scripts/` | Pending | `make check` and unit tests | Pending | Pending |
| P2: Runtime configs, SSH, and provisioning | `components/hermes/`, `components/executor/`, `components/provisioning/`, `scripts/init-config.py`, `scripts/stack.py`, `scripts/deployment.py` | Pending | `make check`, `make test`, `make webapp-test`, `make onion-test` | Pending | Pending |
| P3: Multi-instance qualification and docs | `tests/`, `README.md`, `docs/configuration.md`, `docs/architecture.md`, `docs/development.md`, `docs/webapp.md` | Pending | Concurrent two-instance smoke test on Docker and rootless Podman, link check, `git diff --check` | Pending | Pending |
| Gate G2: Final combined review | `git diff 66bd17fa0ce6fe32433e51ef7b9987703190a028..HEAD` | Pending | All required checks on Docker and rootless Podman | Pending | Pending |
| Plan cleanup | Remove `docs/plans/multi-instance-support.md` after G2 passes | Pending | Link check and `git diff --check` | Pending | Pending |

#### Open findings and next action

- Run Gate G1 (fresh independent subagent design review) on this committed plan
  before beginning P1.

## Intent and scope

### User goals

Allow operators to run two or more Private Hermes instances concurrently on the
same host across Docker Desktop, native Linux Docker, and rootless Podman. Keep
the design simple by requiring a separate repository checkout per instance, and
keep instances safe when checkouts run different commits or upgrade at different
times.

### Current behavior (observed)

1. **Hardcoded Compose project name:** `compose.yaml` sets
   `name: private-hermes`. Separate checkouts collide on container names,
   network names, and named volumes (`private-hermes_hermes-data`,
   `private-hermes_x402_treazury-data`, and `private-hermes_tor-x402_treazury`).
2. **Hardcoded bridge subnets and static IPs:** `compose.yaml` and
   `compose.funnel.yaml` pin 12 `/24` bridge subnets from `10.203.80.0/24`
   through `10.203.91.0/24`. All three engines reject overlapping bridge subnets
   on the same daemon or rootless user network namespace, and
   `scripts/preflight.py` enforces this check before startup.
3. **Hardcoded `10.203.8x.y` addresses across components:** Runtime scripts,
   static bind-mounted files (`resolv.conf`, `torrc`), image-baked SSH files
   (`sshd_config`, `ssh-client.conf`), ASGI middleware (`browser_policy.py`),
   and persisted files (`known_hosts`, `config.yaml`, `proxy.cfg`,
   `mcp-allowlist.json`) embed literal `10.203.8x.y` addresses.
4. **Shared `:local` image tags:** `compose.yaml` and `compose.funnel.yaml` tag
   built images as `private-hermes-*:local`. Rebuilding in one checkout
   overwrites the tag used by another checkout's `make up`, `make chat`,
   maintenance commands, or container recreations.
5. **Already configurable host surfaces:** `WEBAPP_PORT`, `TEEP_HOST_PORT`, and
   `TAILSCALE_HOSTNAME` are already configurable in `.env`, and
   `scripts/preflight.py` already detects host port collisions across projects.
6. **Non-colliding internal addresses:** The GRE inner tunnel subnets
   (`10.204.80.0/30` and `10.204.81.0/30`) and `HOST_ALIAS` (`198.18.255.254`)
   exist only inside private container network namespaces and do not collide
   across instances.

### Intended behavior

1. Each instance uses its own repository checkout (giving it separate `.env`,
   `config/`, and `data/` directories) and configures distinct values in `.env`
   for:
   - `COMPOSE_PROJECT_NAME` (default `private-hermes`),
   - `NETWORK_PREFIX` (default `10.203`),
   - `WEBAPP_PORT` (default `9120`),
   - `TEEP_HOST_PORT` (default `8337`, when Teep is enabled), and
   - `TAILSCALE_HOSTNAME` (default `private-hermes`, when Funnel is enabled).
2. Existing single-instance deployments with no `COMPOSE_PROJECT_NAME` or
   `NETWORK_PREFIX` in `.env` keep their exact current project name, volume
   names, image names, subnets (`10.203.80.0/24` through `10.203.91.0/24`), and
   ports with no operator migration step.
3. Built image tags are namespaced by `COMPOSE_PROJECT_NAME`
   (`${COMPOSE_PROJECT_NAME:-private-hermes}-<component>:local`) so checkouts on
   different commits or upgrade schedules never overwrite each other's images.
   Checkouts on the same commit still share content-addressed build cache layers.
4. Every runtime network rule, resolver file, Tor listener, SSH client and
   server endpoint, HAProxy frontend and backend, Tailscale Funnel target, and
   bootstrap file derives its `80` through `91` addresses from `NETWORK_PREFIX`.
5. Maintenance commands (`make down`, `make chat`, `make plugins`,
   `make onion-address`, `make x402_treazury-status`, and offline maintenance
   jobs) always target the checkout's configured `COMPOSE_PROJECT_NAME` and stay
   available even if an operator enters an invalid `NETWORK_PREFIX` in `.env`.

### Named deferrals

- **Single-checkout multi-instance orchestration:** Running multiple instances
  out of one shared checkout directory is out of scope. Separate checkouts keep
  `data/`, `config/`, `.env`, and Git revisions cleanly isolated without adding
  an instance manager or state directory abstraction.
- **Per-network custom CIDR overrides:** Operators configure one two-octet
  `NETWORK_PREFIX` rather than 12 separate subnet variables. Supporting tighter
  `/20` or `/28` packing can be considered later only if a concrete environment
  cannot spare a two-octet RFC1918 prefix.
- **Parallel execution of existing test suites against a live stack:** Existing
  test targets may remain on their current default prefix (`10.203`) unless
  explicitly parameterized; this plan adds focused multi-instance qualification
  rather than refactoring every historical smoke suite.

### Plan conflict check

Active plans under `docs/plans/` (`changing-mcp-listeners.md`,
`document-search.md`, `hermes-upstream-prep.md`, `readonly-configuration.md`,
and `webapp-interactive-content.md`) do not alter Compose project naming,
bridge subnet allocation, or image tagging. `changing-mcp-listeners.md` targets
loopback (`127.0.0.1`) treasury listeners inside `agent-net`, which do not
depend on `NETWORK_PREFIX`.

## Preserved boundaries

- **Network isolation and default-deny firewalls:** All 12 bridge networks keep
  their exact isolation (`internal: true`, `gateway_mode: isolated` on Docker,
  `isolate: strict` on rootless Podman) and per-namespace iptables rules.
  Instances cannot reach each other's internal bridges; `integrations.py` blocks
  all container networks reported by the engine plus the instance's own
  `RESERVED` block from `HERMES_INTEGRATIONS_LAN_ENDPOINTS`.
- **No embedded engine DNS:** `agent-net` and `executor-net` continue blocking
  `127.0.0.11` and `aardvark-dns` and mounting read-only `resolv.conf` files
  pointing only at Tor's `DNSPort`.
- **Agent, executor, Teep, and treasury separation:** No new capabilities,
  privileged containers, host networking, or widened mounts are added.
- **SSH pinning and root-owned client config:** OpenSSH in Hermes still uses
  strict pinned host-key checking against `/run/agent-ssh/known_hosts` with
  forwarding disabled, and `sshd` in the executor still binds only its
  `execution-control` interface (`<prefix>.82.3:2222`).
- **Non-lockstep and mixed-commit safety:** Because each checkout owns its own
  `COMPOSE_PROJECT_NAME`, named volumes, `data/`, `config/`, `NETWORK_PREFIX`,
  and `<project>-*:local` image tags, an older checkout (including a release
  predating this feature on `private-hermes` and `10.203`) and a newer checkout
  on a distinct project name and prefix operate side by side without colliding
  on images, containers, networks, or volumes.
- **Upgrade and retry safety:** Existing single-instance deployments upgrade via
  `make down`, backup, `git pull`, and `make up` with no `.env` edits required.
  `make up` renders the derived `resolv.conf` files before bind-source checks so
  upgraded checkouts never fail on missing generated files.

## Simplest design

### Why two `.env` settings (`COMPOSE_PROJECT_NAME` and `NETWORK_PREFIX`)

1. **`COMPOSE_PROJECT_NAME` (default `private-hermes`):** Standard Compose
   setting. Setting `name: ${COMPOSE_PROJECT_NAME:-private-hermes}` in
   `compose.yaml` isolates containers, networks, named volumes, and
   `<project>-*:local` image tags without custom wrapper orchestration.
   Validation restricts it to lowercase `[a-z0-9][a-z0-9_-]*` (at most 63
   characters) so the same value is valid as a Compose project name and as a
   Docker or Podman image repository prefix.
2. **`NETWORK_PREFIX` (default `10.203`):** A two-octet RFC1918 IPv4 prefix
   (`10.<0-255>`, `172.<16-31>`, or `192.168`, rejecting `10.204` because
   `10.204.80.0/30` and `10.204.81.0/30` are the GRE inner tunnels).
   - **Native Compose interpolation:** `compose.yaml` and `compose.funnel.yaml`
     interpolate `${NETWORK_PREFIX:-10.203}.80.0/24` through
     `${NETWORK_PREFIX:-10.203}.91.0/24` directly. No generated Compose override
     file is needed, and `docker compose config` or `podman compose config`
     works directly.
   - **Avoids Docker Desktop pool exhaustion:** Docker's default automatic pool
     exhausts after 2 to 3 instances because each instance uses 10 to 12
     bridges. Pinning subnets via `NETWORK_PREFIX` avoids requiring users to
     edit `daemon.json` or `containers.conf` and restart their container engine.
   - **Preserves deterministic startup order:** `tor` starts before `agent-net`
     and `executor-net` and builds GRE tunnels and IP-exact firewall rules from
     deterministic peer addresses without relying on blocked engine DNS.

### Shared addressing helper

Add a small standard-library helper module
`components/network/addressing.py` (no external dependencies) that validates
`NETWORK_PREFIX` and computes the instance's addresses and subnets from one
definition:

- Bridge subnets: `<prefix>.80.0/24` through `<prefix>.91.0/24`.
- Service IPs:
  - `tor`: `.88.2` (`tor-uplink`), `.86.2` (`onion-ingress`), `.80.3`
    (`agent-route`), `.81.3` (`executor-route`).
  - `agent-net`: `.80.2`, `.82.2`, `.83.2`, `.84.2`, `.85.2`.
  - `executor-net`: `.81.2`, `.82.3`.
  - `teep`: `.83.3`.
  - `webapp-proxy`: `.85.3`, `.86.3`, `.87.3`.
  - `tailscale`: `.87.2`.
- Keep GRE inner addresses (`10.204.80.1`, `10.204.80.2`, `10.204.81.1`,
  `10.204.81.2`) and `HOST_ALIAS` (`198.18.255.254`) fixed constants.

### Handling image-baked and static files without per-instance image builds

- **Resolver files (`resolv.conf`):** Replace the static bind mounts
  `./components/hermes/resolv.conf` and `./components/executor/resolv.conf` with
  generated read-only bind mounts `./config/network/hermes-resolv.conf` and
  `./config/network/executor-resolv.conf`, rendered atomically by
  `deployment.render(config)` alongside `config/webapp/proxy.cfg`. (Compose
  `dns:` cannot be used because it routes through blocked embedded DNS.)
- **Executor `sshd_config`:** Remove `ListenAddress 10.203.82.3` from
  `components/executor/sshd_config` and pass
  `-o ListenAddress=${NETWORK_PREFIX:-10.203}.82.3` when launching `sshd` in
  both the lean Alpine `CMD` (via a tiny shell invocation or entrypoint) and
  `components/executor/start-desktop.sh` using `PRIVATE_HERMES_EXECUTOR_SSH_HOST`.
- **Hermes `ssh-client.conf`:** Move `/etc/ssh/ssh_config.d/99-private-hermes.conf`
  to `/etc/ssh/private-hermes-ssh.conf` (root-owned `0644`, outside
  `ssh_config.d/` so it applies only when passed via `TERMINAL_SSH_CONFIG` or
  `-F`) and change `Host 10.203.82.3` to `Host *`. Because `managed_policy.py`
  already passes `TERMINAL_SSH_CONFIG` explicitly to OpenSSH for executor
  connections, this preserves strict host-key pinning and forwarding denial
  while keeping the image prefix-independent.
- **Tor `torrc`:** Remove literal `10.203.80.3` and `10.203.81.3` `DNSPort`
  lines from `components/network/torrc` and have `components/network/network.py`
  append the instance's `DNSPort` lines when writing `/tmp/private-hermes-torrc`
  (where it already appends `HiddenServiceDir` and rewrites `SocksPort`).
- **Hermes `browser_policy.py`:** Read `PRIVATE_HERMES_WEBAPP_BACKEND_IP`
  (default `10.203.85.2`) from the environment instead of hardcoding
  `10.203.85.2`.

### Persisted state and changing `NETWORK_PREFIX` or `COMPOSE_PROJECT_NAME`

- **`known_hosts` and `trusted_proxies`:** `setup` already rewrites
  `data/ssh/agent/known_hosts` and `dashboard.trusted_proxies` on every
  `make up`. Parameterizing them with `NETWORK_PREFIX` keeps them in sync
  automatically.
- **`hermes-data/config.yaml`:** On initial creation, seed `providers.teep.base_url`
  and `terminal.ssh_host` using `NETWORK_PREFIX`. On subsequent `make up` runs
  against an existing `config.yaml`, `managed_policy.py` already overrides
  `terminal.ssh_host` at runtime; for `providers.teep.base_url`, update it
  atomically only when the saved value matches the exact managed pattern
  `http://<digits>.<digits>.83.3:8337/v1` for a different prefix, leaving any
  operator-customized `base_url` untouched.
- **`config/network/mcp-allowlist.json`:** Operator-edited. `network.py`
  validates entries against `<prefix>.84.0/24` and fails visibly if stale IPs
  from another prefix remain.
- **`COMPOSE_PROJECT_NAME` stability:** Document clearly that changing
  `COMPOSE_PROJECT_NAME` on an already initialized instance detaches it from its
  existing named volumes (`<old-project>_hermes-data` and
  `<old-project>_x402_treazury-data`). Do not add an automatic volume-copying
  migration; operators choose `COMPOSE_PROJECT_NAME` before first `make up`.
- **Maintenance command resilience:** `deployment.maintenance_compose()` never
  overrides `COMPOSE_PROJECT_NAME` (so `make down`, `make chat`, `make plugins`,
  and `make x402_treazury-status` always target the checkout's instance). If
  `NETWORK_PREFIX` is invalid in `.env`, `maintenance_compose()` falls back in
  memory to `10.203` for offline and shutdown commands so `make down` and
  offline inspection remain usable. `start_chat()` reads the applied
  `NETWORK_PREFIX` (and `TERMINAL_SSH_HOST`) from the running `hermes`
  container's environment so `make chat` always matches the running stack.

## Implementation phases

### Phase P1: Addressing, Compose, and image namespacing

**Files to create or update:**
- `components/network/addressing.py` (new): `NETWORK_PREFIX` validation,
  `COMPOSE_PROJECT_NAME` validation, and deterministic address derivation.
- `.env.example`: Add commented `COMPOSE_PROJECT_NAME=private-hermes` and
  `NETWORK_PREFIX=10.203` settings with clear guidance for running multiple
  instances.
- `compose.yaml` and `compose.funnel.yaml`:
  - `name: ${COMPOSE_PROJECT_NAME:-private-hermes}`
  - Add `project_name` and `network_prefix` to `x-deployment`.
  - Namespace all local `image:` fields with `${COMPOSE_PROJECT_NAME:-private-hermes}-<component>:local`.
  - Replace all `10.203.8x` subnets, `ipv4_address` fields, and
    `TERMINAL_SSH_HOST` with `${NETWORK_PREFIX:-10.203}.8x...`.
  - Pass `NETWORK_PREFIX: ${NETWORK_PREFIX:-10.203}` to `setup`, `tor`,
    `agent-net`, `executor-net`, `executor`, `hermes`, `webapp-proxy`,
    `onion-init`, and `tailscale`.
- `components/network/network.py`, `components/network/integrations.py`,
  `components/network/onion.py`, `components/network/torrc`: Derive all
  `10.203.8x` addresses, `RESERVED`, `UPLINK_ADDRESS`, `mcp-allowlist` `/24`,
  `DNSPort`, and `HiddenServicePort` from `addressing.py`.
- `components/webapp/settings.py`, `components/webapp/proxy-start.py`,
  `components/tailscale/funnel.py`: Validate `COMPOSE_PROJECT_NAME` and
  `NETWORK_PREFIX` in `Settings.read()`, and derive HAProxy, proxy firewall, and
  Tailscale Funnel addresses from `NETWORK_PREFIX`.
- `scripts/preflight.py`: Validate `NETWORK_PREFIX` and `COMPOSE_PROJECT_NAME`,
  ensure `ADDRESS_PLAN_HELP` and conflict diagnostics guide operators to set a
  distinct `NETWORK_PREFIX` in `.env` when another instance occupies a subnet,
  and pass all existing engine subnets when checking `integrations.grants()`.

**Acceptance checks:**
- `make check` and `CONTAINER_ENGINE=podman make check` pass.
- Unit tests cover valid and invalid `NETWORK_PREFIX` values (including
  rejecting `10.204`, non-RFC1918, and malformed strings), valid and invalid
  `COMPOSE_PROJECT_NAME` values, Compose model rendering with non-default
  project name and prefix on all four Compose overlays, and `preflight.py`
  subnet conflict diagnostics.

### Phase P2: Runtime configs, SSH, and provisioning

**Files to update:**
- `scripts/deployment.py`, `scripts/init-config.py`, `scripts/stack.py`:
  - Render `config/network/hermes-resolv.conf` and
    `config/network/executor-resolv.conf` atomically in `deployment.render()`.
  - Keep `COMPOSE_PROJECT_NAME` intact in `maintenance_compose()` while
    substituting a safe `NETWORK_PREFIX` placeholder only for offline and
    shutdown paths when `.env` has an invalid prefix.
  - Propagate applied `NETWORK_PREFIX` and `TERMINAL_SSH_HOST` in `start_chat()`.
  - Switch `compose.yaml` resolver mounts from `./components/*/resolv.conf` to
    `./config/network/*-resolv.conf` (and remove obsolete static files if unused
    by tests, or update test overlays accordingly).
- `components/executor/sshd_config`, `components/executor/Dockerfile`,
  `components/executor/start-desktop.sh`: Bind `sshd` to
  `${NETWORK_PREFIX:-10.203}.82.3` via `-o ListenAddress=...` at runtime.
- `components/hermes/Dockerfile`, `components/hermes/ssh-client.conf`,
  `components/hermes/managed_policy.py`, `components/hermes/browser_policy.py`:
  - Move SSH client config to `/etc/ssh/private-hermes-ssh.conf` with `Host *`
    and update `SSH_CONFIG` in `managed_policy.py` and `TERMINAL_SSH_CONFIG` in
    `compose.yaml`.
  - Derive the expected webapp backend IP in `browser_policy.py` from
    `NETWORK_PREFIX`.
- `components/provisioning/bootstrap.py`, `components/webapp/configure.py`,
  `components/provisioning/setup.py`:
  - Derive `[<prefix>.82.3]:2222` in `known_hosts`, `<prefix>.85.3` in
    `dashboard.trusted_proxies`, and `<prefix>.83.3` and `<prefix>.82.3` in fresh
    `config.yaml`.
  - On existing `config.yaml`, atomically update `providers.teep.base_url` only
    when it matches the managed `http://<a.b>.83.3:8337/v1` pattern for a
    different prefix.

**Acceptance checks:**
- `make check`, `make test`, `make webapp-test`, and `make onion-test` pass on
  Docker.
- `CONTAINER_ENGINE=podman make check`, `make test`, `make webapp-test`, and
  `make onion-test` pass on rootless Podman.
- Unit tests verify retry-safe `setup` behavior, `NETWORK_PREFIX` update on an
  existing `config.yaml` (preserving custom `base_url` and credentials),
  `make down` resilience with an invalid `NETWORK_PREFIX`, and `start_chat()`
  using the running instance's prefix.

### Phase P3: Multi-instance qualification and documentation

**Qualification tests (`tests/`):**
- Add a focused multi-instance live smoke test (for example,
  `tests/multi_instance_smoke.py`, documented in `docs/development.md`) that:
  1. Launches two isolated instances concurrently with distinct
     `COMPOSE_PROJECT_NAME`, distinct `NETWORK_PREFIX` (for example, `10.205`
     and `10.206`), and distinct host ports (`WEBAPP_PORT`, `TEEP_HOST_PORT`).
  2. Verifies both instances start cleanly, pass SSH execution, Tor routing,
     Teep reachability, and WebApp login independently.
  3. Verifies forbidden paths: instance A's `hermes` and `executor` cannot reach
     instance B's bridges, `webapp-proxy`, `executor`, or `teep`, and vice
     versa.
  4. Verifies `preflight.py` rejects a third launch that reuses either
     instance's `NETWORK_PREFIX` or host ports.
  5. Verifies stopping one instance (`down`) leaves the other instance's
     containers, networks, volumes, and images intact.
- Run this suite on both Docker and rootless Podman.

**Documentation updates (in place, no duplicate tables):**
- `README.md`: Add a concise user-facing "Running multiple instances" section
  explaining separate checkouts, the required `.env` settings
  (`COMPOSE_PROJECT_NAME`, `NETWORK_PREFIX`, `WEBAPP_PORT`, `TEEP_HOST_PORT`,
  and `TAILSCALE_HOSTNAME` if Funnel is used), independent upgrades across
  checkouts, and the warning not to rename `COMPOSE_PROJECT_NAME` on an
  initialized instance.
- `docs/configuration.md`: Add `COMPOSE_PROJECT_NAME` and `NETWORK_PREFIX` to
  the `.env` recipient table, document generated `config/network/*-resolv.conf`
  files, document per-project `<project>-*:local` image tags and mixed-commit
  behavior, and update backup notes to reference `<COMPOSE_PROJECT_NAME>_*`
  named volume names.
- `docs/architecture.md`: Update hardcoded `10.203.8x` references where they
  describe the general contract (noting `10.203` as the default
  `NETWORK_PREFIX`), note that GRE inner tunnels (`10.204.80.0/30` and
  `10.204.81.0/30`) stay namespace-local, and document cross-instance isolation.
- `docs/webapp.md`: Update literal `10.203.85`, `10.203.86`, and `10.203.87`
  references where appropriate to note the configurable `NETWORK_PREFIX`
  (default `10.203`).
- `docs/development.md`: Document the multi-instance smoke test and record
  engine qualification status and limits.

**Acceptance checks:**
- Multi-instance smoke test passes on both Docker and rootless Podman.
- Local markdown link check and `git diff --check` pass.

## Review gates

- **Gate G1 (Pre-implementation design review):** Fresh independent subagent
  review of this committed plan before P1 starts. Must verify that:
  - No simpler design satisfies Docker Desktop, native Linux Docker, rootless
    Podman, and non-lockstep mixed-commit checkouts.
  - All hardcoded `10.203.x` and `private-hermes` references across Compose,
    components, scripts, and persisted state are accounted for.
  - Moving `ssh-client.conf` out of `ssh_config.d/`, parameterizing
    `sshd -o ListenAddress`, and generating `resolv.conf` preserve all existing
    security boundaries and upgrade safety.
  - No unintended breakage occurs for `make down`, `make chat`, or existing
    single-instance upgrades.
- **Gate G2 (Final combined review):** Fresh independent subagent review over
  `git diff 66bd17fa0ce6fe32433e51ef7b9987703190a028..HEAD` after P3 passes all
  checks. Must sweep any G1 or intermediate findings across the entire branch,
  verify allowed-path and forbidden-path runtime evidence on both Docker and
  rootless Podman, and verify all documentation edits against
  [AGENTS.md](../../AGENTS.md#writing-style).

## Engine coverage

- **Docker Desktop (macOS and Windows) and native Linux Docker:**
  - Uses `${NETWORK_PREFIX:-10.203}.80.0/24` through `.91.0/24` with
    `gateway_mode: isolated`, bypassing Docker's default address pool limit.
  - Shared content-addressed BuildKit cache keeps per-project image tags fast
    when checkouts share a commit.
  - Requires runtime verification with `make test`, `make webapp-test`,
    `make onion-test`, and the new multi-instance smoke test.
- **Rootless Podman (Linux):**
  - `deployment.ensure_networks()` already reads declared subnets from the
    effective Compose model and applies `isolate: strict` and
    `no_default_route: true` per project network.
  - Verify `ensure_networks()`, `remove_networks()`, `preflight.py` subnet
    overlap checks across projects, `podman_paths_smoke.sh`, and the new
    multi-instance smoke test on rootless Podman.
  - Note: Separate Linux users on rootless Podman already have isolated user
    network namespaces; this design works both for one user running multiple
    instances and across engines.

## Gaps and authority limits

- **Current host environment:** This macOS host runs Docker Desktop; native
  Linux Docker and rootless Podman runtime qualification require a Linux host
  (or Linux VM) with rootless Podman 5.4+. Any engine not run at completion must
  be recorded explicitly as missing coverage rather than assumed to pass.
- **Authority limits:** Local commits are authorized by `AGENTS.md`. Do not
  push, merge, enroll live Tailscale Funnel, publish live onion services, or
  touch funded wallets or private operator state during qualification.
