# Architecture and isolation

Implementation details for maintainers. For setup and everyday use, start with
[the README](../README.md).

Hermes's agent and its code executor run in separate containers, filesystems,
process namespaces, and network namespaces. Both have only isolated internal
Docker networks. Their public TCP traffic is transparently redirected through
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

No application receives a Docker socket, host networking, privileged mode,
`NET_ADMIN`, or `NET_RAW`. The trusted `agent-net` and `executor-net` services
configure routes and firewall rules before applications start, then remain as
stable namespace owners. Tor is in a third namespace; impersonating Tor's UID
inside an application cannot grant a direct uplink.

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
- Private GRE links carry original-destination packets across Docker's internal
  bridges; plain next-hop routing is blocked by Docker's internal bridge rules.
  The links are internal to the Docker VM, not Internet tunnels or encryption.
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
  administrator or compromised Docker engine remains outside this boundary.
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

## Rootless Podman

The same topology and boundaries apply on rootless Podman. `scripts/deployment.py`
selects `compose.podman.yaml`, and `compose.podman.funnel.yaml` with Funnel, as
the last Compose files, only when the engine identifies as Podman: the `docker`
command is Podman, or the server reports the `Podman Engine` component. Any
other answer selects Docker. On Podman, netavark then rejects the Docker bridge
options, so a missed detection stops startup instead of weakening isolation.

| Docker behavior | Rootless Podman counterpart |
| --- | --- |
| Isolated gateway mode: internal bridges have no host-side address | Rootless bridges live in the user's network namespace, so the gateway is not a host address. The endpoint firewalls deny connected networks and `169.254.0.0/16` on both engines. |
| No forwarding between different bridge networks | Netavark forwards between bridges unless they are isolated. The overlay sets `isolate: strict` on every network. |
| `enable_ip_masquerade: false` on `webapp-publish` | `no_default_route: "true"`: HAProxy has no route out. |
| Published ports enter on the publication interface | The rootless port forwarder runs inside HAProxy's namespace and connects over loopback to one of its addresses. The local frontend listens on all proxy addresses, and the proxy firewall admits new connections to the webapp port only on `lo`, so traffic from connected networks stays dropped. HAProxy's `X-Forwarded-For` value is therefore a proxy address for every client. |
| Embedded DNS at `127.0.0.11` | aardvark-dns at each network gateway, denied by the endpoint firewalls with the connected networks. teep resolves provider names through it on `teep-uplink`. |
| `healthcheck.start_interval`, `gw_priority` | Removed by the overlay. Podman's API refuses `start_interval`. `gw_priority` is not needed: the other network of teep and Tailscale is internal and has no gateway. |
| Restart backoff | A container that exits at once restarts about every 0.3 s. Startup refuses to run without an inference provider key, because teep exits at once without one. Check `podman ps` and restart counts when a service does not become healthy. |

Containers with an uplink can reach the host's loopback services through pasta
at `169.254.1.2`. The router denies this for Tor's own traffic; Hermes and the
executor have no uplink. teep has its direct uplink as on Docker.

Bind data under `data/` is owned by subordinate user IDs on the host; use
`podman unshare` for host-side copies (see [backup scope](configuration.md#backup-scope)).

## Images and other Hermes isolation choices

- Tor: `dockurr/tor:0.4.9.16`, pinned by digest in
  `components/network/Dockerfile`. The derived image adds our firewall/route setup
  and local authenticated bootstrap health check. Tor runs as UID 101 after
  initialization; there is no TCP control API, TCP SOCKS service, or HTTP proxy.
  A private SOCKS Unix socket is mounted only into the x402_treazury container.
- Hermes: derived from official v0.23.0, with base digest and explicit source
  checks in `components/hermes/`. Runtime and maintenance share the derived
  image; see [patch/build procedure](updates-and-plugins.md#derived-hermes-build-and-patch-maintenance).
- teep: built from commit `789918ea606826650447a7f1930b917521d3d135`
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
See [development checks](development.md#executor-desktop-qualification) and the
[capability reduction plan](plans/capability-reduction.md).

Additional Hermes controls were reviewed: `HERMES_WRITE_SAFE_ROOT` guards
selected file tools but not arbitrary shell code; Python `code_execution.mode:
strict` changes staging/interpreter selection, not OS containment. Iron-proxy
can broker additional SDK credentials and enforce HTTP destination policies;
its default host-proxy wiring is not enabled here. Cloud microVM backends and
an external VM executor offer stronger kernel separation, but introduce a
separate runtime/provider. No newly identified mode replaces this SSH design.
