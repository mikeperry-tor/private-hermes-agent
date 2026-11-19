# Planning workflow

This is maintained guidance for Private Hermes, used with
[AGENTS.md](../AGENTS.md). Feature designs and acceptance criteria belong in
`docs/plans/`; operating instructions belong in the relevant maintained guides.
This workflow does not select a new architecture or authorize unrelated work.

Use a plan when requested or when substantial staged work needs explicit design
decisions, commit boundaries and acceptance criteria. Small changes, including
ordinary documentation edits, need neither a ceremonial plan nor independent
review. Scale the process to the actual change.

## Define and review the approach

Before substantive planned implementation, identify the working branch, starting
commit and plan path. Create or update the plan and commit it locally before
implementing it. An already committed, still-current plan needs no duplicate
commit. Preserve unrelated workspace changes.

A useful plan states:

- User intent, scope, current behavior, intended behavior and explicit deferrals.
  Separate observed facts from proposals and unresolved assumptions.
- Accepted trust boundaries and operator workflows to preserve. For affected
  integrations, identify the relevant image/source revision and actual component
  contract, not merely the presence of a reference checkout.
- The simplest proposed approach. Justify added services, state transitions,
  persistent records, configuration options and abstractions against concrete
  needs. Do not add a framework to accommodate hypothetical future integrations.
- Ordered, coherent implementation phases with stable identifiers, affected
  consumers, focused acceptance checks and operating-documentation updates.
  Do not create phases solely to satisfy a commit or review count.
- Independent design and final combined review gates for substantive work, plus
  intermediate gates where meaningful architectural or security boundaries
  change. Specify what each gate establishes and the evidence it needs.
- Missing evidence, remaining decisions and any live exposure, financial or
  destructive operations outside current task authorization.
- Docker and rootless Podman consumers, shared implementation choices, concrete
  engine exceptions and affected native checks on each engine. Reuse the
  [engine guidance](architecture.md#rootless-podman) and
  [qualification workflow](development.md#qualification-and-maintenance); do not
  assume identical Compose models prove identical runtime behavior.

Check relevant active/deferred plans for shared-interface conflicts. Reconcile
affected requirements with the change; do not silently restore superseded names,
topologies or tooling. No legacy compatibility or migration machinery is needed
for this prerelease stack unless the user explicitly requests it. Preserve
current-format state and safe initialization/retry behavior.

Obtain independent design review before substantive implementation. Resolve
material findings before building on affected decisions. Commit material design
changes and review them again when they invalidate earlier conclusions.

## Independent review means a fresh subagent

Start each independent audit/review with a newly spawned, read-only subagent in a
fresh conversation, with no prior turns or inherited history. Use
`fork_turns="none"` when supported. Neither an implementer's self-review nor reuse
of a previous review conversation counts as a new independent review.

Give the reviewer a self-contained brief containing user intent, constraints,
scope, baseline and exact reviewed SHA or identified snapshot including new files,
relevant plans/guides, validation evidence, and earlier findings when applicable.
The reviewer should inspect the repository independently, trace affected
consumers and failure paths, and examine relevant unchanged high-risk code.
Reviewers must not author the changes they review.

Ask reviewers to challenge unnecessary complexity as well as correctness and
security. New hardening must address a concrete threat within the agreed trust
model. A recommendation does not itself authorize scope expansion, extra
services, migrations or a new framework. Delegation grants no additional access,
spending or publication authority.

Use reviews for meaningful phase commits, named gates and the final combined
change. One review can cover a phase and a gate, or a final phase and completion,
when its brief explicitly covers both scopes. There is no fixed reviewer count
and no requirement to review an unchanged snapshot repeatedly. If independent
review is unavailable, disclose it and perform useful remaining work without
claiming the missing gate passed.

## Implement, commit and validate

Commit coherent work during development and at phase boundaries, including
completed changes. Local development commits have standing authorization under
AGENTS.md; do not wait for separate commit requests. Stage only named intended
files. Incomplete checkpoints must be identified honestly and cannot be reported
as completed phases or evidence that acceptance criteria passed.

Include affected consumers, focused checks and relevant guide updates with their
implementation. Use native component behavior and straightforward helpers where
appropriate. Do not turn plan execution or evidence collection into an additional
orchestration, receipt or recovery system.

Validate changed behavior using existing focused checks and controlled fixtures.
For affected runtime contracts, cover both supported engines and record actual
engine, Compose provider, platform and filesystem limits where relevant. Missing
native coverage is not a pass. Reuse unchanged evidence; documentation-only work
does not require runtime suites or a new engine experiment.
Security claims require allowed and forbidden path evidence, with failure and
restart coverage where relevant. Keep fixtures separate from production state
and secrets; serialize checks sharing fixed networks/runtime state. Do not add
arbitrary resource limits or deadlines to force a test or workflow to finish.

Record phase/review evidence, findings, dispositions and remaining work in the
plan. Keep generated reports and private logs outside tracked documentation.
Maintained guides describe current contracts, repository status, qualification
scope and limitations in place. Do not append phase/gate codes, approval histories,
dated probe narratives, cleanup reports or superseding updates to them. Preserve
useful evidence as a concise current qualification statement, not an execution
journal. A retained plan is not a substitute for operator documentation.

## Resolve findings and finish

Resolve material defects before dependent work or completion. Consider
simplifications, but assess their scope and value rather than treating every
suggestion as mandatory. Record reasons for rejecting recommendations. Deferring
a material defect does not satisfy the affected acceptance criterion.

Commit focused corrections. Use ordinary correction commits or fixup commits as
appropriate; do not require a separate review ceremony for every trivial fixup.
Re-review affected decisions or behavior when corrections invalidate prior
evidence, using a fresh subagent. Reuse still-valid evidence and rerun affected
checks; broaden testing only for changed inputs, failures or unresolved concerns.

At completion, independently review the resulting combined change, including
corrections and relevant unchanged contracts. Verify acceptance criteria, current
guides and affected plan consistency. Distinguish implementation, validation and
review completion; unavailable checks are missing coverage, not passes.

After final independent review acceptance and resolution of material findings,
remove the completed plan in the completion commit or a focused cleanup commit,
unless the user explicitly requests that it remain as a reference.
Before removal, ensure maintained guides contain the lasting operating contracts,
current qualification scope and remaining limitations without execution chronology
or retired phase/gate codes. Update inbound links and dependent plans to refer
to those guides. Git history preserves the
plan and detailed historical evidence; do not create an archive copy. Do not
remove a plan merely because implementation is finished while required review
or acceptance remains pending. Keep active and genuinely deferred plans explicit
with a concrete next action. Do not create extra plans or guides merely to record
incidental improvement ideas.

Do not rewrite existing history, push, merge or publish without authorization.
Plan execution does not independently authorize live Funnel enrollment, funded
operations or destruction of private state. Existing task authorization remains
valid; do not repeatedly seek approval for already authorized work.

At handoff, report what changed, the committed revision or uncommitted snapshot,
plan status, review and validation evidence, and material limitations or next
steps. Keep the handoff proportional to the task.
