# Planning workflow

Use this workflow alongside [AGENTS.md](../AGENTS.md) when planning and
executing substantial staged work. Feature plans and acceptance criteria live
under `docs/plans/`; durable operating contracts live in the top-level guides
under `docs/`.

Write a plan when the user asks for one, when continuing an existing plan, or
when staged work genuinely spans multiple dependent phases with distinct design
decisions and acceptance gates. Standalone non-trivial changes and substantive
documentation updates still follow
[independent subagent review](../AGENTS.md#independent-subagent-review) without
requiring a plan file; trivial edits (such as small documentation tweaks or
typos) need neither a plan nor an independent review.

## Define and review the approach

Before starting substantial planned work, record the working branch, starting
commit, and plan path, then create or update the plan and commit it locally
before implementing it. (If an up-to-date plan is already committed, do not
duplicate it.)

A complete plan states:

- **Intent and scope:** User goals, current behavior, intended behavior, and
  named deferrals. Keep observed facts separate from proposals and open
  assumptions.
- **Preserved boundaries:** Accepted trust boundaries and operator workflows to
  keep intact. For integrated components, cite the pinned image or source commit
  and verify its actual contract rather than assuming a reference checkout
  matches.
- **Simplest design:** Justify any new service, state transition, persistent
  record, configuration option, or abstraction against a concrete requirement.
  Do not build a framework for hypothetical future integrations.
- **Implementation phases:** Ordered phases with stable identifiers, consumers
  to update, focused acceptance checks, and documentation updates. Do not split
  phases merely to inflate commit or review counts.
- **Review gates:** Independent design review before implementation, final
  combined review at completion, and intermediate gates where architectural or
  security boundaries change, stating what each gate establishes and the
  evidence it requires.
- **Engine coverage:** Both Docker and rootless Podman impacts, shared choices,
  concrete engine exceptions, and required engine runtime tests (see
  [rootless Podman](architecture.md#rootless-podman) and
  [qualification and maintenance](development.md#qualification-and-maintenance)).
  Identical Compose models do not prove identical runtime behavior.
- **Gaps and authority limits:** Missing coverage, unresolved decisions, and
  any live network exposure, financial action, or destructive step outside
  current task authorization.

Check active and deferred plans under `docs/plans/` for shared-interface
conflicts and reconcile them so superseded names, topologies, or tools are not
reintroduced. Follow
[deployed stack compatibility and upgrades](../AGENTS.md#deployed-stack-compatibility-and-upgrades):
preserve supported deployments and retry-safe initialization using focused
compatibility reads or migrations when needed, without building speculative
compatibility frameworks.

Obtain independent design review before substantive implementation, resolve
material findings before building on them, and commit material plan revisions
before re-reviewing when design changes invalidate earlier conclusions.

## Independent review

Follow [independent subagent review](../AGENTS.md#independent-subagent-review)
and [review method and findings](../AGENTS.md#review-method-and-findings) in
`AGENTS.md`. Use independent subagent reviews for design review, meaningful
phase commits, named gates, and the final combined change.

Provide each reviewer access to the checkout and Git history plus a
self-contained brief containing:

- User intent, constraints, and scope.
- Starting commit and the exact reviewed commit SHA or file snapshot (including
  new files).
- Plans, owning guides, validation evidence, known gaps, and prior findings.

Keep plan-review boundaries clear:

- New hardening must address a real threat within the agreed trust model.
- Reviewer suggestions are proposals, not automatic scope expansion or
  authorization for extra services, migrations, frameworks, spending, or
  publication. Delegation grants no additional access, spending, or publication
  authority.
- One review may cover both a phase and a gate (or the final phase and combined
  completion) when the brief explicitly covers both. There is no fixed reviewer
  count and no need to re-review an unchanged snapshot.
- If independent review is unavailable, disclose that gap and continue other
  useful work without claiming the gate passed.

## Implement, commit, and validate

Commit coherent work during development and at phase boundaries, staging only
named intended files. `AGENTS.md` grants standing authorization for local
development commits. Mark incomplete checkpoints honestly and never report them
as completed phases or evidence that acceptance criteria passed.

Include consumer updates, focused checks, and maintained guide edits alongside
code changes rather than deferring them. Keep helpers small and explicit; do
not turn plan or test execution or evidence collection into a separate
orchestration or recovery framework.

Validate behavior with focused tests and controlled fixtures:

- Cover both Docker and rootless Podman for runtime changes and record engine,
  Compose provider, platform, and filesystem limits. Unavailable checks and
  missing engine coverage are missing coverage, never passes.
- Reuse still-valid evidence across unchanged components; documentation-only
  changes do not need runtime suites.
- Security changes require both allowed-path and forbidden-path tests, plus
  failure and restart behavior.
- Keep test fixtures isolated from operator state and secrets, serialize tests
  that share fixed networks or runtime state, and avoid arbitrary resource
  limits or work deadlines.

Record phase results, review findings, dispositions, and open work inside the
plan, keeping raw logs and private reports out of Git. Update maintained guides
in place with current contracts, qualification status, and limits; never append
phase or gate codes, approval logs, or dated investigation narratives to them.
A retained plan is never a substitute for operator or maintained documentation.

## Resolve findings and finish

Fix material defects before starting dependent work or claiming completion;
deferring a material defect does not satisfy its acceptance criterion. Evaluate
simplification suggestions on merit and record why any recommendation is
rejected or deferred.

Use standalone commits or fixup commits as appropriate, without a separate
review ceremony for trivial edits. When a fix invalidates prior evidence, rerun
invalidated checks and re-review with a fresh subagent.

Before finishing, commit pending changes (or include uncommitted edits and new
files alongside the diff) and run an independent whole-changeset review over
the **net combined diff from the starting baseline (`git diff <base>..HEAD`) as
a single unit**. Reviewing the net diff as one unit surfaces cross-file defects
and simplification opportunities that intermediate fixup commits can obscure.

In that final review, verify:

- The plan's acceptance criteria, unchanged boundaries, and prior findings for
  pattern sweeping across the branch.
- Maintained guides for accuracy and [writing style](../AGENTS.md#writing-style)
  compliance, plus consistency with dependent plans.

If material defects or compelling simplifications emerge, fix them, rerun
invalidated checks, and repeat the whole-changeset review with a fresh subagent
until a clean pass finds no remaining merge-blocking issues. Report
implementation, validation, and review status distinctly.

Do not remove a plan merely because implementation is finished while required
review or acceptance remains pending. After a clean whole-changeset review and
satisfaction of acceptance criteria, remove the completed plan in the
completion commit or a focused cleanup commit (unless the user asks to retain it
as a reference, in which case keep it marked as a reference):

1. Verify that maintained guides hold all lasting operating contracts,
   qualification status, and limitations (matching
   [writing style](../AGENTS.md#writing-style)) without execution chronology or
   retired phase or gate codes.
2. Update inbound links and dependent plans to point to those guides, and check
   local links and `git diff --check`.
3. Delete the plan file. Git history preserves it, so do not create an archive
   copy.
4. If the cleanup commit introduces substantive documentation or code changes,
   run a fresh review over `git diff <base>..HEAD` and resolve any findings
   until clean.

Keep genuinely active and deferred plans clear with a concrete next action, and
do not create extra plans or guides for incidental ideas. Never rewrite
history, push, merge, publish, enroll Funnel, perform funded wallet operations,
or destroy private state without task authorization. Existing task
authorization remains valid; do not repeatedly ask for approval on already
authorized work.

At handoff, keep the summary proportional to the task and report what changed,
the committed revision or uncommitted state, plan status, validation and review
results, and material limitations or next steps.
