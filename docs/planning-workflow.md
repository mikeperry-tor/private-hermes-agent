# Planning workflow

Use this workflow alongside [AGENTS.md](../AGENTS.md) when planning and
executing substantial staged work. Feature plans and acceptance criteria live
under `docs/plans/`; durable operating contracts live in the top-level guides
under `docs/`.

Write a plan when the user asks for one or when multi-step work needs explicit
design decisions, commit boundaries, and acceptance criteria. Small changes,
including routine documentation edits, need neither a plan nor an independent
review.

## Define and review the approach

Before starting substantial planned work, record the working branch, starting
commit, and plan path, then commit the plan locally before implementing it. (If
an up-to-date plan is already committed, do not duplicate it.)

A complete plan states:

- **Intent and scope:** User goals, current behavior, intended behavior, and
  explicit deferrals. Keep observed facts separate from proposals and open
  assumptions.
- **Preserved boundaries:** Accepted trust boundaries and operator workflows to
  keep intact. For external integrations, cite the pinned image or source
  commit and its documented contract rather than assuming a reference checkout
  matches.
- **Simplest design:** Justify any new service, state transition, persistent
  file, configuration option, or abstraction against a concrete requirement. Do
  not build a framework for hypothetical future integrations.
- **Implementation phases:** Ordered phases with stable identifiers, consumers
  to update, focused acceptance checks, and documentation updates. Do not split
  phases merely to inflate commit or review counts.
- **Review gates:** Independent design review before implementation, final
  combined review at completion, and intermediate gates where architectural or
  security boundaries change, stating what evidence each gate requires.
- **Engine coverage:** Both Docker and rootless Podman impacts, shared choices,
  concrete engine exceptions, and required native tests (see
  [rootless Podman](architecture.md#rootless-podman) and
  [qualification and maintenance](development.md#qualification-and-maintenance)).
  Identical Compose models do not prove identical runtime behavior.
- **Gaps and authority limits:** Missing coverage, unresolved decisions, and
  any live network exposure, financial action, or destructive step outside
  current task authorization.

Check active and deferred plans under `docs/plans/` for shared-interface
conflicts and reconcile them so superseded names, topologies, or tools are not
reintroduced. For this prerelease stack, do not add legacy migration machinery
unless explicitly requested; preserve current-format state and retry-safe
initialization.

Obtain independent design review before substantive implementation, resolve
material findings before building on them, and re-review if design changes
invalidate earlier conclusions.

## Independent review

Each independent audit or review must run in a newly spawned, read-only
subagent with a fresh conversation and no inherited history (`fork_turns="none"`
where supported). Neither self-review by the implementer nor reusing an earlier
review conversation qualifies.

Provide the reviewer a self-contained brief containing:

- User intent, constraints, and scope.
- Starting commit and the exact reviewed commit SHA or file snapshot (including
  untracked files).
- Relevant plans, guides, validation evidence, and prior findings.

Ask the reviewer to inspect the codebase directly, trace consumers and failure
paths, check unchanged high-risk code, and challenge unnecessary complexity as
well as correctness and security. Reviewers must not edit code they review.

- New hardening must address a real threat within the agreed trust model.
- Reviewer suggestions are proposals, not automatic scope expansion or
  authorization for extra services, frameworks, spending, or publication.
- One review may cover both a phase and a gate (or the final phase and combined
  completion) when the brief explicitly covers both. There is no fixed reviewer
  count and no need to re-review an unchanged snapshot.
- If independent review is unavailable, disclose that gap and continue other
  useful work without claiming the gate passed.

## Implement, commit, and validate

Commit coherent work during development and at phase boundaries, staging only
named intended files. `AGENTS.md` grants standing authorization for local
development commits. Mark incomplete checkpoints honestly and never report them
as completed phases.

Include consumer updates, focused checks, and maintained guide edits alongside
code changes rather than deferring them. Keep helpers small and explicit; do
not turn test execution or evidence collection into a separate orchestration or
recovery framework.

Validate behavior with focused tests and controlled fixtures:

- Cover both Docker and rootless Podman for runtime changes and record engine,
  Compose provider, platform, and filesystem limits. Missing native coverage is
  never a pass.
- Reuse still-valid evidence across unchanged components; documentation-only
  changes do not need runtime suites.
- Security changes require both allowed-path and forbidden-path tests, plus
  failure and restart behavior.
- Keep test fixtures isolated from operator state and secrets, serialize tests
  that share fixed subnets, and avoid arbitrary resource limits or timeouts.

Record phase results, review findings, dispositions, and open work inside the
plan, keeping raw logs and private reports out of Git. Update maintained guides
in place with current contracts, qualification status, and limits—never append
phase/gate codes, approval logs, or dated investigation narratives to them.

## Resolve findings and finish

Fix material defects before starting dependent work or claiming completion;
deferring a material defect does not satisfy its acceptance criterion. Evaluate
simplification suggestions on merit and record why any recommendation is
rejected or deferred.

Commit focused fixes directly without a separate review ceremony for trivial
edits. When a fix invalidates prior evidence, rerun the affected checks and
re-review with a fresh subagent.

Before finishing, run an independent review of the combined change (including
fixes, unchanged boundaries, maintained guides, and dependent plans). Report
implementation, validation, and review status distinctly.

After final review acceptance and resolution of material findings, remove the
completed plan in the completion commit or a focused cleanup commit (unless the
user asks to retain it as a reference):

1. Verify that maintained guides hold all lasting operating contracts,
   qualification status, and limitations without execution chronology or
   retired phase codes.
2. Update inbound links and dependent plans to point to those guides.
3. Delete the plan file—Git history preserves it, so do not create an archive
   copy.

Keep genuinely active and deferred plans explicit with a concrete next action,
and do not create extra plans or guides for incidental ideas. Never rewrite
history, push, merge, publish, enroll Funnel, spend funds, or destroy private
state without explicit authorization.

At handoff, summarize what changed, the committed revision or uncommitted
state, plan status, validation and review results, and material limitations or
next steps.
