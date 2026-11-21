# Hermes patch reorganization and upstream preparation

## Submission history cleanup

On wrapper branch `upstream-test-fixes`, start from `6d4c5b0` and the active
heads in the submission table. Preserve those upstream heads under
`refs/qualification/pre-history-cleanup/` before updating the local
submission branches. Leave the v0.23.3 replay and packaged patch series intact.

Fold managed dotenv helper corrections into the PR1 dotenv commit, Doctor
port corrections into PR2b, harness readiness and vault revalidation into
PR3 executor integration, and the final acknowledgement protocol into PR4's
WebApp terminal feature. Keep independent changes reviewable, including the
PR2a bug fixes and PR6's dispatch, discovery, persistence and session work.
Include configuration examples with their owning changes or integrated
feature when the example documents several settings together.

Give every active submission commit a Conventional Commit subject and two
body paragraphs, with the prior problem in past tense and the change in
present tense. Wrap each message at 80 columns and preserve explanations.
Review the groupings and final histories independently. Verify exact tree
equality at every topic head and retained commit boundary. PR6 carries its
configuration example from the initial dispatch commit onward. Preserve
authorship, check the resulting review bases, and update all local drafts
and the submission table. Reuse existing runtime evidence for identical
trees and compare a focused Docker smoke run on the rewritten refs.

The rewrite reduces 32 commits to 20. Independent review and exact tree
checks confirm that all seven review diffs are unchanged. Every submission
message has two body paragraphs and a maximum line width of 80 columns.
The seven Linux ARM64 Docker smoke runs passed 301 tests as `hermes`
(UID/GID 10000). The original and rewritten refs, commit groups and logs
are recorded in `upstream_work/pr2-split-evidence/`.

## Full-suite follow-up

Wrapper branch `upstream-test-fixes` starts at `7f2cb77`. The upstream
baseline is `25a1302ea`. The Linux ARM64 Docker matrix ran all seven rebased
heads with the same locked test dependencies. Its baseline had 155 failures
shared by every branch. Follow up on the additional cases in PR1, PR3 and PR6.
PR2, PR4 and PR5 inherited their parent's failures. PR7 is the baseline.
Keep detailed logs in `upstream_work/docker-in-tree-rebase.vyigbP/`.

1. Trace each additional failure to the production contract and its test.
   Repair outdated doubles and expectations where the intended behavior is
   established. Correct production defects where the branch broke an existing
   behavior. Check the PR6 spool memory assertion and the transient gateway
   timeout against matched source and fixtures. Preserve managed authority,
   executor isolation and the existing browser and terminal boundaries.
2. Validate affected tests in Docker with the upstream runner. Put fixes in
   their owning topic commits or in focused standalone commits. Restack the
   local topic branches and verify the combined replay. Leave baseline-only
   failures and publication outside this work.
3. Compare each fix with the v0.23.3 replay. Carry production fixes when the
   packaged source shares the defect. Verify the regenerated candidate patch
   alongside retained deployment patches and qualify changed runtime behavior
   with the relevant Docker and rootless Podman fixtures. Update the submission
   heads, drafts and maintained qualification status. Obtain independent
   review of substantive design, implemented corrections and the combined
   result.

The PR1 dotenv and PR3 desktop, CDP and CUA fixtures exercise the current
interfaces. PR6 keeps the producing-policy stamp in the compression assertion
and captures spool backlog allocations after a warm-up replay, at the original
memory bound. The gateway timeout passed focused checks on the unchanged and
corrected PR6. The production browser runner captures the isolated launch
environment before loading the harness. That change is the only stack backport.

Focused Docker checks passed on PR1–PR6 (159, 19, 152, 50, 59 and 116 tests).
The combined submission passed 319 tests and the combined release passed 129.
The runner regression failed with the legacy v0.23.3 source and passed with the
backport. The complete patch series applied to the release pin. Docker Desktop
ARM64 passed `make browser-use-test` with the rebuilt image and real SSH
executor. Fresh independent design and combined review found no open defects.
Exact logs and heads are in `upstream_work/test-fix-evidence/`.

The same `make browser-use-test` passed on Debian 13.7 ARM64 with rootless
Podman 5.4.2 and Docker Compose 5.7.1 as the Compose provider. The run used
the committed wrapper snapshot `9f21502` and disposable state. It covered
real SSH browser actions, Chromium sandboxing, forbidden paths and harness
failure and recovery. The test project shut down after the run.

## Local review and qualification

The wrapper correction branch is `hermes-v0.23.3-review`, starting at
`500515c`. The release and submission baselines are listed below. The
correction keeps the executor, Tor, Teep, WebApp ingress and wallet boundaries.
PR7 and interactive content remain deferred.

1. **Managed configuration.** Keep administrator-owned dotenv values effective
   during bootstrap and single-profile reload, including when live operations
   read the active backend concurrently. Preserve ordinary profile reload when
   there is no managed claim. Test the shared prerequisite upstream and test
   native reload in the built serving image with disposable state.
2. **Native topics.** Verify browser discovery and routing recover in one
   executor environment, with independent dependency checks and documented
   stock fallback. Enforce the stated SSH forwarding policy in PR4. Clarify
   PR5 gateway coverage. Preserve permitted deferred tools in PR6 background
   review while retaining policy denial. Put behavioral tests and documentation
   with the owning changes.
3. **Wrapper parity.** Carry equivalent fixes in the exact v0.23.3 replay and
   regenerate the candidate patch. Preserve saved WebApp configuration and
   effective profile cwd in its original consumers while keeping the Code
   default. Restore deployment-specific desktop recovery guidance.
4. **Review and qualification.** Rebuild upstream histories around the shared
   prerequisite, standalone SSH fixes and focused browser and tool-policy
   topics. Replay across both bases, check artifact provenance and overlap with
   retained deployment patches, and run focused upstream and packaged checks.
   Qualify affected serving behavior with disposable Docker and rootless
   Podman fixtures, recording actual coverage. Obtain fresh independent design
   and final combined reviews, resolving findings and rechecking affected
   behavior. Update maintained guides and local submission drafts. Keep
   publication out of this work.

## 1. Branches to submit

The working clone is `upstream_work/hermes-agent/`. The submission drafts in
`upstream_work/submissions/` point to the local heads below. The target is
`NousResearch/hermes-agent`. The submission stack starts at upstream main
`25a1302eacb563c59eb3b7454c1a53f8c89f274c`. The author identity is
`Mike Perry <mikeperry-git@untrusted.systems>`.

| Topic | Draft | Submission branch | Head | Review base |
| --- | --- | --- | --- | --- |
| PR1 Managed configuration | `PR1-managed-config.md` | `fix/managed-config` | `9dce85bf45884700171a650517a331b292fc4643` | Upstream main |
| PR2a SSH workspace fixes | `PR2a-ssh-workspace-fixes.md` | `fix/ssh-workspace` | `b594345507d22654555b9b53576e3b6754de630b` | PR1 |
| PR2b Explicit OpenSSH configuration | `PR2b-ssh-client-config.md` | `feat/ssh-client-config` | `97146dc96c3107e879dc7577327c4e8ba234a838` | PR1 |
| PR3 Executor desktop and browser | `PR3-executor-desktop-browser.md` | `feat/executor-desktop-placement` | `f2797c54319528a86cc4617a22b6a2898c831f7a` | PR2b |
| PR4 WebApp executor terminals | `PR4-executor-terminals.md` | `feat/webapp-executor-terminals` | `1ad4c57a21fb7d3e10197e196161b950e26c7daf` | PR1 |
| PR5 URL reference fetching | `PR5-url-reference-fetching.md` | `feat/url-reference-fetching` | `2e50c43fe42b1f42aac04fa80f9fb6c8a9536a3a` | PR1 |
| PR6 Deployment tool restrictions | `PR6-deployment-restrictions.md` | `feat/managed-tool-denials` | `c2500766bc5d3d0d1fa4851502a6ab80f3da3e75` | PR1 |
| PR7 WebApp content privacy | `PR7-webapp-content-privacy.md` | `upstream-pr/webapp-content-privacy` | `25a1302eacb563c59eb3b7454c1a53f8c89f274c` | Deferred |

The original `upstream-pr/*` refs preserve the exact qualification heads.
The current submission refs add commented configuration examples, including
the SSH example in PR2b, and omit the unrelated spool allocation test from PR6.
The original combined PR2 and the superseded PR3 heads remain available
locally at `archive/ssh-executor-config`, `archive/executor-desktop-browser`
and `archive/executor-browser-placement`.
The test-only improvement remains available as `69c941b69` for a separate
submission. The historical combined qualification check is available at
`review/combined-submission` (`73a1e42fce5d77a21ac1ec9fc81b77864c95d2d1`).
PR7's reserved ref contains only the base commit. See the [fork repository](https://github.com/mikeperry-tor/hermes-agent)
and the [v0.23.3 release replay](#v0233-build-provenance).

PR2a and PR2b apply in either order. PR3's review diff is identical on
the updated PR2b base. Adding PR2a reproduces the combined desktop/browser
tree with the Doctor correction. The prepared Linux ARM64 Docker image ran
every changed Python test module plus related regressions as `hermes`
(UID/GID 10000). PR2a passed 19 tests. PR2b passed 268 with 20 skips and
three Doctor failures. The same Doctor module on the exact PR1 base
reproduced all three failures. The six new port regression cases passed.
PR3 passed 477 Python tests with one skip and six desktop Vitest
tests using its frozen dependency lockfile. The combined SSH and browser
tree, including the Doctor module, passed 590 Python tests with 21 skips
and the same three baseline failures. Exact-tip and baseline logs are in
`upstream_work/pr2-split-evidence/`.

PR2b makes Doctor probe the terminal's port when an explicit SSH file is
selected. Omission defaults to 22, and invalid configured values fail before
the probe. The v0.23.3 replay has the original mismatch, but supported
deployments always pass port 2222 through Compose and managed YAML and dotenv.
Both clients already use that port on the packaged source, so the correction
belongs in the upstream submission.

## 2. Upstream submission and merge-order checklist

1. Recheck the local heads against the target main before submission. Submit
   PR1 first. PR2a, PR2b and PR4–PR6 can then proceed independently. PR3 follows
   PR2b because it uses the SSH configuration helper. Include PR2a's archive
   fix before qualifying or shipping PR3 with live Chromium and SSH sync-back
   enabled. Transient profile entries can cause extraction to fail and block
   sync-back of ordinary state.
   For a squash merge, rebase each dependent branch from its listed review
   base onto the updated main so the prerequisite commits stay out of its diff.
2. Preserve both sides at shared paths. The combined submission replay resolves
   the strict-reader descriptions in `website/docs/user-guide/managed-scope.md`
   and joins PR3 executor routing with PR6's `tool_refusal` in
   `tools/browser_use_cli.py`. Preserve native
   `_refresh_name_dependent_defs` and the managed `permitted` filter in
   `tools/mcp_tool_agent.py` during future rebases.
3. Re-run the affected checks after each rebase, including a combined replay.
   Follow the upstream [contribution guide](https://github.com/NousResearch/hermes-agent/blob/main/CONTRIBUTING.md#pull-request-process)
   and [PR template](https://github.com/NousResearch/hermes-agent/blob/main/.github/PULL_REQUEST_TEMPLATE.md).
   Run `just test <paths>`, `just check` and relevant desktop workspace checks
   on the final base. Record the manual checks, platforms and skips. The earlier
   full Linux ARM64 Docker run failed on the pristine base as well, so compare
   any broad failures against the matching base and report the result.
   Keep wrapper-only deployment settings in the wrapper.
4. When an official release includes a topic, run its native regressions at the
   shipped source and rerun the affected packaged checks. Then drop the
   corresponding patch portion and any wrapper test that only repeats the
   native behavior. Keep verification of the wrapper's Tor, SSH, ingress,
   storage and privacy contracts.
5. Review open and merged PRs, issues and current source for overlap. Link an
   existing issue when it matches. Prefer direct submissions for PR1, PR2a and
   PR2b and a feature issue for PR4 when there is no match. PR5 can go direct, with
   issue text available if requested. Use the drafts' issue text to discuss
   scope with maintainers for PR3 and PR6. Assess any undisclosed security
   finding against [SECURITY.md](https://github.com/NousResearch/hermes-agent/blob/main/SECURITY.md#3-scope)
   before public discussion. Use `Fixes #…` only when the PR resolves the
   linked issue. Keep the drafts' local branch details and issue text out of
   the PR body when copying it to GitHub.

## 3. Original design and PR scope

The objective is to reduce downstream maintenance by separating reusable fixes
from Private Hermes deployment policy, while preserving the accepted boundaries:
separate agent/executor processes, mounts and network namespaces; transparent Tor
egress; exact SSH/Teep/MCP grants; executor-only browser and desktop placement;
fail-closed deployment policy; native PTY lifecycle; managed authentication and
host/origin checks; Chromium sandbox and human-control fencing; and preserved
current-format state, credentials and named volumes.

Production patch responsibilities (baseline inventory; the Dockerfile, build
verifier, executor dependency closure, Make targets, setup and ingress policy
also participate):

| Patch | Responsibility |
| --- | --- |
| 0001 | Desktop dependency probe diagnostics and shared discovery timeout budget |
| 0002 | SSH sync-back exclusion of unmapped live browser profile |
| 0003 | Disable automatic inline URL context expansion while preserving URL chips and other refs |
| 0004 | Deployment content/computer-use policy capture and server validation (`external_content.py`) |
| 0005 | Disabled desktop/preview tool enforcement across registry, inline dispatch, approval and background review |
| 0006 | SSH computer-use placement, dependency status, driver permission/transport and display RPC/socket (`computer_use.py`) |
| 0007 | Executor browser harness, launch/ownership lifecycle, strict named-tab setup and sandboxed launch (`browser_use.py`, `browser-session.py`) |
| 0008 | Webapp authenticated content/consent routes and public IPv4 raster retrieval (`external_content.py`, `public_images.py`) |
| 0009 | Webapp response CSP, trusted bootstrap headers and inert private previews (`browser_policy.py`) |
| 0010 | Webapp renderers, origin consent and image Save/Copy (`ui/private-content.tsx`) |
| 0011 | Operator terminal placement, async PTY preparation and truthful mode/cwd handling (`code_terminal.py`) |
| 0012 | SSH file-inspection missing-path (`ENOENT`/404) classification |
| 0013 | SSH pinned host-key client configuration (`-F` and strict known-hosts checks) |

Upstream package boundaries:

| Package | Purpose | Responsibilities |
| --- | --- | --- |
| PR1 | Preserve instance configuration policy while reading or reloading profile settings | Strict managed reads, validated snapshots, dotenv precedence and routed interpolation |
| PR2a | Preserve SSH workspace sync and missing-file behavior | Browser-profile sync exclusion and missing-path handling |
| PR2b | Let operators select explicit SSH client trust | `terminal.ssh_config`, shared across model SSH operations, workspace access, streams, and Doctor |
| PR3 | Keep desktop/browser automation on the selected executor | Remote dependency diagnostics, CUA transport/permission binding, harness recovery, configurable Chromium sandbox policy, managed `bot_desktop.executor_only` and probe budgets |
| PR4 | Executor-backed WebApp terminals | Native PTY reuse, exact cwd, cancellable/acknowledged startup, optional `webapp.executor_ssh_config` |
| PR5 | Selectable URL-reference fetching | `context_references.fetch_urls`; preserve other reference expansion and renderer policy |
| PR6 | Deployment-owned tool restrictions | Managed `tools.disabled` across discovery/dispatch, producing-policy persistence, prompt/worker refresh |
| PR7 | Webapp external-content protection | Gateway-retrieved public raster, origin consent, CSP, inert private previews; interactive media deferred to part 2 |

Boundaries and exclusions remain those in the working plan: no new services,
generic policy/CQRS frameworks, legacy aliasing or upstream publication; no
tenant-isolation claim; no funded-wallet or Funnel enrollment action; keep
`reference_repos/` read-only.

## 4. Execution and qualification record

### v0.23.3 build provenance

The `stack-patches/v0.23.3/*` refs preserve the release-based source history.
The counts are relative to the release base and include the shared managed
prerequisite. The release replay carries PR2a and PR2b on the PR3 branch.
The stack's tracked v0.23.3 patch was exported from the combined replay below.
For a later release, use the
[candidate patch update workflow](../update-workflow.md#rebuild-the-candidate-patch-for-a-new-release).

| Branch under `stack-patches/v0.23.3/` | Head | Commits | Scope |
| --- | --- | --- | --- |
| `managed-config` (PR1) | `32abdfde7c1968d4d8ebd6cd3e16a3d35e4b04d7` | 3 | Strict reader and dotenv authority |
| `executor-desktop-browser` (PR3) | `9606c0e2f313a15ebc6fe9f547f815cca3d102c7` | 14 | SSH fixes, desktop/browser placement and harness recovery |
| `executor-terminals` (PR4) | `4915d01748818b1d098caa0dbe586bf1ad4451f9` | 6 | Executor-backed WebApp terminals and pinned forwarding |
| `url-reference-fetching` (PR5) | `90a40b357b1c0ed9ba8cafae3fe8209373a098b4` | 5 | Selectable inline URL context fetching |
| `deployment-restrictions` (PR6) | `a414ff274857412d7d4b42b96596beb7b4cbde10` | 7 | Managed tool denial, prompt/worker policy and review |
| `webapp-content-privacy` (PR7) | `caafe5389ae585ef77387a962aee05b1bcf17029` | 0 | Deferred privacy candidate |

- Exact release base: Hermes v0.23.3 `caafe5389ae585ef77387a962aee05b1bcf17029`.
- Combined replay: `stack-patches/v0.23.3/combined`
  `553cd75ac4da1c4e9cef7479d1962a026c593cda` (28 commits).
- The pre-correction replay was `087222ccf6cbd04ac89096bab4182e05e2af6b0f`.
- Wrapper branch `hermes-upstreaming` (squashed on top of `origin/main`;
  `cf27eab..a9f24a0`).
- Wrapper baseline at completion of this preparation: `v0.23.2`, source
  `ae2a81ccc00e9b7c06301523e5bb09608397149c`, digest
  `sha256:d6746a084e9341baada483e3d6210444d3c1aeb7c130f0915150065fb2851459`.
  Current packaged evidence is in the [qualification guide](../development.md#packaged-hermes-qualification).

Pre-correction release qualification (Linux ARM64 Docker): each implemented branch
and the combined replay pass docs-drift, contributor-email, 47 guard tests and
all 22 `scripts/check` checks; every intermediate commit is `git show --check`
clean and passes its changed tests. The desktop/browser suite passed 424 tests
with 13 skipped, WebApp terminals passed 114, URL references passed 75, and
deployment restrictions passed 965. The combined suite passed 1,554 with 13
skipped, plus managed-policy `test_doctor.py` checks. The combined WebApp build
and Vitest passed 221 with four skipped. Live POSIX SSH fixtures passed for
desktop/browser and WebApp terminals.

### Local correction evidence

The combined submission and release replays merge their local topic refs.
Both resolve the shared managed-scope guide and browser dispatch hook.
The package matches the filtered release replay. The focused final native suites
each pass 252 tests with nine platform skips. Both replays pass all 22
`scripts/check` checks. The broader native suites before the last managed
interpolation and provenance fixes pass 1,795 tests on main and 1,763 on the
release, with 30 skipped and three Doctor failures that also reproduce on the
pristine bases. Focused final coverage includes managed bootstrap and read
recovery, routed template inputs and source ownership, and terminal admission
and receiver acknowledgement.

Docker Desktop ARM64 and Debian 13 rootless Podman ARM64 pass the affected
packaged tests. The managed-policy image build and URL/context/tool matrix use
the current release replay. Browser, desktop, and lean and desktop terminal
fixtures cover the unchanged executor and renderer code. Fresh independent
reviews cover the combined topics, managed scope, release parity and the
local branch handoff. Current operating limits are recorded in the
[qualification guide](../development.md#packaged-hermes-qualification).

The local submission branches and drafts are prepared. Submission and
qualification against the first official release carrying the accepted changes
remain open, along with PR7.

### Preparation baseline

The wrapper series was reorganized, integrated on `v0.23.2`, reviewed, and then
the four reusable candidates were extracted, folded into topical commits, rebased
onto the current upstream base, and independently reviewed. Corrections from the
review gates addressed: discovery probes summing past the registry `check_fn`
ceiling (one absolute budget shared with environment creation), a persistence
commit's forward import, a stock-sandbox browser-exec fallback for upstream
defaults, CUA lock ordering, Chromium argument/owner handling, and the rebase
merge in `tools/mcp_tool_agent.py`.

The preparation baseline carried production patches `0001`–`0013`. See the
[current patch inventory](../updates-and-plugins.md#downstream-responsibility-inventory)
for adoption status. The `v0.23.2` backports (`code_terminal.py` containment,
`0007` argument/recovery safety, `browser_use.py` per-key locking and probe
budgeting, and `0001`/`computer_use.py` probe budgeting) and the distinct
lean/desktop executor image tags (`private-hermes-executor-false:local` and
`private-hermes-executor-true:local`) were qualified natively on both Docker
Desktop ARM64 and Debian 13 rootless Podman ARM64 (`make check`,
`hermes_build.py`, `desktop_tools_smoke.py`, `desktop_startup_smoke.py`,
`launch_smoke.py`, `computer_use_smoke.py --desktop-only`,
`browser_use_smoke.py`, and both lean and desktop `webapp_smoke.py --terminal-only`,
plus `build_smoke.py` on Podman).
