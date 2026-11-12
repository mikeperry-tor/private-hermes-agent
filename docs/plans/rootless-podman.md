# Rootless Podman support

Status: original G1 passed; P1 is merged; original P2 and P4 are implemented.
P3 is partial. Review of `86c74f9` found three open defects (R1–R3 below).
P5–P7 describe the explicit-selection amendment and are not implemented.
Amendment design gate G1A passed; final combined gate G2 remains open.
Planning baseline: branch `main`, commit `4a08841`. Amendment baseline: branch
`main`, commit `1d83657`.
Explicit-selection amendment baseline: branch `rootless-podman-support`, commit
`86c74f9c2d8089e7cae02e3bf7011e98b24cb085` (2026-11-12).
Plan path: `docs/plans/rootless-podman.md`.
Follow the [planning workflow](../planning-workflow.md) before implementation.

## Intent and scope

Support rootless Podman as an engine next to Docker, from the first release. A
rootless engine runs no root daemon, and container root maps to an unprivileged
host user, so a compromised container or engine has less authority on the host.

In scope:

- Start, operate, back up and stop the current topology on rootless Podman with
  the same trust boundaries as on Docker.
- Preserve the Docker topology, effective security settings and operator Make
  workflow. Unify engine commands across helpers, Make targets and fixtures;
  Docker Desktop remains the qualified Docker regression target.
- Select Docker or local rootless Podman explicitly from root `.env`, with an
  exported shell override for testing. Keep the two narrow Podman overlays.
- Correct R1–R3 without changing persistent state, credentials or wallet identity.

Out of scope:

- Topology changes. GRE stays on both engines. The
  [capability reduction plan](capability-reduction.md) owns the choice between
  GRE, a shared Hermes/Tor namespace and veth pairs.
- Rootful Podman and Podman Desktop. They are not tested.
- Paid treasury operations. The checks below use no funds.

## Current behavior

At the amendment baseline, automatic detection chooses Podman overlays but all
ordinary engine/Compose calls still use the `docker` executable. Podman therefore
requires a shim. Network creation/removal alone calls native `podman`. Preflight
checks rootless mode and `DOCKER_HOST` only on some startup paths. The following
list describes the original planning baseline, before P1–P4:

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

## Review findings to resolve

A fresh independent read-only review of `86c74f9` against `main` (`1d83657`)
confirmed these control-flow/reliability findings. Podman was unavailable for
new runtime reproduction; F10 supplies prior evidence of the network consequence.

| ID | Finding and consequence | Planned resolution |
| --- | --- | --- |
| R1 (P1) | `stack.py compose --profile x402_treazury up -d` and `compose -p another-project up -d` bypass network preparation because only the first argument is checked. API-created Podman networks can lose strict isolation. | P5: identify the real subcommand and provision the same effective model/project used by the launch, including global options. |
| R2 (P1) | Docker-context detection can select a Podman endpoint while native `podman` provisions a different endpoint. `DOCKER_HOST`-only validation misses this, and passthrough/new-wallet startup bypasses preflight. | P5: explicit native commands, one local Podman endpoint policy, and scoped validation on every networked launch. |
| R3 (P2) | The proxy's container sysctl does not lower the host privileged-port floor. `WEBAPP_PORT=80` can pass validation but fail rootless publication, contrary to the compatibility claim. | P6: document the host prerequisite and high-port recommendation; retain the container setting for its separate responsibility. |

## Intended approach and simplifications

1. Replace automatic selection with `CONTAINER_ENGINE=docker|podman` in root
   `.env`; absent means `docker`, and an explicitly exported value takes
   precedence. Invalid/empty values fail visibly. Remove client-brand selection,
   raw socket HTTP probing and fallback selection; no automatic/legacy mode.
2. Construct engine and Compose commands in small shared host helpers. Docker
   uses `docker` / `docker compose`; Podman uses native local `podman` /
   `podman compose`. Inspect, wait, logs, stop, run, volume operations, builds,
   fixtures and network operations must all follow the same selection. A Docker
   shim is no longer required. Do not add an adapter registry or command framework.
3. Apply the endpoint policy in D9 to those commands. Check the selected engine's
   actual requirements before network use. An engine selection is not evidence
   of rootless operation, network isolation or correct Compose provider behavior.
4. Share launch preparation at the existing host-helper boundary: required
   engine checks followed by Podman network preparation, then the requested
   Compose operation. Route managed stack startup, treasury startup, passthrough
   and runtime fixtures through it. Keep explicit networkless maintenance paths
   and read-only rendering separate; no generic dependency/lifecycle engine.
5. Preserve native Docker network creation. Preserve Podman's native network
   creation, option checks, Compose adoption labels and leftover-network cleanup:
   F10 demonstrates why Compose cannot own those Podman options. Use the actual
   effective project/model for both preparation and cleanup. Retain existing
   ownership checks; do not add journals, readiness markers or parallel state.
6. Keep base/Funnel topology and useful Docker settings. Keep
   `compose.podman.yaml` and `compose.podman.funnel.yaml` as narrow engine deltas,
   selected explicitly and appended after all applicable overlays. The second
   file remains necessary because the Funnel-only service is undefined without
   `compose.funnel.yaml`. Do not remove Docker healthcheck cadence or change GRE
   merely to reduce overlay lines. Cosmetic YAML deduplication is not a phase.
7. Unify Make/test command construction, including networkless custom fixture
   models, while preserving each fixture's deliberate topology. Test both
   effective deployment models with either selected Compose provider. All CLI
   inspection/cleanup must address the engine that created the fixture.
8. Correct low-port guidance under D10. Keep image/source pins, network grants,
   external-content policy, provider verification and wallet authority unchanged.

## Decisions

- **D1, explicit engine selection (supersedes automatic detection).** Root
  `.env` remains the unified operator input. Add `CONTAINER_ENGINE=docker` to
  `.env.example`; only exact `docker` and `podman` are valid. An absent key/file
  defaults to Docker; a present blank/invalid value is an error. Exported shell
  values override the file, allowing `CONTAINER_ENGINE=podman make test` without
  editing it. Resolve once for each invocation, before Compose construction;
  validate backend identity before network use rather than using it to select
  a backend. Missing tools, unavailable endpoints or an engine mismatch are
  errors, never permission to switch engines. No container needs this host-only
  selector, and no service receives the full `.env`.
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
- **D8, read the selector from normal `.env`.** Host Python may read this private
  operator file; privacy is not a reason to move the selector elsewhere. Compose
  still owns interpolation of service configuration. Use the small, standalone
  upstream `python-dotenv` parser (initial reference: version 1.2.1
  [parser.py](https://github.com/theskumar/python-dotenv/blob/v1.2.1/src/dotenv/parser.py)),
  vendored unchanged under `scripts/` with its license and exact upstream revision
  recorded. It uses the standard library and avoids a host package-install step,
  a handwritten dotenv grammar, and an engine/Compose bootstrap cycle. Vendor
  only the parser required for this read, not the package's CLI/configuration API.
  Use parsed bindings solely to obtain `CONTAINER_ENGINE`; do not call an API
  that exports all settings. Accept literal unquoted, single/double-quoted values,
  whitespace, comments, optional `export`, CRLF and duplicate assignments (last
  assignment wins). Consume unrelated multiline values correctly so embedded
  selector-looking text is never interpreted as an assignment. Require the
  decoded selector to be a literal enum: no variable interpolation or shell
  evaluation is needed for this setting. Missing files differ from unreadable
  files; I/O and parse errors identify the path/line without printing source
  text or secret values. An exported valid selector can be read without parsing
  `.env`; Compose will still validate any configuration it needs. Existing `.env`
  bytes and permissions are never rewritten to introduce the selector. Test the
  supported literal forms against native Compose parsing. This narrowly scoped
  reader adds no general configuration layer or extra operator location.
- **D9, one endpoint policy (R2).** Docker keeps native context/endpoint handling;
  all Docker commands must share it. Networked operations verify that the endpoint
  is Docker and meets the existing floor; a `docker` shim reaching Podman must
  fail rather than silently selecting an overlay. Podman support is local,
  rootless Linux only: explicitly select native local mode (`--remote=false`)
  for both engine commands and `podman compose`, require the user API socket and
  the supported Docker Compose provider, and ensure that provider uses that same
  socket. Pass a consistent child environment that removes inherited endpoint
  overrides such as `DOCKER_HOST`, `DOCKER_CONTEXT`, `CONTAINER_HOST` and
  `CONTAINER_CONNECTION` from the Podman command path. Before a networked launch,
  report conflicting ambient overrides with an actionable error (variable names,
  no credential-bearing values); do not silently launch on a different endpoint.
  Read-only inspection, repair, backup and shutdown still target the explicitly
  selected local Podman instance using the same normalized commands, without
  requiring startup readiness, valid serving policy or clearing those overrides.
  Validate engine/rootless/provider/endpoint requirements at the network-use
  boundary, including Compose passthrough and new-wallet initialization; keep
  networkless saved-wallet inspection and shutdown available. No raw socket HTTP
  client, remote-Podman support or daemon identity record is added.
- **D10, low host ports (R3).** Keep `net.ipv4.ip_unprivileged_port_start=0` in
  the proxy container: it permits unprivileged HAProxy to bind a low container
  port when the host permits publication. It cannot grant the host forwarder
  that permission. Recommend the default `WEBAPP_PORT=9120` or another high port;
  document that low host ports require deliberate host configuration, subject
  to the host's actual privileged-port floor. Correct the overlay comment and
  architecture table; document the same limitation for a low `TEEP_HOST_PORT`.
  Let native publication report its permission error; do not add an arbitrary
  >=1024 ban, a duplicate permission check, privileged relay or automatic host
  sysctl/capability change. Existing Docker publication behavior is preserved.

## Phases

### P1 — Engine-neutral changes (pull request 1)

GRE through netlink and the Tor control directory owner (F1, F2). Status:
merged as `be62899` (merge `ce5b966`). Its Docker
results are not recorded here.

### P2 — Podman overlay, engine selection and ingress

Original P2 is implemented at the amendment baseline; its automatic-selection
contract is superseded by P5/D1/D8/D9. Original consumers:

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
- After the native network creation fix, the same test on a stack recreated
  with `make down` and `make up` gave all expected results: all of the above blocked, every network
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
outside the tests that already restart services. Docker evidence follows below.

Docker evidence at `86c74f9`, 2026-11-12: Docker Desktop ARM64, Engine
29.9.3, Compose 5.7.0 passed `make test` (114 unit tests, effective Docker/Podman
base/Funnel models, compilation, live SSH/MCP/forbidden-path checks, Tor outage
and recovery), `make webapp-test` (24 content cases across Chromium, Firefox and
WebKit; local/simulated HTTPS auth, ingress-policy refusal, Tor retrieval and
unfunded treasury activation), `tests/storage_smoke.py` (retry/identity/locks and
ordinary-down persistence), and `tests/endpoint_readiness_smoke.py` (cancellation,
delayed readiness, terminal errors and corrected restart). `git diff --check`
passed; disposable containers were cleaned up. No operator state or funds were
used. These passes qualify the existing Docker paths, not the unimplemented
amendment, Linux Docker, Podman or optional desktop runtime on Podman. R1–R3
remain open despite these passes.

### P4 — Guides

Original P4 is implemented; its shim/automatic-selection instructions are to be
replaced with the P5 operating contract as that implementation lands.

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

### P5 — Explicit selection and unified engine operations (not implemented)

Implement D1/D8/D9 and the simplifications together in a coherent new development
commit, after G1A. Cover R1 and R2; no fixup/squash/rebase of existing history.
Consumers: `.env.example`, `scripts/deployment.py`, `preflight.py`, `stack.py`,
`provisioning.py`, `x402_treazury.py`, Makefile, and every direct engine call in
`tests/` (including `hermes_build.py` and custom networkless fixture models).
Existing helpers such as plugins/updates inherit the selected commands; trace
those consumers too. Add the vendored parser/license with source/removal notes.
Update README requirements/operation and maintained configuration, architecture,
development, webapp, treasury and updates/plugin guides where their commands or
engine assumptions change. Documentation must describe implemented behavior only.

For passthrough, locate the actual Compose subcommand after supported global
options; preserve the effective project name, project directory, files, env files
and profiles in model rendering, launch and cleanup. Include `--option=value` and
short forms accepted by the documented wrapper. Keep engine overlays last even
with user-supplied files. Root `.env`/shell selects the host engine; passthrough
`--env-file` selects Compose interpolation inputs and does not silently change
engines. Publish the wrapper's supported global options; reject unsupported or
ambiguous forms before mutation rather than guessing. Do not reimplement the
whole Compose CLI. `config`, inspection and dry-run must not create networks;
explicit existing networkless maintenance jobs must not require networking.
Network-creating operations (`up`, `create`, networked `run`, `start`, and any
supported watch/recreate entry point) must not bypass preparation.

Focused acceptance:

- Selector semantics, missing/unreadable/malformed files, blank/invalid/exported
  values, duplicate/quoted/commented assignments, CRLF, unrelated multiline values,
  and a value containing shell syntax; no evaluation, source-line leakage or
  export of unrelated secrets. Match supported literal parsing with Compose.
- Both executables present: selected Docker never invokes Podman and selected
  Podman never invokes the Docker engine, including build/inspect/log/wait/cleanup.
  Provider executable use is distinct from targeting Docker's daemon. A failed
  selected engine does not query/use the other as a fallback.
- Conflicting Docker contexts/hosts and Podman remote settings: demonstrate one
  selected local Podman socket, or refusal before any network/container creation.
  Docker contexts continue working for Docker. Unsupported/rootful Podman fails
  before network use on managed, passthrough and new-wallet launch paths.
- R1 reproductions with `--profile` and `-p`, plus file/env-file/project-directory
  overrides and dry-run: prepared/adopted/removed networks belong to the actual
  project and retain required options; read-only operations do not mutate them.
- All four base/Funnel engine models, desktop off/on; preserve existing mounts,
  capabilities, firewall grants and shutdown behavior. Native network creation
  and cleanup remain minimal; no additional authoritative state is introduced.
- Offline status/repair/backup/shutdown under invalid unrelated serving settings
  and conflicting ambient Podman endpoint overrides; no provider keys, credentials
  or wallets are rewritten. Repeated init retains the existing selector/config.

### P6 — Accurate rootless publication guidance (not implemented)

A separate focused new commit implements D10/R3: correct the Podman overlay
comment, architecture table and configuration/webapp guidance. Preserve the
container sysctl and the default port. If implementation discovers a concrete
native-error deficiency, report it rather than adding enforcement speculatively.

Acceptance: inspect effective models for default and low webapp/Teep ports, and
on a disposable rootless host show default/high-port publication works while a
port below the actual host floor fails visibly. A low port already allowed by
host policy must not be rejected by a blanket wrapper rule. Do not change host
policy to perform the check; no Docker runtime rerun is needed for comment/prose
changes alone.

### P7 — Amendment qualification and final combined review (not implemented)

Run focused P5 checks, then repeat affected P3/runtime checks on Docker Desktop
and a rootless Podman host with both engines installed. Serialize fixed-subnet
fixtures. In addition to the live SSH/MCP/Tor/failure and storage tests, exercise
Podman strict-isolation paths from a client on a non-isolated network, local plus
simulated Funnel ingress/restart, and treasury endpoint diagnostics/stops without
funds. Prove no cross-engine inspection/cleanup or accidental namespace creation
on rejected launches. Use disposable projects; changing engines never migrates,
recreates or deletes existing credentials/wallets. Engine storage is independent;
shared bind data must not be used by concurrent deployments, and switching an
existing deployment requires stopping it and accounting for ownership/backup.

Record evidence by exact revision and engine/provider/platform. Reuse still-valid
evidence; Docker-only results and mocked dispatch do not establish Podman runtime
isolation. Preserve remaining qualification limits below, including the desktop
and browser harness. Complete G2 only with the required evidence and no open
material findings; otherwise keep the plan with explicit next checks. On final
acceptance, move lasting evidence into maintained guides, reconcile inbound links
and remove the completed plan under the planning workflow.

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
  resolved both through the separate overlay and port-conflict rule (D7).
- **G1A, amendment design gate before P5:** a fresh read-only reviewer checks
  R1–R3, D1/D8–D10, the reader/dependency tradeoff, endpoint normalization and
  operation-scoped checks, actual Compose-option propagation, P5–P7 consumers,
  acceptance evidence and deferrals. Result: pass with no material findings on
  2026-11-12, reviewing `86c74f9` plus plan blob
  `060cb81e324931b8e693d97b0071a95e2dea9458`; the only subsequent plan edit
  records this acceptance. The reviewer accepted the standalone parser tradeoff,
  endpoint policy, actual Compose-option propagation and R3 guidance. This gate
  does not mark the amendment implemented or G2 accepted.
- **G2, final combined gate after P7:** a fresh independent reviewer checks the
  resulting branch against the baseline, R1–R3 corrections, affected P3/P5–P7
  evidence on both engines, preservation of saved state, and maintained guides.
  Meaningful P5 security changes also need independent read-only phase review;
  one review may cover that phase and G2 when all evidence is available. The
  original gate after P4 remains historical. First result on
  `6c6729c`: not pass. A security audit of the same snapshot agreed. Findings
  and resolutions:
  - The overlay's network options did not reach Podman (F10). Resolved by
    native network creation, and by `tests/podman_paths_smoke.sh`, which checks
    the engine's network objects and a client on a network without isolation. The unit test of the
    Compose model stays; it cannot show what the engine applies.
  - x402_treazury startup read Podman's `StartedAt` wrongly: `logs --since`
    refused it and its spaces split the restart count. Resolved by `log_since()`,
    which turns either engine's format into a Unix timestamp.
  - The README's reboot instruction did not apply (see P4). Corrected.
  - The live tests named only the Docker files. They now use `compose_files()`
    and `ensure_networks()`, and `tests/smoke.py` adds the Podman host targets
    (pasta's address and each network gateway, including aardvark-dns).
  - Detection trusted a Podman client while `DOCKER_HOST` named another engine,
    and preflight did not check rootless operation. Original fixes were partial:
    the later R2 review found context/entry-point gaps. P5 supersedes that design.
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

## Commit strategy and scope of this amendment

Use ordinary focused commits: plan/design amendment, P5 implementation with tests
and docs, P6 publication guidance, and qualification/corrections as warranted.
Retain existing review history; do not autosquash or rewrite it without explicit
user authorization. Commit only named intended files. This task updates the
plan only; it does not authorize executing P5–P7, installing tools, changing host
policy, enrolling Funnel, making payments or destroying private state.

## Open assumptions and deferrals

No user input is presently required for selector reading: D8 keeps it in normal
root `.env` and defines a concrete parser approach. G1A must challenge whether
vendoring the standalone parser is the smallest maintainable solution; if a
materially simpler approach preserves these semantics, revise the design before
implementation. No shell sourcing, alternate selector file or runtime dependency
installation is an acceptable shortcut.

Podman's actual provider environment and local-mode behavior must be qualified
on the supported version, including inherited endpoint overrides; documentation
alone is insufficient. Keep full remote/rootful Podman support, generic option
parsing, topology/capability changes, extra relays and automatic state transfer
out of scope. The capability-reduction and configurable-MCP-listener plans retain
their existing responsibilities and require no design change for this amendment.

## Rollback

If reverting implementation commits, restore the corresponding command/docs
contract together; do not leave mixed engine selection and invocation paths.
Never treat the known-defective automatic-selection baseline as qualified merely
because it was restored. Engine changes do not change state formats or authorize
volume deletion, wallet reinitialization or automatic cross-engine migration.

## Missing evidence

- Any live run after the rebase onto `1d83657`: the executor desktop
  (`COMPUTER_USE_ENABLED=true`, with its seccomp profile) and browser
  automation have not run on Podman, and the P3 runs above predate them. Unit
  tests and both Podman Compose models, with the desktop off and on, pass on the
  rebased branch.
- P5–P7 are unimplemented/unqualified. No Podman is installed on the current
  review host; obtain rootless runtime and dual-engine evidence on another host.
- Docker: P3 items outside the recorded `86c74f9` Docker Desktop run, including
  Linux Docker and any checks needed after the P5 command-path changes.
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
  WebKit content checks on Podman, and other kernels/distributions, for example
  hosts with `br_netfilter` loaded or restricted unprivileged user namespaces.
- `research_config_smoke.py`, `endpoint_readiness_smoke.py`, `images_smoke.py`,
  `context_refs_smoke.py`, `desktop_tools_smoke.py` and `hermes_ui.py` were not
  run on Podman. They use custom fixture models, `network_mode: none` or no
  network and do not need deployment overlays, but P5 must route their engine
  commands correctly and requalify affected behavior.
