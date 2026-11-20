# Hermes patch reorganization and upstream preparation

## Local review and qualification

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

The working clone is `upstream_work/hermes-agent/`. The submission drafts in
`upstream_work/submissions/` point to the local heads below. The target is
`NousResearch/hermes-agent`. The submission stack starts at upstream main
`2de9f51b8008a7d49a49221c184f2f11cbfc4af1`. The author identity is
`Mike Perry <mikeperry-git@untrusted.systems>`.

| Topic | Submission branch | Head | Review base |
| --- | --- | --- | --- |
| Managed configuration prerequisite | `upstream-pr/managed-config` | `204a29637c0379bba089342ec28e7ea61297a0aa` | Upstream main |
| Standalone SSH fixes | `upstream-pr/ssh-executor-fixes` | `a05f89f89e9bb1e8643af8462582fb0873c5a2b9` | Managed prerequisite |
| PR1 | `upstream-pr/executor-desktop-browser` | `38bcd749b7c22d373330b825d2c94c9ac9405282` | Standalone SSH fixes |
| PR2 | `upstream-pr/executor-terminals` | `6d57e1830c236526cb707201e61b10f61fd5f868` | Managed prerequisite |
| PR3 | `upstream-pr/url-reference-fetching` | `1dfbb588177f9e0b520dd3871a1ab2e587e3ab83` | Managed prerequisite |
| PR4 | `upstream-pr/deployment-restrictions` | `97b41fb9a554a0777456de80d0bb78379cc37eb7` | Managed prerequisite |

The local combined submission check uses `636551c657ae555dce78f0711da9c2ffe2f42c1b`.
The check is available at `review/combined-submission`.
PR5 remains deferred. Its reserved ref, `upstream-pr/webapp-content-privacy`,
contains only the base commit. See the [fork repository](https://github.com/mikeperry-tor/hermes-agent)
and the [v0.23.3 release replay](#v0233-build-provenance).

## 2. Upstream submission and merge-order checklist

1. Recheck the local heads against the target main before submission. Submit
   the managed configuration prerequisite first. PR2–PR4 can follow
   independently. Submit the SSH fixes before the desktop/browser topic.
   For a squash merge, rebase each dependent branch from its listed review
   base onto the updated main so the prerequisite commits stay out of its diff.
2. Preserve both sides at shared paths. The combined submission replay resolves
   the strict-reader descriptions in `website/docs/user-guide/managed-scope.md`
   and joins PR1 executor routing with PR4's `tool_refusal` in
   `tools/browser_use_cli.py`. Preserve native
   `_refresh_name_dependent_defs` and the managed `permitted` filter in
   `tools/mcp_tool_agent.py` during future rebases.
3. Re-run the affected checks after each rebase, including a combined replay.
   Keep wrapper-only deployment settings in the wrapper.
4. When an official release includes a topic, run its native regressions at the
   shipped source and rerun the affected packaged checks. Then drop the
   corresponding patch portion and any wrapper test that only repeats the
   native behavior. Keep verification of the wrapper's Tor, SSH, ingress,
   storage and privacy contracts.

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
| Managed configuration | Preserve instance configuration policy while reading or reloading profile settings | Strict managed reads, validated snapshots, dotenv precedence and routed interpolation |
| SSH | Keep native SSH transfers, workspace inspection and trust consistent | Browser-profile sync exclusion, missing-path handling and `terminal.ssh_config` |
| PR1 | Keep desktop/browser automation on the selected executor | Remote dependency diagnostics, CUA transport/permission binding, harness recovery, configurable Chromium sandbox policy, managed `bot_desktop.executor_only` and probe budgets |
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
The counts are relative to the release base and include the shared managed
prerequisite.
The stack's tracked v0.23.3 patch was exported from the combined replay below.
For a later release, use the
[candidate patch update workflow](../update-workflow.md#rebuild-the-candidate-patch-for-a-new-release).

| Branch under `stack-patches/v0.23.3/` | Head | Commits | Scope |
| --- | --- | --- | --- |
| `managed-config` | `32abdfde7c1968d4d8ebd6cd3e16a3d35e4b04d7` | 3 | Strict reader and dotenv authority |
| `executor-desktop-browser` (PR1) | `9d31642cb662c9d42eb655c699b48a0d85ecfb15` | 13 | SSH fixes, desktop/browser placement and harness recovery |
| `executor-terminals` (PR2) | `4915d01748818b1d098caa0dbe586bf1ad4451f9` | 6 | Executor-backed WebApp terminals and pinned forwarding |
| `url-reference-fetching` (PR3) | `90a40b357b1c0ed9ba8cafae3fe8209373a098b4` | 5 | Selectable inline URL context fetching |
| `deployment-restrictions` (PR4) | `a414ff274857412d7d4b42b96596beb7b4cbde10` | 7 | Managed tool denial, prompt/worker policy and review |
| `webapp-content-privacy` (PR5) | `caafe5389ae585ef77387a962aee05b1bcf17029` | 0 | Deferred privacy candidate |

- Exact release base: Hermes v0.23.3 `caafe5389ae585ef77387a962aee05b1bcf17029`.
- Combined replay: `stack-patches/v0.23.3/combined`
  `e1311d5cea7b2be762877a74f4755bff4608e92c` (26 commits).
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
clean and passes its changed tests. Branch suites: PR1 424 passed (13 skipped),
PR2 114, PR3 75, PR4 965, combined 1,554 (13 skipped), plus managed-policy
`test_doctor.py` checks. Combined Webapp build and Vitest: 221 passed (4
skipped). Live POSIX SSH executor fixtures pass for PR1 and PR2.

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
remain open, along with PR5.

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
