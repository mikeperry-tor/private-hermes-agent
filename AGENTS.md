# Agent instructions for Private Hermes

This repository is a small deployment wrapper for Hermes Agent, not a general
agent platform. It combines SSH-isolated code execution, transparent Tor egress,
Teep inference, x402_treazury research tools, and an authenticated webapp with
optional Tailscale Funnel and Tor onion ingress. Do not add framework selection
or unrelated services.

Treat [security boundaries](#security-boundaries),
[state safety and upgrades](#state-safety-and-retryable-setup), and
[authority limits](#authority-limits) as hard non-negotiables; simplicity,
review, workflow, and writing-style rules serve those invariants.

## Guides and references

Read the maintained guide for the area you are changing before editing; detailed
contracts and defaults live there rather than in copies here.

| Change area | Read first |
| --- | --- |
| User overview, setup, and operator commands | [README.md](README.md) |
| Network isolation, GRE, Tor, Teep, and executor topology | [architecture and isolation](docs/architecture.md) |
| `.env` settings, offline setup, local inference, and backups | [configuration and backups](docs/configuration.md) |
| Local webapp, Funnel, onion ingress, content policy, and terminals | [webapp](docs/webapp.md) |
| Paid research MCP endpoints, wallet preparation, and funding policy | [x402_treazury](docs/x402_treazury.md) |
| Derived Hermes image, patches, plugins, and privacy defaults | [updates, plugins, and privacy](docs/updates-and-plugins.md) |
| Upgrading to a new official Hermes release | [Hermes update workflow](docs/update-workflow.md) |
| Test commands, engine parity, and qualification status | [development and qualification](docs/development.md) |
| Creating, executing, revising, or completing a staged plan | [planning workflow](docs/planning-workflow.md) |

- Read plans under `docs/plans/` that touch the area you are changing and
  inspect the implementation before changing a shared interface. Plans describe
  intended work; their existence does not make a proposed feature implemented or
  independently authorize it.
- `reference_repos/` contains read-only reference checkouts. Do not edit them or
  put build or runtime state there. Check exact revisions: a reference checkout
  can differ from the pinned image or source used by the stack.
- Documents supplied from other projects are reference material, not governing
  instructions unless explicitly adopted. Preserve this project's accepted
  design rather than importing their topology, restrictions, or tooling.

## Engineering and security

### Security boundaries

See [architecture and isolation](docs/architecture.md) and
[webapp](docs/webapp.md) for exact grants and topology. Preserve these
invariants across all changes:

- **Never weaken isolation to fix a failure:** Do not add host networking,
  privileged application containers, container-engine socket mounts, broad
  private-network grants, or direct-egress fallbacks. Dependency failure must
  never silently select a weaker transport or policy.
- **Agent and executor separation:** Hermes and its SSH executor keep separate
  mounts, processes, and network namespaces. Model and subagent code runs in the
  executor without agent state, provider keys, or wallet mounts (this is not
  per-task or tenant isolation).
- **Tor egress and exact grants:** Public TCP and DNS from both namespaces route
  through the transparent Tor gateway, denying direct Internet, unsupported UDP,
  non-loopback IPv6, unintended peers, and private destinations by default.
  Operator grants for exact host TCP ports and RFC1918 destinations apply only
  to Hermes, never the executor. Keep internal grants exact for SSH, Teep, and
  enabled MCP services; authorized Hermes tool RPC never widens executor network
  access, and configuration flags alone do not prove these boundaries.
- **Teep and treasury separation:** Teep keeps provider keys on its own direct
  uplink and approved host-loopback port without direct-provider fallbacks (a
  health check does not prove attestation; provider choice stays in Hermes).
  `x402_treazury` shares `agent-net` for authenticated loopback MCP while
  keeping separate processes, mounts, wallet ownership, and exclusive access to
  Tor's private SOCKS socket.
- **Ingress and browser containment:** Keep ingress separate from egress:
  HAProxy uses a fixed Hermes backend with restricted outbound access, optional
  Funnel provides public HTTPS (not tailnet authorization), and neither grants
  Hermes host, tailnet, or direct Internet access. Preserve authentication and
  exact host and origin checks for local, Funnel, and onion access, and keep the
  operator's administrative webapp authority distinct from the model's SSH
  executor. Browser-originated remote requests bypass the Tor gateway, so
  preserve the external-content ceiling, authenticated public-raster retrieval,
  origin-scoped image consent, inert private previews, and user-initiated
  external link clicks, and qualify browser containment separately from Tor
  egress.
- **No silent trust-boundary changes:** Explain any new threat and reconcile
  proposed hardening with documented trust decisions. Trusted offline setup may
  handle Hermes and wallet storage; the untrusted SSH executor must never gain
  that authority.

### State safety and retryable setup

- Gate each operation only on its own concrete requirements. Keep inspection,
  backup, repair, and shutdown available when unrelated services or deployment
  settings are invalid; validate network and serving policy before those
  capabilities run, not before reading local state.
- Preserve valid persistent state and completed setup across unrelated source,
  build, and configuration changes. Do not invalidate access, discard
  completion, or repeat setup based on whole-file hashes, build identities,
  timestamps, or arbitrary versions. Require invalidation only for a
  demonstrated incompatibility, and explain the requirement, consequence, and
  recovery.
- Keep prior completion, current readiness, and access to stored data distinct.
  A dependency or policy failure may block an operation, but it never
  invalidates an existing wallet or authorizes initialization, rotation,
  payments, or destructive recovery. Prefer runtime checks over extra persisted
  eligibility markers.
- Distinguish authoritative state from advisory estimates, reporting
  projections, and temporary caches. Missing optional corroboration or stale
  derived data must not veto an established outcome or reopen completed work;
  repair derived data through its owning component while diagnosing conflicting
  required facts directly.
- Make initialization retry-safe with direct, atomic file writes: save
  recoverable inputs before derived outputs, preserve keys, credentials, and
  operator choices, and reconstruct missing derived files from intact
  authoritative state. If recovery is impossible, report the missing material
  and the exact recovery command. Test interruption and retry paths, including
  identity preservation.

### Deployed stack compatibility and upgrades

- The documented `make` entrypoints are the only supported ways for users to
  operate the stack. Direct Compose, container-engine, and helper invocations
  are development or diagnostic interfaces. Malfunctions, security issues, and
  other problems caused by bypassing the `make` entrypoints are outside the
  supported contract and are not bugs in the stack.
- The supported end-user upgrade is the in-place workflow in
  [Updates and Backups](README.md#updates-and-backups). Users run `make down`,
  take the [pre-upgrade backup](docs/configuration.md#backup-scope), then run
  `git pull` and `make up`. They keep their checkout, container engine, Compose
  project, bind mounts, and named volumes. `make up` builds the images and runs
  offline setup against that state. Upgrades outside this workflow are
  unsupported.
- Private Hermes owns its deployment contract: supported root `.env` settings
  and their defaults and precedence, wrapper-owned files under `config/`,
  documented `make` entrypoints, and the storage and identity layout (Compose
  project and volume names, bind paths, permissions, and backup inputs).
  Preserve the meaning of retained settings, especially those governing
  exposure, authentication, and spending. Options may be retired if the
  recommended upgrade workflow leaves existing deployments operational and
  preserves state.
- Hermes and the other components own their own formats, schema migrations, and
  downgrade limits. Keep their state attached to upgraded services with the
  required ownership and mounts, and let the components read and migrate it.
  Private Hermes still owns state written by its setup helpers and downstream
  features, including WebApp credentials and private image consent, even when
  those files live beside component-owned state.
- Preserve supported deployments across updates. When a wrapper-owned change
  requires operator action, name the releases that require it, the smallest safe
  upgrade step, and backup and recovery requirements. Use a focused
  compatibility read or migration when necessary to preserve state or behavior,
  scoped to that format or interface, and regenerate derived files from
  authoritative state when possible.
- Qualify upgrades through this workflow using populated fixtures from a prior
  release. Check effective configuration, credential and identity preservation,
  and safe retry of changed setup or migration steps. Never discard private
  state, rotate credentials, or initialize another wallet to recover from an
  upgrade failure. Document when rollback requires a pre-upgrade backup.

### Simplicity, errors, and timeouts

- Start with each component's built-in capabilities and straightforward code.
  Preserve useful Python setup and lifecycle helpers and the documented Make
  workflow; neither a language ban nor moving code into containers makes a
  design simpler.
- Before adding a service, persistent record, configuration option, or
  abstraction, identify its concrete responsibility and why an existing
  component cannot own it. Prefer fewer responsibilities and state transitions,
  not merely fewer files or containers; keep separate images for genuinely
  separate components rather than merging setup images.
- Check upstream component guarantees before adding wrapper enforcement
  or patches. Add a wrapper check only for a concrete invariant those guarantees
  do not cover; do not mirror component budgets, accounting, readiness, or
  recovery state. An existing limit is not a reason to keep it or add another.
- Do not build generic orchestration, adapter registries, startup journals,
  recovery or compatibility frameworks, configuration engines, speculative state
  machines, or provenance systems. Use Compose directly where suitable, small
  focused helpers where Compose falls short, and documented engine overlays only
  for demonstrated Docker vs. rootless Podman differences.
- Fail visibly with useful reasons and no secret values. Do not mask failures
  with broad exception handling, silent fallback, or unconditional success.
- Do not introduce arbitrary container resource limits, storage quotas, or work
  deadlines. Base safeguards on component requirements and observed failure
  modes, allow for Tor latency, and distinguish slow progress from failure.
- Keep timeout contracts distinct: connection establishment, response
  inactivity, polling and reporting cadences, signed expiry, and test deadlines
  protect different boundaries. Progress must not extend financial authority,
  and a reporting cadence must not become a failure deadline. Let valid work
  continue while it makes progress.

### Repository layout, configuration, and scripts

- Runtime Compose files live at the root. Component Dockerfiles, defaults, and
  container scripts live under `components/`; host helpers under `scripts/`;
  qualification code and test fixtures under `tests/`.
- Keep host helpers in `scripts/` and unit tests in `tests/test_*.py` on the
  Python standard library (plus repo-local modules) so operator commands and
  `make check` work with bare `python3` and no virtualenv. Keep optional
  browser-test dependencies isolated in `tests/requirements-browser.txt`, and
  use strict error handling (`set -eu`) with quoted expansions in shell scripts.
- Root `.env` is the unified operator input. Add settings to `.env.example` and
  explicit service mappings together. Do not load the entire file into services
  or place image or source versions there. Pins live in Compose and Dockerfiles.
- `config/` holds private editable configuration; `data/` holds persistent bind
  data. Hermes and wallet state use named volumes because the qualified Docker
  Desktop bind filesystem fails database and locking requirements. Do not move
  them to binds without requalifying those requirements. `make down` and Compose
  down without `-v` must preserve persistent data; backups must cover binds and
  named volumes.
- Prefer upstream configuration before patching upstream source. Necessary
  source patches must be narrow, clearly documented, tied to the packaged
  revision, and reproducibly built. Document purpose, validation, and removal
  conditions. Do not edit compiled bundles or patch at startup to conceal an
  unreproducible build.
- Preserve intentional plugin installation through Hermes's plugin CLI, prepared
  environments, and persistent storage. Distinguish operator-requested plugin
  management from automatically installing dependencies to repair a broken image
  at startup. Keep core stack updates image-managed and version checks separate
  from applying updates. Disabled telemetry and optional notifications are
  separate decisions.

## Independent review and planning

Use independent subagents for design challenge, audits, and implementation
review as a normal part of engineering work, without waiting for a separate
delegation request. Scale review to the change.

### Independent subagent review

- **Applies independently of plans:** Run independent review for any non-trivial
  code, Compose, firewall, ingress, policy, storage, behavioral, or substantive
  documentation change, including standalone fixes and single-commit work that
  need no plan file. Only trivial edits (small documentation tweaks, typo or
  comment fixes, and isolated minor unit-test edits) skip independent review.
- **Pre-implementation design review:** Before substantive implementation or
  architectural changes, have an independent design reviewer challenge the
  approach, verify component ownership and guarantees against the code and
  pinned revisions, identify removable responsibilities, and test whether a
  simpler design suffices. Resolve material design findings before building on
  that decision.
- **Fresh, non-author isolation:** Every independent review or audit must run in
  a newly spawned subagent with a fresh conversation and no prior turns or
  inherited history. Give the subagent the parent's full tool, Git, MCP, and
  network capabilities (rather than a stripped-down subagent type that blocks
  Git history or MCP tools), and instruct it in its brief to perform a read-only
  review without modifying files or repository state. Never reuse the
  implementation agent or a prior review conversation, and never have a reviewer
  review any changes they suggest.
- **Self-contained coordinator brief:** Supply intent, constraints, baseline,
  exact reviewed commit SHA or snapshot (including new files), owning guides,
  validation evidence, known gaps, and prior findings. Give the reviewer access
  to the checkout and Git history.

### Review method and findings

- **Independent assessment:** Record an initial assessment before consulting
  the author's rationale or prior findings, then reconcile it with prior
  findings and fixes. Trace surrounding consumers, complete call chains,
  failure paths, unchanged high-risk boundaries, and test coverage. Verify any
  assumptions about upstream contracts, behavior, and component interactions
  against `reference_repos/` (checking that each checkout matches the pinned
  revision).
- **Simplification and complexity challenge:** Look for simpler alternate
  designs, especially ones that can rely on upstream components, sub-components,
  or built-in behavior rather than new patches, services, or stack code. Flag
  over-engineering, double enforcement, collapsible behaviors, parallel state,
  fragile ownership, speculative machinery, or other awkward, overly complex
  behaviors that can be simplified or removed. Suggest simpler alternate designs
  and evaluate concrete simplifications against the contracts they must preserve.
- **Pattern-sweep prior findings across the branch:** When follow-up fixes or
  multiple commits accumulate, each subsequent review pass and the final
  combined review must trace **all prior findings and fixes** through the
  surrounding code for recurring causes, shared invalid assumptions,
  excessively complicated or fragile design patterns that could be simplified
  or removed, and coverage gaps elsewhere in the branch. Per-commit or
  per-phase approval does not replace a final combined review of the
  complete change.
- **Documentation review:** Review substantive documentation changes (standalone
  or paired with code) for [writing style](#writing-style) compliance, factual
  accuracy against the implementation, Dockerfiles, Compose files, and pinned
  `reference_repos/` revisions, and preservation of current operational
  procedures, error conditions, security boundaries, and qualification limits.
  Check structure, complexity, scope, single ownership, valid local links and
  anchors, and audience fit (operator `README.md` vs. maintainer guides).
- **Verification discipline:** Reviewers verify from the snapshot, source
  inspection, and recorded evidence; they must not re-run already-run tests or
  lifecycle suites unless explicitly asked or to confirm a suspected finding
  with the smallest focused check needed (stating what was not re-run).
- **Resolving findings and accurate reporting:** Treat reviewer suggestions as
  proposals rather than automatic scope expansion. Fix material defects before
  dependent work, evaluate compelling simplifications on merit, explain rejected
  or deferred items, and re-review when fixes invalidate earlier evidence.
  Report implemented, validated, and independently reviewed work separately, and
  disclose unavailable reviews rather than claiming completion.

### Planning

- Use a committed plan under `docs/plans/` only when the user requests one, when
  continuing an existing plan, or when staged work genuinely spans multiple
  dependent phases with distinct design decisions and acceptance gates. Routine
  single-commit or multi-step fixes use the independent review workflow above
  without creating a plan file.
- Before creating, revising, executing, or completing a plan, follow
  [docs/planning-workflow.md](docs/planning-workflow.md). It owns plan
  structure, phase gates, evidence tracking, and removing completed plans after
  final review acceptance (unless retained as a reference at the user's
  request).

## Validation and authority

### Checks and qualification

| Command or check | When to run | Scope and limits |
| --- | --- | --- |
| `make check` | Default fast baseline for code, script, and Compose changes | Unit tests (`tests/test_*.py`), all four Compose models, and Python compilation. Does not prove runtime engine behavior. |
| Local link check and `git diff --check` | Documentation-only edits | Verifies links, anchors, and whitespace without running container suites. |
| Targeted `make *-test` or `tests/*_smoke.py` | Runtime, Compose, security, ingress, or component changes | Demonstrates changed runtime behavior on isolated fixtures; see [development and qualification](docs/development.md). |

- Compose changes require effective-model validation and runtime checks.
  Security changes need allowed-path and forbidden-path evidence, including
  dependency failure and restart behavior; static inspection is insufficient.
- Qualify runtime behavior on both Docker and rootless Podman using shared
  fixtures. Reuse unchanged evidence across unrelated work, and repeat or
  broaden checks only for new changes, failures, or unresolved concerns.
- Reuse the repository's focused checks and isolated test projects. Serialize
  tests sharing fixed networks or runtime state. Keep live financial secrets out
  of fixtures, qualify filesystem and locking behavior on the target platform,
  and avoid prose snapshots or tests that merely mirror implementation details.
- Record engine, provider, and platform limits, omitted checks, and missing
  coverage. Controlled fixtures do not prove live public ingress, settlement,
  provider attestation, or support for untested platforms.

### Authority limits

- Local development commits do not authorize pushing, merging, publishing, live
  Funnel enrollment, payments, funded wallet operations, or destructive changes
  to private state. Perform these only when task authorization is provided; a
  plan or review recommendation alone grants none of these actions.
- Never shell-source private environment files or print private values
  unnecessarily.

## Git and commits

- **Development commits:** Commit coherent work during development and at plan
  phase boundaries, including completed changes. This is standing authorization
  for local commits; do not wait for a separate request. Never commit failing
  intermediate work as a completed phase.
- **Commit format:** Follow
  [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) for
  subjects (for example, `fix(ssh): preserve workspace sync`) and wrap prose in
  subjects and bodies to 80 columns (long URLs, paths, or hashes do not need
  artificial line breaks). For changes that fix a substantial bug or limitation,
  use two body paragraphs: describe the prior problem in past tense, then
  describe the fix in present tense (see [Writing style](#writing-style)). The
  two-paragraph body is optional for routine documentation cleanup or plan
  updates.
- **Worktree and staging hygiene:** Preserve unrelated tracked, untracked, and
  ignored files. Stage only named intended files; never use `git add .` or
  `git add -A`, and do not rewrite git history without authorization. If an
  unrelated file has unexpected local edits, leave them untouched and ask the
  user if they collide with your task. Keep reference checkouts, secrets, wallet
  data, runtime state, and generated private evidence out of commits.
- **Handoff:** Report what changed, the validation and reviews performed, the
  committed revision or remaining uncommitted work, and material limitations or
  next steps.

## Documentation and writing style

### Maintain current documentation

- Maintained guides, component READMEs, and examples describe current behavior,
  support boundaries, and durable limits. Update the owning section in place and
  remove superseded claims.
  - Place each rule, caveat, and detail once in its owning section, integrated
    into the surrounding structure, and link from elsewhere (a brief safety
    reminder linking to the owning section is fine at the point of action).
  - Never append new topics to the bottom of a file or under an unrelated
    heading, never duplicate reference tables across two guides, and keep test
    notes in verification sections rather than operator setup sections. When a
    setting, default, policy, or contract changes, search across all maintained
    docs to remove every stale copy in the same change.
- Keep [README.md](README.md) user-facing only: explain the stack, its
  components, the problems they solve, setup, everyday operation, and practical
  limits. Put implementation details, development procedures, and qualification
  evidence under `docs/` and link to them.
- Keep development journals, changelogs, dated probe narratives, review logs,
  "initially", "later", and "retested" histories, and retired plan phase or gate
  codes out of permanent docs (and do not relocate them into archive or handoff
  files). Summarize testing contracts, boundaries, and entrypoints rather than
  narrating individual tests' internal mocks, fixtures, or assertion order (test
  source files own their own mechanics). Execution chronology belongs in active
  plans; Git history preserves completed work. Keep active and deferred work and
  next actions clear; completed plans retained at the user's request stay marked
  as references.
- Preserve concise, attributable qualification status (version or source pin,
  platform, checks establishing the contract, missing coverage, and limits), and
  keep raw logs and reports in ignored private storage. Runtime sequencing,
  recovery procedures, version pins, upgrade steps, and submission provenance
  remain valid when they explain a current fact.
- When revising documentation, preserve current procedures, recovery steps,
  error conditions, security boundaries, and qualification limits while removing
  superseded or redundant detail.
  - When condensing prose, do not merge distinct `make` targets, Docker vs.
    rootless Podman behavior, or ingress and content modes into one generalized
    claim that blurs their differences. Keep every documented command runnable,
    including required flags or environment variables (such as
    `CONTAINER_ENGINE=podman`).
  - Verify factual claims against the implementation, Dockerfiles, Compose
    files, and pinned `reference_repos/` revisions.
  - Before renaming headings, changing exact diagnostic strings, or editing
    documented keys or code blocks, cross-check markdown inbound links and any
    tests or scripts that assert on exact diagnostic strings or `.env` keys.
- Keep the user-facing name `x402_treazury`, not an endpoint-specific nickname.

### Writing style

These rules apply to all prose: documentation, plans, commit messages, PR and
issue drafts, code comments, and handoff notes.

- Write directly in plain English for human readers, and be concrete at the
  reader's level of detail. State the behavior, setting, command, or failure
  mode directly rather than using vague shorthand, invented jargon, or
  bureaucratic pseudo-legal framing (for example, "the affected operation",
  "captured policy eligibility", "historical completion authority", "truthful
  current behavior", or "does not certify the candidate"). Say what the code
  does ("rejects the request", "does not fall back", "requires login"),
  reserving terms such as "authority", "claim", and "proof" for concrete
  security, financial, or protocol mechanisms. Use file paths, function names,
  and implementation details in commit bodies, code comments, and maintainer
  docs where they clarify the change, without turning prose into pseudocode.
- State what a feature does rather than piling up defensive negative disclaimers
  about what it does not do or does not prove. State a shared scope limit or
  qualification boundary once at the top of a document or section rather than
  repeating the same boilerplate caveat after every subsection or list item.
  Only add inline caveats that prevent a concrete misunderstanding or safety
  mistake.
- Keep internal process terms (qualification runs, replay branches, cleanup
  passes, or plan phases) out of user-facing docs, commit messages, and
  upstream PR and issue drafts.
- Omit filler qualifiers (`"ordinary"`, `"applicable"`, `"disposable"`,
  `"harmless"`, `"affected"`, `"actual"`, `"deliberate"`, `"relevant"`,
  `"truthful"`, `"honest"`, `"usable"`, `"real"`). Use distinguishing
  adjectives (`"selected"`, `"configured"`, `"native"`, `"existing"`,
  `"matching"`, `"explicit"`, `"saved"`, `"current"`, `"retained"`) only when
  they separate two concrete cases in context (for example, a `configured`
  `.env` setting vs. a built-in default, `native` Linux Docker vs. Docker
  Desktop, or `saved` credentials vs. a freshly generated secret).
- Write complete, grammatical sentences with articles (`a`, `an`, `the`) and
  clear active subjects. Avoid clipped telegram-style prose, dangling modifiers
  (write "HAProxy rejects the request rather than falling back to direct
  access", not "the request is rejected rather than falling back to direct
  access"), and `+` used as a prose conjunction (write `and` or `with`).
- Do not stack nouns or modifiers into dense noun-chains (such as "shared-
  namespace owner recovery qualification check" or "managed startup policy
  enforcement"); break them into clear subject-verb clauses.
- Do not pack multiple concepts into slash-joined compounds (such as
  "identity/mount/profile/cwd restoration", "policy/credential/storage
  validation", or "host/VM", "auth/consent", "outage/recovery"). Spell out
  separate items with commas and conjunctions, or split them into bullets.
  Reserve slashes for file paths, URLs, `owner/repo` names, and standard
  protocol or identifier forms such as `HTTP(S)`, `UID/GID`, or `IPv4/IPv6`.
- Keep paragraphs short (generally 1-4 sentences, one idea per paragraph) and
  keep Markdown table cells concise as rendered (a short phrase, 1-2 sentences,
  or 1-4 primary links per index cell -- never multi-paragraph walls of text).
  Break multi-part details, options, and edge cases into headings, tables, or
  bulleted lists with clear lead-ins.
- Always use the Oxford (serial) comma (`a, b, and c`).
- Use plain ASCII punctuation and symbols instead of Unicode special characters.
  Avoid curly quotes, em and en dashes, ellipses, arrows, multiplication signs,
  box-drawing characters, and decorative symbols; use ASCII equivalents such as
  `"`, `'`, `-`, `--`, `...`, `->`, `x`, and ASCII diagrams instead. Exceptions
  are non-English text, English loanwords that keep their diacritics (such as
  "protégé"), and verbatim quotes of external text or UI literals.
- Enforce clear tense boundaries:
  - Maintained docs, READMEs, and code comments describe **current** behavior
    in present tense. Do not narrate prior code states, how the code evolved, or
    investigation chronology (concrete upgrade or migration steps and factual
    provenance such as version pins or submission dates remain valid where they
    help readers).
  - Commit messages and PR descriptions state the prior bug or limitation in
    **past tense** and the new behavior or fix in **present tense**. Never
    describe both the old broken state and the new state in present tense.

### Target writing style examples

- Avoid: "Explicit configuration of the selected ingress/inference settings
  does not invalidate existing saved wallet credentials or rerun native
  startup/bootstrap validation."
  Prefer: "Changing ingress or inference settings preserves wallet credentials
  and skips setup."
- Avoid: "Process-local inert values satisfy unused ingress/inference
  interpolation without mutating actual operator files or running the affected
  operation."
  Prefer: "Maintenance commands substitute placeholder values for unused ingress
  and inference variables in memory, leaving `.env` and running containers
  unchanged."
- Avoid: "Ordinary serving schedules independent refill opportunities per group;
  explicit bootstrap retains prompt allocation of its captured claims."
  Prefer: "During normal operation, each wallet group schedules refills
  independently, while bootstrap funds its initial wallet immediately."
