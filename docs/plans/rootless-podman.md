# Rootless Podman support

Status: G1 passed. P1 is merged. P2 and P4 are implemented. P3 is partial
(see Missing evidence). G2 is open.
Planning baseline: branch `main`, commit `4a08841`. Amendment baseline: branch
`main`, commit `1d83657`.
Plan path: `docs/plans/rootless-podman.md`.
Follow the [planning workflow](../planning-workflow.md) before implementation.

## Intent and scope

Support rootless Podman as an engine next to Docker, from the first release. A
rootless engine runs no root daemon, and container root maps to an unprivileged
host user, so a compromised container or engine has less authority on the host.

In scope:

- Start, operate, back up and stop the current topology on rootless Podman with
  the same trust boundaries as on Docker.
- Keep every Docker file and command unchanged. Docker Desktop, the qualified
  Docker platform, stays the Docker regression target.
- One Podman overlay that removes or replaces only the Docker-only settings.

Out of scope:

- Topology changes. GRE stays on both engines. The
  [capability reduction plan](capability-reduction.md) owns the choice between
  GRE, a shared Hermes/Tor namespace and veth pairs.
- Rootful Podman and Podman Desktop. They are not tested.
- Paid treasury operations. The checks below use no funds.

## Current behavior

The stack supports Docker only:

- `scripts/preflight.py` requires Docker Engine 28+ and Compose 2.36+.
- `compose.yaml` and `compose.funnel.yaml` use Docker bridge options: isolated
  gateway mode on internal networks (`compose.funnel.yaml:3-5` for
  `funnel-link`), `enable_ip_masquerade: false` on `webapp-publish`, and
  `gw_priority` (`compose.yaml` teep, `compose.funnel.yaml:39`). Health checks use
  `start_interval`.
- `scripts/deployment.py` (`settings()`, `compose()`, `maintenance_compose()`)
  builds the Compose commands. `scripts/stack.py:53`, the Makefile and the smoke
  tests also call `docker compose` with explicit files.
- `tests/smoke.py` checks forbidden destinations at Docker addresses
  (`172.17.0.1`, the Docker Desktop VM `192.168.65.x`, embedded DNS `127.0.0.11`).

## Observed facts

Environment: Debian 13, kernel 6.12, Podman 5.4.2 rootless with netavark 1.14.0
and pasta, Compose 2.26.1 from Debian (`docker-compose`), `podman-docker` for the
`docker` command, and the user `podman.socket` for the Compose API. Commit
`a0650f5` on branch `podman-trial` of `ai-13rac1/private-hermes-agent` holds the
trial changes. It is evidence, not a change for merging, and its base is `main`
commit `0f19d8e`; the changes since then (x402_treazury pin and documents) do not
touch the network code. With the trial changes the full stack started: `tor`,
`agent-net`, `executor-net`, `executor` and `teep` became healthy, Hermes and
HAProxy started, and the webapp answered with a redirect to login. The trial ran
without Funnel and without an initialized treasury.

Some facts below were observed in commands run during the trial, not in saved
logs: F1's message, F6, F7's restart count, the executor Tor result and module
loading. Saved logs show F2, F4 and the started services.

| # | Docker behavior the stack depends on | Rootless Podman behavior | Trial change |
| --- | --- | --- | --- |
| F1 | `ip tunnel add` creates GRE links | Fails with `add tunnel "gre0" failed: No such device` when `ip_gre` is not loaded; `ip link add type gre` loads it | Netlink; in pull request 1, engine-neutral |
| F2 | tmpfs `uid=`/`gid=` options | `unknown mount option "uid=101"` | Router sets the owner of `/run/tor-control`; in pull request 1 |
| F3 | Isolated gateway mode, masquerade option | Netavark rejects the gateway option: `unsupported bridge network option com.docker.network.bridge.gateway_mode_ipv4` | Removed; `no_default_route: "true"` on `webapp-publish` |
| F4 | `healthcheck.start_interval` | Compose refuses it: `can't set healthcheck.start_interval as feature require Docker Engine v25 or later` | Removed |
| F5 | Preflight version floors | Podman reports its own version (5.4.2) | Floors skipped for Podman |
| F6 | Published port enters on the publication interface | `rootlessport-child` runs inside the HAProxy namespace and connects over loopback to the container's first network address, `10.203.85.3:9120`; the proxy firewall dropped it in OUTPUT | Loopback-only accept rule and a second HAProxy listen address |
| F7 | Restart backoff | A container that exits at once restarts about every 0.3 s: teep without a provider key restarted 13,597 times in an hour while `make up --wait` waited | None |
| F8 | Compose 2.36 | Compose 2.26.1 drops `gw_priority` and renders `create_host_path: false` as `bind: {}`, which fails `test_storage`. It keeps `stop_grace_period: -1s` in `config` output; whether it applies it is not known | None |
| F9 | Docker drops forwarding between different bridge networks | Netavark forwards between two ordinary rootless networks: a client on one reached a listener on the other. With `-o isolate=strict` on both, the connection was blocked | None; the trial stack had this exposure |
| F10 | Compose creates networks with the declared driver options | Podman's Docker-compatible network API sets `isolate=true` on every bridge and drops other options, including `isolate=strict` and `no_default_route`. On a stack created this way, a container on a user network without isolation reached teep at its uplink address on port 8337 and HAProxy's edge address | `ensure_networks()` creates the networks with the `podman` command first; Compose adopts networks that carry its labels |

Network evidence from disposable experiments. Except for F9, these used
networks with `-o isolate=strict` and `--disable-dns`. The trial Compose set
neither; the overlay sets `isolate: strict` (D5).

- The executor's public TCP left through Tor over the GRE link in the trial
  stack: `{"IsTor":true}`.
- On a Podman internal network, plain routing to a peer container works for
  public destinations, without GRE. From reading Moby `master` (not a test of
  the pinned Engine): the iptables IPv4 rule for internal networks drops this
  traffic (`-i <bridge> ! -d <subnet> -j DROP`); the IPv6 rule and the nftables
  backend check interfaces and do not. This is evidence for the GRE comparison
  in the capability reduction plan; this plan keeps GRE.
- Rootless bridges live in the user's network namespace. The bridge gateway is
  not a host address. A host service bound to `0.0.0.0` was not reachable at the
  host IP or the gateway from a container on an ordinary network.
- From the same container, that host service was reachable through pasta at
  `169.254.1.2` (`host.containers.internal`). The test did not check services
  bound only to `127.0.0.1`. An internal client routed through Tor could not
  reach it: Tor rejected the private address. The router's `169.254.0.0/16` deny
  covers Tor's own outbound traffic.
- A rootless container loaded `nf_nat`, `xt_REDIRECT` and `ip_gre` on demand. No
  host root step was necessary on this kernel.

## Preserved boundaries

All boundaries in [AGENTS.md](../../AGENTS.md) and
[architecture](../architecture.md) apply on both engines without change:
separate Hermes and executor namespaces, Tor-only public TCP and DNS, denial of
host, VM and private destinations, exact internal grants, ingress separate from
egress, Teep's verification behavior and its accepted direct uplink, and wallet
isolation. A Podman difference must not weaken a boundary on either engine.

## Proposed approach

1. Engine-neutral changes go into the base files. F1 and F2 are merged (pull
   request 1).
2. `compose.yaml`, `compose.funnel.yaml` and all Docker consumers stay as they
   are.
3. Two Podman files remove or replace the Docker-only keys with Compose's
   `!reset` and `!override` tags:
   - `compose.podman.yaml`, always on Podman:
     `driver_opts: !override {isolate: strict}` on every network of
     `compose.yaml`, including the uplinks and `webapp-publish`. This replaces
     Docker's gateway options and restores Docker's separation between networks
     (F9). `webapp-publish` also gets `no_default_route: "true"`. It also holds
     `start_interval: !reset null`, `gw_priority: !reset null` on teep, and an
     environment value for HAProxy's startup (F6, D7).
   - `compose.podman.funnel.yaml`, on Podman with Funnel only: the same
     `isolate` override for `funnel-link` and `tailscale-uplink`, and
     `gw_priority: !reset null` on `tailscale` (`compose.funnel.yaml:39`). A
     single file cannot hold these: without Funnel, the `tailscale` entry makes
     Compose fail (`service "tailscale" has neither an image nor a build context
     specified`).
   Tests with Compose 2.26.1 confirmed that `!reset` and `!override` give
   the intended model, with and without Funnel.
4. The Podman files are always last: `compose.podman.yaml` after
   `compose.funnel.yaml` and any test overlay, then `compose.podman.funnel.yaml`
   when Funnel is on. A test showed that an overlay placed before
   `compose.funnel.yaml` lets `funnel-link` get the Docker options back.
5. `scripts/deployment.py` adds the Podman files to the commands it builds when
   the engine is Podman, and preflight checks the floors of that engine. Other
   callers that name files (`stack.py:53`, `preflight.py:32-34`, the Makefile,
   the smoke tests and unit tests) get the same file list from `deployment.py` or
   a shared helper.
6. Docker gets no new file. The Podman files are selected only when the engine
   positively identifies as Podman (D1). A failed or uncertain detection selects
   Docker; on Podman, Compose then refuses `healthcheck.start_interval` for
   Podman's API version and startup stops with a visible error. (Podman's API
   drops the Docker bridge options with a warning; it does not reject them.)
   With `DOCKER_HOST` set, a Podman client selects the Podman files only when
   that endpoint reports the `Podman Engine` component.
6a. On Podman, `deployment.ensure_networks()` runs before each Compose `up` in
   `stack.py`, the treasury controller and the smoke tests, and before `up`,
   `create`, `run` and `start` through the `stack.py compose` passthrough. After
   `make down`, `stack.py compose down` and a smoke test `down`,
   `deployment.remove_networks()` removes the project's remaining labeled
   networks, because `ensure_networks()` creates the networks of every profile
   and Compose `down` removes only those of the services it manages. It creates every
   project network with `podman network create`, the overlay's options, the
   model's subnet and `internal` flag, and Compose's project and network labels
   (F10). An existing network without these options stops startup until
   `make down` removes it. Preflight requires rootless Podman 5.4+, the `podman`
   command, and a `DOCKER_HOST` that is unset or names the user's Podman socket.
7. The `docker` and `docker compose` commands stay. On Podman, `podman-docker` or
   a `docker` shim and the user `podman.socket` provide them.

Support for both engines is a stated requirement, so this engine selection is
not a speculative option.

## Decisions

- **D1, engine identification.** The engine that matters is the one behind the
  socket Compose uses. With `podman-docker`, `docker` runs `podman` directly and
  `docker version --format json` has no server component list, so a check of the
  component name `Podman Engine` does not work in that form. Decision: select the
  overlay only on a positive Podman identification, in either form: the server
  reports the `Podman Engine` component (the Docker CLI on a Podman socket), or
  the `docker` command is Podman (`podman-docker` or a shim). Everything else is
  Docker, with the Docker floors checked. The check follows the endpoint Compose
  uses, including `DOCKER_HOST` and the current Docker context, which Docker
  Desktop uses in place of `DOCKER_HOST`. The second form identifies the client;
  it is enough because `podman compose` points Compose at the Podman socket. To
  verify on Docker, Docker Desktop and Podman.
- **D2, Compose floor on Podman.** `make down` and the treasury controller pass
  `--timeout -1` (`stack.py:48`, `x402_treazury.py:186,206,242,278`), so
  `stop_grace_period` does not govern them. `gw_priority` leaves the Podman model
  in either case. Open questions: what Podman does with a stop timeout of `-1`
  through the API, and the treasury recreate path (`x402_treazury.py:256`). Also
  check the container's `.Config.StopTimeout` for `stop_grace_period: -1s`: it
  governs stops that the engine starts, such as logout without linger, the user
  `podman-restart.service` and reboot, which can end a running wallet job.
  Recommendation: one floor, Compose 2.36+, on both engines. On Debian 13 this
  means the Compose release binary, installed per user. Compose 2.40.3 also
  renders `create_host_path: false` as `bind: {}`, so `test_storage` fails with
  it as with 2.26.1; the floor does not settle that test. Record the Compose
  version with which the test passes, and check at runtime that a missing bind
  source fails instead of being created.
- **D3, `start_interval` on Podman.** Compose refuses it because of the Podman
  API version, not the Compose version. The overlay resets it.
- **D4, host loopback through pasta (Podman only).** On Docker, teep already
  reaches host services on non-loopback addresses through its gateway; its
  direct uplink is an accepted boundary. The possible new exposure on Podman is
  services bound only to host loopback, which is not tested. Options: accept it
  with a documented reason; set pasta options in the user's `containers.conf`
  (user-wide, outside the repository); or add a deny in teep's namespace, which
  needs a namespace owner or `NET_ADMIN` and conflicts with the least-machinery
  rules. Decision after P3: accept, as teep's direct uplink is an accepted
  boundary on both engines; teep did not reach a host service bound only to
  `127.0.0.1`. The guide states what is and is not tested. The earlier
  recommendation was to test loopback-only reachability from teep first, with a
  host service bound only to `127.0.0.1`, at `169.254.1.2` and at the host's
  default gateway address as seen in the rootless namespace (pasta can map it to
  the host). Then decide. Hermes, the executor and Tor already deny
  `169.254.0.0/16` (`network.py:17-18`). P3 checks follow the decision.
- **D5, network isolation and aardvark-dns.** Decision: `isolate: strict` on
  every network (F9). The endpoint firewalls deny `10.0.0.0/8` and connected
  networks (`network.py:17,107,148`), which covers aardvark at each gateway. DNS
  stays on for `teep-uplink`: teep resolves provider names through aardvark
  there, where Docker uses `127.0.0.11`. Turning DNS off on the internal networks
  is optional and only if Compose can set it. Keep a P3 runtime check of aardvark
  on port 53.
- **D6, restart loops (F7).** Any fail-closed exit restarts about every 0.3 s
  on Podman, and `up --wait` then waits without end. Recommendation: preflight
  checks that teep has at least one provider key, a real startup requirement.
  For other exits, the guide states how to see the loop
  (`podman ps`, restart count). A general backoff stays deferred.
- **D7, Funnel on Podman.** The port forwarder connects to the first network
  address. With Funnel, `funnel-link` (`10.203.87.3`) may sort before
  `webapp-backend`, and F6's rule and listen address would then miss. Podman
  appears to order networks by name. Decision: on Podman, HAProxy's local
  frontend also listens on all of its own addresses at the webapp port, and the
  firewall accepts new connections to the webapp port at those addresses only on
  `lo`, with the matching OUTPUT rule. Only processes inside HAProxy's namespace
  can send loopback traffic, and the port forwarder is one of them; traffic from
  `funnel-link`, `webapp-backend` or `webapp-publish` arrives on other interfaces
  and stays dropped. This does not depend on network order. With Funnel on, the
  webapp port must differ from the Funnel frontend's fixed port 8443
  (`settings.py:103`); settings validation rejects `WEBAPP_PORT=8443` when Funnel
  is enabled, on both engines, so two frontends never share one address and
  port. The engine reaches HAProxy's
  configuration through `render()` (`stack.py:76`), and its startup through the
  overlay's environment value. Check local access with Funnel on, without live
  enrollment.

## Phases

### P1 — Engine-neutral changes (pull request 1)

GRE through netlink and the Tor control directory owner (F1, F2). Status:
merged as `be62899` (merge `ce5b966`). Its Docker
results are not recorded here.

### P2 — Podman overlay, engine selection and ingress

Implement the approach and D1–D7. Consumers:

- `compose.podman.yaml`, `compose.podman.funnel.yaml`, `scripts/deployment.py`,
  `scripts/stack.py`, the Makefile, `.env.example`.
- `scripts/preflight.py`: engine floors (D1, D2), the teep key check (D6), and
  the address-conflict check, which reads Docker's `Labels` and `IPAM.Config`
  and checks nothing on Podman, whose inspect output has `labels` and `subnets`.
- Direct engine calls: `scripts/provisioning.py`, and `docker inspect`, `logs
  --since` and `wait` in `scripts/x402_treazury.py`; Podman's `StartedAt` format
  must work with `logs --since`.
- Tests: `tests/compose.yaml`, `test_configuration.py`, `test_storage.py`,
  `test_endpoint_readiness.py`, `test_maintenance.py`, `test_webapp.py`,
  `hermes_ui.py`, and the smoke tests that build
  Compose or `docker run` commands (`smoke.py`, `storage_smoke.py`,
  `plugins_smoke.py`, `webapp_smoke.py`, `x402_treazury_smoke.py`,
  `research_config_smoke.py`, `endpoint_readiness_smoke.py`, `images_smoke.py`,
  `context_refs_smoke.py`, `desktop_tools_smoke.py`).
- `components/webapp/settings.py`, `components/webapp/proxy-start.py`.

Acceptance: the effective models for Docker and Podman, each with and without
Funnel, differ only in the intended keys; unit tests pass on both engines.

### P3 — Qualification on both engines

On rootless Podman, and on Docker Desktop and Linux Docker for regression, with
disposable state and no funds. Podman targets go into the existing smoke tests,
next to the Docker addresses:

- Allowed paths: executor and Hermes public TCP and DNS through Tor; SSH, Teep
  and MCP grants; webapp through HAProxy with the right `Host`, with and without
  Funnel.
- Forbidden paths: direct egress; host services at the host IP and each gateway;
  `169.254.1.2` from Hermes and the executor, and from teep as D4 decides;
  Docker or Podman DNS; UDP other than DNS; non-loopback IPv6; Hermes to
  HAProxy's listen addresses; wrong `Host` (421). Between networks (F9): teep to
  HAProxy's edge address, `tailscale` to HAProxy's edge address, `tailscale` to
  teep, and teep to the Tor uplink.
- `make storage-test` and the locking checks on rootless volumes.
- x402_treazury without funds: `group_add: 102` access to the Tor SOCKS socket
  under user-namespace mapping, `make x402_treazury-init` and the preparation
  path up to funding.
- Restart and recreation of `tor` and the network owners; stop with
  `--timeout -1` (D2); repeated `make init` and `make up`.

Evidence, rootless Podman 5.4.2 with Compose 2.40.3 (treasury not initialized,
Funnel off):

- First run, commit `7ffdc31`, networks created by Compose: a disposable script
  gave 20 of 20 expected results, but a later check found F10: networks created
  through Podman's compatible API lose their options. Run against that stack, `tests/podman_paths_smoke.sh` failed 12 checks: a
  container on a user network without isolation reached teep's uplink address
  on port 8337 and HAProxy's edge address, every network had `isolate=true`,
  and HAProxy had a default route.
- After item 6a, the same test on a stack recreated with `make down` and
  `make up` gave all expected results: all of the above blocked, every network
  `isolate=strict`, no default route for HAProxy, the allowed and forbidden paths
  of the first run unchanged, and teep's direct HTTPS on its isolated uplink
  (`"IsTor":false`). The current test has 35 checks, including a positive
  control that its DNS probe gets an answer where Podman's DNS server is
  reachable; a container without the probe tool makes a check fail, not pass.
  This check first exposed that Hermes has no `nslookup`, so an earlier "blocked"
  result for Hermes was not evidence; the raw UDP probe replaced it.
- Final run, 2026-11-12, with a clean working tree on this branch before its
  rebase onto `1d83657` (base `d5287db`, so without the executor desktop and
  browser automation): `make up`
  exit 0; the path test passed 35 of 35; after `make down`, `podman network ls`
  listed only `podman`; `tests/smoke.py` then passed all six sections, and
  `podman network ls` again listed only `podman`, so network removal after
  `make down` and after a test `down` worked.

- `tests/smoke.py` (the `make test` suite, run as preflight plus the script,
  because `make check` stops at `test_storage`) passed all six sections on
  Podman, first on an earlier commit and again in the final run: published teep port and host isolation, Tor versus direct egress,
  host/VM, rpcbind TCP/UDP and IPv6 blocks, the real Hermes terminal and
  `execute_code` over SSH, MCP streaming, and Tor outage. Two test-side
  differences were fixed first: the fixture binds port 111 without capabilities,
  which Podman refuses below `ip_unprivileged_port_start=1024`, and cleanup must
  return files to container UID 0, which is the host user under rootless Podman.
- `storage-test`, `x402_treazury-test` and `plugins-test` passed on Podman, on
  the commit before network removal, the `compose` passthrough change and the
  `log_since()` time zone fix; those later changes are covered by unit tests and
  the final run above.
  `webapp-test` passed every ingress check, including capability-free HAProxy
  with separate local and Funnel listeners across restart, exact `Host`
  enforcement, browser login over local HTTP and the simulated Funnel HTTPS path,
  and executor denial of private ingress, plus the Chromium content checks. It
  stopped at the Firefox content check, which could not play the test video on
  this host (missing media codec); WebKit could not start without host libraries
  that need root. These browser limits do not depend on the engine. The test now
  renders its proxy configuration for the engine in use; before that, HAProxy
  refused the mismatched mode and did not start, as designed.
- A host umask of `0002` makes the bind-mounted Hermes SSH client
  configuration group-writable, and OpenSSH then refuses it. This does not
  depend on the engine; it is reported separately and was worked around in the
  test checkout with `chmod g-w`.

Limits: the Tor checks would also be blocked by the router firewall, so the
teep checks are the ones that show isolation. The x402_treazury lifecycle
beyond `x402_treazury-test` did not run (see Missing evidence). The teep result for the
loopback-only host service does not show whether services bound to all host
addresses are reachable from uplink containers under `isolate=strict`. Not yet
run on Podman: the Firefox and WebKit content checks of `webapp-test` (host
browser limits), and restart and recreation of `tor` and the network owners
outside the tests that already restart services. Not yet run on Docker: everything
in this phase.

### P4 — Guides

- README requirements for both engines: `podman-docker` or a shim, the user
  `podman.socket`, the Compose version from D2.
- Rootless operation: containers stop at logout without linger, which may need
  root to enable. After a reboot, run `make up`: `podman-restart.service` starts
  only containers with `restart: always`, and the stack uses `unless-stopped`.
- Backups: bind data under `data/` is owned by subordinate UIDs, so host-side
  backups need `podman unshare` (`docs/configuration.md` backup scope).
- Engine differences in `docs/architecture.md`, including F6 and the
  `X-Forwarded-For` value, which is `10.203.85.3` for every client on Podman.
- Checks in `docs/development.md`.

### Gates

- **G1, design gate before P2:** a fresh independent reviewer checks this plan,
  D1–D7 and the evidence. Result on `f2a08e1`: pass with conditions. Blocking
  findings: missing separation between networks, a D1 rule that must identify
  Podman positively, the overlay's position in the file list, and stale P1
  status. This revision resolves them; F9 was tested after the review. The
  non-blocking findings are in D2, D4, D5, D7 and the P2 consumer list. A fresh
  re-review of the amendment (`dd9c8ed`) passed it with two conditions: a
  separate Podman file for Funnel, because one file fails without Funnel, and a
  rule against the webapp and Funnel frontends sharing port 8443. This revision
  resolves both (items 3–5, D7).
- **G2, final gate after P4:** a fresh independent reviewer checks the combined
  change, the P3 evidence on both engines and the guides. First result on
  `6c6729c`: not pass. A security audit of the same snapshot agreed. Findings
  and resolutions:
  - The overlay's network options did not reach Podman (F10). Resolved by item
    6a, and by `tests/podman_paths_smoke.sh`, which checks the engine's network
    objects and a client on a network without isolation. The unit test of the
    Compose model stays; it cannot show what the engine applies.
  - x402_treazury startup read Podman's `StartedAt` wrongly: `logs --since`
    refused it and its spaces split the restart count. Resolved by `log_since()`,
    which turns either engine's format into a Unix timestamp.
  - The README's reboot instruction did not apply (see P4). Corrected.
  - The live tests named only the Docker files. They now use `compose_files()`
    and `ensure_networks()`, and `tests/smoke.py` adds the Podman host targets
    (pasta's address and each network gateway, including aardvark-dns).
  - Detection trusted a Podman client while `DOCKER_HOST` named another engine,
    and preflight did not check rootless operation. Resolved by D1 and item 6a.
  - The proxy kept its edge-interface accept rule in loopback mode, which no
    rootless connection uses. Removed; `firewall()` is now unit-tested.
  - Guides: the Podman firewall case in `docs/webapp.md`, the key check and the
    8443 rule on both engines, the Compose provider in the README, the pasta
    statement, and the fail-closed mechanism.

## Relation to other plans

- [Optional desktop](../configuration.md#optional-executor-desktop): it uses the same
  executor service, UID, mounts, namespace and existing SSH capability grants.
  Qualify both lean and desktop variants on rootless Podman, including the
  desktop-only seccomp profile and Chromium's nested user-namespace sandbox.
  Include browser-harness execution, SSH owner cleanup and authenticated result
  transfer when qualifying the desktop variant; they add no new capability grant.
  Docker Desktop ARM64 desktop evidence is not Podman evidence; no sudo or
  additional capabilities are authorized as a compatibility workaround.
- [Capability reduction](capability-reduction.md): this plan keeps GRE and adds
  no capability. Its network evidence answers parts of that plan's P1. If that
  plan changes the topology, the Podman overlay and P3 checks must be redone for
  the new design. A rootless engine also removes the root daemon itself, which
  is relevant to that plan's goal.
- [Configurable MCP listeners](changing-mcp-listeners.md): MCP grants stay
  addresses in `10.203.84.0/24` on both engines.

## Rollback

Remove the two Podman files and the engine selection in `deployment.py` and
preflight. Docker is not affected. Volumes, keys and configuration stay; no
state format changes.

## Missing evidence

- Any live run after the rebase onto `1d83657`: the executor desktop
  (`COMPUTER_USE_ENABLED=true`, with its seccomp profile) and browser
  automation have not run on Podman, and the P3 runs above predate them. Unit
  tests and both Podman Compose models, with the desktop off and on, pass on the
  rebased branch.
- Docker: every P3 item on Docker Desktop and Linux Docker, including the unit
  tests, `make check`, the live targets and a recorded Docker Desktop run of P1.
  No Docker engine was available for this work.
- The x402_treazury lifecycle on Podman beyond `x402_treazury-test`:
  `make x402_treazury-init`, the preparation path up to funding, the live
  `serving_instance()` and `log_since()` path, `.Config.StopTimeout` for
  `stop_grace_period: -1s`, and real stops with `--timeout -1` (D2).
- Restart and recreation of `tor` and the network owners on Podman, with the
  services that share their namespaces.
- The Compose version with which `test_storage` passes: 2.26.1 and 2.40.3 both
  omit `create_host_path: false` from `config` output. Compose 2.36 to 2.39 with
  Podman, including adoption of pre-created networks, is not tested; P3 used
  2.40.3.
- Live Funnel enrollment (only the simulated HTTPS path ran), the Firefox and
  WebKit content checks, and other kernels and distributions, for example hosts
  with `br_netfilter` loaded or restricted unprivileged user namespaces.
- `research_config_smoke.py`, `endpoint_readiness_smoke.py`, `images_smoke.py`,
  `context_refs_smoke.py`, `desktop_tools_smoke.py` and `hermes_ui.py` were not
  run on Podman. They are unchanged: they use their own fixture models,
  `network_mode: none` or no network, so they do not depend on the overlays.
