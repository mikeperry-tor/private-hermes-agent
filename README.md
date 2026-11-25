# Private Hermes

<p align="center">
  <img src="docs/images/PrivateHermes.jpg" alt="Private Hermes" width="50%">
</p>

Private Hermes is a Docker and Podman Compose stack for running
[Hermes Agent](https://github.com/NousResearch/hermes-agent)
with private research tools, code execution in a separate container, and an
authenticated web interface. It brings together Tor-routed Internet access,
confidential-computing inference through either
[Teep](https://github.com/13rac1/teep) or local inference, and paid research
APIs through [x402_treazury](https://github.com/mikeperry-tor/x402_treazury).

The goal is to let an agent research and write code while keeping your network
address, inference requests, and agent payment history private, and
[sandboxing the agent](#service-hardening) from accessing your local machine.
You can use Hermes through your browser or terminal, and optionally enable
public HTTPS access through Tailscale Funnel or access through a Tor onion
service.

By default, the webapp also prevents [displayed content](#web-page-previews)
from bypassing Tor through your browser: supported external images load through
the stack's Tor gateway, and active external content is blocked. You can use a
normal browser with these protections; external links you click still use your
browser's connection.

## Components and the problems they solve

- **[Hermes Agent v0.23.3](https://github.com/NousResearch/hermes-agent)**
  provides chat, tool use, skills, and subagent orchestration. Its webapp and
  terminal client let you work with the same persistent agent. This stack
  supports both Docker and rootless Podman with
  [hardened services](#service-hardening): strong network isolation between
  containers, no host access by default, an SSH executor, and least-privilege
  operation.
- **[Tailscale Funnel](https://tailscale.com/docs/features/tailscale-funnel)**
  provides access to the Hermes Admin WebApp over public HTTPS, including on the
  free plan. The deploying node joins a tailnet, while visitors connect from a
  regular browser without joining the tailnet or installing Tailscale. The
  stack's Tailscale node terminates TLS with a local private key and a Let's
  Encrypt certificate, so Tailscale cannot decrypt your traffic. Funnel relays
  forward encrypted traffic, and Tailscale controls the public `ts.net` domain.
  See the
  [Tailscale launch blogpost](https://tailscale.com/blog/introducing-tailscale-funnel)
  for more detail.
- **[Tor](https://hub.docker.com/r/dockurr/tor)** routes TCP traffic and DNS
  from Hermes and its executor through Tor, hiding their source network address
  from Internet destinations. Network rules block direct Internet fallback, and
  local network destinations require a
  [host or LAN grant](#local-inference-and-http-mcp). Optional
  [Tor onion service ingress](#tor-onion-service) lets you reach the Hermes
  Admin WebApp via an onion URL using
  [Tor Browser](https://www.torproject.org/download/) or
  [Brave's Tor Window](https://support.brave.app/hc/en-us/articles/360018121491-What-is-a-Private-Window-with-Tor-Connectivity).
- **[x402_treazury](https://github.com/mikeperry-tor/x402_treazury)** gives
  Hermes research tools backed by paid information APIs. These provide an
  alternative to browsing websites directly, where Tor users face extra
  CAPTCHAs, rate limits, or bans. It pays for x402 APIs using **Zcash-funded
  rotating Base USDC wallets**, with **Tor circuit isolation tied to each
  payment identity**. Rotating wallets and changing the Tor isolation identity
  reduce the linkability of API usage across payments. Hermes receives
  authenticated tool access while wallet files and spending keys stay in a
  separate container.
- **[Teep](https://github.com/13rac1/teep)** connects Hermes to
  confidential-computing inference providers through an OpenAI-compatible API.
  It handles provider credentials and upstream attestation checks in a separate
  service with its own direct Internet connection. The stack preserves Teep's
  upstream verification policy, including its allowed failures. Teep is not
  required; [local inference](#local-inference-and-http-mcp) is also supported.

`x402_treazury` exposes twelve research tool groups covering web, science,
shopping, world, social, property, travel, health, business, finance, security,
and general API discovery. You can start using Hermes before creating or funding
the research treasury.

To avoid blocking during catalog and metadata downloads, `x402_treazury` tries
three isolated Tor circuits, then falls back to up to two paid relay downloads.
This keeps research tools available without relying on direct website browsing.

Funding swaps use Zcash, unique shielded refund addresses, and isolated Tor
circuits. The main remaining funding linkability is correlation by timing and
amount among Near Intents Base USDC swaps, because closely spaced swaps are
easier to correlate. `x402_treazury` schedules swaps early to decouple their
execution from prior transactions, though unlinkability still depends on overall
Near Intents Base USDC swap volume during your usage. After an initial single
bootstrap wallet phase, the provided configuration uses four distinct sets of
rotating USDC wallets assigned by x402 API endpoint topic, and these wallets
rotate independently.

## Prerequisites

You need a container engine, Compose 2.36+, `make`, and Python 3. Use either:

- **Docker Engine 28+** with Linux containers, or
- **rootless Podman 5.4+** on Linux, with the user API socket enabled:
  `systemctl --user enable --now podman.socket`.
  Rootless Podman runs no root daemon, and container root maps to
  your unprivileged user.

### Using Rootless Podman

On rootless Podman, Compose 2.36+ must be the provider of `podman compose`;
Debian 13's `docker-compose` package is older. Install the Compose release binary
for your user and set `PODMAN_COMPOSE_PROVIDER` to its path, or name it in
`compose_providers` in `~/.config/containers/containers.conf`.

Containers stop when you log out unless lingering is enabled for your user
(`loginctl enable-linger`, which may need an administrator). After a reboot, run
`make up` to start the stack again.

## Getting Started

If you use Docker, `.env` is copied into place for you during initialization:

```sh
make init
```

For Podman, run `CONTAINER_ENGINE=podman make init` instead, then set
`CONTAINER_ENGINE=podman` in the generated `.env` for subsequent commands.
Initialization uses your engine's Compose command to render configuration, so
that command must already be installed. Rerunning initialization preserves your
settings.

Set a provider API key in the generated root `.env` to use Teep. The example
selects `neardirect:z-ai/glm-5.3-flash` for NearAI with `NEARAI_API_KEY`. Set
`TEEP_INSTALL_MODEL` to a model your provider serves, or leave it blank to choose
in Hermes after startup. See
[inference configuration](docs/configuration.md#host-inference-access) for Teep
settings, or configure [local inference](#local-inference-and-http-mcp).

To build and start the stack:

```sh
make up
```

> **NOTE**: Use the documented `make` commands to operate the stack (run
> `make` or `make help` for a summary). `make up` prepares local state,
> validates the engine setup, and starts the enabled services. `make down`
> shuts the stack down.

Builds need Internet access and use your host's default networking, not Tor.

Once the stack is up, open **[http://localhost:9120](http://localhost:9120)**
and log in as `admin` with the password in `config/webapp/password`.

With Teep enabled and `TEEP_INSTALL_MODEL` blank, choose **I'll choose a
provider later** if prompted in the WebApp. Open **Settings -> Model**, select
**Teep**, choose a model, and apply the selection. In `make chat`, choose
**Teep** and a model in the provider setup prompt.

The browser's Code terminal and `!command` in `make chat` run in the same SSH
executor as the agent. For an administration shell, set
`WEBAPP_TERMINAL_ENVIRONMENT=agent`, run `make up`, then reload the browser and
reopen `make chat`. See
[terminal operation](docs/webapp.md#terminal-environment).

If you prefer terminal use, open the terminal client with:

```sh
make chat
```

## Local inference and HTTP MCP

To use local inference or local MCP servers, allow their ports in `.env`:

```dotenv
# Set false if you only need local inference. Keep true to switch at runtime.
TEEP_ENABLED=false

# Allow port 11434 and 8080 to be accessed on the host by the hermes framework:
HERMES_INTEGRATIONS_ALLOWED_HOST_PORTS=11434,8080

# Allow these three LAN endpoints to be accessed by the hermes framework:
HERMES_INTEGRATIONS_LAN_ENDPOINTS=192.168.1.50:8765,192.168.1.50:8766,192.168.1.51:9000
```

> **NOTE**: Docker's default AppArmor profile can keep host port grants closed
> on Linux hosts (including Debian). Rootless Podman supports host and LAN
> grants on Linux. If you need to keep Docker, see the
> [gateway-only AppArmor workaround](docs/configuration.md#native-linux-docker-with-apparmor)
> for host port grants.

Run `make down` followed by `make up` after changing either allow list or Teep
mode.

To configure local inference, use Hermes
[provider setup](http://localhost:9120/#/settings?tab=providers&pview=custom-endpoints)
to add an OpenAI-compatible provider for the local endpoint. **Use
`host.docker.internal` for the host, rather than `localhost`**.

You can configure HTTP MCP services and credentials in Hermes as well. See the
[configuration guide](docs/configuration.md#local-inference-and-http-mcp) for
provider setup.

> **NOTE**: Agent-created code can still invoke allowlisted Hermes tools by RPC
> from the code sandbox container, including tools that access a local backend.
> By default, none of these tools can access host or LAN addresses, but plugin
> tools you add may not block access to your allowed host or LAN endpoints.

## Paid Research APIs and Cryptocurrency Wallet

The stack includes
[x402_treazury](https://github.com/mikeperry-tor/x402_treazury/), which gives
Hermes Agent x402 APIs for web search, web page access, and a collection of data
services using privacy-enhanced [x402 micropayments](https://x402.org/).

To create a treasury and back it up before depositing ZEC:

```sh
make x402_treazury-init
```

The provided `config/x402_treazury/research_desk.toml` (created after `make
x402_treazury-init`) has 12 MCP endpoints organized by topic, automatically
connected to your Hermes Agent. Funding this wallet with $5 worth of ZEC enables
all endpoints sharing a pair of ~$2.50 USDC wallets.

This gets you started, while adding $20 worth of ZEC improves privacy: the 12
MCP endpoints split across four independent wallet groups after your agent uses
an API from each group for the first time, avoiding linking research across
broad topic areas.

You can still start with $5 worth of ZEC to try it out and add more ZEC to the
agent's shielded wallet at any time; the four isolated wallet groups are created
as you use those topics.

USDC wallet addresses also rotate to reduce long-term linkability of your
research over time. See the
[x402_treazury README](https://github.com/mikeperry-tor/x402_treazury/#how-it-works)
for details on this process and its privacy properties.

After funding the displayed shielded receive address with sufficient ZEC, ensure
the stack is up (`make up`), then run:

```sh
make x402_treazury-prepare
```

Preparation funds a single initial shared bootstrap wallet, warms provider
catalogs, and connects research tools without restarting Hermes. The 12 MCP
endpoints are added to Hermes Agent automatically, and become ready once
funding and catalog warming complete.

Use `make x402_treazury-status` to inspect wallet funding status and the
shielded ZEC funding address (this also works while the stack is down).

See the
[x402_treazury README](https://github.com/mikeperry-tor/x402_treazury/blob/main/README.md),
[README_ADVANCED.md](https://github.com/mikeperry-tor/x402_treazury/blob/main/README_ADVANCED.md),
and this repository's
[x402_treazury onboarding guide](docs/x402_treazury.md) for more information.

For config changes after the stack is running, stop with `make down`, edit, and
restart with `make up`; there is no hot reload.

## Living Dangerously: Full wallet access

You can give the agent a general-purpose cryptocurrency wallet by uncommenting
the `[servers.toolbox.swap_control]` stanza at the bottom of
`config/x402_treazury/research_desk.toml`.

This gives your agent **full control over its ZEC wallet**: it can send and
receive shielded ZEC using single-use shielded addresses, create
exact-input-amount cryptocurrency addresses on Near Intents for any supported
cryptocurrency, and execute Near Intents swaps of any amount to any
cryptocurrency destination address supported by Near Intents.

**This allows your Hermes agent to conduct arbitrary cryptocurrency activity**.
The default outgoing limit is 0.5 ZEC, and if you leave that commented, there is
no outgoing limit other than whatever ZEC you send to your agent's wallet. Send
and receive swap tools can be enabled independently.

These tools live on the `x402_treazury_toolbox` MCP endpoint, which also
provides tools for arbitrary x402 raw calls by default, even without this swap
option enabled. You can assign this toolbox endpoint to individual agent
profiles in the Hermes agent profile configuration tools panel.

As with everything else in this stack, all swaps run over Tor using
independently isolated Tor circuits.

> *NOTE*: There is no built-in command to transfer ZEC out of `x402_treazury`
> other than enabling this feature and politely asking your agent to send you
> its remaining ZEC. **Be kind to your agents!**

## Sharing directories with Private Hermes agents

Share folders from your computer when you want an agent to work on an existing
project. Add a comma-separated list of `host:executor` pairs to `.env`. For
each pair, enter the absolute path on your computer first and the path the agent
will use below `/mnt/projects/` second.

```dotenv
CODE_EXECUTOR_BIND_MOUNTS="/home/me/my-app:/mnt/projects/my-app,/home/me/notes:/mnt/projects/notes"
```

Use your own folder paths, then run `make down && make up`. Ask the agent to
use its terminal to work in `/mnt/projects/my-app` or `/mnt/projects/notes`.
Its edits update the files on your computer. See the
[shared project setup](docs/configuration.md#shared-project-setup) for applying
changes and removing shares.

Share only folders whose contents the agent and any software it runs may
read, change, or delete. Keep credentials outside shared folders and include
the host folders in your [backups](docs/configuration.md#backup-scope).
Review changes before using host tools that can run project scripts,
Git hooks, or editor tasks. The same risk applies when you work on the host
with files from `data/executor/workspace/` or `data/executor/home/`, even if
you never set `CODE_EXECUTOR_BIND_MOUNTS`.

Review Git changes in the WebApp's **Code** terminal, or ask the agent to use
its terminal tool in chat. See [reviewing changes in the executor](docs/configuration.md#reviewing-changes-in-the-executor)
and [Git's security guidance](https://git-scm.com/docs/git#_security).

See [project permissions](docs/configuration.md#shared-project-filesystem-permissions)
for UID mappings and permission troubleshooting. Run the
[project mount tests](docs/development.md#project-mount-tests) to check
compatibility with your local engine.

## Web Page Previews

By default, the Web UI uses a Content Security Policy and an internal Tor proxy
to retrieve supported external raster images. External audio, video, and
interactive web previews are blocked. This policy covers content rendered in the
Web UI; external links you click use your browser's normal connection.

To allow Hermes Agent to show you previews of web pages inside the agent Web UI,
set `WEBAPP_EXTERNAL_CONTENT=browser_native` in `.env`, run `make up`, reload
the webapp, and start a new conversation.

If IP address privacy is important to you, use this mode only with Tor Browser
or Brave Browser's Private Window with Tor. For remote access, choose
[Funnel or onion ingress](#webapp-ingress); the stack does not detect or verify
browser Tor routing in `browser_native` content access mode.

See the [webapp content policy](docs/webapp.md#external-content-policy) for
modes and limits.

## Browser and Computer Use

To give Hermes Agent a full Linux graphical desktop environment inside an
isolated container service, set `COMPUTER_USE_ENABLED=true` in `.env`, then run
`make down` and `make up`.

This selects a substantially larger image and enables computer-use and browser
automation tools for the agent.

## WebApp Ingress

Local access at **[http://localhost:9120](http://localhost:9120)** is always
enabled. Remote ingress is optional: you can enable Tailscale Funnel, a Tor
onion service, or both.

Each hostname requires its own login using the same username and password: log
in as `admin` with the password in `config/webapp/password`.

### Tor onion service

Onion ingress is disabled by default. Its image is included in `make build` and
`make up`, even while onion ingress is disabled. Create or display your address
with:

```sh
make onion-address
```

If you have only run `make init` and have not built the stack yet, run
`make build` first.

Creating the identity is offline and does not publish the service. If the stack
is already running, run `make down` before first creation or repair. Once
created, the same command displays the address while the stack is running.

Add `TOR_ONION_ENABLED=true` to root `.env`, then run `make up`. Open the
printed `http://...onion` URL in Tor Browser and log in. If changing a running
deployment, run `make down` followed by `make up` to apply the setting. Funnel
can stay off.

The address and private key are stored together in `data/tor/onion-service/`.
Back up the whole Tor state directory with its ownership and permissions intact;
the address alone cannot restore the identity. Repeating `make onion-address`,
rebuilding, or disabling and re-enabling ingress preserves the address. Restore
damaged keys from backup; the command refuses to replace them silently.

Set `TOR_ONION_ENABLED=false` and run `make down` followed by `make up` to
withdraw onion ingress without deleting its key or changing localhost and Funnel
access. See
[onion operation and recovery](docs/webapp.md#optional-onion-ingress) and
[backup scope](docs/configuration.md#backup-scope).

### Public HTTPS with Tailscale Funnel

Tailscale Funnel provides a **public HTTPS** URL you can access from anywhere;
visitors do not need a Tailscale account. Funnel is available on the Tailscale
free plan, so it costs nothing to sign up and use, though it is not enabled by
default and requires manual configuration in the Tailscale Admin WebUI.

> **NOTE**: You must regenerate a new auth key every 90 days. Tailscale does not
> support permanent Funnel registration keys.

To use Funnel, permit Funnel for a tag in your tailnet policy, then generate a
tagged auth key for that tag:

1. In the [Tailscale admin JSON editor](https://console.tailscale.com/admin/acls/file)
   (open **Access controls -> JSON editor**), register a tag owner for
   `tag:private-hermes` under `tagOwners` plus a top-level `nodeAttrs` entry
   allowing Funnel for it, merged with your tailnet policy (not nested inside
   `acls` or `grants`):

```json
{
  "tagOwners": {
    "tag:private-hermes": ["autogroup:admin"]
  },
  "nodeAttrs": [
    { "target": ["tag:private-hermes"], "attr": ["funnel"] }
  ]
}
```

   Defining `tagOwners` only authorizes who can assign `tag:private-hermes`;
   the tag itself is applied to the container when it enrolls with the auth key
   below. (If you enroll with an untagged user auth key instead, `"target"`
   must match that user or `"autogroup:member"`, which permits Funnel for all
   user-owned nodes; a tagged key is preferred because it scopes Funnel to this
   node's tag.)
2. In the [Tailscale admin key panel](https://console.tailscale.com/admin/settings/keys)
   (open **Settings -> Keys -> Auth keys -> Generate auth key**), enable
   **Tags**, and select `tag:private-hermes` so the generated `TS_AUTHKEY` tags
   the node on enrollment.

The stack writes the Funnel serve configuration directly, so it does not trigger
the Tailscale CLI's interactive approval that normally adds the `funnel`
attribute. Allow the policy and public DNS to propagate after saving.

Add these settings to root `.env`, using your node's exact assigned `.ts.net`
hostname:

```dotenv
TAILSCALE_FUNNEL_ENABLED=true
TAILSCALE_HOSTNAME=private-hermes
TAILSCALE_FUNNEL_HOST=private-hermes.your-tailnet.ts.net
TAILSCALE_FUNNEL_PORT=443
TS_AUTHKEY=your-enrollment-key
```

Run `make down` and `make up` (`make up` builds any newly enabled images,
including `tailscale`). Open `https://private-hermes.your-tailnet.ts.net` and
log in with Hermes credentials.

The WebApp login cookies for this domain are marked Secure. Ports 443, 8443, and
10000 are supported; include a nondefault port in the URL. You can remove
`TS_AUTHKEY` after successful enrollment because the node identity persists in
its state volume.

If the URL does not resolve, confirm the node's `funnel` capability and public
DNS record as described in
[Funnel setup and troubleshooting](docs/webapp.md#optional-public-funnel).

## Updates and Backups

Update component images in place with:

```bash
make down
git pull
make up
```

If the packaged `x402_treazury` `research_desk.toml` config changes during an
update, or you customize `config/x402_treazury/research_desk.toml`, `make up`
and `make x402_treazury-prepare` display differences from the packaged defaults.
To reset this file to the defaults, remove it and run `make
x402_treazury-config` (it creates the file only if missing).

Use `make check-updates` to check stack versions and `make plugins` to manage
persistent Hermes plugins. See
[updates, plugins, and privacy defaults](docs/updates-and-plugins.md) for
applying plugin updates and understanding plugin authority.

Backups must include the named volumes as well as local `config` and `data`
directories; see [backup scope](docs/configuration.md#backup-scope).

## Service hardening

Private Hermes adds substantially stronger containment than the
[stock Hermes v0.23.3 Compose setup](https://github.com/NousResearch/hermes-agent/blob/v0.23.3/docker-compose.yml),
which uses host networking.

The additional controls limit what malicious tool output, prompt-injected
commands, or a compromised service can reach:

- **Network containment:** Hermes and its executor have isolated networks and
  default-deny firewalls. Host, VM, private network, and cloud metadata
  addresses are blocked by default, while you can grant Hermes exact host or LAN
  TCP sockets. The firewalls prevent direct Internet fallback if Tor fails. Tor
  egress does not cover Teep's direct provider connection or your browser's
  connection to the webapp.
- **Code and secret separation:** Agent code and desktop usage run as an
  unprivileged user in the SSH executor, without mounts for agent config,
  provider keys, or wallets. This limits theft or modification of those files by
  generated code. Different agent profiles share the same code and desktop
  environment.
- **Reduced service privileges:** Services drop default container capabilities
  and receive only those needed for their work, with privilege escalation
  through setuid executables and file capabilities blocked. The executor and
  most supporting services have read-only root filesystems, limiting system-file
  modification while keeping designated state and work directories writable.
- **Protected browser rendering:** The default webapp content policy prevents
  automatic external content from exposing the viewing browser's network
  address, including when you use a normal browser.

These controls reduce exposure and the damage a compromise can cause; they do
not protect against kernel or container-engine exploits or a compromised host.

For exact grants and trust boundaries, see
[architecture and isolation](docs/architecture.md). For build procedures and
test coverage, see [development and qualification](docs/development.md).

## Near Hackathon Submission

Private Hermes is the judging entry-point repository in a three-repository
submission for the [NEAR Hackaton](https://nearhackaton.com).

Private Hermes was developed exclusively during the Hackathon's official
contest dates (2026-10-19 through 2026-11-14).

Our official submission also covers
[x402_treazury](https://github.com/mikeperry-tor/x402_treazury/) and
[TEEProof](https://github.com/13rac1/teep), both of which were updated
significantly during the hackathon to improve their functionality and
performance with Near ecosystem technologies for use in this stack.

Together, these three repositories compose one submission by Mike Perry and
Bradley Erickson (as team Hardened Minds) in the following three
[official hackathon tracks](https://nearhackathon.com/#tracks):

1. **Private by design**

   Private Hermes is privacy-by-design end-to-end, starting with a local,
   sandboxed, hardened, and Tor-routed Hermes Agent (this repository).
   Best-in-class privacy technology is used for every connected component: Tor,
   Zcash, NearAI, and Near Intents swaps.

   Hermes Agent itself, chosen for its top-ranking spot on
   [multiple OpenRouter App Leaderboard Categories](https://openrouter.ai/apps),
   has been modified to disable analytics, improve component isolation, reduce
   service capabilities, support rootless Podman, and route everything through
   Tor, including agent-provided remote media elements. Anything that could not
   be safely sent through Tor is blocked.

   NearAI's verifiably private inference is verified thoroughly, with TEE
   attestation checked by [TEE Proof](https://github.com/13rac1/teep) before
   each prompt is sent. Attestation-pinned TLS and end-to-end encryption are
   enforced (`neardirect` uses pinned TLS to the TEE-generated TLS key;
   `nearcloud` uses both cloud-pinned TLS and end-to-end OpenAPI field-level
   encryption to the inference endpoint TEE).

2. **Give AI a wallet**

   Private Hermes can be given tools to
   [send and receive any cryptocurrency](#living-dangerously-full-wallet-access)
   supported by Near Intents, via single-use exact-input and exact-output
   unique address swaps to and from its shielded Zcash reserve. These swaps are
   isolated over independent Tor circuits.

   Private Hermes also has privacy-enhanced access to Tor-routed x402 research
   APIs via
   [x402_treazury](https://github.com/mikeperry-tor/x402_treazury/), which uses
   shielded Zcash swaps via Near Intents to fund rotating, small-denomination,
   isolated Base USDC wallets to pay for x402 API micropayments.

3. **Trust, but verify**

   On the cryptocurrency side, you can set per-transaction payment limits, and
   the agent stays isolated from cryptocurrency keys through the hardened
   containerization of this stack.

   The connected
   [x402_treazury Research Desk](https://github.com/mikeperry-tor/x402_treazury/blob/main/examples/deployments/research_desk.toml)
   provides blockchain analysis, banking compliance, IP address analysis, phone
   number analysis, company financial data, customer review data, website
   technology stack assessment tools, and many other tools to help the agent
   evaluate entities it interacts with and research any assigned topic.

## Work done in the hackathon

- **This repository** is hackathon work: every commit is dated 2026-11-08 or
  later; tag `nearhackathon2026` marks the submission entry version.
- **Other Repositories:** these existed before the hackathon period, but have
  qualifying patches and commits.
  - [Hermes Agent](https://github.com/NousResearch/hermes-agent) (MIT License),
    Nous Research. The agent and webapp, built from the official release with
    local patches in
    [components/hermes/](https://github.com/mikeperry-tor/private-hermes-agent/tree/main/components/hermes).
  - [x402_treazury](https://github.com/mikeperry-tor/x402_treazury)
    (AGPL-3.0), a project of this team. Its NEAR Intents swap code dates from
    2026-10-02, and significant work was done after the official hackathon start
    date to improve the privacy and reliability of its USDC payments; these
    privacy properties rely heavily on Near Intents for shielded Zcash swaps.
    Additionally, the built-in cryptocurrency send and receive tools were
    created using Near Intents swaps specifically for this competition.
    Repository commit `b9efb0fc6692eb349e3143b2fa94ad159cd64858` is the first
    commit within the hackathon timeframe; tag `nearhackathon2026` marks the
    submission entry version.
  - [TEE Proof (teep)](https://github.com/13rac1/teep) (AGPL-3.0), a project of
    this team. Its repository was created on 2026-03-20, and its NEAR AI
    provider dates from 2026-03. Changes in the hackathon period include
    [13rac1/teep#191](https://github.com/13rac1/teep/pull/191): teep reports
    the failed Sigstore lookup for one image that NEAR AI runs instead of
    blocking the request, and still enforces `compose_binding`. Eligible
    timeframe commits begin at `a43d14166c130d8cb1a4937eca28984d93bf75b1`; tag
    `nearhackathon2026` marks the submission entry version.
- **Non-Covered Repositories**: external independent work, not submitted for
  consideration.
  - Tor, HAProxy, Tailscale, Alpine, and Debian images, as pinned in
    `components/`.

**Other Submissions**: Separate from these repositories (which are a team
effort of Mike Perry and Bradley Erickson), Bradley Erickson is also the sole
developer of his independent NEAR HACKATHON 2026 project,
[BuildDeed](https://github.com/13rac1/builddeed). That submission shares no
code with this one. Mike Perry has no independent NEAR HACKATHON submissions.
