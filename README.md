# Private Hermes

Private Hermes is a Docker Compose stack for running [Hermes Agent](https://github.com/NousResearch/hermes-agent)
with private research tools, code execution in a separate container, and an
authenticated web interface. It brings together Tor-routed Internet access,
confidential-computing inference through Teep, and paid research APIs through
x402_treazury.

The goal is to let an agent research and write code while keeping your network
address, inference requests, and agent payment history private, and sandboxing
the agent from accessing your local machine. You can use Hermes through your
browser or terminal, and optionally enable public HTTPS access through Tailscale
Funnel.

## Components and the problems they solve

- **Hermes Agent** provides chat, tool use, skills, and subagent orchestration.
  Its webapp and terminal client let you work with the same persistent agent.
- **SSH code executor** runs model-issued shell commands and Python code in a
  separate container and workspace. It keeps that code away from the agent's
  stored state, inference provider keys, and research wallet files. Sessions and
  subagents share this executor; each task does not get a separate sandbox.
- **Tor gateway** routes public TCP traffic and DNS from Hermes and its executor
  through Tor, hiding their source network address from Internet destinations.
  Network rules block direct Internet fallback and access to host, VM, and
  private-network services except the stack's explicit internal connections.
- **[Teep](https://github.com/13rac1/teep)** connects Hermes to confidential-computing
  inference providers through an OpenAI-compatible API. It handles provider
  credentials and upstream attestation checks in a separate service with its own
  direct Internet connection. The stack preserves Teep's upstream verification
  policy, including its allowed failures; service health alone does not prove
  successful attestation.
- **[x402_treazury](https://github.com/mikeperry-tor/x402_treazury)** gives Hermes
  research tools backed by paid information APIs. These provide an alternative
  to directly browsing websites that subject Tor users to extra CAPTCHAs,
  rate limits, or bans. It pays for x402 APIs using **Zcash-funded rotating Base
  USDC wallets**, with **Tor circuit isolation tied to each payment identity**.
  Rotating wallets and changing the Tor isolation identity reduce the linkability
  of API usage across payments. Hermes receives authenticated tool access while
  wallet files and spending keys stay in a separate container.
- **HAProxy and optional Tailscale Funnel** provide access to the authenticated
  webapp. HAProxy supplies the local entry point; Funnel optionally makes it
  reachable over public HTTPS without requiring visitors to join a tailnet.
  Remote access remains separate from the agent's Tor egress.

x402_treazury exposes twelve research tool groups covering web, science,
shopping, world, social, property, travel, health, business, finance, security,
and general API discovery. You can start using Hermes before creating or
funding the research treasury.

To avoid blocking during catalog and metadata downloads, x402_treazury tries
three isolated Tor circuits, then falls back to up to two paid relay downloads.
This keeps research tools available without relying on direct website browsing.

Funding swaps use Zcash, unique shielded refund addresses, and isolated Tor
circuits. The main remaining funding linkability is correlation by timing and
amount among Near Intents Base USDC swaps. Closely spaced funding swaps are
easier to correlate. x402_treazury makes effort to schedule swaps early and
decouple their execution from prior transactions, but this unlinkability
ultimately depends upon the incoming volume of Base USDC swaps coming from Near
Intents over the course of your usage. After an initial single bootstrap wallet
phase, the provided configuration uses four distinct sets of rotating USDC
wallets, with usage assigned by x402 API endpoint topic. These wallets rotate
independently. See the [x402_treazury guide](docs/x402_treazury.md) for funding,
wallet groups, and operation.

## Get started

You need a container engine, Compose 2.36+, `make`, and Python 3. Use either:

- **Docker Engine 28+** with Linux containers, or
- **rootless Podman 5.4+** on Linux, with the `docker` command provided by
  `podman-docker` (or a `docker` script that runs `podman`) and the user API
  socket enabled: `systemctl --user enable --now podman.socket`. Rootless Podman
  runs no root daemon, and container root maps to your unprivileged user.

The stack detects Podman and adds its overlay files itself. It requires isolated
bridge networking and Linux GRE support; startup checks reject unsupported
setups. Its fixed `10.203.80.0/24` through `10.203.84.0/24` networks, local
ingress `10.203.85.0/24`, and optional Funnel `10.203.87.0/24` must not overlap
your existing networks.

On rootless Podman, containers stop when you log out unless lingering is enabled
for your user (`loginctl enable-linger`, which may need an administrator), and
they start again after a reboot only with `systemctl --user enable
podman-restart.service`. See [engine differences](docs/architecture.md#rootless-podman).

Initialize your local settings:

```sh
make init
```

Set `NEARAI_API_KEY` in the generated root `.env` for the default NearAI
`neardirect` inference route through Teep. The default model is
`neardirect:z-ai/glm-5.3-flash-long`. Set `HERMES_DEFAULT_MODEL` in `.env` and
run `make up` to choose another default. See [inference configuration](docs/configuration.md#host-inference-access)
for model selection and the local OpenAI-compatible endpoint.

Start the stack (including cached image builds):

```sh
make up
```

Open **http://127.0.0.1:9120** and log in as `admin` with the password saved in
`config/webapp/password`. Tor bootstrapping can take several minutes.
`make init` preserves existing configuration and credentials; add new settings
to an existing `.env` explicitly using [`.env.example`](.env.example).
Startup rebuilds changed image inputs and reuses Docker's cache for unchanged
layers. Builds may need Internet access. Use `make build` to build ahead of time.

Use the terminal client with:

```sh
make chat
```

For an optional desktop inside the SSH executor, set `COMPUTER_USE_ENABLED=true`
in `.env`, then run `make down` and `make up`. This selects a substantially larger
image and enables computer-use and browser automation tools when ready. See
[desktop configuration and qualification status](docs/configuration.md#optional-executor-desktop).

For remote browser access, follow the [optional Funnel setup](docs/webapp.md#optional-public-funnel).
Funnel is disabled by default and requires explicit enrollment and activation.

## Enable paid research when ready

Edit `config/x402_treazury/research_desk.toml` to adjust wallet funding policy,
payment caps, source/tool selections, or instructions.

You can restore this file to the defaults by removing it: `make x402_treazury-config`
and `make x402_treazury-init` below will create this file if missing; both commands
preserves an existing file. You can also edit the `config/x402_treazury/research_desk.toml`
**before or after** `make x402_treazury-init`: initialization does not freeze the
policy or require it to be finalized.

For config changes after the stack is running, stop with `make down`, edit, then
restart with `make up`; there is no hot reload. Starting with a changed policy
can spend funds under its automatic funding settings. Keep the deployment's
network, state paths, and listener settings intact, and use the documented
procedure when renaming wallet groups to preserve their wallets. See
[configuration and wallet renaming](docs/x402_treazury.md#edit-the-research-configuration).

Follow the [x402_treazury onboarding guide](docs/x402_treazury.md) to create a
treasury and back it up before depositing ZEC:

```sh
make x402_treazury-init
```

The provided `research_desk.toml` uses a `[wallet_boostrap]` stanza that
prepares only `general` initially, with a randomized $2-3 USDC allocation plus
Zcash fees and bridge costs. If you just want to try out some light x402 usage,
an initial funding of $5 worth of ZEC is plenty. For continued usage, ~$20
worth of ZEC will fully fund all four wallet groups in a staggered fashion,
triggered by the first use of an API call from each group.

If you remove the `[wallet_bootstrap]` stanza, preparation funds all declared
managed groups at during the following `make x402_treazury-prepare` step; this
prevents any of the other wallet group's API calls from ever being funded by the
initial shared bootstrap wallet, but the immediate consecutive nature of these
swaps likely makes them easy to correlate on the Base blockchain. It also will
make the prepare step take much longer before you can get going, and require
~$12 worth of ZEC to fund these wallets, before you are able to use all APIs.

After adjusting your wallet selection and funding the displayed shielded receive
address with sufficient ZEC, ensure the stack is up (`make up`), then run:

```sh
make x402_treazury-prepare
```

Preparation funds the selected bootstrap wallets, warms provider catalogs, and
connects research tools without restarting Hermes. It can spend ZEC and USDC
under the configured policy and will wait for spendable funds while the webapp
remains available, but the agent will be unable to use any x402_treazury APIs
until funding and catalog warming complete.

Use `make x402_treazury-status` to inspect current wallet funding status (this also works while the stack is down).

## Living Dangerously: Full wallet access

You can also give the agent a general-purpose cryptocurrency wallet by uncommenting
the `[servers.toolbox.swap_control]` stanza at the bottom of `config/x402_treazury/research_desk.toml`.

This gives your agent **full control over their ZEC wallet**: they can send and
receive shielded ZEC using single-use shielded addresses, create
exact-input-amount cryptocurrency addresses on Near Intents for any supported
cryptocurrency, and execute Near Intents swaps of any amount to any
cryptocurrency destination address supported by Near Intents.

**This allows your Hermes agent to conduct arbitrary cryptocurrency activity**.
The default outgoing limit is 0.5 ZEC, but if you leave that commented, there is
no outgoing limit other than whatever ZEC you send to your agent's wallet. Send
and receive swap tools can be enabled independently.

These tools are available on the `x402_treazury_toolbox` MCP endpoint, which
also contains tools to perform arbitrary x402 raw calls by default, even without
this swap option enabled. You can give this toolbox endpoint to select agent
profiles in the Hermes agent profile configuration tools panel.

As with everything else in this stack, all swaps are conducted over Tor. Swaps use independently isolated Tor circuits.

> *NOTE*: There currently is no way to transfer ZEC out of x402_treazury
> other than by enabling this feature and politely asking your agent to please
> send you its remaining ZEC. **Be kind to your agents!**

## Everyday operation

Use `make up` and `make down` to start and stop the deployment. Ordinary shutdown
preserves conversations, configuration, wallets, and executor work. **Do not use
`docker compose down -v` for routine shutdown:** it deletes application volumes,
including wallets and conversations. Backups must include the named volumes as
well as local configuration and data; see [backup scope](docs/configuration.md#backup-scope).

Use `make check-updates` to check stack versions and `make plugins` to manage
persistent Hermes plugins. See [updates, plugins, and privacy defaults](docs/updates-and-plugins.md)
for applying updates and understanding plugin authority.

For startup diagnostics:

```sh
python3 scripts/stack.py compose logs -f hermes tor executor
```

Use the deployment-aware `scripts/stack.py compose` wrapper for other Compose
operations so your enabled options are included.

## Privacy and access limits

An authenticated webapp user has administrative agent authority. The browser's
interactive terminal runs in the agent container and is separate from the
model's SSH code executor. Plugins also run with agent privileges. Only grant
access to people and plugins you trust.

By default, supported external raster images load through the authenticated
gateway over Tor. Active previews and external players have non-loading
fallbacks. Deliberate external link clicks use your browser's own connection;
browser requests do not inherit Docker's Tor route. See [webapp content policy](docs/webapp.md#external-content-policy)
for image consent, other policy modes, and current limits.

Tor egress does not cover Teep's direct provider connection or your browser's
connection to the webapp. The container boundaries do not protect against a
compromised host or Docker engine. For exact grants and trust boundaries, see
[architecture and isolation](docs/architecture.md). For build procedures and
test coverage, see [development and qualification](docs/development.md).
