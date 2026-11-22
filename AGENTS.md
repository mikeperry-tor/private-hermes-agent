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
  [updates, plugins, and privacy](docs/updates-and-plugins.md).
- Read relevant plans under `docs/plans/` and inspect the implementation before
  changing a shared interface. Plans describe intended work; their existence
  does not make a proposed feature implemented or independently authorize it.
- Read the [planning workflow](docs/planning-workflow.md) before creating,
  executing, materially revising, or completing an implementation plan.
- `reference_repos/` contains read-only reference checkouts. Do not edit them or
  put build/runtime state there. Check exact revisions: a reference checkout can
  differ from the pinned image or source used by the stack.
- Documents supplied from other projects are reference material, not governing
  instructions unless explicitly adopted. Preserve this project's accepted
  design rather than importing their topology, restrictions, or tooling.

## Maintain current documentation

- Maintained guides, component READMEs, and examples describe current behavior,
  repository status, support boundaries, and durable limitations. Update the
  owning section in place and remove superseded claims; readers must not
  reconcile a sequence of updates to discover what is true.
- Keep [README.md](README.md) user-facing only: explain the stack, its
  components, the problems they solve, setup, everyday operation, and practical
  limitations. Put implementation details, development procedures, and
  qualification evidence in documents under `docs/`, and link to them instead of
  expanding the README with maintainer material.
- Runtime sequencing, recovery procedures, version pins, data-as-of dates, and
  submission provenance remain valid when they explain a current fact.
  Distinguish them from the sequence in which an agent discovered or changed
  that fact.
- Do not append development journals, changelogs, dated test/probe narratives,
  review-acceptance logs, cleanup reports, or "initially/later/retested"
  histories outside plans. Do not carry retired plan phase/gate codes into
  permanent docs. Keep execution chronology and phase evidence in the plan; Git
  history preserves completed development history. Do not create an archive or
  another handoff document to relocate the journal.
- Preserve concise, attributable qualification status: version or source pin,
  platform, checks that establish the current contract, missing coverage, and
  practical limits. Keep detailed logs and generated reports in ignored/private
  evidence storage. A source pin or evidence identifier may support a current
  claim; it must not become a chronology of approvals or failed attempts.
- Keep active/deferred work and concrete next actions explicit. A completed plan
  retained at the user's request stays marked as a reference, without exporting
  its historical phase/status updates into maintained guides.
- Keep the user-facing name `x402_treazury`, not an endpoint-specific nickname.

## Writing style

These rules apply to all prose: documentation, plans, commit messages, PR and
issue drafts, code comments, and handoff notes.

- Write directly in plain English for human readers, and be concrete at the
  reader's level of detail. State the behavior, setting, command, or failure
  mode directly rather than using vague shorthand or invented jargon (for
  example, "the affected operation", "captured policy eligibility", or
  "historical completion authority"). Use file paths, function names, and
  implementation details in commit bodies, code comments, and maintainer docs
  where they clarify the change, without turning prose into pseudocode.
- State what a feature does rather than piling up defensive negative disclaimers
  about what it does not do or does not prove. Only use caveats that prevent a
  real misunderstanding or safety mistake.
- Keep internal process terms (qualification runs, replay branches, cleanup
  passes, or plan phases) out of user-facing docs, commit messages, and
  upstream PR/issue drafts.
- Omit filler qualifiers such as "selected", "ordinary", "applicable",
  "configured", "disposable", "harmless", "affected", "actual", "native",
  "existing", "matching", "deliberate", "explicit", "saved", "current", or
  "relevant" unless the adjective distinguishes two real cases in that
  sentence.
- Do not stack nouns or modifiers into dense noun-chains (such as "shared-
  namespace owner recovery qualification check" or "managed startup policy
  enforcement"); break them into clear subject-verb clauses.
- Do not pack multiple concepts into slash-joined compounds (such as
  "identity/mount/profile/cwd restoration" or "policy/credential/storage
  validation"). Spell out separate items with commas and conjunctions, or split
  them into bullets.
- Keep paragraphs short (2–4 sentences, one idea per paragraph). Break
  multi-part details, options, and edge cases into headings, tables, or
  bulleted lists with clear lead-ins rather than dense walls of text.
- Place each rule, caveat, and detail once in the section that owns it,
  integrated into the surrounding structure, and link to it from elsewhere. Do
  not repeat the same rule or caveat across multiple sections or sibling guides,
  do not bolt unrelated caveats onto the end of a nearby paragraph, and do not
  scatter test-suite notes inside operator setup sections when a dedicated
  verification section exists.
- Always use the Oxford (serial) comma (`a, b, and c`).
- Enforce clear tense boundaries:
  - Maintained docs, READMEs, and code comments describe **current** behavior
    in present tense. Never narrate prior code states, how the code evolved, or
    lab-note investigation chronology.
  - Commit messages and PR descriptions state the prior bug or limitation in
    **past tense** and the new behavior or fix in **present tense**. Never
    describe both the old broken state and the new state in present tense.

## Prefer the least machinery that meets the requirement

- Start with native component capabilities and straightforward code. Preserve
  useful Python setup/lifecycle helpers and the documented Make workflow; neither
  a language ban nor moving code into containers makes a design simpler.
- Before adding a service, persistent record, configuration option, or
  abstraction, identify its concrete responsibility and why an existing
  component cannot reasonably own it. Prefer fewer responsibilities and state
  transitions, not merely fewer files or containers. Separate images are
  appropriate for genuinely separate components; avoid merged setup images just
  to reduce service counts.
- Before adding enforcement, check the owning component's existing guarantees.
  Add a wrapper check only for a concrete invariant those guarantees do not
  cover; do not mirror native budgets, accounting, readiness, or recovery state.
  Existing limits are not evidence that retaining or adding another limit is
  necessary.
- Do not build generic orchestration, adapter registries, lifecycle/recovery
  engines, configuration frameworks, or provenance systems for speculative
  needs. Use native Compose behavior where suitable and small explicit helpers
  where native behavior does not meet a demonstrated requirement.
- Support Docker and rootless Podman through the existing engine selector and
  Make/Compose workflow. Prefer shared service behavior and explicit grants;
  justify engine-specific overlays with demonstrated native differences. Consult
  the maintained engine guidance rather than adding a compatibility framework.
- Fail visibly with useful reasons, without secret values. Do not mask failures
  with broad exception handling, silent fallback, or unconditional success.
- Do not introduce arbitrary container resource limits, storage quotas, or work
  deadlines. Base safeguards on component requirements and observed failure
  modes. Allow for Tor latency and distinguish slow progress from failure.
  Connection establishment, response inactivity, polling/reporting cadence,
  signed expiry, and test deadlines protect different contracts. Progress must
  not extend financial authority, and a reporting cadence must not become a
  failure deadline. Let valid work continue while it makes progress.

## Compatibility for deployed stacks

- The documented `make` entrypoints are the only supported ways for users to
  operate the stack. Direct Compose, container-engine, and helper invocations
  are development or diagnostic interfaces. Malfunctions, security issues, and
  other problems caused by bypassing the `make` entrypoints are outside the
  supported contract and are not bugs in the stack.
- The supported end-user upgrade is the in-place workflow in
  [Updates and Backups](README.md#updates-and-backups). Users run `make down`,
  take the [pre-upgrade backup](docs/configuration.md#backup-scope), then run
  `git pull` and `make up`. They keep their existing checkout, container engine,
  Compose project, bind mounts, and named volumes. `make up` builds the images
  and runs offline setup against existing state. Upgrades outside this workflow
  are unsupported.
- Private Hermes owns its deployment contract: supported root `.env` settings
  and their defaults and precedence, wrapper-owned files under `config/`,
  documented `make` entrypoints, and the storage and identity layout. The layout
  includes Compose project and volume names, bind paths, permissions, and the
  inputs needed to back up and restore a deployment. Preserve the meaning of
  retained settings, especially those governing exposure, authentication, and
  spending. Options may be retired if the recommended upgrade workflow leaves
  existing deployments operational and preserves saved state.
- Hermes and the other components own their native formats, schema migrations,
  and downgrade limits. Keep their saved state attached to upgraded services
  with the required ownership and mounts, and let the components read and
  migrate it. Private Hermes still owns state written by its setup helpers and
  downstream features, including saved WebApp credentials and private image
  consent, even when those files live beside component-owned state.
- Preserve supported deployments across updates. When a wrapper-owned change
  requires operator action, document the affected releases, the smallest safe
  upgrade step, and backup and recovery requirements. Use a focused
  compatibility read or migration when necessary to preserve state or behavior,
  scoped to that format or interface. Regenerate derived files from
  authoritative state when possible.
- Qualify upgrades through this workflow using populated fixtures from a prior
  release. Check effective configuration, credential and identity preservation,
  and safe retry of changed setup or migration steps. Never discard private
  state, rotate credentials, or initialize another wallet to recover from an
  upgrade failure. Document when rollback requires a pre-upgrade backup.

## Scope enforcement to the operation

- Each blocking check must protect a concrete requirement of the operation being
  attempted. Keep inspection, backup, repair, and shutdown available when
  unrelated services or deployment settings are invalid. Validate
  network/serving policy before those capabilities are used, without making it a
  prerequisite for reading saved local state.
- Preserve valid persistent state and completed setup across unrelated source,
  build, and configuration changes. Do not use whole-file hashes, build
  identities, timestamps, or arbitrary versions as reasons to revoke access,
  discard completion, or repeat setup. Require invalidation only for a
  demonstrated incompatibility, explaining the requirement, practical
  consequence, and recovery.
- Keep historical completion, current readiness, and access to saved data
  distinct. A dependency or policy failure may block that operation; it does not
  make an existing wallet invalid or authorize initialization, rotation,
  payments, or destructive recovery. Prefer checking runtime requirements over
  adding another persisted eligibility marker.
- Distinguish authoritative state from advisory estimates, reporting
  projections, and disposable caches. Missing optional corroboration or stale
  derived data must not veto an established outcome or reopen completed work.
  Repair derived data through its owning component instead of adding agreement
  checks, certificates, or parallel accounting. Conflicting required facts still
  need scoped diagnosis.
- Make initialization retry-safe with native persistence and small explicit
  code: atomically publish individual files, save recoverable inputs before
  derived outputs, and reconstruct missing derived files from intact
  authoritative state. Preserve keys, credentials, and operator choices. If
  recovery is impossible, report the specific missing material and deliberate
  recovery command.
- Do not turn partial-initialization handling into startup journals, recovery
  frameworks, or speculative state machines. Test interruption and retry paths,
  including identity preservation, and stop at the simplest behavior that meets
  the demonstrated need.

## Preserve the accepted boundaries

- Hermes and its SSH executor have separate mounts, processes, and network
  namespaces. Model/subagent code runs in the executor without agent state,
  provider credentials, or wallet mounts. This is not per-task or tenant
  isolation.
- Public TCP from both namespaces goes through the transparent Tor gateway;
  DNS follows the Tor policy. Preserve denial of direct Internet, unsupported
  UDP, non-loopback IPv6, unintended peers, and private destinations by default.
  Operators may grant the Hermes identity exact engine-host TCP ports and
  RFC1918 address/port pairs through the existing gateway. Preserve executor
  denial, Tor-only public egress, and separation from inter-service grants.
  Configuration flags alone do not establish these boundaries.
- Preserve exact internal grants for SSH, Teep, and enabled MCP services. The
  executor cannot directly access agent APIs, inference, or MCP endpoints.
  Authorized Hermes tool RPC is a separate capability, not permission to widen
  the executor's network access.
- Teep has its own direct uplink and explicitly approved host-loopback port.
  Provider keys belong there. Preserve its verification behavior; a health check
  is not evidence of successful attestation. Do not add direct-provider
  fallbacks around the Teep inference route. Use managed `make up` and
  `make down` for stack lifecycle and Teep selection. Provider choice stays in
  Hermes.
- x402_treazury shares the agent network namespace for authenticated loopback
  MCP, but retains separate processes, mounts, and wallet ownership. Only
  treasury receives its private Tor SOCKS socket. Keep wallet data away from
  Hermes and the executor; do not add per-port relays without a concrete need.
- Keep ingress separate from egress. HAProxy has a fixed Hermes backend and
  restricted outbound access. Optional Funnel provides public HTTPS, not tailnet
  authorization. Neither component may give the agent host, tailnet, or direct
  Internet connectivity. Preserve authentication, exact-host/origin checks, and
  credential handling for local and Funnel access.
- An authenticated webapp operator has administrative agent authority. Its
  interactive terminal is distinct from the model's SSH execution backend.
  Document that distinction instead of claiming all browser actions are confined
  to the executor.
- Browser-originated remote requests do not pass through the stack's Tor
  gateway. Preserve the deployment external-content ceiling, authenticated
  public-raster retrieval, origin-scoped image consent, and inert private
  previews. Browser-native interactive opt-in and streaming remain deferred to
  part 2. Preserve deliberate external link clicks and qualify browser
  containment separately from Tor egress.
- Never solve a failure by adding host networking, privileged application
  containers, container-engine socket mounts, broad private-network grants, or
  direct egress. Dependency failure must not silently select a weaker transport
  or policy.
- Do not add hardening against a hypothetical threat by silently revising an
  accepted trust boundary. Explain the threat and reconcile it with documented
  trust decisions. Trusted offline setup may handle both Hermes and wallet
  storage; the untrusted SSH executor must not gain that authority.

## Repository, configuration, and persistence

- Runtime Compose files live at the root. Component Dockerfiles, defaults, and
  container scripts live under `components/`; host helpers under `scripts/`;
  qualification code and test fixtures under `tests/`.
- Root `.env` is the unified operator input. Add settings to `.env.example` and
  explicit service mappings together. Do not load the entire file into services
  or place image/source versions there. Pins live in Compose and Dockerfiles.
- `config/` holds private editable configuration; `data/` holds persistent bind
  data. Hermes and wallet state use native named volumes because the qualified
  Docker Desktop bind filesystem fails database/lock requirements. Do not move
  them to binds without requalifying those requirements. `make down` and Compose
  down without `-v` must preserve persistent data; backups must cover binds and
  named volumes.
- Prefer native configuration before patching upstream. Necessary source patches
  must be narrow, explicit, tied to the packaged revision, and reproducibly
  built. Document purpose, validation, and removal conditions. Do not edit
  compiled bundles or patch at startup to conceal an unreproducible build.
- Preserve intentional native plugin installation, prepared environments, and
  persistent storage. Distinguish operator-requested plugin management from
  automatically installing dependencies to repair a broken image at startup.
  Keep core stack updates image-managed and version checks separate from
  applying updates. Disabled telemetry and optional notifications are separate
  decisions.

## Plans, review, and development commits

- Use a plan when requested or when substantial staged work needs explicit
  design decisions and acceptance criteria. Small changes need no ceremonial
  plan, extra subsystem guide, or independent review.
- State current and intended behavior, preserved boundaries, the simplest
  proposed approach, unresolved assumptions, and explicit deferrals. Include
  consumers, focused validation, and permanent documentation in coherent
  implementation phases. Reconcile other plans affected by shared changes.
- Commit coherent work during development and at plan phase boundaries,
  including completed changes. This is standing authorization for local
  development commits; do not wait for a separate commit request. Record the
  baseline and plan path for substantive planned work. Never commit failing
  intermediate work as though it were a completed phase.
- Follow the [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/)
  specification for commit subjects (for example,
  `fix(ssh): preserve workspace sync`) and keep subjects and bodies within 80
  columns. In addition to that standard, use two body paragraphs for changes
  that fix a substantial bug or limitation: describe the prior problem in past
  tense, then describe the fix in present tense (see
  [Writing style](#writing-style)). The two-paragraph body is optional for
  routine documentation cleanup or plan updates.
- Preserve unrelated tracked, untracked, and ignored files. Stage only named
  intended files; never use `git add .` or `git add -A`. Do not rewrite existing
  history without authorization. Keep reference checkouts, secrets, wallet data,
  runtime state, and generated private evidence out of commits.
- Use independent read-only reviewers for substantive design/security changes,
  meaningful phase commits, named plan gates, and the completed combined change.
  Scale review to the change; no fixed reviewer count or repeated review of an
  unchanged snapshot is required. Small documentation edits can use self-review.
- An independent audit/review means a newly spawned subagent with a fresh
  conversation and no prior turns or inherited conversation history. Use
  `fork_turns="none"` when supported. Do not reuse an implementation agent or an
  existing review conversation for a new independent review. Supply context in
  the review brief; the reviewer's own fresh inspection supplies the assessment.
- Give reviewers self-contained briefs with intent, constraints, exact SHA or
  identified snapshot including new files, relevant guides, and evidence. Ask
  them to trace consumers and failure paths and challenge unnecessary
  complexity. Reviewers must not author the changes they independently review.
- Reviewers must not re-run already-run tests, suites, or lifecycle
  qualification as part of a review unless the user specifically asks them to,
  or unless a new focused check is needed to confirm a suspected finding. Verify
  from the supplied snapshot, source inspection, and recorded evidence, state
  what was not re-run, and if confirmation is required run only the smallest
  check needed.
- Reviewer suggestions are proposals, not automatic scope additions. Address
  material defects, consider simpler solutions, and explain rejected or deferred
  recommendations. Keep unrelated improvements separate.
- Resolve material findings before dependent work. Commit focused corrections;
  re-review and rerun checks when changes invalidate earlier evidence. Do not
  require a separate review ceremony for every trivial fixup. Phase reviews do
  not substitute for assessing the resulting combined change.
- Distinguish implemented, validated, and independently reviewed work. Disclose
  unavailable reviews or checks rather than claiming completion evidence that
  does not exist. Update operating guides with implementation and keep plan
  status accurate. After final review acceptance, remove completed plans using
  the planning workflow, preserving maintained documentation and resolving
  links.

## Validation and authority

- Choose checks that demonstrate the changed behavior. Documentation-only work
  needs inspection, local-link checks, and `git diff --check`, not a runtime
  suite. Avoid prose snapshots and tests that merely mirror implementation
  details.
- Compose changes require effective-model validation and runtime checks.
  Security changes need allowed-path and forbidden-path evidence, including
  dependency failure and restart behavior; static inspection is insufficient.
- Qualify runtime behavior on both supported engines using shared fixtures.
  Model/unit checks do not prove native engine behavior. Reuse unchanged
  evidence across unrelated work, and repeat or broaden checks only for new
  changes, failures, or unresolved concerns.
- Reuse the repository's focused checks and isolated test projects. Serialize
  tests sharing fixed networks or runtime state. Keep real financial secrets out
  of fixtures, and qualify filesystem and locking behavior on the target
  platform.
- Record engine, provider, and platform limits, omitted checks, and missing
  coverage. Controlled fixtures do not prove live public ingress, settlement,
  provider attestation, or support for untested platforms.
- Local development commits do not authorize pushing, merging, publishing, live
  Funnel enrollment, payments, funded wallet operations, or destructive changes
  to private state. Use existing task authorization where provided; a plan or
  review recommendation alone grants none of these actions. Never shell-source
  private environment files or print private values unnecessarily.

At handoff, report what changed, relevant validation and review, the committed
revision or remaining uncommitted work, and material limitations or next steps.
