# Configuration ownership and backups

## Repository files and local files

`components/` contains tracked implementation files and defaults, grouped by
component. Dockerfiles retain their base image and source-revision pins. The
official Hermes base digest and source checks live in
`components/hermes/Dockerfile` and `verify-build.mjs`; Compose shares the derived
`private-hermes-agent:local` image between runtime and maintenance.
Changing an image version is a reviewed repository change rather than a local
`.env` override.

The root `.env` is the unified operator configuration input to Compose. Start
with `make init`, edit the desired settings, then build/start the stack. The
initializer creates a missing `.env` from `.env.example` with mode 0600. It
leaves existing contents and permissions unchanged; add new settings explicitly
using the example as a reference. Existing exported
shell variables retain Compose's normal precedence over `.env` values.

Compose explicitly selects each service's environment variables:

| Settings | Recipient |
| --- | --- |
| Inference provider API keys | teep |
| `HERMES_DEFAULT_MODEL` | Offline setup, which saves the preferred Hermes default |
| `TEEP_HOST_PORT` | Compose loopback port publication for teep |
| `TEEP_SERVE_ARGS` | Compose command arguments for `teep serve` |
| `COMPUTER_USE_ENABLED` | Executor build/security selection and Hermes's captured computer/browser tool policy |
| `TS_AUTHKEY` | Optional Tailscale container |
| `WEBAPP_EXTERNAL_CONTENT` | Deployment validation, Hermes, offline setup and ingress proxy |
| Funnel enablement, local webapp port and hostname | Deployment workflow and selected ingress components |
| `TOR_ONION_ENABLED` (default `false`) | Deployment validation, Tor and HAProxy; no conditional overlay |

Generated webapp credentials are kept separately under `config/webapp/`; see
[webapp setup](webapp.md). The networkless `setup init` command copies native auth settings into
Hermes state without exposing them to the executor.
`make init` creates missing webapp credentials and renders proxy configuration;
repeating it preserves the credentials.

No service loads the entire root `.env`. Hermes and the SSH executor receive
none of the provider or Tailscale credentials. Keep provider credentials out of the
Hermes workspace, skills, and profile. Add future deployment settings to the
example and explicit Compose mappings together.

`config/` contains operator-owned editable files mounted into services. The
initial file is `config/network/mcp-allowlist.json`; its tracked default is
`components/network/mcp-allowlist.json`. `make init` creates the local copy only
if missing. Existing local policy is preserved. The service mounts it read-only,
and managed startup refuses missing required bind sources before container
creation. Raw Compose lacks this enforcement on the qualified Podman API. Run
`make init` before starting a fresh checkout. Use `make up` and the
`scripts/stack.py compose` wrapper so enabled ingress layers are selected.

Other component files, such as Tor/SSH settings, resolver settings, and the
initial Hermes configuration template, remain implementation-owned defaults.
They live beside their owning components. Their existing delivery through image
COPY instructions or read-only bind mounts is preserved. Moving these files
does not implement the separate read-only Hermes configuration plan.

## Offline setup and maintenance

Offline jobs have explicit mount requirements: `setup` provisions the stack,
`hermes-config` repairs only Hermes configuration, `setup-storage` checks the
full storage layout, `mcp-config` publishes MCP credentials/registrations, and
`x402_treazury-inspect` reads
saved wallet state, and `x402_treazury-admin` handles policy-aware administration.
`x402_treazury-setup` performs Tor-routed wallet initialization/preparation. The offline `setup` service uses the same derived pinned
Hermes image as the agent, with component scripts mounted read-only. No custom
setup image or combined Hermes/treasury image is built. It has a read-only root,
no network, and only `CHOWN`, `FOWNER`, and `DAC_OVERRIDE`.
It is trusted with the persistent directories, Hermes state, and wallet volume
for ownership/lock checks; it does not contain or invoke the wallet CLI.
Its tool search path excludes the writable Hermes profile, and SSH provisioning
uses `/usr/bin/ssh-keygen`, so profile-installed tools cannot run as setup's root.

`make up` first runs cached image builds for the selected deployment and treasury,
then recreates the canonical `setup` container once, checks its exit code,
and starts applications only after it succeeds. Initialization prepares storage,
creates missing SSH identities, reconstructs missing or incomplete public key files from intact
private keys, validates/preserves Hermes configuration, installs
webapp authentication, and removes managed research registrations before the new
gateway starts. The managed workflow explicitly starts runtime services with
`--no-deps` afterward, preventing another setup run; Compose dependencies still
guard direct first-run startup. Treasury activation
reconnects MCP only after authenticated readiness succeeds.

SSH client and host keys live in separate persistent directories; setup pins the
executor host key and initializes its workspace/home. It publishes
`components/hermes/config.example.yaml` only if Hermes configuration is absent.
Defaults are written completely to same-directory temporary files and atomically
published without replacing operator files. An interrupted first copy leaves no
partial final configuration; retries preserve any existing complete file and modes.
Initial SSH keys are generated in temporary storage and their private identity is
published atomically before deriving the public file. Retries repair empty/truncated
public files from the private identity; matching public files and operator comments
are preserved. Existing compatible configuration and keys are preserved. Incompatible Hermes
configuration blocks agent startup. Setup also installs the generated SSH
file-browser settings.

`make gateway` uses the same startup workflow. After `make up`, `make chat` uses
the existing runtime namespaces without starting setup again. The optional
Tailscale service is also started without rerunning its completed dependencies.

Use the unprivileged offline configuration job for repair, or trusted setup for
deliberate full storage qualification:

```sh
python3 scripts/stack.py compose run --rm --no-deps hermes-config set model.default 'neardirect:z-ai/glm-5.3-flash'
python3 scripts/stack.py compose run --rm --no-deps setup-storage
```

`hermes-config` invokes the native configuration CLI directly as UID/GID 10000,
with only the Hermes profile volume, no networking and no startup/bootstrap
validation. It can repair incompatible settings without mounting webapp credentials,
executor paths or the wallet. `setup-storage` deliberately prepares the full storage
layout and checks native-volume locks; ordinary saved-wallet inspection does not
run or depend on it. Trusted networkless `mcp-config token|connect` publishes the MCP credential and
registrations with the profile and bind-data auth storage, without webapp credentials
or wallet mounts. The controller removes registrations using the profile-only
`hermes-config` job as UID 10000 with public helper code; missing auth/bind-data paths
do not block disconnection. It does not rerun SSH/auth initialization.

The Compose wrapper bypasses unrelated deployment-settings validation for logs,
inspection, exec/control of existing containers, and documented `run --rm --no-deps`
maintenance jobs. It includes the Funnel overlay so existing optional services are
visible. Process-local inert values satisfy unused ingress/inference interpolation;
`.env` and running container environments are unchanged. Normal launch and deployment validation still use actual operator settings.
Raw `compose config` inspects actual values through native Compose validation.
Image builds use only source/build inputs and do not initialize operator state. `make down` uses the same maintenance
interpolation and includes all ingress resources, even after a malformed Teep port
or command setting. Existing native policy checks still guard actual application
startup. Malformed Compose/ dotenv syntax or ambiguous project identity can still
require correction before Compose can identify the deployment safely.

## Tool discovery default

New Hermes profiles disable Hermes Tool Search (`tools.tool_search.enabled: "off"`).
Enabled tools appear directly in the model's tool list, including built-in and
plugin tools that Hermes would otherwise defer. x402_treazury retains its packaged
endpoint-level discovery settings, so most research endpoints expose search/call
wrappers instead of every API schema. This avoids nesting treasury discovery
inside Hermes Tool Search; the web endpoint advertises its selected API tools
directly. Enabling additional tools or plugins increases the model's tool context.

Existing profiles retain their saved configuration. To apply this preference to
an existing profile, gracefully stop the stack and use native offline maintenance:

```sh
make down
python3 scripts/stack.py compose run --rm --no-deps hermes-config set tools.tool_search.enabled off
make up
```

Use `auto` in place of `off` to restore Hermes Tool Search. Tool discovery settings
control model presentation; they do not enable disabled tools or change MCP
authentication, wallet policy, or network access.

Hermes v0.23.1's native configuration migration changes the former default
`agent.clarify_timeout` of 3600 seconds to 90 seconds. Other explicitly chosen
values are retained. This affects how long an unanswered clarification holds a
chat turn; it does not change network or payment deadlines.

## Optional executor desktop

`COMPUTER_USE_ENABLED=false` selects the lean Alpine executor and excludes
`computer_use` and `browser_exec`. Set it to exactly `true` in the root `.env` to select the larger
Debian desktop image and make those tools available when their SSH dependencies are
present. Apply with `make down` followed by `make up`; startup builds the selected
image and recreates affected services. Start a new conversation to refresh the
advertised tools. A profile can still exclude either tool. `browser_cdp`,
`browser_dialog` and `browser_vault` remain disabled.

Docker selects this wrapper's pinned Moby-derived seccomp profile with Chromium
namespace allowances. Rootless Podman uses its native default seccomp policy for
both lean and desktop executors. Both retain no-new-privileges and Chromium's
own sandbox. The policies differ; selecting Podman keeps the same engine baseline
used by its lean executor. See [engine differences](architecture.md#rootless-podman)
and [native Podman desktop qualification](development.md#native-podman-desktop-support).

Browser automation supports the executor's packaged Chromium only. External CDP,
cloud browsers, real host profiles and alternate engines fail before execution.
Its Python harness, daemon, workspace helpers and child processes run as runner
in the executor. Named sessions have separate tabs, with the same shared browser
profile/cookies. Recreating the executor clears stale browser process coordination
while retaining the profile, cookies and credentials. Workspace files under `/workspace/browser-use/` persist; Python
variables do not persist between calls. Cancellation or a lost connection can
leave an already-issued browser action completed; inspect state before retrying.
Browser downloads use the shared `/workspace/browser-use/downloads` directory;
named tabs do not provide separate download or cookie authority.

The same executor service, Tor namespace, runner UID/GID 10000, SSH identity and
home/workspace mounts serve both choices. Neither enables sudo or a writable
system filesystem. Docker's desktop selects a maintained seccomp profile for
Chromium's namespace sandbox; Podman keeps its native default. Neither desktop
configuration adds container capabilities. Desktop processes
start on demand through native SSH streams, with native idle shutdown. Standard
cua-driver permissions and native approvals apply; modes that would create a
gateway-local driver, including approval-bypass mode, fail with a scoped reason.
Desktop dependencies are built into images, never repaired by runtime installers.

Switching off preserves browser state under the executor home
(`data/executor/home/.hermes/bot-desktop/browser-profile`) and all workspace data;
include them in backups. Cookies and logins are available to executor code, so
use only accounts entrusted to the agent. Alpine/glibc and runtime changes can
make home-installed binary dependencies incompatible across switches. Preserve
their files and repair the affected environment deliberately rather than deleting
the home, workspace or SSH keys. This is one shared executor, not per-bot isolation.

Qualification covers the default profile with one active desktop. The pinned
native SSH helper uses display `:20` for each profile and shares the runner's
browser profile; do not run concurrent profile screens, which can interrupt one
another. Per-profile desktop multiplexing remains unqualified and is not supplied
by this option.

Qualification evidence and platform/surface limitations are recorded in the
[development guide](development.md#executor-desktop-qualification).

## Host inference access

The recommended provider is NearAI via teep's `neardirect` backend. Set
`NEARAI_API_KEY` in `.env`. `make up` refuses to start when no provider API key
is set, because teep does not start without one. The native Hermes model picker has a **Teep** entry
with these choices:

- `neardirect:z-ai/glm-5.3-flash` (initial default)
- `neardirect:deepseek-ai/DeepSeek-V4.1-Flash-1017-abliterated`
- `neardirect:deepseek-ai/DeepSeek-V4.1-Flash-1017`

To set a preferred default, add this to the root `.env`, then run `make up`:

```dotenv
HERMES_DEFAULT_MODEL=neardirect:z-ai/glm-5.3-flash
```

This accepts any model ID supported by a configured Teep provider, including
models outside the supplied choices. Keep the complete Teep ID, including its
provider prefix and any organization path. Availability still depends on the
provider's catalog and credentials; adding an ID does not validate inference.

`make init` only creates missing host files; rerunning it does not change Hermes's
saved model. `make up` runs offline setup, saves a nonblank `HERMES_DEFAULT_MODEL`
to `model.default`, adds it to the native picker catalog, and recreates Hermes.
The supplied catalog is seeded for existing profiles if absent; operator-edited
catalogs are preserved. The picker uses this saved catalog rather than fetching
Teep's full catalog automatically. Blank or absent `HERMES_DEFAULT_MODEL` preserves
the saved default, including a choice made through Hermes's native configuration.
Clearing the variable does not reset the previous choice. A nonblank value is
reapplied on every `make up`; clear it to manage the default entirely in Hermes.
Existing sessions may retain their session-specific model selections.

Without an `.env` preference, use `hermes-config set model.default` followed by
`make up` to save another default. Preserve the custom Teep endpoint and SSH
backend when editing native configuration.

List Teep's live model IDs and select an alternative with:

```sh
python3 scripts/stack.py compose exec teep curl -fsS http://127.0.0.1:8337/v1/models
python3 scripts/stack.py compose run --rm --no-deps hermes-config set model.default 'neardirect:deepseek-ai/DeepSeek-V4.1-Flash-1017-abliterated'
make up
```

The default Hermes command runs a messaging gateway. To configure messaging
platform credentials and allowlists, run
`python3 scripts/stack.py compose run --rm --no-deps hermes setup`, then
`make gateway`. Preserve the custom inference endpoint and SSH backend.

Extra Teep server arguments can be set in the root `.env`:

```dotenv
TEEP_SERVE_ARGS=--log-level debug
```

Run `make up` to recreate Teep with the new arguments; no `make init` or image
rebuild is needed. Blank or absent means plain `teep serve`. Compose splits
the value into command arguments, honoring quoted argument values. No shell runs
the command, so pipes and command substitutions are not executed. Compose's
normal `.env` interpolation rules still apply.
Supply only arguments after `serve`, not another command. Malformed quoting
fails Compose validation; unknown arguments fail in Teep. Inspect the packaged
options with `python3 scripts/stack.py compose run --rm --no-deps teep serve --help`.
The listen address remains `0.0.0.0:8337` inside Teep's container and host
publication remains loopback-only. No verification flags are supplied by default.
Teep's `--offline` skips external verification and falls outside the stack's
qualified verification behavior; preserve verification for normal operation.

Teep publishes container port 8337 directly on `127.0.0.1:${TEEP_HOST_PORT:-8337}`.
Host OpenAI-compatible clients use `http://127.0.0.1:8337/v1` by default. The bind
address is fixed to IPv4 loopback; changing `TEEP_HOST_PORT` changes only the host
port. Recreate Teep after changing it. This uses Docker's port publication on
Teep's existing direct uplink, with no additional bridge service, network,
capabilities, or changes to the isolated namespace firewall rules.

If another host process already listens on 8337, set `TEEP_HOST_PORT` to an unused
port such as `18337` before starting the stack. A collision prevents Docker from
starting Teep with its configured publication; there is no silent port change,
omitted endpoint or fallback to the host process. The disposable integration
fixtures use ephemeral host ports and leave an existing host Teep alone.

Hermes continues to use `10.203.83.3:8337` internally. The executor cannot reach
Teep, and neither isolated namespace gains access to host/VM addresses through
this mapping. Local host processes can use the inference API and its configured
provider accounts; this endpoint has no added client authentication and does
not use the Hermes webapp login. It is not published through Funnel.

Docker documents loopback-only publication in
[port publishing](https://docs.docker.com/engine/network/port-publishing/).
The stack already requires Docker Engine 28+, avoiding the older localhost
publication behavior described there. Tests publish a disposable loopback port,
verify host access to `/health`, and check agent/executor host-address blocks
alongside the existing executor-to-inference denial and Tor routing checks.

## Persistent data layout

Hermes profile/database state and x402_treazury wallet/database state use native
container-engine named volumes (`hermes-data` and `x402_treazury-data`). Other
persistent files use the bind directories below. This keeps lock-sensitive state off the
host-backed filesystem that failed qualification on this Docker Desktop host.
`setup init` checks locking on the native volumes before applications start.
No existing volume contents are copied or deleted by this change.

PrivateOnyxApp's PostgreSQL/OpenSearch initialization was checked as a possible
workaround. Its Podman path initializes a temporary native volume and copies the
stopped database into the host bind; its macOS PostgreSQL preparation removes
only `user.containers.override_stat`. That attribute was absent on our test paths,
and Docker's `com.docker.grpcfuse.ownership` attribute must remain intact.

Our disposable mount reports filesystem type `fakeowner`. A competing process
incorrectly acquired an exclusive lock on a freshly created file, but correctly
failed after the file was closed and reopened. This matches the creation-path
behavior described in [Docker issue #7004](https://github.com/docker/for-mac/issues/7004).
Initializing a SQLite database in native container storage, closing it, copying it
to the bind, and then opening it in WAL mode still allowed two writers to acquire
the writer lock. Consequently, staging initialization or changing ownership is
not a sufficient workaround for this host. Qualification must include fresh-file
locking and SQLite writer exclusion, rather than just successful startup or
database reads/writes. These observations describe the tested host, not all
Docker Desktop or Linux bind mounts.

Track that upstream issue when evaluating Docker Desktop updates. Before moving
live state to host binds, rerun the fresh-file `flock` and competing SQLite WAL
writer probes on the proposed bind filesystem; existing-file locking alone is
not sufficient. `components/provisioning/storage.py:verify_filesystem` contains
both probes. Do not remove the checks or assume that closing the upstream issue
qualifies a particular host. `make storage-test` checks the current native-volume
layout and verifies files and SQLite data survive ordinary Compose `down` and
container recreation, using only a disposable test project and no network access.

After updating Docker Desktop or the engine's file-sharing backend, test the
host-backed `data/` filesystem directly with:

```sh
python3 scripts/stack.py compose run --rm --no-deps setup-storage check-filesystem /persistent-data
```

This creates and removes temporary probe files without changing application data
or permissions. A nonzero exit means the filesystem is still unsuitable. Passing
these probes is necessary before considering a storage-layout change; it does
not by itself change the deployment or replace full application qualification.

| Storage | Contents |
| --- | --- |
| `hermes-data` named volume | Hermes profile, configuration, credentials, conversations, memory, skills and uploads |
| `data/executor/workspace/` | Durable agent-created work, repositories, documents and scripts |
| `data/executor/home/` | Executor home, shell/tool configuration and caches |
| `data/ssh/agent/` | Agent SSH client identity and pinned host trust |
| `data/ssh/executor/` | Executor host identity and authorized client key |
| `x402_treazury-data` named volume | Entire treasury home: wallet state/key, financial journals, catalog cache and onboarding record |
| `config/x402_treazury/` | Editable research policy |
| `data/x402_treazury-auth/` | Persistent MCP bearer token, separately mounted from the wallet |
| `data/tor/` | Tor guard-selection/state and optional native onion identity under `onion-service/` |
| `data/tailscale/` | Optional Funnel node enrollment and identity |

`make init` creates missing directories without replacing data. A trusted,
networkless `setup` service checks native-volume filesystem locking and sets the declared
leaf-directory UIDs, GIDs and modes before applications start. It does not
recursively chown/chmod existing files. Restore backups with their ownership and
permissions intact rather than relying on initialization to repair file metadata.

The host-owned `data/` parent is mode 0700. Application identities remain unchanged;
wallet and SSH private-file permissions remain restrictive. On Linux, service-owned
private directories may require privileged access or a container backup helper
for backup. Do not loosen wallet permissions to make them readable to host tools.

Only trusted offline setup/storage and MCP jobs mount the whole `data/` parent. Hermes,
the executor, financial services, Tor and Tailscale each receive their own leaf
mounts. The executor never receives Hermes state, wallet files, or the MCP token.
The shared Tor Unix-socket directory remains a named volume: it is runtime IPC,
not backup data. `/tmp` remains disposable; `/workspace` is durable work, not an
automatically cleared scratch directory.

`.env`, `config/`, and `data/` are Git-ignored and excluded from container build
contexts. Builds receive only `components/`.

## Applying configuration changes

Edit the root `.env` and local MCP policy as needed. Recreate the deployment
with `make down` followed by `make up` when changing namespace configuration;
retain persistent data. Rebuild images with `make build` after implementation
changes. Wallet initialization and funding remain explicit operator actions.

Use the same whole-stack procedure after an `agent-net` or `executor-net`
failure. Restarting only a namespace owner can leave its applications attached
to an obsolete namespace, even if the replacement owner is healthy. Docker has
a known shared-namespace lifecycle limitation; restart policies do not guarantee
reattachment, and independent owner restart is unsupported on both engines. See
[namespace ownership and recovery](architecture.md#network-and-execution-boundaries)
for upstream reports and the distinction from supported Tor-only restarts.
Ordinary `make down` preserves persistent data; do not add `--volumes` for recovery.

## Backup scope

Include `data/tor/onion-service/` with all native key files, not just `hostname`.
The secret key preserves the onion address and permits impersonating it; protect
it as private identity material. Restore ownership (container UID 101/GID 102)
and native modes rather than loosening permissions for host-side inspection.
Use `make onion-address` to display the saved address, including while serving
settings are invalid. After `make down` it reconstructs a missing hostname and
public key from an intact secret. If only the public key is missing, the target
continues to display the saved hostname without writing; native enabled Tor
reconstructs that public file at startup. Missing/malformed secrets require
deliberate backup recovery, not reinitialization or automatic rotation. See
[onion operation](webapp.md#optional-onion-ingress).

Back up the root `.env` and `config/` as private operator configuration. Protect
these backups as secrets; `.env` may contain paid API keys and Tailscale
enrollment credentials. Record the repository commit so the corresponding implementation and
image/source pins can be recovered.

The backup scope is `.env`, `config/`, `data/`, and both application named volumes,
together with the repository revision needed to reproduce images and configuration.
Protect all of these as
secrets. x402_treazury keeps its encryption key alongside encrypted wallet state;
its native wallet backup also contains that key.

Use the native wallet backup command or gracefully stop writers with `make down`
before making a complete filesystem copy. Copying live SQLite databases and their
sidecars independently is not a consistent backup. Preserve file modes, ownership
and the full application directories. Tor sockets and other runtime IPC do not
need backup. `make down` retains named volumes and host bind directories on both
engines.
Prefer it over raw Compose shutdown so optional/profiled namespace users are
included. Starting again with the same Compose project name
reattaches the existing volumes. The default project name is `private-hermes`;
changing it selects a different set of volumes. Compose `down -v` explicitly
deletes the application volumes, including wallets and conversations, as well as
the runtime socket volume. Do not use it on a deployment whose state you need.
Deleting bind-mounted host data requires a separate filesystem operation.
Backing up `data/` alone does not include the application volumes. On rootless
Podman, files under `data/` belong to subordinate user IDs; copy them inside the
user namespace, for example `podman unshare tar -C data -cpf backup.tar .`, so
ownership is preserved.

Hermes's generated profile `.env` in `hermes-data` is distinct from the root
deployment `.env`: it contains the MCP token and Hermes-owned credentials.
`x402_treazury-data` contains preparation records and catalog cache as well as
the wallet. Those records are historical preparation evidence, not current
spendability or perpetual cache freshness. Editable research policy remains under `config/x402_treazury/`; include this
directory in backups. The shared host operation lock is `.operation.lock` at the
project root; it is concurrency coordination, not wallet state or a backup input. See
[editing research policy](x402_treazury.md#edit-the-research-configuration) and
[staged onboarding](x402_treazury.md).

## External-content policy

`WEBAPP_EXTERNAL_CONTENT` accepts exactly `tor_proxied`, `ask`, `off`, or
`browser_native`. An absent root setting defaults to `tor_proxied`; an explicitly
empty or invalid value fails validation. The gateway rejects missing or invalid
process settings. Native bootstrap captures the injected setting before profile
dotenv loading; profile edits do not relax this deployment policy. `make up` renders ingress configuration and recreates Hermes
and HAProxy; a proxy mode/configuration mismatch refuses startup. Editing `.env`
alone does not change running processes. Reload open browser pages after applying
policy changes.

See [webapp operations](webapp.md#external-content-policy) for mode behavior,
image approval, inert previews, browser scope and stale-page limits. Integrated
qualification and limitations are recorded in the
[webapp guide](webapp.md#qualification).

Tor-image remembered consent uses `webapp-image-consent.sqlite3` in `hermes-data`,
with a native SQLite table and mode 0600. Its method is fixed to private image
retrieval; it is separate from profile/model configuration and not mounted in the
executor. One authenticated deployment administrator shares remembered grants
across sessions on the same exact browser origin. Logout and restart retain them;
explicit revocation removes them. Backing up/restoring Hermes's named volume
includes this state. Load once creates no persistent grant or reusable bearer
credential. Policy and retrieval responses are no-store, with no server image
cache that could bypass a changed policy or revoked grant.

## Adding other selected HTTP MCP servers

The base allowlist is deliberately empty. A server should join only the
`mcp-access` internal network and receive a fixed unused address such as
`10.203.84.10`. Grant exactly its streaming HTTP port in
`config/network/mcp-allowlist.json`, for example:

```json
[{"ip": "10.203.84.10", "port": 8000}]
```

Then add its URL under Hermes's persisted `mcp_servers`:

```yaml
mcp_servers:
  selected_tools:
    url: http://10.203.84.10:8000/mcp
```

Recreate the agent namespace and Hermes together after firewall edits
(`make down`, then `make up`). Other ports on that MCP container remain blocked;
executor access is not granted. HTTP streaming and SSE require no forwarding
service or HTTP buffering proxy. The integration fixture demonstrates both.

Do not give an MCP server an uplink, host mounts, or engine access unless its
role requires that authority. Servers needing public access can be given a
separately reviewed Tor route; they do not inherit the agent's egress. Powerful
MCP tools remain explicitly granted capabilities available through Hermes.
The twelve x402_treazury MCP servers activate after preparation; this allowlist is for additional servers.
