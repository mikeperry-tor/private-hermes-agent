# Hermes patch reorganization and upstream preparation

## Review corrections in progress

The wrapper correction branch is `hermes-v0.23.3-review`, starting at
`500515c`. The release and submission baselines are listed below. The
correction keeps the executor, Tor, Teep, WebApp ingress and wallet boundaries.
PR5 and interactive content remain deferred.

1. **Managed configuration.** Keep administrator-owned dotenv values effective
   during bootstrap and single-profile reload, including when live operations
   read the active backend concurrently. Preserve ordinary profile reload when
   there is no managed claim. Test the shared prerequisite upstream and test
   native reload in the built serving image with disposable state.
2. **Native topics.** Verify browser discovery and routing recover in one
   executor environment, with independent dependency checks and documented
   stock fallback. Enforce the stated SSH forwarding policy in PR2. Clarify
   PR3 gateway coverage. Preserve permitted deferred tools in PR4 background
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

Use **only the `upstream-pr/*` branches listed below** for PR1–PR4. Each
row is one PR. The `stack-patches/v0.23.3/*` refs preserve the source history
of the stack's pinned replay. See [v0.23.3 build provenance](#v0233-build-provenance).

Publish both ref namespaces to the `fork` remote before using the GitHub
branch and commit links below. The local working clone is
`upstream_work/hermes-agent/`, and submission drafts live under
`upstream_work/submissions/`. [Fork repository](https://github.com/mikeperry-tor/hermes-agent)

The submission branches are based on upstream `origin/main` at
`2de9f51b8008a7d49a49221c184f2f11cbfc4af1`. Their commits use
`Mike Perry <mikeperry-git@untrusted.systems>`.

| PR | Submission branch | Head | Validation |
| --- | --- | --- | --- |
| PR1 | [`upstream-pr/executor-desktop-browser`](https://github.com/mikeperry-tor/hermes-agent/tree/upstream-pr/executor-desktop-browser) | `3b02fb7268f45ea5027102829e1f0b95718a15b7` | Reconciles upstream pinned vault channels and executor ownership. 78 focused vault/managed desktop tests passed |
| PR2 | [`upstream-pr/executor-terminals`](https://github.com/mikeperry-tor/hermes-agent/tree/upstream-pr/executor-terminals) | `f616392b522872342b03ed5be3a28f46f2a54df7` | 89 focused native tests passed |
| PR3 | [`upstream-pr/url-reference-fetching`](https://github.com/mikeperry-tor/hermes-agent/tree/upstream-pr/url-reference-fetching) | `22eb62cb37a0d612cb679f9733c1e868b7dad982` | 67 focused native tests passed |
| PR4 | [`upstream-pr/deployment-restrictions`](https://github.com/mikeperry-tor/hermes-agent/tree/upstream-pr/deployment-restrictions) | `8f37dcb7916fbbf7936f590aea16405e27b47674` | 83 focused native tests passed |

PR5 remains deferred. Its reserved ref, `upstream-pr/webapp-content-privacy`,
contains only the base commit.

## 2. Upstream submission and merge-order checklist

1. Recheck the submission branches against the target `origin/main`. Open
   PR1 first. PR1–PR4 share `66652468b`. After PR1 merges, rebase the other
   branches so the shared commit can drop by patch identity.
2. Reconcile known adjacency points:
   - `website/docs/user-guide/managed-scope.md` (strict-reader paragraph and
     later additions),
   - `website/docs/user-guide/configuration.md` (independent key blocks),
   - `tools/browser_use_cli.py` (PR1 executor helpers plus PR4's shared
     `tool_refusal` gate),
   - `tools/mcp_tool_agent.py` (`restore_agent_tool_prefix`: keep upstream
     `_refresh_name_dependent_defs` and the managed `permitted` filter).
3. Apply the [five-package boundaries](#3-original-design-and-pr-scope) exactly;
   do not merge PR1's mechanism/policy residue wholesale or copy a production
   patch into a candidate.
4. Re-run the affected checks from the maintained workflow after any rebase.
5. After an upstream release ships PR1–PR4, remove the retired production
   patches and helpers together with the tests upstream now owns. PR5 and the
   deferred interactive-content work remain downstream until separately agreed.

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
| PR1 | Keep desktop/browser automation on the selected executor | Remote dependency diagnostics, CUA transport/permission binding, harness execution and recovery, work-sync correctness, configurable Chromium sandbox policy, `terminal.ssh_config`, managed `bot_desktop.executor_only` and probe budgets |
| PR2 | Executor-backed WebApp terminals | Native PTY reuse, exact cwd, cancellable/acknowledged startup, optional `webapp.executor_ssh_config` |
| PR3 | Selectable URL-reference fetching | `context_references.fetch_urls`; preserve other reference expansion and renderer policy |
| PR4 | Deployment-owned tool restrictions | Managed `tools.disabled` across discovery/dispatch, producing-policy persistence, prompt/worker refresh |
| PR5 | Webapp external-content protection | Gateway-retrieved public raster, origin consent, CSP, inert private previews; interactive media deferred to part 2 |

Boundaries and exclusions remain those in the working plan: no new services,
generic policy/CQRS frameworks, legacy aliasing or upstream publication; no
tenant-isolation claim; no funded-wallet or Funnel enrollment action; keep
`reference_repos/` read-only.

## 4. Execution and qualification record

### v0.23.3 build provenance

The `stack-patches/v0.23.3/*` refs preserve the release-based source history.
The stack's tracked v0.23.3 patch was exported from the combined replay below.
For a later release, use the
[candidate patch update workflow](../update-workflow.md#rebuild-the-candidate-patch-for-a-new-release).

| Branch | Head | Commits | Scope | Status |
| --- | --- | --- | --- | --- |
| `stack-patches/v0.23.3/executor-desktop-browser` (PR1) | `53043aeb9d0dc1f90528504e4b88c66bb8bb6398` | 10 | Desktop/browser execution placement, SSH config, sandbox launch policy | Rebased, qualified, `G-UPSTREAM` PASS |
| `stack-patches/v0.23.3/executor-terminals` (PR2) | `f7f0b244545b2943a58b8f915c14066463262cec` | 4 | Executor-backed WebApp terminals, cancellable startup | Rebased, qualified, `G-UPSTREAM` PASS |
| `stack-patches/v0.23.3/url-reference-fetching` (PR3) | `50ab0a4cfe9dc08f85b62ed5991d10f3bc39cec1` | 2 | Selectable inline URL context fetching | Rebased, qualified, `G-UPSTREAM` PASS |
| `stack-patches/v0.23.3/deployment-restrictions` (PR4) | `7495b47bc25f8b8ac8cfb8c939ffd6c5eec3fa35` | 4 | Managed `tools.disabled` ceiling and prompt/worker policy | Rebased, qualified, `G-UPSTREAM` PASS |
| `stack-patches/v0.23.3/webapp-content-privacy` (PR5) | `caafe5389ae585ef77387a962aee05b1bcf17029` (base only) | 0 | Webapp external-content ceiling and gateway raster retrieval | Deferred design; not implemented |

- Base for the release references: Hermes v0.23.3 `caafe5389ae585ef77387a962aee05b1bcf17029`.
- Shared first commit (PR1–PR4): `15de33f3af9d2fc2e63f05abdade39b1750bb038`
  (`fix(config): fail closed on invalid managed configuration when strict`),
  including the contributor-email mapping.
- Combined four-branch replay: `stack-patches/v0.23.3/combined`
  [`087222ccf6cbd04ac89096bab4182e05e2af6b0f`](https://github.com/mikeperry-tor/hermes-agent/commit/087222ccf6cbd04ac89096bab4182e05e2af6b0f) (17 commits).
- Wrapper branch `hermes-upstreaming` (squashed on top of `origin/main`;
  `cf27eab..a9f24a0`).
- Wrapper baseline at completion of this preparation: `v0.23.2`, source
  `ae2a81ccc00e9b7c06301523e5bb09608397149c`, digest
  `sha256:d6746a084e9341baada483e3d6210444d3c1aeb7c130f0915150065fb2851459`.
  Current packaged evidence is in the [qualification guide](../development.md#packaged-hermes-qualification).

Release-reference qualification (Linux ARM64 Docker): each implemented branch
and the combined replay pass docs-drift, contributor-email, 47 guard tests and
all 22 `scripts/check` checks; every intermediate commit is `git show --check`
clean and passes its changed tests. Branch suites: PR1 424 passed (13 skipped),
PR2 114, PR3 75, PR4 965, combined 1,554 (13 skipped), plus managed-policy
`test_doctor.py` checks. Combined Webapp build and Vitest: 221 passed (4
skipped). Live POSIX SSH executor fixtures pass for PR1 and PR2.

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
