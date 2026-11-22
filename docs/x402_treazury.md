# x402_treazury MCP integration

`x402_treazury` gives Hermes paid research APIs as an alternative to browsing
websites that block or CAPTCHA Tor traffic. It funds rotating Base USDC payment
wallets from a shielded Zcash treasury and binds Tor circuit isolation to each
payer identity, reducing wallet and network linkability across API calls.

- **Catalog and metadata downloads:** By default, each download makes one origin
  attempt and two retries on fresh Tor circuits, then falls back to up to two
  paid relay GET requests. Relay fallback is enabled for source discovery and
  provider metadata, and disabled for API requests themselves.
- **Funding privacy:** Funding swaps run over isolated Tor circuits using Zcash
  with a unique shielded refund address per swap. The main remaining funding
  linkability is correlation by timing and amount against overall Near Intents
  ZEC-to-Base USDC swap volume; closely spaced swaps are easier to correlate.
  Deferred first-use funding spreads initial swaps out, though calls made before
  a group's first funding share the `general` payer and later separation cannot
  undo earlier links.
- **Key isolation:** Wallet keys stay inside the `x402_treazury` container;
  Hermes receives authenticated MCP tool access only.

## Architecture, endpoints, and wallet groups

`compose.yaml` runs one `x402_treazury` container sharing `agent-net`'s network
namespace with Hermes. Its twelve HTTP MCP listeners bind to
`127.0.0.1:3010–3021` with no published host ports, forwarding proxies, or
extra firewall grants. Serving and Hermes MCP registration activate only after
staged wallet preparation; Hermes and its WebApp work normally beforehand.

| Hermes MCP name | Local port | Wallet group (after funding) |
| --- | --- | --- |
| `x402_treazury_toolbox` | 3010 | `general` |
| `x402_treazury_web` | 3011 | `general` |
| `x402_treazury_science` | 3012 | `general` |
| `x402_treazury_shopping` | 3013 | `general` |
| `x402_treazury_world` | 3014 | `general` |
| `x402_treazury_social` | 3015 | `personal` |
| `x402_treazury_property` | 3016 | `personal` |
| `x402_treazury_travel` | 3017 | `personal` |
| `x402_treazury_health` | 3018 | `health` |
| `x402_treazury_business` | 3019 | `financial` |
| `x402_treazury_finance` | 3020 | `financial` |
| `x402_treazury_security` | 3021 | `financial` |

Wallet groups separate payment linkability across broad topics (`general`,
`personal`, `health`, and `financial`). They are upstream payment policies, not
separate MCP access-control roles.

New Hermes profiles disable Hermes Tool Search while keeping
`discover_on_demand = true` on every `x402_treazury` endpoint except `web`
(which advertises its API tools directly). See
[tool discovery default](configuration.md#tool-discovery-default) for details.

### Upstream pin and deferred funding policy

The image builds unmodified upstream commit
`ee92a067655d8d34d5cbc490ddbeb938635d0144` (Rust 1.99.1, locked dependencies).
The wrapper overrides only the Tor SOCKS socket path, persistent state path, and
HTTP `Host` allowlists; wallet groups, rotation, funding, payment caps, and tool
lists follow upstream policy
([upstream wallet rotation guide](https://github.com/mikeperry-tor/x402_treazury/blob/ee92a067655d8d34d5cbc490ddbeb938635d0144/docs/wallet-rotation.md)).

The packaged `research_desk.toml` sets `[wallet_bootstrap]` with
`bootstrap_group = "general"` and
`deferred_groups = ["personal", "health", "financial"]`:

- **Initial funding:** `make x402_treazury-prepare` funds only `general`'s
  initial $2–3 reserve (plus swap and bridge fees). Funding all four groups over
  time needs $8–12 nominal, plus ongoing relay and refill capital.
- **Deferred group activation:** Until a deferred group receives its first
  positive credit, its API calls use `general`'s payer and $1 cap (including
  `health` calls). The first validated API call in a deferred group (even a free
  response or cache hit) triggers funding, with its first refill opportunity
  scheduled after an independent 30–120-second wait. Once funded, future calls
  permanently use that group's own payer and cap (`$0.50` for `health`), even if
  later depleted.
- **Metadata relays:** Paid metadata relays for catalogs, pricing, help, and
  discovery always pay from `general` under this policy (overriding
  `relay_fallback.wallet`) and do not trigger deferred group funding.
- **Customizing bootstrap behavior:** Existing saved `research_desk.toml` files
  are preserved across updates. To fund every group separately from the start,
  remove the `[wallet_bootstrap]` table. Omitted reserve bounds use upstream's
  $2–3 default.

Inspect the packaged default policy offline before funding (no private mounts):

```sh
# Docker
docker run --rm --network none private-hermes-x402_treazury:local config show

# Rootless Podman
podman --remote=false run --rm --network none private-hermes-x402_treazury:local config show
```

## Start Hermes first

```sh
make init
# Set NEARAI_API_KEY in .env (or configure local inference).
make up
```

Log in at `http://127.0.0.1:9120` (see [webapp setup](webapp.md)). No wallet or
MCP token is needed yet. `make up` runs cached builds (including the treasury
image so default policy is available) and automatically activates
`x402_treazury` on later startups once preparation is complete.

## Edit the research configuration

Seed `config/x402_treazury/research_desk.toml` from the built image at any time
without creating a wallet:

```sh
make x402_treazury-config
```

`make up` and `make x402_treazury-init` also seed the file if missing, never
overwriting an existing file. Both `make up` and `make x402_treazury-prepare`
print an advisory unified diff between the image's rendered default and your
saved policy so you can review upstream changes without losing local edits. To
view that diff standalone:

```sh
make x402_treazury-config-diff
```

Run `make build` first if comparing against a new source pin. The diff prints
saved configuration values, so inspect it before sharing logs.

### Applying edits

There is no hot reload. Stop the stack, edit
`config/x402_treazury/research_desk.toml`, validate it offline, and restart:

```sh
make down
# Edit config/x402_treazury/research_desk.toml.
python3 scripts/stack.py compose run --rm --no-deps --entrypoint /usr/local/bin/x402_treazury x402_treazury-admin config show
make up
```

- Relative `../../providers/` paths resolve against the image's bundled provider
  definitions. You can also place custom provider files in
  `config/x402_treazury/` and reference them relative to the TOML. Keep the
  directory and files readable by container UID 10003 (`0755`/`0644`), and
  include `config/x402_treazury/` in backups.
- Keep the fixed deployment fields intact: Tor mode, private SOCKS socket with
  extended auth, treasury state/key paths, and the twelve loopback listeners
  with their `Host` checks and token variable. Wallet pools, payment caps,
  sources, tools, and instructions are editable.
- Invalid configuration blocks networked init, preparation, and serving without
  falling back to defaults, while offline wallet inspection stays usable.
- Editing policy does not invalidate prior preparation. On restart, `serve`
  applies the new policy and may fund newly added groups or download new
  catalogs if ZEC and automatic funding are available.

### Rename a wallet group without replacing it

Back up the treasury first, stop the stack, rename the group offline **before**
starting with the new name, and update every reference in `research_desk.toml`:

```sh
make down
python3 scripts/stack.py compose run --rm --no-deps --entrypoint /usr/local/bin/x402_treazury x402_treazury-admin wallet rename general research
# Update [wallets.general] -> [wallets.research], source/listener references,
# and wallet_bootstrap entries in config/x402_treazury/research_desk.toml.
python3 scripts/stack.py compose run --rm --no-deps --entrypoint /usr/local/bin/x402_treazury x402_treazury-admin wallet preview --json
make up
```

Renaming preserves the group's UUID, payer keys, funds, history, and pending
work (as well as its historical payer correlation). The destination name must be
unused. Changing the name only in TOML creates a brand-new empty group on
startup and leaves the old group's funds unused. See the
[upstream wallet rename guide](https://github.com/mikeperry-tor/x402_treazury/blob/ee92a067655d8d34d5cbc490ddbeb938635d0144/docs/wallet-cli.md#rename-a-managed-wallet-group).

## Create the wallet and deposit when ready

```sh
make x402_treazury-init
```

On first run, this connects through Tor for wallet birthday discovery, prints
the shielded ZEC receive address, and exits without funding, serving, or
registering MCP endpoints. It starts `tor` and `agent-net` if needed (reusing
running containers). On subsequent runs, it inspects saved state offline and
prints the existing status and address without starting services or touching
unrelated host config. Unreadable or corrupted wallet state always raises an
error and never triggers replacement wallet creation.

Back up the wallet before depositing ZEC:

```sh
python3 scripts/stack.py compose run --rm --no-deps --entrypoint /usr/local/bin/x402_treazury x402_treazury-inspect wallet backup --help
```

Mount a private host destination for the backup (the container root filesystem
is read-only), and never write recovery material into the Hermes or executor
workspace.

Check the receive address, saved balances, and preparation/activation state at
any time, even while serving or while WebApp/serving config is invalid:

```sh
make x402_treazury-status
```

Status runs offline without exclusive wallet ownership, reading saved
observations (not live spendability) via temporary snapshot files in the admin
container's `/tmp`. To compare saved wallet groups against your policy offline:

```sh
python3 scripts/stack.py compose run --rm --no-deps --entrypoint /usr/local/bin/x402_treazury x402_treazury-admin wallet preview --json
```

See the
[upstream wallet CLI guide](https://github.com/mikeperry-tor/x402_treazury/blob/ee92a067655d8d34d5cbc490ddbeb938635d0144/docs/wallet-cli.md)
for `wallet preview` and `wallet rename` constraints.

## Prepare and connect research tools

After depositing ZEC and ensuring Hermes is up, run:

```sh
make x402_treazury-prepare
```

`x402_treazury` uses its built-in Base RPC endpoints over Tor (no RPC URL
setting is needed). The command first runs a cached build of the treasury image
without restarting Hermes; a build failure stops before changing any running
services.

If matching preparation already succeeded, the command skips straight to step 4
(serving and Hermes activation). Otherwise, it runs five steps in order:

1. Disconnect managed Hermes research MCP clients and stop any running
   `x402_treazury` serving container gracefully.
2. Run `wallet bootstrap --json`, waiting for ZEC confirmation and funding
   `bootstrap_group` (or every group if `[wallet_bootstrap]` is absent). This
   spends ZEC according to your policy.
3. Run `catalog warm` over Tor (never `--direct`; paid relay fallback can spend
   USDC). Cached entries are saved under `http-cache/` in `x402_treazury-data`.
   A zero exit completes this step even if some remote sources are degraded or
   unavailable, so partial degradation never replays bootstrap or repeats paid
   swaps.
4. Start `serve` and run authenticated MCP `initialize` and `tools/list` checks
   on all twelve endpoints (without making paid research calls).
5. Install the bearer token and twelve MCP entries into Hermes and invoke
   Hermes's `reload.mcp` RPC so tools appear without restarting Hermes or its
   network namespace. Unrelated MCP entries are preserved.

### Readiness diagnostics, cancellation, and retries

All twelve endpoints must become ready before Hermes registration occurs. While
waiting, the command streams `x402_treazury` startup logs and prints a status
line every 30 seconds with no artificial startup deadline:

- **Terminal vs. retryable errors:** Native terminal catalog-startup or
  endpoint-tool-selection errors fail activation visibly even if other endpoints
  stay up. Retryable native errors (such as temporary SOCKS checks with retries
  remaining) do not fail activation. Packaged remote sources set
  `allow_catalog_failure = true` so unavailable sources degrade gracefully;
  required sources keep strict startup failure.
- **Process loss:** Container exit, restart, or loss of the log observer fails
  activation while keeping Hermes running and preserving preparation history.
  Inspect logs (`python3 scripts/stack.py compose logs -f x402_treazury`), fix
  the cause, and rerun `make x402_treazury-prepare`.
- **Financial safety on failure or Ctrl-C:** Cancellation, disconnect, or a
  missing status message never proves a financial action did nothing. Signed
  transactions and pending swaps stay owned by `x402_treazury`'s native
  journals. Inspect `make x402_treazury-status` before retrying, and never
  delete `x402_treazury-data` or manually repeat deposits to force recovery.
- **Graceful stop and orphaned one-shot containers:** Ctrl-C waits for graceful
  cleanup with no force-kill timeout. One-shot jobs have no auto-restart policy.
  If a host crash leaves a `*-x402-onboarding` container running, stop it
  gracefully before retrying:

  ```sh
  # Docker
  docker stop --timeout -1 CONTAINER

  # Rootless Podman
  podman --remote=false stop --timeout -1 CONTAINER
  ```

### Completion record and offline jobs

Preparation completion is saved atomically under `/var/lib/x402/onboarding/` in
`x402_treazury-data`, tied to the wallet identity and successful bootstrap and
catalog warming. Code rebuilds and routine policy edits do not invalidate it.
On subsequent `make up` runs, a prepared stack automatically starts
`x402_treazury` and connects Hermes; invalid runtime policy blocks activation
with an explanation without erasing preparation history.

Helper containers keep minimal privileges and mounts:

- `x402_treazury-inspect`: mounts only `x402_treazury-data` for offline status
  and activation bookkeeping.
- `x402_treazury-admin`: adds read-only `config/x402_treazury/` for offline
  config and wallet administration.
- `x402_treazury-setup`: one-shot container in `agent-net` (no restart policy)
  for Tor-routed wallet init and preparation.
- `mcp-config`: networkless job mounting `hermes-data` and
  `data/x402_treazury-auth/` (never the wallet or WebApp credentials) to install
  the bearer token and twelve MCP registrations. Disconnection runs as UID 10000
  with only `hermes-data`, so missing auth files cannot block removal.

## Secrets and execution boundary

- **Process and filesystem isolation:** `x402_treazury` runs as UID 10003 with
  its own PID and mount namespaces, empty capability sets, read-only root
  filesystem, and private `x402_treazury-data` volume. Hermes mounts neither the
  wallet volume nor `data/x402_treazury-auth/`.
- **Tor SOCKS isolation:** Tor exposes a group-restricted Unix SOCKS socket only
  to `x402_treazury` (keeping Tor's control socket and cookie private to Tor).
  `x402_treazury`'s Tor policy and SOCKS auth stay enabled, and the shared
  `agent-net` namespace retains transparent Tor routing and private-network
  denials.
- **Executor boundary:** The SSH executor runs in a separate network namespace
  with no access to `127.0.0.1:3010–3021`, no wallet or agent mounts, no MCP
  bearer token, and SSH forwarding disabled. Hermes's `execute_code` RPC
  allowlist excludes dynamic MCP tools; widening that allowlist or copying
  secrets into the executor changes this boundary.
- **Shared namespace and token scope:** All twelve MCP endpoints share one
  bearer token, so Hermes (and its subagents) hold authority over all twelve;
  client-side tool filters do not create separate server credentials. Sharing
  `agent-net` lets Hermes and `x402_treazury` reach each other's loopback
  listeners. Container isolation protects wallet files from normal agent code,
  not from kernel/engine compromise or vulnerabilities in the MCP API itself.

## Shutdown and testing

Run `make down` to stop the stack gracefully while preserving
`x402_treazury-data` and `data/x402_treazury-auth/` (never use `down -v` on a
deployment whose wallet you need). Because `wallet.key` sits alongside the
encrypted wallet in `x402_treazury-data` (and is included in `wallet backup`),
treat both full volume backups and native wallet backups as secrets. A missing
onboarding record requires rerunning `make x402_treazury-prepare` and never
triggers wallet replacement.

With normal deployments stopped, run the test suites:

```sh
make check
python3 tests/endpoint_readiness_smoke.py
make x402_treazury-test
python3 tests/research_config_smoke.py
make test
```

- **`tests/endpoint_readiness_smoke.py`:** Networkless fixture with ephemeral
  unfunded keys covering delayed readiness, terminal endpoint errors alongside
  healthy siblings, restart without stale-error replay, empty-inventory
  activation, and probe cleanup.
- **`tests/research_config_smoke.py`:** Offline policy tests using the built
  image and a temporary unfunded wallet covering policy loading, atomic edits,
  invalid/missing TOML refusal, offline status availability under broken policy
  or ingress config, `wallet preview`, and `wallet rename` error paths.
- **`make x402_treazury-test`:** Builds the treasury image and tests bearer-token
  auth, MCP `initialize`/`tools/list` on all twelve endpoints, HTTPS through
  Tor's Unix SOCKS socket against a free Tor-check API, executor isolation, RPC
  denial, disabled SSH forwarding, and Tor failure without direct fallback. No
  paid calls or wallet funding occur.

### Current qualification

Commit `ee92a067655d8d34d5cbc490ddbeb938635d0144` is qualified on Linux ARM64
under Docker Desktop 29.9.3 / Compose 5.7.0 and Debian 13 ARM64 rootless Podman
5.4.2 / Compose 5.7.1 (unit tests, effective Compose models, native treasury
builds, endpoint readiness, offline configuration, degraded warming during Tor
outage, and unfunded smoke fixtures).

On Podman, the treasury build is native while Teep in the test run used an
imported ARM64 image matching the unchanged Dockerfile (not a fresh native
Podman Teep build). Unfunded fixtures do not test live wallet sync, funded
bootstrap, paid relay downloads, or settlement.

## Pending live qualification

Staged onboarding passes all local fixture checks, but live wallet birthday
discovery, ZEC deposit receipt, managed USDC swaps, and funded catalog warming
remain untested. When conducting live financial qualification:

1. Confirm Hermes works normally before initializing or funding a treasury.
2. Run `make x402_treazury-init`, record the shielded ZEC address, back up the
   wallet before depositing, and verify that rerunning `make x402_treazury-init`
   preserves the wallet identity.
3. Deposit ZEC, run `make x402_treazury-prepare`, and confirm bootstrap, catalog
   warming, authenticated readiness on all twelve MCP endpoints, and live Hermes
   registration without restarting the gateway.
4. Verify `make x402_treazury-status` and automatic reconnection after
   `make down` and `make up`. If a step fails, diagnose and retry against the
   same wallet without discarding state or repeating payments manually.
5. Record the tested revision and results privately without committing seeds,
   keys, bearer tokens, or financial identifiers. Test paid research calls
   separately from MCP listing.

Upstream: [x402_treazury](https://github.com/mikeperry-tor/x402_treazury).
