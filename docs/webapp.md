# Authenticated webapp and optional remote ingress

The base Compose stack always includes the local Hermes WebApp, bound to host
loopback and protected by Hermes username and password login. You can optionally
add public HTTPS access through Tailscale Funnel, Tor Browser access through a
Tor onion service, or both.

Tailscale Funnel does not require visitors to have a Tailscale account; all
remote visitors authenticate with Hermes credentials. Because upstream designed
Hermes password authentication for trusted networks and VPNs, enabling public
ingress exposes its login and session endpoints to Internet traffic.

## First-run localhost access

Run `make init`, then edit the root `.env` explicitly (rerunning `make init`
never modifies an existing `.env`):

```dotenv
WEBAPP_BIND=127.0.0.1
WEBAPP_PORT=9120
WEBAPP_USERNAME=admin
TAILSCALE_FUNNEL_ENABLED=false
```

Build and start the stack:

```sh
make build
make up
```

Open `http://127.0.0.1:9120` or `http://localhost:9120` and sign in with
`WEBAPP_USERNAME` and the password stored in `config/webapp/password`.

### Credentials and generated proxy config

`make init` creates missing credentials and renders `config/webapp/proxy.cfg`
without starting containers or initializing wallets:

- `config/webapp/password` and `config/webapp/auth.json` (which stores the
  scrypt hash and persistent signing secret) have mode `0600`. The generator
  never prints the password.
- Credentials are published atomically, password first. Rerunning `make init`
  preserves matching credentials, finishes an interrupted creation using the
  saved password, and resyncs a mismatched hash to the saved password while
  keeping the signing secret.
- If `config/webapp/password` is missing while `auth.json` remains valid,
  existing authentication continues to work and initialization warns without
  replacing the identity. Restore the password from backup or run
  `make webapp-rotate` intentionally.
- `make webapp-credentials` creates missing credentials and prints the
  configured `WEBAPP_USERNAME` and password file path (`config/webapp/password`)
  without printing the password. Both `make webapp-credentials` and
  `make webapp-rotate` touch only credential files, so unrelated invalid
  settings in `.env` never block login repair. If rotation is interrupted, rerun
  `make webapp-rotate` to rotate both password and signing secret cleanly.
- `config/webapp/proxy.cfg` is regenerated on every `make up`; edit `.env`
  rather than the generated file. Only offline `setup` mounts `config/webapp/`
  (read-only) to copy auth settings into `hermes-data`. Neither the executor nor
  Tailscale receives WebApp credentials.

For day-to-day commands after `make up`, use the Compose wrapper so active
overlays match `.env`:

```sh
python3 scripts/stack.py compose logs -f hermes webapp-proxy
make chat
python3 scripts/stack.py compose exec teep curl -fsS http://127.0.0.1:8337/v1/models
```

Use `make down` followed by `make up` when changing namespace or ingress
settings. Persistent state remains intact.

## Optional public Funnel

Scope Funnel access to a tag in your tailnet policy so only this node receives
public Funnel permission:

1. In the Tailscale admin console, open **Access controls -> JSON editor** and
   merge `tagOwners` and top-level `nodeAttrs` into your policy (do not nest
   `nodeAttrs` inside `acls` or `grants`):

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

   Replace `"autogroup:admin"` with whichever user or group owns the tag.
   `tagOwners` only authorizes who may assign the tag; the auth key below
   applies it at enrollment. (Note: `"autogroup:member"` matches only untagged
   user-owned nodes, not tagged nodes.)
2. Open **Settings -> Keys -> Auth keys -> Generate auth key**, enable **Tags**,
   select `tag:private-hermes`, and copy the key into `TS_AUTHKEY`.

Because the stack writes the Funnel serve config directly without triggering the
Tailscale CLI's interactive prompt, allow the policy and public DNS to propagate
after saving. Add these settings to `.env` using your node's exact `.ts.net`
hostname:

```dotenv
TAILSCALE_FUNNEL_ENABLED=true
TAILSCALE_HOSTNAME=private-hermes
TAILSCALE_FUNNEL_HOST=private-hermes.your-tailnet.ts.net
TAILSCALE_FUNNEL_PORT=443
TS_AUTHKEY=your-enrollment-key
```

Tailscale Funnel supports ports `443`, `8443`, and `10000` (include non-443
ports in the browser URL). Run `make down` and `make up` (`make up` builds the
`tailscale` image when Funnel is enabled).

Verify capability and public DNS resolution before relying on the URL:

```sh
python3 scripts/stack.py compose exec tailscale \
  tailscale --socket=/tmp/tailscaled.sock status --json
# Self.CapMap must include "funnel"

dig @1.1.1.1 +short A private-hermes.your-tailnet.ts.net
# Must return Tailscale Funnel relay addresses
```

### Funnel lifecycle and isolation

- Tailscale runs with userspace networking: no host networking, TUN device,
  network capabilities, or engine socket.
- Startup begins with an empty forwarding config, waits for an authenticated
  node, checks that its assigned DNS name matches `TAILSCALE_FUNNEL_HOST`, and
  fails closed on a mismatch.
- Node identity persists in `data/tailscale/`, so you can remove `TS_AUTHKEY`
  after enrollment (re-enrolling a new node requires a fresh key).
- To disable Funnel while keeping localhost access, set
  `TAILSCALE_FUNNEL_ENABLED=false` and run `make up`. The workflow resets Funnel
  forwarding, removes the Tailscale container, and keeps node state in
  `data/tailscale/`. If reset cannot be confirmed, the container stops and
  reports an error; any subsequent start begins with empty forwarding.

## Optional onion ingress

`TOR_ONION_ENABLED` defaults to `false`. Onion ingress works independently of
Funnel; localhost stays available regardless of which remote paths are enabled.

The Tor image is built during every `make build` and `make up` with no separate
overlay. After building the stack, generate or print your onion address:

```sh
make onion-address
```

This runs Tor offline in a networkless maintenance container and prints the
  `http://...onion` URL without publishing a descriptor or starting the stack. On
a fresh checkout after `make init`, run `make build` first (`make onion-address`
never builds or pulls images implicitly).

- Creating an identity or repairing derived files requires the runtime `tor`
  container to be stopped and removed (`make down`), including paused or
  restarting containers. Printing an already-saved address works while the stack
  is running and even when unrelated serving settings are invalid.
- Enable onion ingress by setting `TOR_ONION_ENABLED=true` in `.env`, then
  running `make down` and `make up`. Open the printed URL in Tor Browser. If
  enabling before `make init`, create the identity with `make onion-address`
  first, because rendering the enabled proxy configuration requires a saved
  address.
- Disable onion ingress with `TOR_ONION_ENABLED=false` followed by `make down`
  and `make up`. Keys persist across shutdown and across disabling and
  re-enabling ingress.
- When onion ingress is enabled, `WEBAPP_PORT` cannot be `8080` (just as `8443`
  is reserved when Funnel is enabled).

### Onion identity and security

`data/tor/onion-service/` holds `hostname`, `hs_ed25519_secret_key`, and
`hs_ed25519_public_key`. Back up the entire directory with UID 101 / GID 102 and
private permissions intact:

- After `make down`, `make onion-address` rebuilds missing `hostname` and
  `hs_ed25519_public_key` files from an intact secret key. (If only the public
  key is missing, `make onion-address` prints the hostname without writing, and
  enabled Tor regenerates the public key on startup.)
- Missing or malformed secret keys require restoring from backup; neither
  `make onion-address` nor runtime startup silently generates a new identity.
  (Reading a hostname still works without complete key files, but reports the
  stored address rather than serving readiness; a malformed hostname is rejected
  before rendering HAProxy configuration.)
- Tor and HAProxy share an isolated network (`10.203.86.0/24`). Only Tor
  (`10.203.86.2`) can reach HAProxy's onion frontend (`10.203.86.3:8080`), which
  accepts only the saved onion hostname (with optional `:80`), strips forwarded
  headers, and passes HTTP as the trusted scheme. Neither Hermes nor the
  executor joins this network, and HAProxy never mounts `data/tor/`.
- Onion HTTP uses host-only `HttpOnly; SameSite=Lax` cookies (without `Secure`,
  unlike Funnel HTTPS). All ingress hostnames share the same credentials and
  signing key, while image consent is scoped per exact browser origin. Onion
  ingress does not change the external-content policy or route a regular
  browser's direct external requests through Tor.

## Authentication, origins, and authority

Hermes password auth uses scrypt hashes, 12-hour access tokens, and 30-day
refresh tokens. Because tokens are stateless, clearing browser cookies or
logging out does not revoke already-captured tokens, open WebSockets, or
already-issued display tickets (single-use, 30-second expiry). To revoke all
outstanding sessions across every ingress path, rotate both the password and
signing secret and recreate Hermes:

```sh
make webapp-rotate
make up
```

HTTP and HTTPS sessions use separate cookie names (`Secure` on HTTPS), and every
hostname requires its own login.

### HAProxy firewall and header handling

HAProxy binds the host loopback port directly and receives Funnel and onion
traffic on separate isolated networks. Hermes connects only to its isolated
backend network; the executor connects to no ingress network.

At startup, HAProxy installs default-deny IPv4/IPv6 firewall rules before
dropping to UID 10005 with empty effective, permitted, inheritable, ambient, and
bounding capability sets:

- **Inbound:** Accepts local connections on the publication interface (or over
  `lo` from the rootless port forwarder on Podman; see
  [engine differences](architecture.md#rootless-podman)), Funnel connections
  only from Tailscale to port `8443`, and onion connections only from Tor to
  port `8080`.
- **Outbound:** Initiates connections only to Hermes at `10.203.85.2:9120` plus
  established replies. Connections to the host, VM, LAN, Internet, DNS, or other
  services are blocked, and IP forwarding is off.
- **Headers and origins:** Enforces exact `Host` headers separately on local,
  Funnel, and onion frontends, strips incoming `Forwarded` and `X-Forwarded-*`
  headers, and injects the trusted scheme and peer identity. Hermes trusts only
  HAProxy's backend IP, so origin checks use the client's host and scheme.
  WebSockets and streaming pass through without added body or idle-timeout
  limits (HAProxy logs an expected startup warning about infinite timeouts).
- **Rate limiting:** Hermes throttles login attempts to 10 per 60 seconds per
  observed peer IP (reset on restart). Because Tor, Funnel, and container port
  forwarding can aggregate visitors behind one ingress IP, this deployment does
  not provide per-visitor rate limiting.

### Operator authority

An authenticated WebApp user has administrative authority over the Hermes
container. The default **Code** terminal runs in the SSH executor, while the
optional **Agent** terminal runs inside Hermes with access to `/opt/data`. The
browser file API uses SSH for workspace paths, while staged agent files remain
in Hermes. Do not treat WebApp UI controls as executor sandboxing. The executor
has no ingress network membership, no WebApp or Tailscale credentials, and no
path to private WebApp listeners.

## External content policy

Set `WEBAPP_EXTERNAL_CONTENT` in `.env` and apply it with `make up`:

```dotenv
WEBAPP_EXTERNAL_CONTENT=tor_proxied
```

| Mode | In-app behavior |
| --- | --- |
| `tor_proxied` | Default. Supported external raster images and icons load through the authenticated Hermes gateway over Tor. Unsupported media and previews show a non-loading placeholder and external link. |
| `ask` | No external image loads until you approve a one-time load or remember that origin for Tor images. Unsupported media and previews remain placeholders. |
| `off` | All external in-app loading and proxy image retrieval are disabled, including previously remembered origins. In-app UI controls cannot override this ceiling. |
| `browser_native` | External content loads directly through your browser's own connection. Native Hermes social preferences still apply, while auth, script policies, and preview sandboxes remain active. |

Leaving `WEBAPP_EXTERNAL_CONTENT` unset defaults to `tor_proxied`; an explicitly
empty or invalid value fails validation and blocks gateway startup. Hermes
captures the setting before loading profile dotenv files so profile edits cannot
loosen it. HAProxy verifies its rendered mode marker before listening and passes
a mode header that Hermes checks; a mismatch blocks access.

Reload open browser tabs after changing modes. New policy applies immediately to
new gateway requests (including from stale tabs), but already-delivered bytes
and browser document policies cannot be recalled. Close existing
`browser_native` tabs and previews when switching back to a private mode.

> **WARNING:** Use `browser_native` only in Tor Browser or Brave Browser's
> Private Window with Tor. External content uses your browser's connection
> directly, bypassing the stack's Tor gateway. Regular Brave windows do not use
> Tor, and the stack cannot detect or verify browser Tor routing. Brave's Tor
> windows also lack many of Tor Browser's anonymity protections
> ([Brave documentation](https://support.brave.app/hc/en-us/articles/360018121491-What-is-a-Private-Window-with-Tor-Connectivity)).

### Image approval, saving, and proxy limits

In `ask` mode, placeholders show the target origin and offer three actions:
**Load once through Tor / retry**, **Remember this origin for Tor images**, and
**Open externally (uses your browser connection)**. Fetching a unique URL over
Tor still tells the remote server that someone loaded it; Tor hides your IP
address, not the fetch itself. Proxy errors show a reason without falling back
to a direct browser request, and SVG or other unsupported types stay as
placeholders.

- **Revoking consent:** Manage remembered origins in **Settings -> Appearance ->
  Chat display -> Image permissions**. Grants cover Tor image retrieval only and
  are scoped to exact browser and remote origins (`localhost`, `127.0.0.1`,
  Funnel, and onion have separate scopes). Grants persist across logout and
  restart until revoked; load-once creates no grant.
- **Saving and copying images:** Save buttons that need a fresh external image
  fetch it over Tor in private modes (with a one-time prompt in `ask` mode;
  `off` refuses). Right-clicking an already-rendered Tor image saves or copies
  its displayed bytes without a second request. Suggested filenames come from
  the original URL, with extensionless URLs inferring the suffix (including
  `.ico`) from the delivered media type. Local, `data:`, and `blob:` images keep
  standard handling.
- **Proxy rules:** The image proxy allows public IPv4 HTTP(S) PNG, JPEG, GIF,
  WebP, BMP, and ICO images whose bytes match their media type. It pins the
  validated IP address, preserves `Host` and TLS SNI, validates every redirect
  hop, strips browser cookies and referrers, and rejects private or IPv6-only
  targets without fallback. In `ask` mode, cross-origin redirects are rejected
  before contacting the next host. Responses are capped at 25 MiB while
  streaming, allow 60 seconds per socket operation for Tor latency, cap redirect
  counts, and send `no-store` with no server-side cache.

### Previews, media, URL chips, and tools

- **URL chips (`@url:`):** Pasted or typed URLs keep Hermes's URL chips, and
  submitting sends the `@url:` text to the model, but automatic page fetching
  and URL-extraction warnings are disabled (in both WebApp and CLI, independent
  of `WEBAPP_EXTERNAL_CONTENT`). Ask the agent to use web research or terminal
  tools when you want a page fetched. File, folder, Git, and plugin context
  references keep standard expansion.
- **Local media and generated files:** Local generated images, graphs, and audio
  or video use authenticated Hermes file paths. Any file hosted on a public CDN
  is treated as external even if the agent generated it. Markdown, gallery,
  thumbnail, connector, and pet image renderers all pass through the private
  image gate. Browser-hosted link-title fetching is disabled, and favicon
  discovery stays desktop-only.
- **Audio, video, and social players:** In private modes, external audio, video,
  posters, subtitles, manifests, and social embeds stay as placeholders with
  external links, overriding saved social preferences. Browser-native
  interactive opt-in and streaming remain deferred (see
  [deferred interactive content plan](plans/webapp-interactive-content.md)).
- **HTML and plugin previews:** In private modes, HTML and plugin previews
  display inert source text rather than executing untrusted HTML, frames,
  workers, or scripts (CSP alone cannot contain arbitrary preview JavaScript).
  Sanitized local SVG and Mermaid diagrams still render with external SVG
  references blocked. Active HTML, SVG, and plugin-asset files serve as binary
  attachments with an inert sandbox header even on direct navigation.
- **Preview tools:** `desktop_preview`, `drive_preview`, and `annotate_preview`
  are available only in `browser_native` mode (omitted from discovery and
  rejected on stale calls in private modes). `read_window_below`, `browser_cdp`,
  `browser_dialog`, and `browser_vault` are disabled in every mode. Start a new
  conversation after changing modes to refresh advertised tools.
- **Executor desktop and Bot Screen:** `computer_use` and `browser_exec` follow
  `COMPUTER_USE_ENABLED` (see
  [optional executor desktop](configuration.md#optional-executor-desktop)).
  Viewing Bot Screen screenshots and RFB pixels travels over authenticated
  same-origin connections and the executor SSH stream; it does not make your
  browser contact the websites shown on the desktop and does not require
  `browser_native`. Takeover leases fence computer-use tools and viewer input
  only, not arbitrary code running as `runner`; a second viewer's takeover
  revokes the previous viewer's input, though it does not guarantee immediate
  closure of the previous watch connection across processes. If desktop
  dependency inspection fails, status reports a connection diagnostic without
  claiming dependencies are present; restore the executor connection and refresh
  status or click **Start** (refreshing status does not start a desktop).
- **Scope of browser controls:** Main-app responses keep bootstrap script hashes
  and restrict private modes to same-origin APIs, exact-origin WebSockets, no
  referrers, and disabled DNS prefetch. Clicking an external link or opening a
  downloaded document outside the WebApp still uses your normal browser or host
  connection. These browser rules do not restrict agent inference, backend
  plugins, host software, or browser extensions.

## Terminal environment

By default (`WEBAPP_TERMINAL_ENVIRONMENT=code`), the WebApp terminal is labeled
**Code** and opens an interactive `runner` bash shell inside the SSH executor
at `/workspace`. With `COMPUTER_USE_ENABLED=true`, it opens in the desktop
executor without attaching to a graphical terminal or inheriting `DISPLAY`.
Use **Code** to [review Git changes inside the executor](configuration.md#reviewing-changes-in-the-executor).

Set `WEBAPP_TERMINAL_ENVIRONMENT=agent`, run `make up`, and reload browser tabs
for an **Agent** terminal inside Hermes with administrative access to
`/opt/data`. Browser input and profile config cannot override this deployment
setting. Saved gateway terminals keep their separate remote-Hermes path.

The same applied setting selects the shell for `!command` in classic and TUI
chat. Reopen `make chat` after applying a change. In Code mode, `!pwd` uses the
chat's last executor directory or starts in `/workspace`. In either mode, saved
`quick_commands` of type `exec` run in the executor when invoked from
`make chat`. The model's terminal tool uses the executor in both modes.

When the model has the `read_terminal` tool, it can read visible output and
scrollback from the selected terminal tab, including an **Agent** terminal.
Keep secrets out of its output.

- **Working directory:** Code terminals start in `/workspace` (or the requested
  executor directory, or parent directory for a file path). Missing paths,
  inaccessible directories, and control-character paths fail cleanly instead of
  falling back. Bash OSC prompt updates track `cd` changes (preserving spaces,
  Unicode, and shell metacharacters). The workspace file API always targets the
  executor, so in Agent mode its view can differ from local container files;
  agent-side `/workspace` is empty and ephemeral across restarts.
- **Lifecycle and cancellation:** Page refresh reattaches to a surviving shell
  and replays buffered output. Closing a Code tab during startup cancels the
  pending SSH probe, and closing an open tab terminates the shell and foreground
  children via remote hangup (intentionally detached jobs may remain running,
  and shells do not survive backend or executor restarts). If the executor is
  unreachable or SSH keys fail, the terminal returns an error without falling
  back to an Agent shell.
- **Mode switches and stale tabs:** Switching between Code and Agent clears
  saved local tabs, working directories, and scrollback on reload while keeping
  saved gateway tabs. Stale pages must reload before opening new terminals. Each
  tab pins its gateway, profile, and placement at creation and acknowledges its
  terminal ID on startup so closing a tab mid-handshake discards the orphan
  shell cleanly.

## Verification and qualification

### Running the WebApp test suites

```sh
make check
make test
make webapp-test
```

Provision the Playwright browser test environment once:

```sh
python3 -m venv /tmp/private-hermes-browser-tests
/tmp/private-hermes-browser-tests/bin/pip install -r tests/requirements-browser.txt
/tmp/private-hermes-browser-tests/bin/python -m playwright install chromium firefox webkit
WEBAPP_BROWSER_PYTHON=/tmp/private-hermes-browser-tests/bin/python make webapp-test
```

Set `PLAYWRIGHT_BROWSERS_PATH` if the browser cache lives outside its default
location. Stop running deployments first because tests reuse the fixed subnets.
No Tailscale container starts, and no paid inference or MCP calls run.

### Qualification

Current per-engine test results are recorded in the
[packaged Hermes qualification table](development.md#packaged-hermes-qualification).
Interactive opt-in and streaming media remain deferred.

- **`make images-test`:** Uses isolated HTTP and TLS canaries with no uplink or
  published ports to verify socket destination pinning, DNS rebinding checks,
  raster and size limits, and authentication and consent rules. (Does not itself
  prove Tor routing.)
- **`make webapp-test`:** Runs against production images with seeded history,
  deterministic local inference, local media, TCP and TLS canaries, and
  simulated HTTPS on ports `19120` and `10000`. All four content modes run on
  Chromium 156.0.8078.4, Firefox 157.0, and WebKit 27.2 on ARM64. Chromium
  additionally runs `ask` consent over HTTPS
  plus ingress auth, cookies, origin checks, terminals, and a live WebSocket
  chat turn (Firefox and WebKit run focused HTTPS auth and navigation checks).
  Direct DNS and preconnect NetLog observation is Chromium-only. Although
  routine tests avoid external image fetches, they still wait for Tor bootstrap.
- **`make webapp-live-test`:** Verifies live authenticated Tor image fetches,
  Tor exit-node controls, transparent-route counters, and Tor outage and
  recovery. Run both `make webapp-test` and `make webapp-live-test` for full
  coverage.

### Pending live Funnel qualification

Local ingress and Funnel configuration are tested with a local TLS fixture, not
against a live tailnet or public Funnel relay. When ready to enable live Funnel:

1. Enroll with your tailnet auth key and ACL policy, verifying that the assigned
   `.ts.net` name matches `TAILSCALE_FUNNEL_HOST`.
2. Connect from outside the tailnet: confirm unauthenticated requests require
   Hermes login, authenticated chat streaming and WebSockets work, and
   `localhost` stays reachable independently.
3. Disable Funnel via `TAILSCALE_FUNNEL_ENABLED=false` and `make up`, confirm
   public access stops while `localhost` remains up, and verify `make down` and
   re-enablement preserve both Tailscale and Hermes state.

Record tested revisions and results privately without committing credentials or
node identifiers.

References:
[Tailscale Docker parameters](https://tailscale.com/docs/features/containers/docker/docker-params),
[Tailscale Funnel](https://tailscale.com/docs/features/tailscale-funnel), and
[HAProxy configuration](https://docs.haproxy.org/3.4/configuration.html).
