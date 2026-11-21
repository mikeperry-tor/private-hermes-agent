# Private webapp content: streaming and interactive opt-in

Status: planned. Part 2, dependent on
the implemented [safe defaults and passive media](../webapp.md#external-content-policy).
Execution follows the [planning workflow](../planning-workflow.md) and
[repository instructions](../../AGENTS.md).

Planning baseline: branch `main`, commit `2d0ec55`. This revision is planning
only. At execution, record the actual baseline and completed/reviewed part 1
revision; do not assume today's official Hermes image is still the runtime.
Engine-parity amendment baseline: `rootless-podman-support`, `3f66fa5`.

## Objective and starting state

Restore additional media and interactive functionality without weakening the
safe default established by part 1. This plan is not required to close known
automatic browser leaks. It must be possible to defer it indefinitely.

Part 1's implemented contract provides private raster image/icon loading and
local content. External audio/video and social players have placeholders and
external links. Previews
operate without external networking where enforceable, or use inert/download
fallbacks. Unsupported private loading never silently switches to the browser.

Keep the same `WEBAPP_EXTERNAL_CONTENT=tor_proxied|ask|off|browser_native` setting,
policy authority, consent vocabulary and permission storage. Do not introduce a
second conflicting switch or a compatibility/migration layer.

Structured desktop actions are available through the implemented
[optional executor desktop](../configuration.md#optional-executor-desktop), with
[documented qualification limits](../development.md#executor-desktop-qualification).
The implemented [browser automation](../development.md#browser-harness-and-results)
runs both Chromium and model-written Python in the SSH executor under the same desktop preference;
CDP/dialog/vault tools remain excluded. The separate `desktop_preview`,
`drive_preview` and `annotate_preview` tools target the viewer's renderer and are
available only in `browser_native`; they are not disabled by the executor policy.
Preserve that explicit opt-in and private-mode restrictions. This plan must not
use browser-native previews as evidence of executor isolation or authorize
model Python execution in Hermes.

The derived image retains official v0.23.3 source
`caafe5389ae585ef77387a962aee05b1bcf17029`. Part 1 owns
`/api/private-content/{policy,consent,image}`, exact browser/external-origin
Tor-image grants in the native Hermes volume, early deployment-mode capture,
shared resource renderers and additive response enforcement. Private HTML
previews display source text without parsing it; unknown active HTML/SVG file
and plugin assets are attachments in every mode. Reuse these concrete boundaries;
do not restore the removed CDN proxy or bypass the inert preview with executable
content. Current acceptance evidence and final review status remain in part 1.

Part 1's P1-FINAL gate is a prerequisite. Before substantive implementation,
verify its documented guarantees and supported-browser evidence against the
selected derived image. Record any changes to the shared contract in both plans
and maintained guides. Fix a broken prerequisite before restoring functionality;
do not silently treat a part 1 leak as a harmless deferred feature.

Update [webapp operations](../webapp.md) with supported formats/providers,
consent and revocation, [configuration](../configuration.md) for any changed
permission persistence, and [updates/plugins](../updates-and-plugins.md) for
patch/build changes. Do not create a second set of policy docs or a new generic
permission framework. Hermes's exact host/LAN socket grants are agent-tool
authority. Preserve the WebApp's private-destination checks for browser and
gateway content loading independently of those grants.

## Streaming external media through Tor

- Add authenticated streaming for validated public audio/video destinations,
  supporting Range requests, seeking, cancellation and appropriate response
  types. Reuse the image proxy's SSRF and credential-isolation requirements.
- Cover dependent resources: posters, subtitles, playlists, manifests, segments,
  redirects and encryption-key URLs where applicable. A privately loaded initial
  manifest must not direct subsequent browser requests to external servers.
- Begin with ordinary self-contained media files. Select and document initial
  formats during design; support segmented streaming only if concrete usage
  warrants it and its dependency handling can be bounded. The requirement above
  applies to any format advertised as supported, not an obligation to implement
  every playlist protocol, encryption system or player.
- Only claim support for formats whose dependencies can be safely handled. Keep
  unsupported players/DRM/login-dependent media as placeholders or external links.
  Do not build a general rewriting proxy for arbitrary websites.
- Under `tor_proxied`, allow supported private playback; under `ask`, require
  approval before any external request. Under `off`, refuse retrieval even if a
  browser submits the endpoint directly. Preserve existing local playback.
- Report Tor latency or incompatibility without falling back to browser-native
  playback. Reuse endpoint safeguards rather than adding container-wide quotas.

## Runtime consent for browser-native interactive content

Extend the shared placeholder to offer direct in-app loading when supported:

- Show the destination/provider and a clear warning that this uses the user's
  browser connection, not the stack's Tor gateway. Do not infer that a browser
  is Tor Browser or that it provides network isolation.
- Offer load once, allow for this session, and revocable remembered permission.
  Scope by exact origin or a defined provider with documented dependencies, and
  distinguish browser-native grants from Tor-proxied grants.
- Keep `off` an unoverrideable deployment ceiling. `ask` requires consent before
  private or direct retrieval; `tor_proxied` requires consent for direct loading.
  `browser_native` explicitly permits automatic native resource loading while
  retaining unrelated authentication, script and sandbox protections.
- Integrate social embeds into the same policy rather than allowing a separate
  provider preference to bypass it. Display and revoke effective grants in one
  settings surface. Handle localhost and Funnel browser state explicitly; do
  not assume their independent origins share consent storage. Include the optional
  onion HTTP origin in this contract; its ingress reuses the same authentication
  and content policy, with independently scoped browser consent.

## Consent-scoped frames and generated previews

CSP cannot be relaxed by adding a policy after a click. Keep the main app
restricted, and load approved interactive content through a separately served,
sandboxed frame whose response policy reflects the authorized permission.

1. Design an authenticated consent and frame issuance flow. Validate session,
   origin/CSRF protections, content identity, approved dependencies and expiry.
   Keep approval authority in the trusted UI/backend, not model-generated HTML
   or preview postMessage handlers. Avoid reusable tokens in external URLs.
2. Keep parent CSP restrictive while allowing the same-origin wrapper. Scope
   the wrapper's response policy to the approved provider/origins, then preserve
   sandbox boundaries and prevent access to parent credentials or DOM. Avoid
   sharing the authenticated origin with executable untrusted content through
   an unsafe combination of script and same-origin permissions.
3. Audit social provider scripts, nested frames, redirects and subsidiary hosts.
   Approving a YouTube player must not silently grant arbitrary third-party
   access. If dependencies cannot be reasonably bounded, keep the external-link
   fallback or explain the broader grant before approval.
4. For generated HTML, inventory external dependencies where feasible. Prefer
   locally packaged libraries or safely retrieved passive assets. Unknown
   dependencies must not receive a wildcard network grant automatically.
5. Resolve WebRTC/STUN, scripted navigation, workers and resource hints for each
   supported browser before claiming network containment. If selective access
   cannot be enforced, preserve the inert/external fallback instead of enabling
   arbitrary scripts under an incomplete allowlist. A grant for browser-native
   execution must accurately describe its actual network authority.
6. Define revocation semantics: remove active frames/players and prevent new
   authorized loads. Already delivered executable content or completed remote
   requests cannot be recalled; do not imply revocation can undo them.

The permission is to load a particular class of external content, not to access
host/LAN services. Define and test local-destination handling; do not implicitly
turn public embed consent into permission to probe the user's private network.

Explicitly qualify how origin allowlists interact with DNS changes, nested
third-party documents and browser private-network protections. A parent CSP
does not confine the network access of every remotely served descendant. If a
player requires broader browser authority than can be enforced or accurately
consented to, preserve the external-link fallback. Do not claim host/LAN denial
from a hostname allowlist alone.

## Open decisions and design gate P2-DESIGN

Record answers from read-only inspection and controlled experiments before
substantive implementation:

- Which exact part 1 source/base/patch revision is selected, and which existing
  image proxy, consent, preview and CSP interfaces can be extended directly?
- Which initial media formats and social provider are worth supporting? Identify
  dependencies and use deterministic fixtures. There is no universal provider
  compatibility requirement and no permission to contact real user accounts.
- How will per-grant frame policies coexist with HAProxy and native CSP without
  an unrestricted route, forged approval or blanket removal of a source policy?
- What enforceable authority can a provider/preview receive in supported browsers,
  including descendant frames, WebRTC, navigation and local-network access?
  State when the fallback is required rather than adding a general browser proxy.
- What state is actually needed for single-load, session and remembered grants,
  and what changes to part 1 are required? Prefer its existing mechanism. Define
  expiry, replay resistance, logout/restart and active-frame revocation precisely.

Gate P2-DESIGN is a fresh read-only subagent review with no inherited turns. Give
the reviewer this plan, the completed part 1 contract and evidence, exact reviewed
revisions/snapshot, chosen initial support and relevant guides. Review policy
authority, media SSRF, frame isolation and scope/complexity. Resolve material
findings before implementing the affected design.

## Commit phases and review gates

Use focused development/correction commits within these stable phases, with
tests and guide updates alongside behavior. Independently review meaningful
phase SHAs. A phase review may cover its named gate and accumulated work in one
fresh review brief; do not add duplicate reviews just to satisfy labels.

### P2-1: privately streamed media

- Extend the existing proxy for the selected formats, Range/seek, cancellation
  and approved dependent resources. Keep authentication, public-only destination
  enforcement and policy checks on every retrieval, including subsequent ranges.
- Wire the player to same-origin routes before browser loading begins. Retain
  unsupported-format and error placeholders with no direct fallback.
- Test success, partial/error responses, redirects, cache/grant behavior, Tor
  loss, private targets, metadata/preloads and policy revocation during playback.
  Update media support and diagnosis in `docs/webapp.md`.
- Gate P2-MEDIA reviews exact commits and the shared proxy call chain. Exit
  requires no unapproved browser requests and no expanded internal fetch access.

### P2-2: consent-scoped provider frames

- Extend the existing consent UI/store and issue narrowly scoped sandboxed
  wrapper responses for the selected provider. Keep strict main-app policies
  and authenticated/CSRF-protected grant mutations.
- Add load-once/session/remembered controls and revocation in the unified settings
  surface. Audit logout, restart, local/Funnel scope and stale frames. Do not
  assume removing a wrapper instantly recalls all previously delivered content.
- Test forged/replayed grants, content-origin messages, nested dependencies,
  unauthorized hosts, parent credential/DOM isolation, and exact effective CSP
  on main/wrapper/guest documents. Qualify the actual browser authority granted,
  including any descendant behavior that cannot be narrowed.
- Update operator docs. Gate P2-FRAMES independently reviews the phase and
  accumulated media/permission boundary before in-app direct loading is declared
  supported. Keep external links for providers failing qualification.

### P2-3: bounded generated previews and completion

- Reuse the frame/permission path for generated previews only where dependency
  scope and sandbox behavior are enforceable. Unknown dependencies or unsupported
  browser behavior retain inert/download/external fallbacks. No arbitrary-site
  rewriting proxy, generic dependency loader or second permission framework.
- Test malicious dependencies, nested documents, script navigation and relevant
  WebRTC behavior, plus retained local/offline functionality. An inability to
  safely support a preview is a documented feature limitation, not authority to
  weaken part 1. Update the shared docs and both plans accordingly.
- Gate P2-FINAL reviews the whole accumulated implementation, corrections,
  shared part 1 invariants and acceptance evidence below. It also serves as
  the P2-3 phase review. Resolve material findings and record exactly which
  formats/providers/browsers passed; do not claim universal compatibility.
- Commit completion/docs and remove the completed plan after final acceptance
  under the planning workflow, preserving lasting limits in maintained guides.
  Retain it while gates remain pending. A bounded fallback is acceptable; an
  unresolved required security condition cannot be relabeled as completed work.

All phases extend the explicit Hermes patches and reproducible asset build from
part 1, with patch mismatch failures and update-inventory changes as needed.
No topology change or new service is assumed. Justify any necessary addition
against an actual boundary rather than hypothetical future provider support.

## Qualification and acceptance

Use one media/consent/frame implementation and image patch set for Docker and
rootless Podman. The engine controls server-side Tor retrieval, ingress transport
and persistent state; the viewer's browser controls direct content loading.
Neither engine routes viewer requests through Tor or changes browser sandbox/CSP
semantics. Keep these axes separate from executor computer-use/browser-use, which
retain their own placement, sandbox and engine-policy qualification.

Run affected backend/streaming and browser-containment checks on both qualified
engines using the maintained focused browser/ingress matrix. Cover each supported
browser's relevant security behavior without restoring a full Cartesian product
of engine, mode, ingress and lifetime cases. New browser-dependent behavior needs
focused evidence in each claimed browser; reuse unchanged part 1 evidence.
Use deterministic local media/provider fixtures and simulated HTTPS for Range,
seeking, redirects, nested dependencies, revocation and cancellation. Keep public
Tor retrieval/outage/recovery in separate live checks on each engine; a local
fixture or browser request counter cannot prove Tor routing. Do not repeat public
HTTPS controls in every browser case or add blanket retries to hide failures.

Trace stream cancellation and client disconnect through Hermes and HAProxy,
including the Podman ingress forwarder. Qualify reconnect and relevant dependency
restart/recreation without direct fallback. Verify remembered grants survive
container recreation and volume backup/restore with their origin scope intact.
Rootless ownership handling must not loosen permissions or mount the grant store
into the executor.
Validate effective base/Funnel models when definitions change. Simulated HTTPS
and ingress fixtures do not qualify live Funnel or arbitrary providers.

- Retain all part 1 no-unapproved-egress tests in the default policy. Adding a
  player or preview must not widen the main application's source permissions.
- Test each mode and permission lifetime, including saved provider grants,
  revocation during playback, logout, restart, and independent local/Funnel
  origins. Test forged grants, replay, cross-origin writes and untrusted
  messages; approval must not be obtainable by content itself.
- Observe actual browser and gateway traffic for media dependencies, seeking,
  cancellation, redirects, nested frames and rejected destinations. Use
  controlled fixtures without contacting live social accounts or trackers.
- Verify unsupported/failed proxying never silently becomes a direct browser
  request. Verify explicitly approved native requests use only the authority
  documented by the approval UI.
- Exercise authentication, sandbox/parent separation, SSRF protections and the
  retained host/VM/executor isolation checks. Check relevant WebRTC and scripted
  navigation behavior across the documented supported browser versions.
- Preserve deliberate external links and offline/local content. Run focused
  browser/media/security tests and appropriate repository checks without live
  Funnel enrollment or production wallet operations.

Completion means added functionality works within explicit permissions. It does
not require universal compatibility with arbitrary websites or executable HTML.

Use `make check`, focused proxy/player/grant tests, and extended
`make webapp-test` browser qualification against the built image. Run routing or
plugin suites when their contracts change; reuse valid part 1 evidence for
unchanged behavior. Serialize fixed-network fixtures. Simulated providers and
HTTPS do not constitute live provider/Funnel qualification; report unsupported
or untested cases rather than requiring production accounts to finish the suite.

## Evidence and completion status

- Prerequisite: part 1 is implemented, qualified and independently reviewed;
  P1-FINAL passed at `3db58120e78f003d5b3402d34a4541e9fa39a6a7`. Consult its
  retained evidence and requalify any changed prerequisite before starting here.
- Implementation: not started; P2-1 through P2-3 pending.
- Design/phase/final gates: not yet passed. This plan does not supply evidence of
  future permission enforcement or runtime functionality.
- Initial formats/provider/browser coverage: selection pending P2-DESIGN.
- Planning-only review: a fresh read-only subagent reviewed `2d0ec55` plus both
  revised plan files, with no blocking findings. This does not pass P2-DESIGN or
  establish that part 1's implementation prerequisite has been met.
- Authority: local commits and disposable qualification within task scope; no
  live Funnel enrollment, production financial secrets or funded calls.
- Engine-parity amendment against `3f66fa5`: fresh independent read-only review
  accepted it together with the listener and document-search amendments, with no
  material findings. Local-link targets and `git diff --check` passed. No runtime
  tests were run for these documentation-only changes; future gates remain pending.

Maintain reviewed SHAs, material finding dispositions and focused results here as
work lands. Report missing review/validation explicitly without generating a
separate evidence-management subsystem.
