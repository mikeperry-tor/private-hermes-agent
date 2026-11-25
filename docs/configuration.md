# Configuration ownership and backups

## Repository files and local files

Tracked component files and defaults live under `components/`, grouped by
service. Image digest pins and source commits live in Dockerfiles and Compose
files, not in `.env`. Hermes's base digest and source checks live in
`components/hermes/Dockerfile` and `components/hermes/verify-build.mjs`;
runtime and offline maintenance jobs share the derived
`private-hermes-agent:local` image.

The root `.env` file is the unified operator input to Compose. Run `make init`
to create a missing `.env` from `.env.example` with mode `0600`, then edit the
settings you need. Rerunning `make init` leaves an existing `.env` and its
permissions untouched; add new settings manually using `.env.example` as a
reference. Exported shell variables override `.env` values according to standard
Compose precedence.

Compose passes each setting only to the services that need it:

| Settings | Recipient |
| --- | --- |
| Inference provider API keys | `teep` |
| `TEEP_ENABLED` (default `true`) | Managed startup (includes or omits Teep) |
| `TEEP_INSTALL_MODEL` | Offline `setup` when creating a fresh Hermes profile with Teep enabled |
| `TEEP_HOST_PORT` | Compose loopback port publication for `teep` |
| `TEEP_SERVE_ARGS` | Compose command arguments for `teep serve` |
| `HERMES_INTEGRATIONS_ALLOWED_HOST_PORTS`, `HERMES_INTEGRATIONS_LAN_ENDPOINTS` (default `none`) | Direct IPv4 TCP socket grants for Hermes |
| `COMPUTER_USE_ENABLED` | Executor image and seccomp selection, and Hermes desktop and browser tool policy |
| `CODE_EXECUTOR_BIND_MOUNTS` | Extra read-write directory mounts for the executor during managed startup |
| `TS_AUTHKEY` | Optional `tailscale` container |
| `WEBAPP_TERMINAL_ENVIRONMENT` | Deployment validation and `hermes` |
| `WEBAPP_EXTERNAL_CONTENT` | Deployment validation, `hermes`, offline `setup`, and `webapp-proxy` |
| `WEBAPP_BIND`, `WEBAPP_PORT`, `WEBAPP_USERNAME`, and Funnel settings | Deployment workflow and ingress services |
| `TOR_ONION_ENABLED` (default `false`) | Deployment validation, `tor`, and `webapp-proxy` |

No service loads the entire root `.env`. Hermes and the SSH executor never
receive inference provider keys or Tailscale credentials; keep provider keys out
of the Hermes workspace, skills, and profile. Add any future deployment setting
to `.env.example` and explicit Compose service mappings together.

### Local editable directories

- **`config/`** holds private editable files mounted into containers.
  `make init` copies `components/network/mcp-allowlist.json` to
  `config/network/mcp-allowlist.json` if missing, without overwriting existing
  policy. Required bind sources are checked before container creation; run
  `make init` on a fresh checkout before `make up`.
- **`config/webapp/`** holds generated WebApp credentials (`password`,
  `auth.json`) and rendered HAProxy configuration (`proxy.cfg`). `make init`
  creates missing credentials and renders proxy config while preserving existing
  credentials. Offline `setup` installs authentication into `hermes-data`
  without exposing it to the executor. See [webapp setup](webapp.md).
- **Implementation defaults** (Tor and SSH configuration, resolver settings, and
  the initial Hermes config template) stay under `components/` and are delivered
  by image `COPY` instructions or read-only bind mounts.

## Offline setup and maintenance

Offline maintenance jobs use minimal mounts and have no network access (except
`x402_treazury-setup`, which runs Tor-routed wallet operations):

| Job | Purpose and mounts |
| --- | --- |
| `setup` | Full stack provisioning. Shares `private-hermes-agent:local` with read-only root, no network, and `CHOWN`, `FOWNER`, `DAC_OVERRIDE`. Mounts persistent directories, `hermes-data`, and `x402_treazury-data` for ownership and lock checks, without running the wallet CLI. |
| `hermes-config` | Runs the Hermes configuration CLI as UID/GID 10000 with only `hermes-data` mounted and no startup validation. Repairs incompatible settings without touching webapp credentials, executor paths, or wallet state. |
| `setup-storage` | Prepares the full storage layout and runs named-volume filesystem lock probes. |
| `mcp-config` | Publishes the MCP bearer token and Hermes registrations using `hermes-data` and `data/x402_treazury-auth/` (no webapp credentials or wallet mounts). Disconnection runs as UID 10000 via `hermes-config` so missing auth paths never block removal. |
| `x402_treazury-inspect` | Reads wallet state using only `x402_treazury-data` (no serving policy bind mount). |
| `x402_treazury-admin` | Runs offline, policy-aware treasury administration (`config show`, `wallet preview`, `wallet rename`). |
| `x402_treazury-setup` | Runs Tor-routed wallet initialization and preparation in `agent-net`. |

`setup`'s `PATH` excludes the writable Hermes profile, and SSH key generation
calls `/usr/bin/ssh-keygen` directly so profile-installed binaries cannot execute
as root.

### Startup sequence and retry safety

`make up` runs cached image builds for the enabled services and treasury, runs
`setup` once, checks its exit code, and then starts runtime services with
`--no-deps` so `setup` does not run a second time. During initialization,
`setup`:

1. Prepares storage permissions and verifies locking on named volumes.
2. Generates missing SSH keys in temporary storage, atomically publishes private
   keys before deriving public keys, and repairs missing or truncated public
   keys from intact private keys (preserving matching public keys and comments).
   SSH client and host keys live in separate directories, and the executor host
   key is pinned.
3. Creates a missing Hermes `config.yaml` from
   `components/hermes/config.example.yaml` via atomic temporary-file write,
   applying `TEEP_INSTALL_MODEL` when Teep is enabled. Existing operator files
   are never replaced.
4. Installs WebApp authentication into `hermes-data` and clears managed research
   MCP registrations before the gateway starts. Treasury activation reconnects
   MCP only after authenticated endpoint readiness succeeds.

At runtime, the Hermes container writes root-owned managed SSH settings before
loading profiles, pinning the executor endpoint, client key, known-hosts file,
and workspace across profile reloads. `make gateway` uses the same startup path.
After `make up`, `make chat` reuses the running namespaces without rerunning
`setup`, and Tailscale starts without rerunning completed dependencies.

Use `hermes-config` for offline configuration repair or `setup-storage` to run
storage checks explicitly:

```sh
python3 scripts/stack.py compose run --rm --no-deps hermes-config set model.default 'neardirect:z-ai/glm-5.3-flash'
python3 scripts/stack.py compose run --rm --no-deps setup-storage
```

### Maintenance resilience

`scripts/stack.py` skips unrelated deployment validation for logs, inspection,
`exec`, `stop`, `down`, and `run --rm --no-deps` maintenance jobs. It includes
the Funnel overlay so optional services remain visible, supplying process-local
placeholder values for unused ingress or inference variables without modifying
`.env` or running containers.

- `make down` uses this maintenance path and shuts down all ingress services
  even if a Teep port or argument setting is malformed.
- `make build` uses only build inputs and never initializes operator state.
- `stack.py compose config` and normal launches still validate operator
  settings. Syntax errors in `.env` or Compose files must still be fixed before
  Compose can identify the project.

## Tool discovery default

New Hermes profiles disable Hermes Tool Search
(`tools.tool_search.enabled: "off"`), exposing enabled built-in and plugin tools
directly in the model's tool list. `x402_treazury` keeps its own endpoint-level
discovery settings, so most research endpoints expose search and call wrappers
while the web endpoint advertises its API tools directly. This avoids nesting
treasury discovery inside Hermes Tool Search; note that enabling extra tools or
plugins increases tool prompt context.

Existing profiles keep their saved setting. To update an existing profile, stop
the stack and edit it offline:

```sh
make down
python3 scripts/stack.py compose run --rm --no-deps hermes-config set tools.tool_search.enabled off
make up
```

Pass `auto` instead of `off` to re-enable Hermes Tool Search. Tool discovery
changes only model presentation; it does not enable disabled tools or alter MCP
auth, wallet policy, or network access.

Hermes's configuration migration also updates the default
`agent.clarify_timeout` from 3600 seconds to 90 seconds while preserving other
explicit values. This governs how long an unanswered clarification pauses a chat
turn and does not affect network or payment deadlines.

## Optional executor desktop

`COMPUTER_USE_ENABLED` defaults to `false`, selecting the lean Alpine executor
and disabling `computer_use` and `browser_exec`. Set `COMPUTER_USE_ENABLED=true`
in `.env`, then run `make down` and `make up` to build the Debian desktop image
and expose those tools (start a new conversation to refresh the model's tool
list). Individual profiles can still disable either tool. `browser_cdp`,
`browser_dialog`, and `browser_vault` stay disabled in all modes.

Both executor variants share the same Compose service, Tor namespace, runner
UID/GID 10000, SSH keys, and home and workspace mounts. Neither adds sudo, a
writable root filesystem, or extra container capabilities:

- **Seccomp:** Docker applies a pinned Moby-derived seccomp profile that allows
  Chromium's user-namespace sandbox. Rootless Podman uses its default seccomp
  policy for both lean and desktop executors. Both keep `no-new-privileges` and
  Chromium's sandbox. See [engine differences](architecture.md#rootless-podman)
  and [native Podman desktop support](development.md#native-podman-desktop-support).
- **Desktop startup:** Graphical processes launch on demand over SSH and shut
  down when idle. Standard `cua-driver` approvals apply, and modes that would
  spawn a gateway-local driver (including approval-bypass mode) fail with an
  error. All desktop dependencies are baked into the image rather than installed
  at runtime.
- **Browser automation:** Only the executor's packaged Chromium is supported;
  external CDP, cloud browsers, host profiles, and other engines fail before
  execution. The Python harness, daemon, and child processes run as `runner` in
  the executor.
- **Tabs, scratch files, and downloads:** Each named session opens a fresh tab
  on first run and after a harness restart, then keeps that tab (including
  tab switches); failed tab setup aborts before model code runs.
  Scratch files are keyed per profile and task, while browser cookies, logins,
  and `/workspace/browser-use/downloads` are shared across tabs. Files under
  `/workspace/browser-use/` persist across calls, whereas Python variables do
  not, and a cancelled or dropped call can still leave an already-sent browser
  action completed.

### Switching variants and limits

Switching `COMPUTER_USE_ENABLED` back to `false` preserves browser state under
`data/executor/home/.hermes/bot-desktop/browser-profile` and all workspace data
(include both in backups). Because cookies and logins are readable by executor
code, use only accounts you trust the agent with. Switching between Alpine
(musl) and Debian (glibc) can break binaries installed under
`data/executor/home/`; repair those environments rather than deleting home,
workspace, or SSH keys.

Only the default profile with one active desktop is supported. The SSH helper
uses display `:20` for every profile and shares the runner's browser profile, so
concurrent profile desktops can interrupt one another. See
[executor desktop qualification](development.md#executor-desktop-qualification)
for test coverage and platform limits.

## Shared project setup

Set up new shares using the [README workflow](../README.md#sharing-directories-with-private-hermes-agents).
An empty `CODE_EXECUTOR_BIND_MOUNTS` adds no mounts. Paths may contain spaces.
When a path contains literal dollar signs, single-quote the entire value in
`.env`. For agent terminal working directories, use names with letters,
numbers, hyphens, underscores, and spaces between words. Commas and colons
separate entries and paths. Use paths without double quotes or control
characters. Run `make down` before adding a share, changing the list while
keeping shares, or moving or replacing a shared directory, even if its path
stays the same. Then run `make up`. To remove all shares, clear the setting
and run `make up`.

With shares configured, the executor stays stopped after an exit. Run
`make up` to check the project sources and start it again. If the executor's
network namespace owner also needs recovery, follow the
[stack recovery procedure](architecture.md#failure-behavior-and-shared-namespace-restarts).

### Shared project filesystem permissions

Setup leaves project ownership, labels, modes, and ACLs under your control.
Hermes can read project files over SSH. Its packaged `HERMES_WRITE_SAFE_ROOT`
setting is `/opt/data`, so `write_file` and `patch` reject writes under
`/mnt/projects/` even when the runner has filesystem permission. Use the
agent's terminal tool or the WebApp **Code** terminal to edit shared files.

| Engine | Permission behavior |
| --- | --- |
| Docker Desktop on macOS | Use the standard local Desktop socket and a directory on the home volume that Docker Desktop can share. Check file sharing and host permissions if the engine cannot mount the directory. |
| Native Docker on Linux | Use the standard local Docker socket and direct UID mapping. The host sees `runner` as UID `10000`. |
| Rootless Podman on Linux | Use the local user API socket and default user namespace. The host sees `runner` as a subordinate UID. |

Check `ls -ldn` in the executor to see how the mounted project appears to
`runner`. On Linux, set `runner_uid=10000` for native Docker. For rootless
Podman, derive the host ID from the default namespace:

```sh
runner_uid=$(podman unshare awk '$1 <= 10000 && 10000 < $1 + $3 { print $2 + 10000 - $1 }' /proc/self/uid_map)
test -n "$runner_uid"
```

On Linux, use an ACL-capable ext4, XFS, or Btrfs filesystem mounted at its
filesystem root. Install the host ACL utilities if needed. Grant access to
the directories and files you intend to share. This example grants access
to one directory and one existing file:

```sh
host_uid=$(id -u)
project=/home/me/my-app
setfacl -m "u:${runner_uid}:rwx,d:u:${runner_uid}:rwx,d:u:${host_uid}:rwx" "$project"
setfacl -m "u:${runner_uid}:rw" "$project/notes.md"
```

Repeat the directory step for existing subdirectories that both users
should write to. Default ACLs apply to new files and directories below
them. A tool that creates private files with mode `0600` can keep the
other writer out. Use `getfacl` to check the ACL and effective mask after
an edit or rename. The host user also needs permission to list and traverse
each directory for the startup scan to complete. Confirm that the mounted
source is the one you intended, and apply any filesystem security labels
through the host's policy.

If Git refuses a checkout because it belongs to the other user, trust that
exact project path in the account that runs Git. For example, run
`git config --global --add safe.directory /mnt/projects/my-app` in the
executor for a host-owned checkout. Use only paths whose configuration and
hooks you trust. For a checkout the executor can modify, see
[reviewing changes in the executor](#reviewing-changes-in-the-executor).

## Security considerations for shared projects

Host tools can run code from shared folders through build scripts, Git hooks,
or editor tasks.

In particular, when the executor can modify a checkout's `.git` directory,
keep inspection of that checkout in the executor. Git configuration can launch
programs during inspection, including through filesystem monitors or diff
filters. Using `git -c core.hooksPath=/dev/null` on the host will override
traditional hook files, but there are other ways to run code from a malicious
repository's git commands beyond these traditional hooks. See [Git's
security guidance](https://git-scm.com/docs/git#_security).

This means you should always review executor-written files in the executor
before using them on the host. This also applies to files in the built-in
executor workspace and home that the stack bind-mounts in `data/executor`
by default.

### Reviewing changes in the executor

The best way to review changes in the executor is currently through the
WebApp: open the interactive **Code** terminal and go to the project
directory. For example, run the following commands for a project at
`/mnt/projects/my-app`. Use `/workspace` as the starting point for
checkouts in the built-in workspace. See
[terminal environment](webapp.md#terminal-environment) if the WebApp
terminal is labeled **Agent**.

```sh
cd /mnt/projects/my-app
git status --short
git --no-pager diff
git --no-pager diff --cached
git --no-pager log -p -n 5
```

In WebApp chat or `make chat`, you can also ask the agent to run these
commands with its terminal tool in the project directory and show the output.
Both the **Code** terminal and the agent's terminal tool run Git inside the
executor. In the classic `make chat` interface, an operator command such as
`!git status` runs in the Hermes container.

### Host-side shared project security enforcement

On the host side, the shared project directories must be independent. Keep
host configuration and automation from following links into a share, and keep
hard links to protected files out of it. Keep custom engine storage,
configuration, and host executables outside shares. When preparing a share
from a trusted local Git repository, use `git clone --no-hardlinks` to keep
the object files independent.

With Docker, use share paths that resolve to the same directories for the
engine and the shell running `make up`.

Before attaching an extra project directory, managed startup checks the host
source for existing device nodes, sockets, other special files, and nested
mounts. It rejects a share containing any of these or overlapping the
deployment checkout, host control directories, or known engine storage. This
scan only applies to `CODE_EXECUTOR_BIND_MOUNTS`. The built-in home and
workspace mounts go through [offline setup](#offline-setup-and-maintenance).

### Agent-side code executor shared project security enforcement

All executor sessions can read, change, or delete shared files as host
permissions allow. This includes the built-in `data/executor/workspace/`
and `data/executor/home/` directories, even when you add no project mounts.
Compromised software can change build scripts, Git hooks, or editor tasks
that host tools later run with your account's permissions and network access.

Agent commands run as `runner` with UID/GID `10000:10000` and no effective
Linux capabilities. The `no-new-privileges` setting prevents them from
gaining privileges by running a setuid binary or a binary with file
capabilities.

The root SSH listener uses `CHOWN` to assign ownership of remote terminals,
`SETUID` and `SETGID` to start sessions as `runner`, and `SYS_CHROOT` to
isolate clients before authentication. The desktop variant also uses
`AUDIT_WRITE` to submit audit records for interactive terminals.
See [executor capability requirements](architecture.md#executor-capability-requirements).

While the executor runs, even UID 0 lacks `CAP_MKNOD`, so it cannot create a
block or character device node in a bind mount. Creating a mount in the
executor's main mount namespace requires `CAP_SYS_ADMIN`, which the service
drops. On Linux, private bind propagation also keeps mounts made in the
executor from appearing on the host. Linux allows processes to create named
pipes and pathname sockets without either capability where permissions and
the filesystem allow it. An entry added on either side after startup can
appear on the other side. A later `make up` checks for entries left in an
extra project directory.


## Host inference access

The recommended inference backend is NearAI through Teep's `neardirect` route.
Set `NEARAI_API_KEY` in `.env` (managed startup requires a provider key whenever
`TEEP_ENABLED=true`).

### Choosing an initial model

Set `TEEP_INSTALL_MODEL` in `.env` before the first `make up` to preselect a
model for a fresh profile:

```dotenv
TEEP_INSTALL_MODEL=neardirect:z-ai/glm-5.3-flash
```

Keep the full Teep model ID, including provider prefix and organization path.
When set, setup adds that model to the starter **Teep** picker alongside three
NearAI entries:

- `neardirect:z-ai/glm-5.3-flash` (the `.env.example` default)
- `neardirect:deepseek-ai/DeepSeek-V4.1-Flash-1017-abliterated`
- `neardirect:deepseek-ai/DeepSeek-V4.1-Flash-1017`

If `TEEP_INSTALL_MODEL` is blank or unset, setup still registers the Teep
provider with live model discovery and leaves the initial model unselected; pick
  one later in **Settings -> Model** or in `make chat`.

To list live Teep models or open the terminal picker:

```sh
python3 scripts/stack.py compose exec teep curl -fsS http://127.0.0.1:8337/v1/models
python3 scripts/stack.py compose run --rm --no-deps hermes model
```

For messaging gateways, configure platform credentials and allowlists with
`python3 scripts/stack.py compose run --rm --no-deps hermes setup`, then run
`make gateway`.

### Extra `teep serve` arguments

Pass extra flags to `teep serve` in `.env`:

```dotenv
TEEP_SERVE_ARGS=--log-level debug
```

Apply changes with `make up` (no `make init` or rebuild needed). Leave it blank
for plain `teep serve`. Compose splits quoted arguments directly without a
shell, so shell pipes and substitutions are not executed, though standard `.env`
interpolation applies. Supply only flags after `serve`. Inspect supported flags
with:

```sh
python3 scripts/stack.py compose run --rm --no-deps teep serve --help
```

Teep always listens on `0.0.0.0:8337` inside its container and publishes only on
host loopback. Passing `--offline` disables attestation verification and is
unsupported for normal operation.

### Host loopback port publication

Teep publishes port 8337 on `127.0.0.1:${TEEP_HOST_PORT:-8337}`, so host
OpenAI-compatible clients can use `http://127.0.0.1:8337/v1`. Changing
`TEEP_HOST_PORT` changes only the host port (apply by recreating Teep).

- **Port collisions:** If port 8337 is busy, set `TEEP_HOST_PORT` (for example,
  `18337`) before starting. Preflight checks `TEEP_HOST_PORT`, `WEBAPP_BIND`,
  and `WEBAPP_PORT` before startup and identifies the conflicting service or
  container without silently remapping ports.
- **Isolation:** Hermes still connects internally to `10.203.83.3:8337`. The
  executor cannot reach Teep, and neither isolated namespace gains host access
  through this port publication.
- **Local trust:** Any process on the host can call `127.0.0.1:${TEEP_HOST_PORT}`
  using Teep's provider keys; the endpoint has no client login and is never
  published through Funnel.

The stack requires Docker Engine 28+, which implements loopback-only port
publishing as documented in
[Docker port publishing](https://docs.docker.com/engine/network/port-publishing/).

## Local inference and HTTP MCP

To let Hermes reach inference or HTTP MCP servers on the engine host or LAN,
grant exact TCP sockets in `.env`:

- `HERMES_INTEGRATIONS_ALLOWED_HOST_PORTS`: comma-separated TCP ports on
  `host.docker.internal` (default `none`).
- `HERMES_INTEGRATIONS_LAN_ENDPOINTS`: comma-separated literal RFC1918 IPv4
  `address:port` pairs (default `none`).

Each entry authorizes one IPv4 TCP socket for Hermes. LAN grants exclude the
stack's own subnets and container networks checked at startup. Because a grant
can reach any host, VM, or VPN destination the engine can route to, verify who
owns each address before granting it.

### Configuring Hermes providers and MCP URLs

In Hermes, add a named OpenAI-compatible provider (for example, base URL
`http://host.docker.internal:11434/v1`), configure its credentials, and pick a
model. For a LAN HTTP MCP server, add its URL under `mcp_servers` in Hermes's
persisted configuration:

```yaml
mcp_servers:
  lan_tools:
    url: http://192.168.1.50:8765/mcp
```

- **HTTPS certificates:** Keep TLS verification enabled. Clients verify against
  the hostname or IP in the URL, so a `host.docker.internal` server needs a
  certificate for `host.docker.internal`, and a literal LAN IP server needs that
  IP in its certificate's SANs.
- **HTTP proxy variables:** Managed Hermes clears `HTTP_PROXY`, `HTTPS_PROXY`,
  and `ALL_PROXY` (including values from the engine or profile `.env`) so
  traffic uses the gateway's socket grants for local targets and Tor for public
  targets (including public MCP OAuth issuers). Image builds keep their own
  proxy settings.
- **MCP redirects:** The MCP SDK enforces its origin policy on session requests.
  If an MCP endpoint redirects to another origin, configure the final target URL
  directly.

### Engine reachability and Teep interaction

- **Host mapping:** The gateway uses the engine's IPv4 host mapping. On Docker
  Desktop, it reaches listeners bound to host loopback. On native rootless
  Podman with pasta, bind the host server to a reachable host interface address
  (loopback-only listeners are unreachable). Re-run `make down` and `make up`
  if the daemon's host mapping changes.
- **LAN grants:** Literal LAN grants work on Docker Desktop and rootless Podman;
  on native Linux Docker, LAN grants remain closed. If the host mapping is
  unavailable, host grants stay closed while literal LAN grants remain
  available.
  `make up` warns if any requested grant stayed closed and the gateway logs why.
- **Path MTU:** The gateway forwards IPv4 fragmentation-needed ICMP replies for
  granted flows, though VPNs or firewalls that drop ICMP can still stall large
  transfers.
- **Toggling Teep:** Keep `TEEP_ENABLED=true` to switch between Teep and a local
  provider at runtime. Setting `TEEP_ENABLED=false` skips Teep's image build,
  container, uplink network, published port, and API key check; fresh profiles
  start without a default provider. Existing profiles retain their saved model.
  To add Teep to a profile created with Teep off, re-enable Teep and add an
  OpenAI-compatible provider with base URL `http://10.203.83.3:8337/v1`.

Apply changes to `TEEP_ENABLED` or either allowlist with `make down` followed by
`make up`. Once the stack is running, local grants continue working during a Tor
circuit outage as long as the `tor` gateway container stays running.

Hermes tools and plugins share Hermes's socket grants. The executor has no
direct path to host or LAN sockets, though allowlisted Hermes tool RPC calls
from executor code can invoke a local backend configured in Hermes. Browser
content and image-fetch rules apply independently. See
[network and execution boundaries](architecture.md#network-and-execution-boundaries).

### Native Linux Docker with AppArmor

On native Linux Docker, the default AppArmor profile can block `tor` from
enabling IPv4 forwarding. `make up` then warns that local grants are closed
while Tor egress stays up. Rootless Podman is the recommended Linux engine for
host and LAN grants.

If you need Docker host-port grants on native Linux, attach a dedicated AppArmor
profile to the `tor` service (tested on Debian 13 ARM64 with Docker Engine
29.10.0 and AppArmor 4.1; literal LAN grants on Docker remain Docker Desktop
only):

1. Create `/etc/apparmor.d/private-hermes-tor` from the `baseTemplate` shipped
   with your Docker Engine release
   ([Docker AppArmor guide](https://docs.docker.com/engine/security/apparmor/#understand-the-policies),
   [Engine 29.10.0 template](https://github.com/moby/moby/blob/docker-v29.10.0/vendor/github.com/moby/profiles/apparmor/template.go)).
   On Debian 13, put `abi <abi/3.0>,` and `#include <tunables/global>` above the
   profile declaration and `#include <abstractions/base>` inside it. Keep the
   template's flags and rules from `network,` onward, substituting
   `private-hermes-tor` for `.Name` and `.PeerName`, and the daemon's AppArmor
   label (`unconfined` on the tested host) for `.DaemonProfile`.
2. Add this rule inside the profile so only IPv4 forwarding is writable while
   all other sysctl denials remain intact
   ([AppArmor rule priorities](https://apparmor.net/man/4.1/apparmor.d/)):

   ```text
   priority=1 /proc/sys/net/ipv4/ip_forward rw,
   ```

3. Compile and load the profile:

   ```sh
   sudo apparmor_parser -Q -K /etc/apparmor.d/private-hermes-tor
   sudo apparmor_parser -r -W /etc/apparmor.d/private-hermes-tor
   ```

4. Run `make down`, append `apparmor=private-hermes-tor` to the `tor` service's
   `security_opt` list in `compose.yaml` (keeping existing entries), then run
   `make up` and test the granted endpoint from Hermes.

Keep that `compose.yaml` edit as a local patch to reapply after stack updates,
and refresh the profile from the new template when upgrading Docker. To remove
the workaround, run `make down`, remove the `security_opt` entry, unload the
profile
([Docker profile unloading](https://docs.docker.com/engine/security/apparmor/#load-and-unload-profiles)),
and run `make up`.

## Persistent data layout

Hermes state (`hermes-data`) and `x402_treazury` wallet state
(`x402_treazury-data`) live in container-engine named volumes; other persistent
files live in bind directories under `data/` and `config/`.

When working with files from the executor workspace or home on the host,
review the [risks of opening executor-written files](#security-considerations-for-shared-projects).

| Storage | Contents |
| --- | --- |
| `hermes-data` (named volume) | Hermes profile, configuration, credentials, conversations, memory, skills, plugins, uploads, and `webapp-image-consent.sqlite3` |
| `x402_treazury-data` (named volume) | Treasury home: encrypted wallet state, decryption key, financial journals, catalog cache, and onboarding record |
| `data/executor/workspace/` | Agent-created repositories, documents, and scripts (durable, not cleared automatically) |
| `data/executor/home/` | Executor home directory, shell and tool config, browser profile, and caches |
| `data/ssh/agent/` | Hermes SSH client key and pinned executor host key |
| `data/ssh/executor/` | Executor SSH host key and authorized client key |
| `data/x402_treazury-auth/` | Persistent MCP bearer token, kept separate from wallet state |
| `data/tor/` | Tor guard state and optional onion identity under `onion-service/` |
| `data/tailscale/` | Optional Tailscale Funnel enrollment and node identity |
| `config/x402_treazury/` | Editable research desk policy (`research_desk.toml`) |

`make init` creates missing directories without overwriting files. Before
services start, `setup` sets the declared leaf-directory ownership and modes
without recursively changing existing files; restore backups with ownership and
permissions intact.

- The `data/` parent directory has mode `0700`. Only offline `setup`,
  `setup-storage`, and `mcp-config` mount the whole `data/` parent; runtime
  containers mount only their own leaf directories. The executor never mounts
  Hermes state, wallet files, or the MCP token.
- The Tor SOCKS Unix socket directory is a runtime IPC named volume and does not
  need backup. `/tmp` is ephemeral; `/workspace` is durable.
- `.env`, `config/`, and `data/` are Git-ignored and excluded from container
  build contexts (builds receive only `components/`).

### Why databases stay in named volumes

Docker Desktop's host-backed bind filesystem (`fakeowner`) fails fresh-file
exclusive `flock` and competing SQLite WAL writer exclusion
([docker/for-mac#7004](https://github.com/docker/for-mac/issues/7004)), even when
locking an already-existing file succeeds. `setup` verifies both probes on
`hermes-data` and `x402_treazury-data` before startup (`components/provisioning/storage.py:verify_filesystem`).
Preserve Docker's `com.docker.grpcfuse.ownership` extended attribute rather than
stripping ownership metadata as a workaround.

`make storage-test` verifies that files and SQLite databases survive `make down`
and container recreation using a temporary test project without network access.
To test whether a host-backed `data/` bind filesystem passes both locking probes
after a Docker Desktop upgrade, run:

```sh
python3 scripts/stack.py compose run --rm --no-deps setup-storage check-filesystem /persistent-data
```

This creates and deletes temporary probe files without touching application
data. A nonzero exit means the bind filesystem is still unsuitable; a passing
probe is necessary before considering a layout change, not sufficient by itself
to migrate live state.

## Applying configuration changes

Edit `.env` or `config/network/mcp-allowlist.json`, then run `make down`
followed by `make up` so namespace owners and application containers recreate
together while preserving persistent data. Run `make build` after modifying
tracked implementation files.

Use the same full `make down` and `make up` sequence to recover from an
`agent-net` or `executor-net` failure. Restarting only a namespace owner can
leave its application containers attached to an obsolete namespace (see
[failure behavior and shared-namespace restarts](architecture.md#failure-behavior-and-shared-namespace-restarts)).
Never add `--volumes` (`-v`) during recovery.

## Backup scope

A complete backup covers:

1. Root `.env` and `config/` (including `config/webapp/` and
   `config/x402_treazury/`).
2. The `data/` directory tree, including `data/tor/onion-service/` with all key
   files (`hs_ed25519_secret_key`, `hs_ed25519_public_key`, and `hostname`).
3. Both application named volumes: `hermes-data` and `x402_treazury-data`.
4. The Git commit hash of this repository so matching images and defaults can be
   rebuilt.

Back up the host sources listed in `CODE_EXECUTOR_BIND_MOUNTS` separately.
Their files live outside the stack's `data/` directory and named volumes.
Preserve any filesystem ACLs you use for two-way editing on Linux.

Protect all of these artifacts as secrets: `.env` holds provider API keys and
optional Tailscale keys, `data/tor/onion-service/` holds the onion identity
private key, `hermes-data` holds the MCP token and Hermes's own profile `.env`
(distinct from the root deployment `.env`), and `x402_treazury-data` stores
`wallet.key` alongside the encrypted wallet (the `wallet backup` command also
includes that key).

### Consistent backup and restore rules

- **Stop writers first:** Run `make down` before taking a filesystem copy (or
  use `x402_treazury`'s native `wallet backup` command for the wallet). Copying
  live SQLite databases and their WAL sidecars independently produces corrupt
  backups.
- **Use `make down`, never `down -v`:** `make down` stops all profiles
  gracefully and preserves both bind directories and named volumes. Compose
  `down -v` permanently deletes `hermes-data` and `x402_treazury-data`.
- **Preserve the Compose project name:** Restarting with the default project
  name (`private-hermes`) reattaches existing volumes; changing the project name
  creates a separate volume set.
- **Preserve ownership and modes:** Do not loosen private directory or wallet
  permissions so host tools can read them. On Linux, use privileged access or a
  container helper for service-owned files. On rootless Podman, files under
  `data/` belong to subordinate UIDs; copy them inside the user namespace:

  ```sh
  podman unshare tar -C data -cpf backup.tar .
  ```

- **Exclude runtime IPC:** The Tor socket volume and the project-root
  `.operation.lock` concurrency lock file do not need backup.
- **Onion identity recovery:** Restore `data/tor/onion-service/` with UID 101 /
  GID 102 and its private permissions. After `make down`, `make onion-address`
  can rebuild a missing `hostname` and public key from an intact secret key (if
  only the public key is missing, `make onion-address` still prints the address
  and enabled Tor regenerates the public key on startup); a missing or damaged
  secret key requires restoring from backup. See
  [optional onion ingress](webapp.md#optional-onion-ingress).

`x402_treazury-data` also contains onboarding records and the catalog cache,
which record past preparation rather than live spendability or cache freshness.
See [x402_treazury integration](x402_treazury.md).

## External-content policy

`WEBAPP_EXTERNAL_CONTENT` accepts `tor_proxied` (default when unset), `ask`,
`off`, or `browser_native`. An explicitly empty or unknown value fails
validation, and the Hermes gateway refuses to start with a missing or invalid
setting. Hermes captures the variable before loading profile dotenv files so
profile edits cannot relax the deployment ceiling.

`make up` regenerates HAProxy configuration and recreates both Hermes and
HAProxy; a mode mismatch between them blocks startup. Reload open browser tabs
after changing modes. See
[external content policy](webapp.md#external-content-policy) for mode behavior
and [webapp qualification](webapp.md#qualification) for test coverage.

Remembered Tor-image origin grants are stored in
`webapp-image-consent.sqlite3` inside `hermes-data` (mode `0600`, not mounted in
the executor). Grants apply only to private image retrieval and are scoped to
the exact browser origin, shared across sessions for that origin, and preserved
across logout and restart until revoked. Backing up `hermes-data` includes this
file. Load-once approvals persist nothing, and policy and image responses use
`no-store` with no server-side image cache.

## Adding other HTTP MCP servers

Use [local inference and HTTP MCP](#local-inference-and-http-mcp) for servers on
the host or LAN. To connect an HTTP MCP server deployed on the stack's internal
`mcp-access` network, add it to the separate internal allowlist:

1. Attach the server container only to `mcp-access` with a static unused IP
   (such as `10.203.84.10`).
2. Add its exact IP and port to `config/network/mcp-allowlist.json` (empty by
   default):

   ```json
   [{"ip": "10.203.84.10", "port": 8000}]
   ```

3. Register its URL under `mcp_servers` in Hermes's persisted configuration:

   ```yaml
   mcp_servers:
     custom_tools:
       url: http://10.203.84.10:8000/mcp
   ```

4. Recreate the namespace and Hermes with `make down` followed by `make up`.

Other ports on that MCP container stay blocked, and the executor gets no access.
HTTP streaming and SSE work directly without a forwarding proxy. Do not give an
internal MCP container a direct uplink, host mounts, or container-engine access
unless required; servers that need Internet access should get a separate
reviewed Tor route. The twelve `x402_treazury` endpoints activate automatically
after preparation and do not use this file.

## WebApp terminal environment

`WEBAPP_TERMINAL_ENVIRONMENT` defaults to `code` when unset:

- **`code`:** Opens a `runner` bash shell in the SSH executor at `/workspace`.
- **`agent`:** Opens a shell inside the Hermes container with administrative
  access to `/opt/data`.

Empty or unknown values fail serving validation while leaving inspection,
backup, repair, and shutdown available. After editing `.env`, run `make up` and
reload browser tabs. Switching modes recreates Hermes, preserves credentials and
executor files, and clears local terminal tabs, saved working directories, and
scrollback from the previous mode (saved gateway tabs survive, and running
processes never migrate between environments).

In Code mode, requested directories are validated inside the executor (files
open in their parent directory). Missing or inaccessible paths, control
characters, and invalid UTF-8 are rejected, while spaces, Unicode, and shell
metacharacters are treated safely as path data. SSH errors never fall back to an
Agent shell: fix the executor or SSH keys and open a fresh terminal without
regenerating keys unnecessarily. Upgrading from the pre-v0.23.3 wrapper also
clears previously saved local terminal tabs (saved gateway tabs and executor
files survive).

The profile's `terminal.cwd` setting applies to model execution and Agent
shells. Workspace file APIs always read the executor, so their files can differ
from what an Agent shell sees locally. Agent-side `/workspace` is ephemeral;
durable agent files live under `/opt/data`. See
[terminal environment](webapp.md#terminal-environment).
