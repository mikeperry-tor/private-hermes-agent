# Architecture and isolation

Implementation details for maintainers. For setup and everyday use, start with
[the README](../README.md).

Hermes's agent and its code executor run in separate containers, filesystems,
process namespaces, and network namespaces. Both have only isolated internal
container networks. Their public TCP traffic is transparently redirected through
an independently running Tor gateway; their DNS goes to Tor. Teep alone has a
separate direct uplink for confidential-computing inference providers.

```text
Hermes agent ── private SSH ── executor (/workspace, no agent volume or keys)
      │                           │
      ├── internal inference      └── executor route ─┐
      │      └── teep ── direct internet              │
      ├── selected MCP IP:port grants                ▼
      └── agent route ──────────────────────── transparent Tor ── internet
```

No application receives a container-engine socket, host networking, privileged mode,
`NET_ADMIN`, or `NET_RAW`. The trusted `agent-net` and `executor-net` services
configure routes and firewall rules before applications start, then drop to
UID/GID 65534 with every capability set empty and remain as stable namespace
owners. Tor is in a third namespace and likewise drops to UID 101/GID 102 with
empty sets after initialization; impersonating Tor's UID inside an application
cannot grant a direct uplink.

## Network and execution boundaries

- Internal networks use `gateway_mode: isolated` for IPv4 and IPv6, so their
  bridges have no host-side address. Neither application has an uplink.
- Each namespace also has a default-deny firewall. Agent grants are limited to
  executor SSH at `10.203.82.3:2222`, teep at `10.203.83.3:8337`, configured MCP
  IP/port pairs, and DNS at its Tor router. The executor gets only Tor DNS,
  public TCP through Tor, and replies to agent-initiated SSH connections.
- Other private, shared-address, loopback (outside its own local process
  namespace), link-local, multicast, reserved, and connected-network targets
  are denied. This covers ordinary Docker VM/host gateways, RPC port 111,
  metadata addresses, and DNS answers that point into prohibited space.
  Docker embedded DNS at `127.0.0.11` is blocked before DNAT.
- Private GRE links carry original-destination packets across internal bridges;
  plain next-hop routing is blocked by Docker's internal bridge rules. The same
  GRE topology is used on Podman. The links stay within the container host or
  Docker Desktop VM; they are not Internet tunnels or encryption.
  Only the trusted namespace services create them. Linux GRE support is required;
  setup fails closed if it is unavailable.
- The router independently blocks prohibited destinations before NAT and
  blocks all IP forwarding. It terminates permitted traffic at Tor's TransPort
  and DNSPort. Tor's own outbound connections cannot reach private destinations.
- This deployment intentionally blocks non-loopback IPv6 and unsupported UDP,
  including QUIC. Tor DNS supports A, AAAA, and PTR over UDP; it is not a general
  DNS server. Public TCP is routed through Tor, not destination-allowlisted.
- These controls cover the host/VM's private and connected address space. A
  service exposed on an unrelated public Internet IP is still a public target;
  add an explicit deny rule if such an address must be excluded too. A host
  administrator or compromised container engine remains outside this boundary.
- Hermes terminal commands, remote Python `execute_code`, and backend-aware
  file tools use SSH. Native subagents remain orchestrator instances; their
  code calls use this executor. Sessions/subagents share one executor user and
  workspace: this is agent/executor separation, not tenant or per-task isolation.
- Provider credentials and the agent data directory are not mounted into the
  executor. Hermes can intentionally synchronize skills, selected caches, and
  skill/operator-declared credential files to remote backends. Keep
  `terminal.credential_files` and skill passthrough declarations under review.
  Code's authorized Hermes tool RPC remains a capability, not a network bypass.
  The executor's browser profile is excluded from native SSH sync-back archives;
  it remains in its persistent home mount. Its live socket symlinks must not
  prevent selected skills/caches from synchronizing through the native mechanism.
- SSH is key-only, with pinned host identity. Password login, TCP/agent
  forwarding, tunnels, and root login are disabled. The SSH daemon has only
  the capabilities needed for privilege separation; executed code runs as
  unprivileged UID 10000 with no capabilities.
- Tor failure blocks public egress; established application namespaces keep
  their firewall rules and have no direct fallback. Existing local teep/MCP/SSH
  paths remain usable. Initial startup waits for Tor readiness.

Do not independently restart or recreate `agent-net` or `executor-net` while
their application containers exist. Namespace-sharing containers can retain the
old namespace rather than reattach to the replacement. This is a longstanding
Docker shared-network-namespace lifecycle limitation, reported in
[Compose #6626](https://github.com/docker/compose/issues/6626) and
[Compose #11872](https://github.com/docker/compose/issues/11872); container restart
policies do not guarantee dependency ordering or namespace reattachment after a
crash or host restart. Independent owner restart is unsupported on either engine;
Podman reattachment has not been qualified. This limitation predates the
capability reductions and is not evidence of a failed privilege drop.
For namespace-owner recovery or network-policy changes, run `make down` followed
by `make up` to recreate the stack together.
This preserves persistent data. Tor has its own namespace and can be restarted
independently; its outage/recovery behavior is qualified separately.

## Optional onion ingress

The base stack always includes isolated `onion-ingress` (`10.203.86.0/24`),
connecting only Tor (`.2`) and HAProxy (`.3`). `TOR_ONION_ENABLED` defaults false
and changes publication/listeners/grants, not membership or Compose selection.
Enabled Tor OUTPUT admits only UID 101 TCP from `10.203.86.2` to
`10.203.86.3:8080` before private-destination denial. Existing raw PREROUTING
denial still prevents agent/executor traffic from using this private exception.
HAProxy admits new connections only from that Tor address on the onion listener;
its only outbound backend remains `10.203.85.2:9120`. Disabled mode has neither
new-connection grant nor onion listener/HiddenService configuration. The Podman
overlay adds `isolate: strict` for this network like the other internal bridges.

`onion-inspect` and `onion-init` are networkless, dependency-free maintenance
jobs using the existing network image and only the Tor bind. Inspection mounts
it read-only; initialization runs native Tor with DisableNetwork=1 and drops all
child capabilities. Its trusted parent retains KILL only to stop/reap the
UID-101 child; serving Tor receives no extra capability. It preserves native
keys and reconstructs derived files.
The host target serializes mutation and requires removal of the runtime Tor
container before writing, so a paused/restarting service cannot resume as a
concurrent writer. Reading a saved address has no such restriction.
Tor itself replaces malformed secret files, so the wrapper checks the native
secret header/length before repair and enabled runtime start. This guard protects
identity preservation, not an additional cryptographic identity certification.
No serving component gains Tor-state access. See [onion operations](webapp.md#optional-onion-ingress).

## Rootless Podman

Managed container creation checks required bind sources in the effective Compose
model before creating containers or networks. This applies to both engines,
including offline setup/treasury jobs and `stack.py compose up/create/run/scale`.
Checks follow selected services and dependencies; `--no-deps` excludes dependency
mounts, and run-volume overrides replace mounts at the same target. Noncreating
inspection, shutdown and exec remain available. Unsupported creation commands
and watch recreation are refused; use explicit supported commands. Managed `make down` and wrapper `compose down` include all profiles so stopped treasury namespace users
are removed before their owner; operator volumes are preserved unless explicitly
removed. Use `stop` for selected services instead of project-wide shutdown. Bare Compose
bypasses the bind check. It prevents ordinary missing-source mistakes but cannot
prevent concurrent host deletion after checking; Podman 5.4.2's compatible API
still lacks native enforcement of `create_host_path: false`.


The same topology and boundaries apply on rootless Podman. `CONTAINER_ENGINE`
(`docker` or `podman`, from the environment or root `.env`, default `docker`)
selects the engine; any other value is an error, never a fallback.
`scripts/deployment.py` builds every engine and Compose command from that
selection: `docker` and `docker compose`, or the local `podman --remote=false`
and `podman --remote=false compose`. With Podman it adds `compose.podman.yaml`,
and `compose.podman.funnel.yaml` with Funnel, as the last Compose files, after
any file a command adds.

With Podman, the stack removes `DOCKER_HOST`, `DOCKER_CONTEXT`, `CONTAINER_HOST`
and `CONTAINER_CONNECTION` from the environment of its commands: `podman compose`
passes an inherited `DOCKER_HOST` to its Compose provider. Inspection, backup and
shutdown then use the local Podman; a launch refuses to start while one of these
variables is set (`make up` checks this before preflight and setup). The Make
targets run the Podman command without these variables too. Before each launch
(`make up`, treasury startup and wallet creation, the test fixtures, and every
`stack.py compose` subcommand except those that create no network, such as
`config`, `ps`, `logs`, `exec`, `stop`, `down` or `build`; `run` is exempt only
when the job and all dependencies use `network_mode: none`), `deployment.prepare_launch()` checks the
engine: on Docker, Docker Engine 28+ (not Podman behind a `docker` command) and
Compose 2.36+; on Podman, rootless 5.4+, the user API socket, and Docker Compose
2.36+ as the provider. `stack.py compose` reads the global options before the
subcommand (`-p`, `--profile`, `-f`, `--env-file`, `--project-directory`,
`--dry-run`) and uses them for settings validation, ingress selection,
preparation, the command and cleanup alike; it
refuses other global options.
Native `--dry-run` placement after the subcommand is also recognized, including
`up`, `run` and `down`; a container command's own `--dry-run` argument is not a
Compose flag. Dry runs neither prepare nor remove real project networks.
Shared-namespace runs and none-mode jobs with dependencies can create their
owner's/dependencies' networks even with `--no-deps`, so they are prepared too.
Named offline maintenance jobs reject overrides that network the job or its
dependencies; inspection and repair retain their networkless path. Treasury
one-shot work uses the same launch classification as stack startup, so engine
policy is checked before online wallet preparation, not only at later activation.

Compose creates networks through Podman's Docker-compatible API, which sets
only `isolate=true` and drops other bridge options. Before Compose starts
services, `deployment.ensure_networks()` therefore creates each project network
with the `podman` command, using the options the overlays declare and Compose's
labels; Compose adopts these networks, and `make down` removes them. Every
non-external network must declare `isolate: strict`; a network without it, or an
existing network that is not a bridge network of this project or lacks the
declared options, stops startup.

| Docker behavior | Rootless Podman counterpart |
| --- | --- |
| Isolated gateway mode: internal bridges have no host-side address | Rootless bridges live in the user's network namespace, so the gateway is not a host address. The endpoint firewalls deny connected networks and `169.254.0.0/16` on both engines. |
| No forwarding between different bridge networks | Netavark forwards between bridges unless they are isolated. Every network has `isolate=strict`, which also blocks traffic from the user's other networks without isolation. |
| `enable_ip_masquerade: false` on `webapp-publish` | `no_default_route=true`: HAProxy has no default route. |
| Published ports enter on the publication interface | The rootless port forwarder runs inside HAProxy's namespace and connects over loopback to one of its addresses. The local frontend listens on all proxy addresses, and the proxy firewall admits new connections to the webapp port only on `lo`, so traffic from connected networks stays dropped. HAProxy's `X-Forwarded-For` value is therefore a proxy address for every client. |
| Embedded DNS at `127.0.0.11` | aardvark-dns at each network gateway, denied by the endpoint firewalls with the connected networks. teep resolves provider names through it on `teep-uplink`. |
| `healthcheck.start_interval`, `gw_priority` | Removed by the overlay. Podman's API refuses `start_interval`. `gw_priority` is not needed: the other network of teep and Tailscale is internal and gives no default route. |
| Unprivileged processes may bind any port (`net.ipv4.ip_unprivileged_port_start=0`) | Podman sets the floor to 1024 in a container. The overlay sets 0 for HAProxy so that it can bind a low port inside its namespace. This does not let the rootless user publish a host port below the host's own floor (`net.ipv4.ip_unprivileged_port_start`, usually 1024): keep `WEBAPP_PORT` and `TEEP_HOST_PORT` at 1024 or above unless the host allows lower ports. Publication then fails with the engine's own error. |
| Docker desktop uses a pinned Moby-derived seccomp profile with Chromium namespace allowances | Both lean and desktop Podman executors use the native default seccomp policy, with no-new-privileges and Chromium sandboxing retained. Native policy differs from Docker's profile. Custom file profiles remain unsupported through the configured Compose API: it sends inline JSON while Podman expects a filename; preflight diagnoses those overrides. |
| Empty executor `/tmp` and `/run` tmpfs mounts | Podman's overlay sets `notmpcopyup`, retaining the same modes and destinations. This prevents image-seeded files owned by upstream UID 1000 from blocking runner UID 10000's runtime setup. |
| Restart backoff | A container that exits at once restarts about every 0.3 s. Startup refuses to run without an inference provider key, on both engines, because teep exits at once without one. Check `podman ps` and restart counts when a service does not become healthy. |

Pasta maps `169.254.1.2` to the host's own address, not to host loopback. A
host service bound to the host's address (or to all addresses) is reachable
there from teep, which has a direct uplink and no endpoint firewall; Hermes, the
executor, Tor and HAProxy did not reach it (`make podman-paths-test`). This is
teep's accepted direct uplink. On Docker, teep is expected to reach the host
through its uplink gateway in the same way; this is not tested on Docker. Do not run
host services that trust local network peers while the stack runs. A service
bound only to `127.0.0.1` is not reachable at `169.254.1.2`. Tailscale was not
tested.

Bind data under `data/` is owned by subordinate user IDs on the host; use
`podman unshare` for host-side copies (see [backup scope](configuration.md#backup-scope)).
`tests/podman_paths_smoke.sh` checks the allowed and forbidden paths of a running
Podman stack, including a client on a network without isolation.

## Images and other Hermes isolation choices

- Tor: `dockurr/tor:0.4.9.16`, pinned by digest in
  `components/network/Dockerfile`. The derived image adds our firewall/route setup
  and local authenticated bootstrap health check. Tor runs as UID 101 after
  initialization with empty capability sets; there is no TCP control API, TCP
  SOCKS service, or HTTP proxy.
  A private SOCKS Unix socket is mounted only into the x402_treazury container.
- Hermes: derived from official v0.23.1, with base digest and explicit source
  checks in `components/hermes/`. Runtime and maintenance share the derived
  image; see [patch/build procedure](updates-and-plugins.md#derived-hermes-build-and-patch-maintenance).
- teep: built from commit `eecd7e41a6d9f0b5a8324f2c174e25c831b9c941`
  with Go 1.26. It runs as UID 10002, read-only except temporary files, without
  `--offline`, `--force`, or debug tags. Upstream's default attestation policy
  (including allowed failures) is preserved. Health is not proof of attestation.
- Executor: lean Alpine by default, or a pinned Debian desktop sandbox selected
  by `COMPUTER_USE_ENABLED`. Both have Python, Node, Git, SSH, curl, read-only root
  and separate writable home/workspace. The desktop adds Xvnc/Xfce, Chromium and
  cua-driver and an isolated browser-harness environment, with no new container capabilities. Base tags and OS packages can
  change on rebuild; review/pin further when qualifying upgrades.

Browser automation's trusted gateway helper starts an SSH stdio launcher for each
harness identity. The launcher and native harness daemon live in the executor;
each model program runs in a separate executor process group. The existing native
owner-death supervisor covers the gateway's SSH process group. Closing that
connection stops the remote program and daemon; native session cleanup closes the
same owner. Program output is data, and screenshot paths are fetched from the
executor into generated gateway cache files through native bounded transfer.
No model program, workspace helper or printed path is imported/opened as gateway
code or a gateway-selected file. Native session bookkeeping may retain its
gateway-loopback CDP forward; remote Python uses the executor-local endpoint.
No published endpoint or internal network grant is added.

### Executor capability requirements

On 2026-11-11, disposable networkless Docker Desktop ARM64 experiments tested
the optional Debian 13 desktop executor's OpenSSH listener with all capabilities
dropped, then selectively restoring `SETUID`, `SETGID`, and `SYS_CHROOT`.
Key-only login to runner UID 10000 succeeded with those three. Removing each
independently reproduced a native failure:

| Removed capability | Observed authentication failure | Responsibility |
| --- | --- | --- |
| `SYS_CHROOT` | `chroot("/run/sshd"): Operation not permitted [preauth]` | OpenSSH's pre-authentication privilege separation |
| `SETUID` | `setresuid 997: Operation not permitted [preauth]` | Drop to the image's unprivileged SSH account, then create runner sessions |
| `SETGID` | `setgroups: Operation not permitted [preauth]` | Clear supplementary groups during privilege separation/session setup |

The test used the pinned desktop base index
`c7d8607d076f26a64e0bd6828f74e1764af43fe3281368188459bb693bfa7567`,
Debian OpenSSH `1:10.0p1-7+deb13u4`, a root listener, generated fixture keys,
`UsePAM=no`, read-only root, writable `/run` and `/tmp`, and
`no-new-privileges`. No host network, external connection or real credentials
were involved. This establishes why the current listener retains these grants;
it does not establish every alternative SSH design's minimum or qualify Alpine,
AMD64 or Podman by inference. UID 997 is image-specific.

Desktop software adds no container capability requirement. Its Chromium sandbox
needs user-namespace syscalls allowed by the desktop seccomp profile; those are
distinct from capability grants. A non-root process can gain capabilities within
a new child user namespace without acquiring authority over the parent-owned
executor network namespace. Qualify parent-namespace restrictions separately.
Actual ARM64 SSH desktop qualification found UID 10000, empty effective,
permitted, inheritable and ambient sets, and `NoNewPrivs=1` for Xvnc, xfwm4,
xfdesktop, xfce4-panel and cua-driver. The listener's capability bounding set is
not a claim that every child retains those effective privileges. Chromium's own
diagnostics reported namespace, PID/network-namespace and seccomp-BPF sandbox
layers enabled; nested user-namespace root was unable to rejoin the parent-owned
network namespace or create a raw socket in it.
Keep effective/permitted capability evidence for runner processes distinct from
the root listener's grants and from namespace-local browser sandbox capabilities.
Both-engine Docker/Podman qualification measured authenticated runner sessions at
UID 10000 with empty effective, permitted, inheritable and ambient sets and
bounding set `0x400c0`; that residual is not authority in the executor's original
user namespace under `NoNewPrivs=1` with no file capabilities. `SYS_CHROOT`
remains a functional desktop/Podman Chromium sandbox requirement and is not
security-only cleanup. See [development checks](development.md#executor-desktop-qualification) and the
[qualification record](development.md#qualification-and-maintenance).

### Hermes capability boundary

Hermes starts as root for the native s6 bootstrap and supervision. Its explicit
container grants are `CHOWN`, `DAC_OVERRIDE`, `FOWNER`, `KILL`, `SETUID` and
`SETGID`; both-engine lifecycle probes showed each is required for profile
readiness, permission repair or clean shutdown. Engine defaults not used by that
lifecycle, including `NET_ADMIN`, `NET_RAW`, `SETPCAP`, `SYS_CHROOT` and `MKNOD`,
are dropped. Dropped application processes have empty effective, permitted,
inheritable and ambient sets; they inherit bounding set `0xeb`, which is not
authority under `NoNewPrivs=1` with no file capabilities. Clearing that bounding
set would require replacing the native s6 drop or adding a helper and is deferred.

Root services and profile wrappers share a `PATH`. The user-writable profile
wrapper directory `/opt/data/.local/bin` is placed last so root s6, cont-init and
wrapper command lookup prefers trusted directories, while uniquely named profile
wrappers still resolve. This closes the demonstrated path where a UID-10000
`sleep` in the writable directory ran as root after restarting the static service.

Additional Hermes controls were reviewed: `HERMES_WRITE_SAFE_ROOT` guards
selected file tools but not arbitrary shell code; Python `code_execution.mode:
strict` changes staging/interpreter selection, not OS containment. Iron-proxy
can broker additional SDK credentials and enforce HTTP destination policies;
its default host-proxy wiring is not enabled here. Cloud microVM backends and
an external VM executor offer stronger kernel separation, but introduce a
separate runtime/provider. No newly identified mode replaces this SSH design.
