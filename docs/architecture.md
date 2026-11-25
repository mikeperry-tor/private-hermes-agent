# Architecture and isolation

Implementation details for maintainers. For setup and everyday use, start with
[the README](../README.md).

Hermes and its code executor run in separate containers, filesystems, process
namespaces, and network namespaces. Both connect only to isolated internal
container networks. Public TCP traffic from both namespaces routes transparently
through an independent Tor gateway, and DNS resolves through Tor. Only Teep has
a direct Internet uplink for confidential-computing inference providers.

```text
Hermes agent -- private SSH -- executor (/workspace, no agent volume or keys)
      |                           |
      +-- internal inference      +-- executor route -+
      |      +-- teep -- direct internet              |
      +-- allowed MCP IP:port grants                  v
      +-- agent route ------------------------ transparent Tor -- internet
```

No application container receives a container-engine socket, host networking,
privileged mode, `NET_ADMIN`, or `NET_RAW`. The `agent-net` and `executor-net`
services configure routes and firewall rules before applications start, then
drop to UID/GID 65534 with empty capability sets and remain running as stable
namespace owners. Tor runs in a third namespace and drops to UID 101 / GID 102
with empty capability sets after initialization, so impersonating Tor's UID
inside an application container cannot grant a direct uplink.

## Network and execution boundaries

### Network isolation and default-deny firewalls

- **No host-side bridge gateways:** Internal networks use
  `gateway_mode: isolated` for IPv4 and IPv6, so their bridges have no host-side
  address. Neither Hermes nor the executor has a direct uplink.
- **Per-namespace firewall rules:** Both `agent-net` and `executor-net` install
  default-deny firewalls.
  - Hermes can reach executor SSH at `10.203.82.3:2222`, Teep at
    `10.203.83.3:8337`, allowed MCP IP and port pairs, and DNS on its Tor
    router. Operators can also grant the Hermes UID specific host TCP ports and
    RFC1918 `address:port` pairs through the gateway.
  - The executor can reach only Tor DNS, public TCP through Tor, and replies to
    agent-initiated SSH connections.
- **Blocked destinations:** Private, shared-address, loopback (outside a
  container's own namespace), link-local, multicast, reserved, and
  connected-network targets are denied by default. This blocks Docker host and
  VM gateways, RPC port 111, cloud metadata addresses, and DNS answers pointing
  into private space. Docker's embedded DNS at `127.0.0.11` is blocked before
  DNAT.
- **Protocol restrictions:** Non-loopback IPv6 and unsupported UDP (including
  QUIC) are blocked. Tor DNS handles A, AAAA, and PTR queries over UDP and is
  not a general DNS server. Public TCP is routed through Tor rather than
  destination-allowlisted.
- **Scope of network controls:** These rules cover the host and VM private and
  connected address space. A service exposed on a public Internet IP is still a
  public target; add an explicit deny rule if it must be excluded. A host
  administrator or compromised container engine is outside this boundary.

### GRE transport and local socket forwarding

Private GRE links carry original-destination packets across internal bridges,
because Docker's internal bridge rules block plain next-hop routing. Podman uses
the same GRE topology. These links stay inside the container host or Docker
Desktop VM; they do not encrypt traffic or cross the Internet.

Only `agent-net`, `executor-net`, and `tor` create GRE interfaces. Linux GRE
support is required, and startup fails if it is unavailable. The GRE MTU is
1,400 bytes for both the Tor path and the internal leg of host and LAN
forwarding. Tor opens separate outbound sockets on its uplink, where the uplink
route sets the MTU.

The `tor` router starts with IPv4 forwarding disabled and installs a
default-drop forwarding policy before enabling host or LAN exceptions:

- Each forwarding rule matches the agent GRE tunnel, source address, granted
  destination, backend address, and uplink in both directions.
- IPv4 fragmentation-needed ICMP replies pass only when connection tracking ties
  them to a granted flow.
- Hermes uses a reserved IPv4 alias across the tunnel so the router can
  distinguish host-port grants from literal LAN grants. The container engine's
  host mapping stays inside the gateway.
- IPv6 forwarding remains closed. Public traffic terminates at Tor's `TransPort`
  and `DNSPort`, and Tor's own outbound connections cannot use host or LAN
  exceptions.
- Managed Hermes clears `HTTP_PROXY`, `HTTPS_PROXY`, and `ALL_PROXY` so
  inference and MCP clients rely on the firewall and gateway instead of a second
  allowlist.

When host-port or LAN grants are enabled, startup allows `tor` to write to
`/proc/sys/net/ipv4/ip_forward` after installing its firewall rules:

- On Podman, `/proc/sys` is exposed to `tor`.
- On Docker, `tor` uses `systempaths=unconfined` (which removes Docker's default
  masked and read-only system paths) and recalculates TCP checksums on GRE
  return traffic after NAT.
- Native Linux Docker keeps default system-path protections for LAN-only
  configurations because Docker LAN forwarding requires Docker Desktop.
- Empty grant lists keep default system-path protections on both engines.
- Hermes and the executor always keep their default system-path protections, and
  `tor` drops its initialization capabilities before starting the Tor daemon.

### Code execution and SSH isolation

Model terminal commands, Python execution, and project file tools run over SSH
in the executor. A subagent starts in its parent's executor directory and
resumes in its own last saved directory. Scheduled scripts and enabled inline
skill commands also run as `runner`. Each session shares UID 10000 and the
executor's workspace. Isolation separates Hermes from executed code.

- Provider credentials and the `hermes-data` volume are not mounted in the
  executor.
- Hermes can copy approved profile skills, caches, and operator-declared
  credentials to the executor. An operator can trust project skills by their
  verified executor checkout. Those skills can read their own supporting files
  and use installed executor dependencies. Hermes does not register their
  requests for profile environment variables, credential files, or packages.
- The managed project list comes from the applied mounts. Project-aware
  commands refuse work when SSH or the saved directory is unavailable. Existing
  transcripts and job records stay available for inspection. Managed SSH
  checkpoints, delegated Git worktree isolation, and Kanban worktree workers
  decline workspace operations that require a local checkout.
- Code running in the executor can invoke allowlisted Hermes tools over RPC;
  this is an authorized tool capability, not a network bypass.
- The executor's browser profile stays in its persistent home mount and is
  excluded from SSH sync-back archives so live socket symlinks do not break
  skill and cache synchronization.
- The built-in home and workspace mounts hold files that executor code can
  change. Review those files before using host tools that can run them. See
  [reviewing changes in the executor](configuration.md#reviewing-changes-in-the-executor).
- SSH allows key-based authentication only, with a pinned host key. Password
  login, TCP forwarding, agent forwarding, tunnels, and root login are disabled.
  The Hermes image packages its SSH client configuration as a root-owned file
  so OpenSSH accepts it under the unprivileged Hermes account.
  The SSH daemon keeps only the capabilities required for privilege separation;
  executed code runs as UID 10000 with empty capability sets.

### Failure behavior and shared-namespace restarts

If Tor fails, public egress stops, while `agent-net` and `executor-net` keep
their firewall rules. Local Teep, internal MCP, and SSH continue working after
startup. Host and LAN forwarding also survives Tor circuit failure as long as
the `tor` container's network namespace stays up, though stopping or restarting
`tor` interrupts active local connections. Initial startup waits for Tor
bootstrap.

Do not restart or recreate `agent-net` or `executor-net` while their application
containers exist. Containers sharing a network namespace can remain stuck in the
old namespace instead of attaching to the replacement. This is a known Docker
limitation ([Compose #6626](https://github.com/docker/compose/issues/6626),
[Compose #11872](https://github.com/docker/compose/issues/11872)), and restart
policies do not guarantee dependency ordering or reattachment after a crash or
host reboot. Independent owner restarts are unsupported on both Docker and
Podman (Podman reattachment has not been tested).

To recover a namespace owner or apply network-policy changes, recreate the stack
together with `make down` followed by `make up`. Persistent data is preserved.
Tor runs in its own namespace and can be restarted independently.

## Optional onion ingress

The base stack always creates the isolated `onion-ingress` network
(`10.203.86.0/24`), connecting only Tor (`.2`) and HAProxy (`.3`).
`TOR_ONION_ENABLED` (default `false`) toggles HiddenService publication, the
HAProxy onion listener, and firewall grants without changing network membership
or Compose overlays.

- When enabled, Tor's `OUTPUT` rules allow only UID 101 TCP from `10.203.86.2`
  to `10.203.86.3:8080` ahead of private-destination denial. Raw `PREROUTING`
  rules still block Hermes and executor traffic from reaching that address.
- HAProxy accepts new connections on the onion listener only from `10.203.86.2`,
  and its only outbound backend remains `10.203.85.2:9120`.
- When disabled, neither the firewall grant nor the onion listener or
  HiddenService configuration is present.
- The Podman overlay adds `isolate: strict` to `onion-ingress` alongside the
  other internal bridges.

`onion-inspect` and `onion-init` are networkless maintenance jobs that reuse the
network image and mount only `data/tor/`:

- `onion-inspect` mounts `data/tor/` read-only.
- `onion-init` runs Tor with `DisableNetwork=1` and drops all child
  capabilities. Its parent process retains `KILL` only to stop and reap the
  UID-101 child; serving Tor receives no extra capabilities.
- `make onion-address` serializes writes and requires the runtime `tor`
  container to be removed (`make down`) before creating or repairing files, so a
  paused or restarting Tor container cannot write concurrently. Reading an
  existing address has no such restriction.
- Because Tor replaces malformed secret files on its own, the wrapper checks the
  secret key header and length before repair or enabled startup to protect the
  saved identity from silent rotation.

No serving component other than Tor mounts `data/tor/`. For operator commands
and recovery steps, see [optional onion ingress](webapp.md#optional-onion-ingress).

## Rootless Podman

The same network topology and isolation boundaries apply on rootless Podman.
`CONTAINER_ENGINE` (`docker` or `podman`, set in the environment or root `.env`,
default `docker`) selects the engine; any other value raises an error without
falling back.

`scripts/deployment.py` builds every engine and Compose command from that
selection: `docker` and `docker compose`, or local `podman --remote=false` and
`podman --remote=false compose`. Under Podman, it appends `compose.podman.yaml`
(and `compose.podman.funnel.yaml` when Funnel is enabled) after all other
Compose files.

### Environment sanitization and launch checks

Under Podman, the stack strips `DOCKER_HOST`, `DOCKER_CONTEXT`,
`CONTAINER_HOST`, and `CONTAINER_CONNECTION` from subprocess environments
because `podman compose` forwards an inherited `DOCKER_HOST` to its Compose
provider. Inspection, backup, and shutdown then target local Podman, while
container launches refuse to start if any of those variables is set (`make up`
checks this before preflight and setup).

Before launching containers, `deployment.prepare_launch()` verifies engine
versions and prerequisites:

- **Docker:** Docker Engine 28+ (rejecting Podman shimmed behind a `docker`
  binary) and Compose 2.36+.
- **Podman:** rootless Podman 5.4+, an active user API socket, and official
  Docker Compose 2.36+ as the provider.

This check runs for `make up`, treasury initialization and preparation, test
fixtures, and `stack.py compose` commands that create networks. Read-only and
shutdown commands (`config`, `ps`, `logs`, `exec`, `stop`, `down`, `build`) are
exempt, as is `run` when the job and all of its dependencies use
`network_mode: none`. Shared-namespace `run` commands and `none`-mode jobs with
networked dependencies still trigger network preparation even with `--no-deps`.
Offline maintenance jobs reject CLI overrides that attach a network to the job
or its dependencies.

`stack.py compose` accepts `-p`, `--profile`, `-f`, `--env-file`,
`--project-directory`, and `--dry-run` before the subcommand and applies them
consistently across validation, overlay selection, network preparation, and
cleanup; other global flags are rejected. It also recognizes `--dry-run` after
subcommands such as `up`, `run`, and `down` (ignoring `--dry-run` passed to a
container command). Dry runs neither create nor remove container networks.

### Bind-source checks and network creation

On both Docker and Podman, managed container creation checks that required bind
sources exist in the effective Compose model before creating containers or
networks. This covers `make up`, offline setup and treasury jobs, and
`stack.py compose up/create/run/scale`:

- Checks follow the targeted services and their dependencies (`--no-deps`
  excludes dependency mounts, and `run -v` overrides replace mounts at the same
  target).
- Inspection, shutdown, and `exec` bypass the check. Unsupported creation
  commands and `watch` recreation are refused.
- `make down` and `stack.py compose down` include all profiles so stopped
  treasury containers sharing `agent-net` are removed before their namespace
  owner; named volumes are preserved unless removed with `-v`. Use `stop` to
  halt individual services.
- Bare Compose bypasses the bind check. The check catches missing host paths
  before launch, though it cannot prevent concurrent host deletion afterward
  (Podman 5.4.2's Docker-compatible API does not enforce
  `create_host_path: false`).

Managed startup adds configured project binds only to the executor. It checks
sources from the host before starting containers. On rootless Podman, it
also compares the API service's filesystem view. It checks the selected
mount sources again before creating the executor.
Project shares grant the executor write access to host files under the chosen
directories. See [security considerations for shared projects](configuration.md#security-considerations-for-shared-projects).

Compose creates networks through Podman's Docker-compatible API, which preserves
only `isolate=true` and drops other bridge options. Before Compose creates
containers, `deployment.ensure_networks()` creates the project's networks
directly with `podman`, keeping all declared options and Compose labels. Compose
adopts those networks, and `make down` removes them. Every non-external network
must declare `isolate: strict`; missing options or a mismatched existing network
halts startup.

### Engine differences

| Docker behavior | Rootless Podman counterpart |
| --- | --- |
| `gateway_mode: isolated` gives internal bridges no host-side address | Rootless bridges live in the user's network namespace, so their gateways are not host addresses. Endpoint firewalls deny connected networks and `169.254.0.0/16` on both engines. |
| No forwarding between different bridge networks | Netavark forwards between bridges unless isolated. Every network sets `isolate=strict`, which also blocks traffic from the user's non-isolated networks. |
| `enable_ip_masquerade: false` on `webapp-publish` | `no_default_route=true`, leaving HAProxy with no default route. |
| Published ports enter on the publication interface | The rootless port forwarder runs inside HAProxy's namespace and connects over loopback. The local frontend listens on all proxy addresses, and the proxy firewall admits new webapp connections only on `lo`, dropping traffic from connected networks. As a result, HAProxy sees a proxy address in `X-Forwarded-For` for every client. |
| Embedded DNS at `127.0.0.11` | `aardvark-dns` at each network gateway, blocked by endpoint firewalls along with connected networks. Teep resolves provider names through it on `teep-uplink`. |
| `healthcheck.start_interval` and `gw_priority` | Removed by `compose.podman.yaml`. Podman's API rejects `start_interval`, and `gw_priority` is unnecessary because Teep's and Tailscale's second networks are internal and provide no default route. |
| `net.ipv4.ip_unprivileged_port_start=0` lets unprivileged processes bind any port | Podman defaults this floor to 1024 inside containers. The overlay sets it to 0 for HAProxy so it can bind low internal ports. Host port publication still follows the host's own floor (usually 1024): keep `WEBAPP_PORT` and `TEEP_HOST_PORT` at 1024 or above unless the host lowers its floor. |
| Desktop executor uses a pinned Moby-derived seccomp profile with Chromium namespace allowances | Both lean and desktop Podman executors use Podman's default seccomp policy, keeping `no-new-privileges` and Chromium sandboxing. Custom file seccomp profiles are unsupported through the Compose API because Compose sends inline JSON while Podman expects a file path; preflight flags those overrides. |
| Empty executor `/tmp` and `/run` tmpfs mounts | The overlay sets `notmpcopyup` with the same modes and targets so image-seeded files owned by upstream UID 1000 do not block runner UID 10000. |
| Standard restart backoff | A container that exits immediately restarts roughly every 0.3 s. Check `podman ps` and restart counts if a service fails to become healthy (for example, when Teep is enabled without an API key). |

Pasta's native host alias reaches the host's interface address rather than host
loopback. Bind any granted host service to that reachable interface address; a
loopback-only listener is unreachable through the alias. Teep's direct uplink
can also reach host services on that interface, whereas the executor, Tor, and
HAProxy cannot use Hermes's host grants. See
[local inference and HTTP MCP](configuration.md#local-inference-and-http-mcp).

Bind data under `data/` is owned by subordinate UIDs on the host. Copy it inside
the user namespace with `podman unshare` (see
[backup scope](configuration.md#backup-scope)). `tests/podman_paths_smoke.sh`
tests allowed and forbidden paths on a running Podman stack, including a client
on a non-isolated network.

## Component images and runtime isolation

- **Tor:** `dockurr/tor:0.4.9.17`, pinned by digest in
  `components/network/Dockerfile`. The derived image adds route and firewall
  setup and a local authenticated bootstrap health check. After initialization,
  Tor runs as UID 101 with empty capability sets and exposes no TCP control API,
  TCP SOCKS port, or HTTP proxy. Only `x402_treazury` mounts its private SOCKS
  Unix socket.
- **Hermes:** derived from official Hermes v0.23.3, with base digest and source
  verification in `components/hermes/`. Runtime and offline maintenance share
  this image; see
  [derived Hermes build and patch maintenance](updates-and-plugins.md#derived-hermes-build-and-patch-maintenance).
- **Teep:** built from commit `6548996bb53ffa74e05d2b2f52e71534d1650149` with
  Go 1.26. It runs as UID 10002 with a read-only root filesystem (except
  temporary files) and without `--offline`, `--force`, or debug tags. Upstream's
  default attestation policy (including its allowed failures) is preserved. A
  passing health check does not prove attestation succeeded.
- **Executor:** a lean Alpine image by default, or a pinned Debian desktop image
  when `COMPUTER_USE_ENABLED=true`. Both include Python, Node, Git, SSH, and
  `curl`, with a read-only root filesystem and writable `/home/runner` and
  `/workspace` mounts. The desktop image adds Xvnc, Xfce, Chromium, `cua-driver`,
  and an isolated browser harness with no GUI-specific container capabilities.
  Base tags and OS packages can change on rebuild; review them when qualifying
  upgrades.

For browser automation, Hermes's gateway helper launches an SSH stdio process
per harness identity. The launcher and harness daemon run inside the executor,
and each model program runs in its own executor process group. Closing the SSH
connection stops both the remote program and the daemon via Hermes's
owner-death supervisor. Program output is treated as untrusted data, and
screenshots are copied into gateway cache files via bounded transfers; no model
program, workspace helper, or printed path is imported or opened directly by the
gateway. Session bookkeeping may keep a gateway-loopback CDP forward, while
remote Python connects to the executor-local CDP endpoint rather than any
published port or new internal grant.

### Executor capability requirements

The root SSH listener keeps four capabilities in both executor variants, plus
`AUDIT_WRITE` in the Debian desktop variant for interactive PTYs. These are
OpenSSH requirements for privilege separation, not privileges granted to model
commands.

| Capability | Responsibility and failure without it |
| --- | --- |
| `CHOWN` | Sets runner ownership on `/dev/pts`; PTY allocation fails without it. |
| `SETUID` | Drops to the unprivileged SSH account and starts runner sessions (`setresuid` fails without it). |
| `SETGID` | Clears supplementary groups during privilege separation (`setgroups` fails without it). |
| `SYS_CHROOT` | Supports OpenSSH pre-authentication chroot and Podman's Chromium namespace chroot. |
| `AUDIT_WRITE` (desktop only) | Submits Debian OpenSSH PTY audit records; sessions exit if `linux_audit_write_entry` is denied. |

The lean Alpine executor has bounding set `0x400c1`; the desktop executor has
bounding set `0x200400c1`. `AUDIT_CONTROL` is omitted, so audit submission
cannot modify audit policy. Read-only root filesystems, read-only key mounts,
and `no-new-privileges` stay enabled.

Authenticated runner sessions and GUI processes run as UID 10000 with empty
effective, permitted, inheritable, and ambient capability sets under
`NoNewPrivs=1`. The listener's bounding set does not grant those capabilities to
child sessions.

Desktop Chromium also requires user-namespace syscalls in the engine's seccomp
policy, independently of daemon capabilities. Chromium's sandbox uses user, PID,
and network namespaces plus seccomp-BPF. Becoming UID 0 inside a child user
namespace grants no control over the parent-owned executor network namespace:
joining it and creating raw sockets there are both denied. See
[executor desktop qualification](development.md#executor-desktop-qualification)
and [code terminal qualification](development.md#code-terminal-qualification).

### Hermes capability boundary

Hermes starts as root for s6 bootstrap and process supervision. Its container
capabilities are `CHOWN`, `DAC_OVERRIDE`, `FOWNER`, `KILL`, `SETUID`, and
`SETGID`, each required for profile readiness, permission repair, or clean
shutdown on both engines. Unused engine defaults (`NET_ADMIN`, `NET_RAW`,
`SETPCAP`, `SYS_CHROOT`, `MKNOD`, and others) are dropped.

After dropping privileges, application processes have empty effective,
permitted, inheritable, and ambient capability sets. They inherit bounding set
`0xeb`, which grants no authority under `NoNewPrivs=1` with no file
capabilities. Clearing that bounding set would require replacing s6's privilege
drop and is deferred.

Root services and profile wrappers share `PATH`. The writable profile wrapper
directory `/opt/data/.local/bin` sits last in `PATH` so root s6, `cont-init`,
and wrapper lookups prefer system directories, preventing a UID-10000 executable
from shadowing a root service command while still resolving uniquely named
wrappers.

Hermes tools and configuration provide these additional controls.

- With the SSH backend, `read_file` resolves paths and checks protected files on the executor.
  It records complete, unredacted text reads by SSH endpoint and file version.
- `search_files` checks each executor path before returning or counting matches.
  Multiline content search requires ripgrep on the executor.
- `HERMES_WRITE_SAFE_ROOT=/opt/data` limits local structured writes. The SSH
  file tools use the roots supplied by managed startup and refuse writes when
  that list is unavailable. They inspect the executor's requested path,
  resolved file, and directory entry. A whole-file replacement requires the
  task to have read every page without redaction or written the current version.
  The executor checks the version before publishing. SSH patches use the
  executor's permissions and keep instruction-file approvals.
  The executor mounts and runner permissions govern access to shared files.
  See [shared project permissions](configuration.md#shared-project-filesystem-permissions).
- The model's `text_to_speech` tool writes to the active Hermes profile's audio
  cache. Internal voice playback can supply a temporary output file.
- Filesystem checkpoints, rollback, and checkpoint-based session diffs are
  unavailable for SSH workspaces. Hermes keeps profile checkpoint records for
  administrative inspection.
- Python `code_execution.mode: strict` changes staging and interpreter
  selection, not OS containment.
- Iron-proxy can broker SDK credentials and enforce HTTP destination rules, but
  its default host-proxy wiring is disabled here.
- Cloud microVM backends and external VM executors offer stronger kernel
  isolation at the cost of a separate runtime or provider.

## WebApp terminal architecture

`WEBAPP_TERMINAL_ENVIRONMENT` selects **Code** (default, SSH executor) or
**Agent** (Hermes container shell) at process bootstrap, before profile dotenv
files load. The code-terminal patch modifies only the local-terminal preparation
branch, keeping Hermes's ticket authentication, profile ownership, PTY registry,
replay, resize, close, and expiry behavior intact. Saved gateway terminals keep
their separate remote path.

Remote working-directory validation runs outside the PTY registry lock so a slow
SSH probe does not block unrelated terminal operations. Local PTY creation uses
the profile home directory while session metadata reports the remote launch
directory.

Code shells reuse Hermes's SSH connection settings and client key with strict
pinned host verification, batch authentication, and forwarding disabled. OpenSSH
forwards resize events, input, and signals over a remote PTY. Human and model
commands share the same runner filesystem, process namespace, and Tor firewall
policy in both lean and desktop executors, with no extra network grants, mounts,
or services. Choosing Code mode does not remove an authenticated operator's
administrative WebApp authority. See
[terminal environment](webapp.md#terminal-environment).
