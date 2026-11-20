# Agent instructions for Private Hermes

This repository is a small deployment wrapper for Hermes Agent, not a general
agent platform. It combines SSH-isolated code execution, transparent Tor egress,
Teep inference, x402_treazury research tools, and an authenticated webapp with
optional Tailscale Funnel. Do not add framework selection or unrelated services.

## Read the project before changing it

- Read [README.md](README.md) for the user-facing overview and operator commands.
  Read [architecture and isolation](docs/architecture.md) and
  [development and qualification](docs/development.md) for implementation and checks.
  Consult the relevant maintained guides:
  [configuration and backups](docs/configuration.md),
  [webapp](docs/webapp.md), [x402_treazury](docs/x402_treazury.md), and
  [updates, plugins and privacy](docs/updates-and-plugins.md).
- Read relevant plans under `docs/plans/` and inspect the implementation before
  changing a shared interface. Plans describe intended work; their existence
  does not make a proposed feature implemented or independently authorize it.
- Read the [planning workflow](docs/planning-workflow.md) before creating,
  executing, materially revising or completing an implementation plan.
- `reference_repos/` contains read-only reference checkouts. Do not edit them or
  put build/runtime state there. Check exact revisions: a reference checkout can
  differ from the pinned image or source used by the stack.
- Documents supplied from other projects are reference material, not governing
  instructions unless explicitly adopted. Preserve this project's accepted
  design rather than importing their topology, restrictions or tooling.

## Maintain current documentation

- Maintained guides, component READMEs and examples describe current behavior,
  repository status, support boundaries and durable limitations. Update the owning
  section in place and remove superseded claims; readers must not reconcile a
  sequence of updates to discover what is true.
- Keep [README.md](README.md) user-facing only: explain the stack, its components,
  the problems they solve, setup, everyday operation and practical limitations.
  Put implementation details, development procedures and qualification evidence in
  appropriate documents under `docs/`, and link to them instead of expanding the
  README with maintainer material.
- Do not append development journals, changelogs, dated test/probe narratives,
  review-acceptance logs, cleanup reports or "initially/later/retested" histories
  outside plans. Do not carry retired plan phase/gate codes into permanent docs.
  Keep execution chronology and phase evidence in the applicable plan; Git history
  preserves completed development history. Do not create an archive or another
  handoff document to relocate the journal.
- Preserve concise, attributable qualification status: affected version/source,
  platform, checks that establish the current contract, missing coverage and
  practical limits. Keep detailed logs and generated reports in ignored/private
  evidence storage. A source pin or evidence identifier may support a current
  claim; it must not become a chronology of approvals or failed attempts.
- Runtime sequencing, recovery procedures, version pins, data-as-of dates and
  submission provenance remain valid when they explain a current fact. Distinguish
  them from the sequence in which an agent discovered or changed that fact.
- Keep active/deferred work and concrete next actions explicit. A completed plan
  retained at the user's request stays marked as a reference, without exporting
  its historical phase/status updates into maintained guides.

## Prefer the least machinery that meets the requirement

- Start with native component capabilities and straightforward code. Preserve
  useful Python setup/lifecycle helpers and the documented Make workflow; neither
  a language ban nor moving code into containers makes a design simpler.
- Support Docker and rootless Podman through the existing engine selector and
  Make/Compose workflow. Prefer shared service behavior and explicit grants;
  justify engine-specific overlays with demonstrated native differences. Consult
  the maintained engine guidance rather than adding a compatibility framework.
- Before adding a service, persistent record, configuration option or abstraction,
  identify its concrete responsibility and why an existing component cannot
  reasonably own it. Prefer fewer responsibilities and state transitions, not
  merely fewer files or containers. Separate images are appropriate for genuinely
  separate components; avoid merged setup images just to reduce service counts.
- Before adding enforcement, check the owning component's existing guarantees.
  Add a wrapper check only for a concrete invariant those guarantees do not cover;
  do not mirror native budgets, accounting, readiness or recovery state. Existing
  limits are not evidence that retaining or adding another limit is necessary.
- Do not build generic orchestration, adapter registries, lifecycle/recovery
  engines, configuration frameworks or provenance systems for speculative needs.
  Use native Compose behavior where suitable and small explicit helpers where
  native behavior does not meet a demonstrated requirement.
- Do not add hardening against a hypothetical threat by silently revising an
  accepted trust boundary. Explain the threat and reconcile it with documented
  trust decisions. Trusted offline setup may handle both Hermes and wallet storage;
  the untrusted SSH executor must not gain that authority.
- Reviewer suggestions are proposals, not automatic scope additions. Address
  material defects, consider simpler solutions, and explain rejected or deferred
  recommendations. Keep unrelated improvements separate.
- Do not introduce arbitrary container resource limits, storage quotas or work
  deadlines. Base safeguards on actual component requirements and observed
  failure modes. Allow for Tor latency and distinguish slow progress from failure.
  Connection establishment, response inactivity, polling/reporting cadence,
  signed expiry and test deadlines protect different contracts. Progress must not
  extend financial authority, and a reporting cadence must not become a failure
  deadline. Let valid work continue while it makes progress.

## No prerelease compatibility layer

This stack has not been deployed and has no installed user base requiring legacy
compatibility. Change interfaces and all consumers directly. Do not add old-name
aliases, deprecated formats, legacy readers, version-detection branches,
migration commands or transitional services without an explicit user requirement.

Repeated initialization must preserve current-format credentials, keys, wallets
and operator configuration. Safe retries, native wallet recovery and ordinary
state persistence are functional requirements, not legacy compatibility. Do not
delete private state as a shortcut to simplifying implementation or tests.

## Scope enforcement to the operation

- Each blocking check must protect a concrete requirement of the operation being
  attempted. Keep inspection, backup, repair and shutdown available when unrelated
  services or deployment settings are invalid. Validate network/serving policy
  before those capabilities are used, without making it a prerequisite for
  reading saved local state.
- Preserve valid persistent state and completed setup across unrelated source,
  build and configuration changes. Do not use whole-file hashes, build identities,
  timestamps or arbitrary versions as reasons to revoke access, discard completion
  or repeat setup. Require invalidation only for a demonstrated incompatibility,
  with the affected requirement, practical consequence and recovery explained.
- Keep historical completion, current readiness and access to saved data distinct.
  A dependency or policy failure may block the affected operation; it does not
  make an existing wallet invalid or authorize initialization, rotation, payments
  or destructive recovery. Prefer checking actual runtime requirements to adding
  another persisted eligibility marker.
- Distinguish authoritative state from advisory estimates, reporting projections
  and disposable caches. Missing optional corroboration or stale derived data must
  not veto an established outcome or reopen completed work. Repair derived data
  through its owning component instead of adding agreement checks, certificates
  or parallel accounting. Conflicting required facts still need scoped diagnosis.
- Make initialization retry-safe with native persistence and small explicit code:
  atomically publish individual files, save recoverable inputs before derived
  outputs, and reconstruct missing derived files from intact authoritative state.
  Preserve keys, credentials and operator choices. If recovery is impossible,
  report the specific missing material and deliberate recovery command.
- Do not turn partial-initialization handling into startup journals, recovery
  frameworks or speculative state machines. Test the relevant interruption and
  retry paths, including identity preservation, and stop at the simplest behavior
  that meets the demonstrated need.

## Preserve the accepted boundaries

- Hermes and its SSH executor have separate mounts, processes and network
  namespaces. Model/subagent code runs in the executor without agent state,
  provider credentials or wallet mounts. This is not per-task or tenant isolation.
- Public TCP from both namespaces goes through the transparent Tor gateway;
  DNS follows the Tor policy. Preserve denial of direct Internet, unsupported
  UDP, non-loopback IPv6, host/VM/private destinations and unintended peers.
  Configuration flags alone do not establish these boundaries.
- Preserve exact internal grants for SSH, Teep and selected MCP services. The
  executor cannot directly access agent APIs, inference or MCP endpoints.
  Authorized Hermes tool RPC is a separate capability, not permission to widen
  the executor's network access.
- Teep has its own direct uplink and explicitly approved host-loopback port.
  Provider keys belong there. Preserve its verification behavior; a health check
  is not evidence of successful attestation. Do not add direct-provider fallbacks
  around the configured inference route.
- x402_treazury shares the agent network namespace for authenticated loopback MCP,
  but retains separate processes, mounts and wallet ownership. Only treasury
  receives its private Tor SOCKS socket. Keep wallet data away from Hermes and
  the executor; do not add per-port relays without a concrete need.
- Keep ingress separate from egress. HAProxy has a fixed Hermes backend and
  restricted outbound access. Optional Funnel provides public HTTPS, not tailnet
  authorization. Neither component may give the agent host, tailnet or direct
  Internet connectivity. Preserve authentication, exact-host/origin checks and
  credential handling for local and Funnel access.
- An authenticated webapp operator has administrative agent authority. Its
  interactive terminal is distinct from the model's SSH execution backend.
  Document that distinction instead of claiming all browser actions are confined
  to the executor.
- Browser-originated remote requests do not pass through the stack's Tor gateway.
  Preserve the deployment external-content ceiling, authenticated public-raster
  retrieval, origin-scoped image consent and inert private previews. Browser-native
  interactive opt-in and streaming remain deferred to part 2. Preserve deliberate
  external link clicks and qualify browser containment separately from Tor egress.
- Never solve a failure by adding host networking, privileged application
  containers, container-engine socket mounts, broad private-network grants or
  direct egress. Dependency failure must not silently select a weaker transport
  or policy.

## Repository, configuration and persistence

- Runtime Compose files live at the root. Component Dockerfiles, defaults and
  container scripts live under `components/`; host helpers under `scripts/`;
  qualification code and disposable fixtures under `tests/`.
- Root `.env` is the unified operator input. Add settings to `.env.example` and
  explicit service mappings together. Do not load the entire file into services
  or place image/source versions there. Pins live in Compose and Dockerfiles.
- `config/` holds private editable configuration; `data/` holds persistent bind
  data. Hermes and wallet state use native named volumes because the qualified
  Docker Desktop bind filesystem fails database/lock requirements. Do not move
  them to binds without requalifying those requirements. Ordinary Compose down
  must preserve persistent data; backups must cover binds and named volumes.
- Keep the user-facing name `x402_treazury`, not an endpoint-specific nickname.
- Prefer native configuration before patching upstream. Necessary source patches
  must be narrow, explicit, tied to the packaged revision and reproducibly built.
  Document purpose, validation and removal conditions. Do not edit compiled
  bundles or patch at startup to conceal an unreproducible build.
- Preserve intentional native plugin installation, prepared environments and
  persistent storage. Distinguish operator-requested plugin management from
  automatically installing dependencies to repair a broken image at startup.
  Keep core stack updates image-managed and version checks separate from applying
  updates. Disabled telemetry and optional notifications are separate decisions.

## Plans, review and development commits

- Use a plan when requested or when substantial staged work needs explicit
  design decisions and acceptance criteria. Small changes need no ceremonial
  plan, extra subsystem guide or independent review.
- State current and intended behavior, preserved boundaries, the simplest
  proposed approach, unresolved assumptions and explicit deferrals. Include
  affected consumers, focused validation and permanent documentation in coherent
  implementation phases. Reconcile other plans affected by shared changes.
- Commit coherent work during development and at plan phase boundaries, including
  completed changes. This is standing authorization for local development
  commits; do not wait for a separate commit request. Record the baseline and
  plan path for substantive planned work. Never commit failing intermediate work
  as though it were a completed phase.
- Use independent read-only reviewers for substantive design/security changes,
  meaningful phase commits, named plan gates and the completed combined change.
  Scale review to the change; no fixed reviewer count or repeated review of an
  unchanged snapshot is required. Small documentation edits can use self-review.
- An independent audit/review means a newly spawned subagent with a fresh
  conversation and no prior turns or inherited conversation history. Use
  `fork_turns="none"` when supported. Do not reuse an implementation agent or an
  existing review conversation for a new independent review. Supply context in
  the review brief; the reviewer's own fresh inspection supplies the assessment.
- Give reviewers self-contained briefs with intent, constraints, exact SHA or
  identified snapshot including new files, relevant guides and evidence. Ask
  them to trace consumers/failure paths and challenge unnecessary complexity.
  Reviewers must not author the changes they independently review.
- Reviewers must not re-run already-run tests, suites or lifecycle qualification
  as part of a review unless the user specifically asks them to, or unless a new
  focused check is needed to confirm a suspected finding. Verify from the supplied
  snapshot, source inspection and recorded evidence, state what was not re-run,
  and if confirmation is required run only the smallest disposable check needed.
- Resolve material findings before dependent work. Commit focused corrections;
  re-review and rerun affected checks when changes invalidate earlier evidence.
  Do not require a separate review ceremony for every trivial fixup. Phase
  reviews do not substitute for assessing the resulting combined change.
- Distinguish implemented, validated and independently reviewed work. Disclose
  unavailable review/checks rather than claiming completion evidence that does
  not exist. Update operating guides with implementation and keep plan status
  accurate. After final review acceptance, remove completed plans using the
  planning workflow, preserving maintained documentation and resolving links.

## Validation and authority

- Choose checks that demonstrate the changed behavior. Documentation-only work
  needs inspection, local-link checks and `git diff --check`, not a runtime suite.
  Avoid prose snapshots and tests that merely mirror implementation details.
- Compose changes require effective-model validation and affected runtime checks.
  Security changes need allowed-path and forbidden-path evidence, including
  relevant dependency failure/restart behavior; static inspection is insufficient.
- Qualify affected runtime behavior on both supported engines using shared
  fixtures. Model/unit checks do not prove native engine behavior. Record actual
  engine/provider/platform limits and missing coverage; reuse unchanged evidence
  and keep documentation-only work scoped to documentation checks.
- Reuse the repository's focused checks and disposable projects. Serialize tests
  sharing fixed networks or runtime state. Keep real financial secrets out of
  fixtures, and qualify filesystem/locking behavior on the actual target.
- Once relevant checks pass, repeat or broaden them only for new changes,
  failures or unresolved concerns. Report omitted checks and practical limits.
  Controlled fixtures do not prove live public ingress, settlement, provider
  attestation or support for untested platforms.
- Fail visibly with useful reasons, without secret values. Do not mask failures
  with broad exception handling, silent fallback or unconditional success.
- Local development commits do not authorize pushing, merging, publishing, live
  Funnel enrollment, payments, funded wallet operations or destructive changes
  to private state. Use existing task authorization where provided; a plan or
  review recommendation alone grants none of these actions.
- Preserve unrelated tracked, untracked and ignored files. Stage only named
  intended files; never use `git add .` or `git add -A`. Do not rewrite existing
  history without authorization. Keep reference checkouts, secrets, wallet data,
  runtime state and generated private evidence out of commits. Never shell-source
  private environment files or print private values unnecessarily.

At handoff, report what changed, relevant validation and review, the committed
revision or remaining uncommitted work, and material limitations or next steps.
