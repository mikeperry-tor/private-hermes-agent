# Hermes Upstream Preparation Plan

## Objective and status

Prepare the Private Hermes upstream candidate topics in `upstream_work/hermes-agent/`
for clean submission to `NousResearch/hermes-agent` (`origin`) under author
identity `Mike Perry <mikeperry-git@untrusted.systems>`.

- **Plan path:** `docs/plans/hermes-upstream-prep.md`
- **Wrapper branch and starting commit:** `executor-access-consistency_gem` at
  `d3fc3a5`
- **Current status:** Ready to start Phase 0 (this revised plan passed
  independent review before execution). All 13 prior local candidate branches
  are verified on `88a1c1f4b19d1bc2b9fe8db870dee9ba0803fad5` (2026-11-22), and
  the packaged v0.23.3 release replay is qualified at
  `1d3dec980055f3bbffaa15e5eabf7a998520d962`.
- **Target restructuring:** Reorganize submissions into **3 waves (11 active PRs
  and 1 deferred design)** using wave-numbered drafts (`W1-*.md`, `W2-*.md`,
  `W3-*.md`, `deferred-*.md`) instead of `PR[1-7]*.md`. Keep each security and
  isolation boundary whole in a single PR, and split commits cleanly and
  sequentially inside each PR so component maintainers can review their range or
  split off a tail cleanly if requested.
- **Engine and qualification scope:** Upstream native branch verification runs
  in offline Linux ARM64 Docker containers as UID 10000. Packaged Private
  Hermes runtime requalification on Docker Desktop, native Linux Docker, and
  rootless Podman is required only if Phase 2 or Phase 3 uncovers a v0.23.3
  runtime or security defect that also needs backporting into
  `components/hermes/patches/0001-upstream-candidates.patch`.
- **Hard constraints:**
  - Never weaken isolation boundaries, fail-closed checks, or existing wrapper
    security contracts (`AGENTS.md`).
  - Keep wrapper-only deployment settings in Private Hermes; keep upstream
    changes generic and independent of Private Hermes paths.
  - Do not push to `origin`, open GitHub PRs, or force-push `fork` without
    explicit user authorization.
  - Keep `reference_repos/` read-only. Never store secrets or live credentials
    in branches, drafts, or evidence logs.
  - Every modified branch must pass `scripts/check` (0 blocking findings),
    `git show --check` on every commit, Conventional Commits (80-column wrap,
    two-paragraph past-then-present body for substantial changes), and Docker
    native tests as UID 10000 with `--network none`.

## Agent handoff protocol

If an agent stops mid-plan (for example, due to usage limits), the next agent
must:

1. Read the [Execution checkpoint](#execution-checkpoint) table below and run
   `git -C upstream_work/hermes-agent for-each-ref --format='%(refname:short) %(objectname:short) %(subject)' refs/heads/fix/ refs/heads/feat/`
   along with `ls upstream_work/submissions/`.
2. Never redo branches already marked `Done` with matching SHAs and saved logs
   under `upstream_work/wave-rebase-evidence/`.
3. Update the checkpoint table and commit the plan update in the wrapper repo at
   the end of each completed phase (or after completing a major Wave 3 branch) so
   progress is persisted in Git before moving on.

### Execution checkpoint

Update this table as each phase and branch completes.

| Phase or item | Target branch | Target base | Current SHA | `scripts/check` | Docker tests | Draft renamed | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Phase 0: Pre-flight and fetch `origin/main` | `origin/main` | `origin/main` | `88a1c1f4b` (stale; remote `02afb7489` or newer) | n/a | n/a | n/a | Pending |
| `W1-1` Managed config | `fix/managed-config` | `MAIN_SHA` | `d4aa66920` (on `88a1c1f4b`) | Pending rebase | Pending rebase | Pending | Pending |
| `W1-2` SSH workspace fixes | `fix/ssh-workspace` | `MAIN_SHA` | `73a53241d` (on `88a1c1f4b`) | Pending rebase | Pending rebase | Pending | Pending |
| `W1-3` Desktop and browser fixes | `fix/executor-desktop-browser` | `MAIN_SHA` | `1f2eefc51` (on `88a1c1f4b`) | Pending rebase | Pending rebase | Pending | Pending |
| `W1-4` Literal SSH and OSC 7 `cwd` | `fix/terminal-ssh-cwd` | `MAIN_SHA` | `868773aa8` (on `88a1c1f4b`) | Pending rebase | Pending rebase | Pending | Pending |
| `W1-5` Speech output placement | `fix/tts-output-placement` | `MAIN_SHA` | `ecae8682a` (on `88a1c1f4b`) | Pending rebase | Pending rebase | Pending | Pending |
| `W2-1` Explicit SSH client config | `feat/ssh-client-config` | `W1-1` | `db7587772` (on `88a1c1f4b`) | Pending rebase | Pending rebase | Pending | Pending |
| `W2-2` URL reference opt-out | `feat/url-reference-fetching` | `W1-1` | `c3a6b8a0b` (on `88a1c1f4b`) | Pending rebase | Pending rebase | Pending | Pending |
| `W2-3` Managed tool denials | `feat/managed-tool-denials` | `W1-1` | `14e980021` (on `88a1c1f4b`) | Pending rebase | Pending rebase | Pending | Pending |
| `W3-1` Executor desktop and browser | `feat/executor-desktop-placement` | `W2-1` and `W1-3` | `24a750de0` (on `88a1c1f4b`) | Pending rebase | Pending rebase | Pending | Pending |
| `W3-2` Operator shells and terminals | `feat/webapp-executor-terminals` | `W1-1` and `W1-4` | `7ae5fd82c` (on `88a1c1f4b`) | Failing (1 ruff, 11 health) | Pending rebase | Pending | Pending |
| `W3-3` Managed SSH isolation (workspaces, skills, and cron) | `feat/ssh-executor-isolation` (consolidating `feat/ssh-project-workspaces`, `feat/ssh-skill-shell`, and `feat/ssh-cron-execution`) | `W1-1`, `W1-2`, and `W2-1` | `39cdc0ce2`, `0c67369ef`, and `c73e521b8` | Pending split and rebase | Pending rebase | Pending | Pending |
| Phase 4: Combined native replay, docs, and review | Temporary merge of `W1-1` through `W3-3` | `MAIN_SHA` | Pending | Pending | Pending | n/a | Pending |

## 1. Branches to submit

The working clone is `upstream_work/hermes-agent/`, the fork remote is `fork`
(`git@github.com:mikeperry-tor/hermes-agent.git`), and submission drafts live
under `upstream_work/submissions/`.

Wave 1 contains independent `main`-based fixes and the managed-config
foundation. Wave 2 contains standalone controls built on `W1-1` that operate on
existing Hermes features immediately without requiring Wave 3. Wave 3 contains
the three complete executor-isolation boundaries, each introducing its own
configuration keys alongside all consumers that enforce them.

| ID | Target draft (`upstream_work/submissions/`) | Legacy draft to replace | Local branch | Current head (`88a1c1f4b` base) | Review base | Current scope (`base..HEAD`) | Restructuring needed |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `W1-1` | `W1-1-managed-config.md` | `PR1-managed-config.md` | `fix/managed-config` | `d4aa66920ce76794a580a877b6e4383ffc94b72d` | `origin/main` | 2 commits, 18 files (+674 / -159) | Rebase only; keep 2 commits. Carries `contributors/emails/mikeperry-git@untrusted.systems`. |
| `W1-2` | `W1-2-ssh-workspace-fixes.md` | `PR2a-ssh-workspace-fixes.md` | `fix/ssh-workspace` | `73a53241def871e21e758dfc8abc448c6b848b7f` | `origin/main` | 8 commits, 53 files (+3,250 / -314) | Rebase only; keep 8 linear commits (or fold `73a53241d` into `eb93959ce` and `23be2f3b5`) and refresh draft. |
| `W1-3` | `W1-3-executor-desktop-browser-fixes.md` | `PR3a-executor-desktop-browser-fixes.md` | `fix/executor-desktop-browser` | `1f2eefc51cddeec8f7d1c02de4e46a25f9f40b65` | `origin/main` | 3 commits, 29 files (+1,421 / -242) | Rebase only; keep 3 commits. |
| `W1-4` | `W1-4-terminal-ssh-cwd.md` | `PR4a-terminal-ssh-cwd.md` | `fix/terminal-ssh-cwd` | `868773aa8ba037511134868cf9a9c3bbf90a1337` | `origin/main` | 1 commit, 11 files (+57 / -15) | Rebase only. |
| `W1-5` | `W1-5-tts-output-placement.md` | `tts-output-placement.md` | `fix/tts-output-placement` | `ecae8682a4c5915ae58d760e1d46f40ade4aa1b7` | `origin/main` | 1 commit, 6 files (+110 / -19) | Rebase and format draft with upstream PR template. |
| `W2-1` | `W2-1-ssh-client-config.md` | `PR2b-ssh-client-config.md` | `feat/ssh-client-config` | `db7587772b60966eed365d0cce892be59c6d1273` | `W1-1` | 1 commit, 17 files (+206 / -19) | Rebase onto updated `W1-1`. Immediately enables `terminal.ssh_config` on existing SSH backend, workspace browser, streams, and Doctor. |
| `W2-2` | `W2-2-url-reference-fetching.md` | `PR5-url-reference-fetching.md` | `feat/url-reference-fetching` | `c3a6b8a0bc49a16b907f98917cfbc50c5cd84e4e` | `W1-1` | 1 commit, 6 files (+333 / -6) | Rebase onto updated `W1-1`. Immediately enables `context_references.fetch_urls: false`. |
| `W2-3` | `W2-3-managed-tool-denials.md` | `PR6-deployment-restrictions.md` | `feat/managed-tool-denials` | `14e980021941c92aef57d2dd305332eb36fa2773` | `W1-1` | 6 commits, 60 files (+2,173 / -458) | Rebase onto updated `W1-1`; keep 6 clean commits. Immediately enables `tools.disabled`. |
| `W3-1` | `W3-1-executor-desktop-placement.md` | `PR3b-executor-desktop-browser.md` | `feat/executor-desktop-placement` | `24a750de04e194f58004db78156db25439b95b1a` | `W2-1` and `W1-3` | 4 commits (`16816db7d..24a750de0`), 53 files (+3,100 / -278) | Rebase all 4 commits onto updated `W2-1` and `W1-3`; preserve the 4 clean sequential commits. |
| `W3-2` | `W3-2-webapp-executor-terminals.md` | `PR4b-executor-terminals.md` | `feat/webapp-executor-terminals` | `7ae5fd82c5369718a0073d8795e3ca14ec7fd930` | `W1-1` and `W1-4` | 11 commits, 97 files (+4,150 / -548) | Rebase onto `W1-1` and `W1-4`, fix all 12 `scripts/check` findings, reorder into 6 clean commits, and rewrite draft for full operator-shell scope. |
| `W3-3` | `W3-3-ssh-executor-isolation.md` | `ssh-project-workspaces.md`, `ssh-skill-shell.md`, `ssh-cron-execution.md` | `feat/ssh-executor-isolation` (consolidates `feat/ssh-project-workspaces`, `feat/ssh-skill-shell`, and `feat/ssh-cron-execution`) | `39cdc0ce2`, `0c67369ef`, and `c73e521b8` | `W1-1`, `W1-2`, and `W2-1` | 196 unique files (+7,408 / -965) | Rebase and linearize (drop 2 merge commits), fold 2 review cleanups, and split internally into 10 sequential commits with skills (#9) and cron (#10) cleanly splittable at the tip. |
| Deferred | `deferred-webapp-content-privacy.md` | `PR7-webapp-content-privacy.md` | `upstream-pr/webapp-content-privacy` | `25a1302eacb563c59eb3b7454c1a53f8c89f274c` | Deferred | Design only (0 commits) | Rename draft only; keep downstream patches `0008`-`0010` until upstream design is settled. |

The `W1-1` through `W3-3` branches on `88a1c1f4b` have prior verified logs under
`upstream_work/executor-access-evidence/` and `upstream_work/pr-rebased-evidence/`.
After each branch is rebased onto the new `origin/main` target, save fresh logs
under `upstream_work/wave-rebase-evidence/`.

## 2. Upstream submission and merge-order checklist

1. **Wave 1 (`W1-1` through `W1-5`):** Submit `W1-1` (`fix/managed-config`)
   first because it carries `contributors/emails/mikeperry-git@untrusted.systems`
   and unblocks Wave 2. `W1-2`, `W1-3`, `W1-4`, and `W1-5` have no code
   dependency on `W1-1` and can open in parallel once `W1-1` lands (or carry the
   contributor email file if opened earlier).
2. **Wave 2 (`W2-1`, `W2-2`, `W2-3`):** Open after `W1-1` merges (rebasing from
   `W1-1` onto updated `main` so `W1-1` commits stay out of each PR diff).
3. **Wave 3 (`W3-1`, `W3-2`, `W3-3`):** Open once their prerequisites land:
   - `W3-1` after `W2-1` and `W1-3` (keep `W1-2`'s Chromium sync-exclusion fix
     when testing or shipping `W3-1` with live Chromium and SSH sync-back).
   - `W3-2` after `W1-1` and `W1-4`.
   - `W3-3` after `W1-1`, `W1-2`, and `W2-1`. Point component maintainers to
     the sequential commit ranges listed in `W3-3-ssh-executor-isolation.md`; if
     maintainers request smaller PRs, split commits 9 (skills) and 10 (cron) off
     cleanly without disturbing commits 1-8.
4. **Shared-path conflict rules across rebases and combined merges:**
   - `website/docs/user-guide/managed-scope.md`: preserve strict-reader and
     config documentation from `W3-1`, `W3-2`, and `W3-3`.
   - `tools/browser_use_cli.py`: preserve both `W3-1` executor routing and
     `W2-3` `tool_refusal` checks.
   - `tools/mcp_tool_agent.py`: preserve native `_refresh_name_dependent_defs`
     and `W2-3`'s managed `permitted` filter.
   - `apps/shared/src/gateway-contract.{generated.ts,openrpc.json}` and
     `tests/hermes_cli/serve_handler_ledger.json`: always regenerate with
     `scripts/gen_gateway_contracts.py` and `scripts/gen_serve_handler_ledger.py`
     rather than hand-editing merges.
5. **Pre-PR GitHub checks:** Follow upstream
   [CONTRIBUTING.md](https://github.com/NousResearch/hermes-agent/blob/main/CONTRIBUTING.md#pull-request-process)
   and the upstream
   [PR template](https://github.com/NousResearch/hermes-agent/blob/main/.github/PULL_REQUEST_TEMPLATE.md).
   Search open and merged upstream PRs and issues for duplicates before filing,
   use `Fixes #<n>` only when the PR fully closes the issue, evaluate any
   security-sensitive finding against upstream `SECURITY.md`, and strip local
   submission notes and issue drafts from the pasted PR body.
6. **Post-merge downstream cleanup:** Once an official Hermes release includes a
   merged topic, run its native regression tests on the shipped source, rerun
   matching Private Hermes packaged tests, and drop the superseded portion of
   `components/hermes/patches/0001-upstream-candidates.patch` along with any
   wrapper test that only repeats native unit coverage.

## 3. Docker verification recipes

Run all upstream checks in temporary container checkouts (`--network none`,
`--init`, UID `10000:10000`, `--tmpfs /workspace:ro,mode=000`) so host worktrees
and host `~/.hermes` are never mutated and the container's stale `/workspace`
directory cannot trigger false failures in `test_web_server_fs_session_workspace.py`.

### Python tests and `scripts/check`

Image `private-hermes-executor-access-native-tests:local` provides the Python
test venv at `/opt/executor-access-test-env/bin/python` and cached TypeScript
6.0.3 at `/opt/hermes/node_modules/typescript`.

```sh
mkdir -p upstream_work/wave-rebase-evidence
docker run --rm --init --entrypoint "" --user 10000:10000 --network none \
  --tmpfs /workspace:ro,mode=000 \
  -v "$(pwd)/upstream_work/hermes-agent:/src-repo:ro" \
  -e HOME=/tmp/home -e HERMES_HOME=/tmp/hermes-home \
  -e HERMES_PYTHON=/opt/executor-access-test-env/bin/python \
  -e PATH=/opt/executor-access-test-env/bin:/usr/local/bin:/usr/bin:/bin \
  private-hermes-executor-access-native-tests:local \
  sh -c '
    mkdir -p /tmp/home/.cache/hermes-code-health/typescript-6.0.3/node_modules /tmp/hermes-home /tmp/work &&
    ln -s /opt/hermes/node_modules/typescript /tmp/home/.cache/hermes-code-health/typescript-6.0.3/node_modules/typescript &&
    git clone -q --no-checkout /src-repo /tmp/work &&
    cd /tmp/work &&
    git checkout -q "<TARGET_SHA>" &&
    python3 scripts/check --base "<BASE_SHA>" &&
    scripts/run_tests.sh <TEST_PATHS...>
  ' | tee "upstream_work/wave-rebase-evidence/<NAME>.log"
```

*Note on `scripts/code_health` TypeScript version:* If upstream bumps the pinned
TypeScript version in `scripts/code_health/` after `origin/main` advances, check
the expected version in `upstream_work/hermes-agent/scripts/code_health/` and
update the symlink directory name (or rebuild the offline test image if a newer
TypeScript compiler is required).

*Known container-only baseline skips and failures:* Inside Docker (`/.dockerenv`),
`tests/cron/test_file_permissions.py` fails 4 mode assertions (`0755` and `0644`
instead of `0700` and `0600`) identically on unmodified upstream `main`, and
Windows-only tests skip on Linux. Compare any unexpected failure against
unmodified `MAIN_SHA` in the same container before treating it as a regression.

### Regenerating OpenRPC contracts and serve-handler ledger

Whenever `tui_gateway/contracts/` or `hermes_cli/web_routers/` changes (`W3-2`,
`W3-3`, or the combined merge), regenerate the tracked artifacts inside Docker
and copy only the generated files back into the worktree. Grant write access on
the temporary output directory so UID `10000` can write on both macOS Docker
Desktop and native Linux Docker:

```sh
OUT_DIR="$(mktemp -d)"
chmod 777 "$OUT_DIR"
docker run --rm --init --entrypoint "" --user 10000:10000 --network none \
  -v "<WORKTREE_ABS_PATH>:/work:ro" \
  -v "$OUT_DIR:/out" \
  -e HOME=/tmp/home -e HERMES_HOME=/tmp/hermes-home \
  -e PATH=/opt/executor-access-test-env/bin:/usr/local/bin:/usr/bin:/bin \
  private-hermes-executor-access-native-tests:local \
  sh -c '
    mkdir -p /tmp/home /tmp/hermes-home /tmp/src /out/gen &&
    cp -a /work/. /tmp/src/ && rm -f /tmp/src/.git &&
    cd /tmp/src &&
    python3 scripts/gen_gateway_contracts.py &&
    python3 scripts/gen_serve_handler_ledger.py &&
    cp apps/shared/src/gateway-contract.generated.ts /out/gen/ &&
    cp apps/shared/src/gateway-contract.openrpc.json /out/gen/ &&
    cp tests/hermes_cli/serve_handler_ledger.json /out/gen/
  '
# Copy files from "$OUT_DIR/gen/" into "<WORKTREE_ABS_PATH>", then remove "$OUT_DIR".
```

### Desktop (`apps/desktop`) and TUI (`ui-tui`) TypeScript and Vitest

Image `private-hermes-webapp-build:qualification` holds frozen `node_modules` for
`apps/desktop` (under `/opt/hermes/.build/webapp-workspace/apps/desktop`) and
`ui-tui` (under `/opt/hermes/ui-tui`). Replace `apps/shared/src`,
`apps/shared/package.json`, `apps/desktop/src`, and `ui-tui/src` cleanly inside
a temporary `--network none` container before running `tsc --noEmit` and
`vitest`:

```sh
docker run --rm --init --entrypoint "" --network none \
  -v "<WORKTREE_ABS_PATH>:/src:ro" \
  private-hermes-webapp-build:qualification \
  sh -c '
    rm -rf /opt/hermes/.build/webapp-workspace/apps/shared/src /opt/hermes/.build/webapp-workspace/apps/desktop/src &&
    cp -a /src/apps/shared/src /opt/hermes/.build/webapp-workspace/apps/shared/src &&
    cp /src/apps/shared/package.json /opt/hermes/.build/webapp-workspace/apps/shared/package.json &&
    cp -a /src/apps/desktop/src /opt/hermes/.build/webapp-workspace/apps/desktop/src &&
    mkdir -p /opt/hermes/.build/webapp-workspace/tests/fixtures &&
    cp /src/tests/fixtures/session-resume-active-turn.json /opt/hermes/.build/webapp-workspace/tests/fixtures/ &&
    cd /opt/hermes/.build/webapp-workspace/apps/desktop &&
    node --max-old-space-size=4096 node_modules/typescript/bin/tsc -p tsconfig.json --noEmit &&
    node node_modules/vitest/vitest.mjs run --project ui <DESKTOP_TEST_PATHS...>
  '
```

For `ui-tui`:

```sh
docker run --rm --init --entrypoint "" --network none \
  -v "<WORKTREE_ABS_PATH>:/src:ro" \
  private-hermes-webapp-build:qualification \
  sh -c '
    rm -rf /opt/hermes/apps/shared/src /opt/hermes/ui-tui/src &&
    cp -a /src/apps/shared/src /opt/hermes/apps/shared/src &&
    cp /src/apps/shared/package.json /opt/hermes/apps/shared/package.json &&
    cp -a /src/ui-tui/src /opt/hermes/ui-tui/src &&
    cd /opt/hermes/ui-tui &&
    /opt/hermes/node_modules/.bin/tsc -p tsconfig.json --noEmit &&
    /opt/hermes/.build/webapp-workspace/apps/desktop/node_modules/.bin/vitest run <TUI_TEST_PATHS...>
  '
```

If upstream `origin/main` adds new npm dependencies to `apps/desktop`,
`apps/shared`, or `ui-tui` that are absent from
`private-hermes-webapp-build:qualification`, note the missing package and
refresh the offline build image from the updated lockfile before running UI
tests.

## 4. Phased execution plan

### Phase 0: Pre-flight, safety refs, and `origin/main` fetch

1. **Snapshot current `88a1c1f4b` heads locally before any rebase:** Create
   read-only backup refs `backup/88a1c1f4b/<branch-leaf>` for all 13 active
   branches in `upstream_work/hermes-agent/` so every pre-rebase commit remains
   recoverable locally even if a rebase encounters conflicts.
2. **Push current `88a1c1f4b` snapshots to `fork` (if not already pushed by the
   operator):** `fork` still points at older heads for `fix/ssh-workspace`
   (`734837a9f` vs. local `73a53241d`) and `feat/webapp-executor-terminals`
   (`703b3f869` vs. local `7ae5fd82c`), and has no refs yet for
   `fix/tts-output-placement`, `feat/ssh-project-workspaces`,
   `feat/ssh-skill-shell`, or `feat/ssh-cron-execution`. Pushing over SSH
   requires host access outside the agent sandbox; if the operator has not
   pushed those 6 fast-forward and new branches yet, record the exact non-force
   push command (or push `backup/88a1c1f4b/*` refs) in the handoff note.
3. **Fetch latest `origin/main`:** Run `git -C upstream_work/hermes-agent fetch origin main`
   and record the exact 40-character `MAIN_SHA` and commit date in the
   [Execution checkpoint](#execution-checkpoint) table.
4. **Worktree hygiene:**
   - Run `git -C upstream_work/hermes-agent worktree prune` to clear the 13
     stale prunable `/private/tmp` and `/private/var/folders` entries.
   - Inspect and discard the leftover uncommitted WIP in
     `upstream_work/worktrees/combined-replay` (on `stack-patches/v0.23.3/combined`,
     which is superseded by `stack-patches/v0.23.3/executor-project-integration`
     at `1d3dec980`). Do not remove or modify any `stack-patches/v0.23.3/*` ref.
   - Check upstream commits in `88a1c1f4b..MAIN_SHA` for any merged fixes that
     overlap with `W1-1` through `W3-3` (run `git log --oneline 88a1c1f4b..MAIN_SHA`
     filtered by touched paths).
5. **Phase 0 gate:** `MAIN_SHA` recorded, backup refs created, prunable
   worktrees cleared, and overlap notes recorded in the checkpoint table.

### Phase 1: Rebase Waves 1 and 2 (`W1-1`..`W1-5`, `W2-1`..`W2-3`)

Use clean temporary worktrees under `upstream_work/worktrees/` (always setting
`GIT_COMMITTER_NAME="Mike Perry"` and
`GIT_COMMITTER_EMAIL="mikeperry-git@untrusted.systems"`).

1. **Wave 1 (`origin/main` = `MAIN_SHA`):**
   - **`W1-1` (`fix/managed-config`):** Rebase `88a1c1f4b..d4aa66920` onto
     `MAIN_SHA` (2 commits). Run `scripts/check --base MAIN_SHA` and tests:
     `tests/hermes_cli/test_managed_scope*.py`,
     `tests/hermes_cli/test_config*.py`, `tests/ci/test_docs_drift.py`, and
     `tests/ci/test_prompt_surface.py`.
   - **`W1-2` (`fix/ssh-workspace`):** Rebase `88a1c1f4b..73a53241d` onto
     `MAIN_SHA` (8 commits; keep `73a53241d` as a clean standalone tip commit,
     or fold its `tools/file_tools.py` change into `eb93959ce` and its
     `tests/agent/test_subprocess_env_guard.py` change into `23be2f3b5`). Run
     `scripts/check --base MAIN_SHA` and tests:
     `tests/tools/test_ssh_environment.py`, `tests/tools/test_file_tools*.py`,
     `tests/hermes_cli/test_ssh_workspace_fs.py`,
     `tests/agent/test_subprocess_env_guard.py`, `tests/ci/test_docs_drift.py`,
     and `tests/ci/test_prompt_surface.py`.
   - **`W1-3` (`fix/executor-desktop-browser`):** Rebase `88a1c1f4b..1f2eefc51`
     onto `MAIN_SHA` (3 commits). Run `scripts/check --base MAIN_SHA` and
     desktop, CUA, and browser fix tests (`tests/tools/test_computer_use*.py`,
     `tests/tools/test_browser*.py`, `tests/tools/test_bot_desktop*.py`,
     `tests/ci/test_docs_drift.py`, and `tests/ci/test_prompt_surface.py`).
   - **`W1-4` (`fix/terminal-ssh-cwd`):** Rebase `88a1c1f4b..868773aa8` onto
     `MAIN_SHA` (1 commit). Run `scripts/check --base MAIN_SHA`, terminal and
     SSH `cwd` Python tests, and Desktop `cwd-tracking.test.ts` and
     `ssh-connection.test.ts`.
   - **`W1-5` (`fix/tts-output-placement`):** Rebase `88a1c1f4b..ecae8682a` onto
     `MAIN_SHA` (1 commit). Run `scripts/check --base MAIN_SHA` and
     `tests/tools/test_tts_output_placement.py`,
     `tests/tools/test_tts_output_dir_profile_scope.py`,
     `tests/tools/test_tts_path_traversal.py`, `tests/ci/test_docs_drift.py`,
     and `tests/ci/test_prompt_surface.py`.
2. **Wave 2 (base = rebased `W1-1`):**
   - **`W2-1` (`feat/ssh-client-config`):** Rebase `d4aa66920..db7587772` onto
     rebased `W1-1` (1 commit). Run `scripts/check --base <W1-1>` and
     `tests/tools/test_ssh_environment.py`, `tests/hermes_cli/test_doctor.py`,
     `tests/hermes_cli/test_managed_scope_env.py`,
     `tests/hermes_cli/test_ssh_workspace_fs.py`, and
     `tests/ci/test_docs_drift.py`.
   - **`W2-2` (`feat/url-reference-fetching`):** Rebase `d4aa66920..c3a6b8a0b`
     onto rebased `W1-1` (1 commit). Run `scripts/check --base <W1-1>` and
     `tests/agent/test_context_references.py`,
     `tests/gateway/test_local_context_ref_turn_text.py`, and
     `tests/ci/test_docs_drift.py`.
   - **`W2-3` (`feat/managed-tool-denials`):** Rebase `d4aa66920..14e980021`
     onto rebased `W1-1` (6 commits). Run `scripts/check --base <W1-1>` and
     managed tool-denial, prompt-surface, MCP, and worker tests.
3. **Rename and refresh Wave 1 and Wave 2 submission drafts:**
   - Rename `PR1-managed-config.md` -> `W1-1-managed-config.md`,
     `PR2a-ssh-workspace-fixes.md` -> `W1-2-ssh-workspace-fixes.md`,
     `PR3a-executor-desktop-browser-fixes.md` -> `W1-3-executor-desktop-browser-fixes.md`,
     `PR4a-terminal-ssh-cwd.md` -> `W1-4-terminal-ssh-cwd.md`,
     `tts-output-placement.md` -> `W1-5-tts-output-placement.md` (expand into
     full upstream PR template), `PR2b-ssh-client-config.md` ->
     `W2-1-ssh-client-config.md`, `PR5-url-reference-fetching.md` ->
     `W2-2-url-reference-fetching.md`, and `PR6-deployment-restrictions.md` ->
     `W2-3-managed-tool-denials.md`.
   - Update branch SHAs, commit lists (including `W1-2`'s document extraction
     and env guard commit), and Docker validation summaries in each draft.
   - Rename `PR7-webapp-content-privacy.md` -> `deferred-webapp-content-privacy.md`.
4. **Phase 1 gate:** All 8 Wave 1 and Wave 2 branches pass `scripts/check`
   (0 blocking), `git show --check`, and focused Docker tests; drafts renamed
   and refreshed; checkpoint table updated and committed in the wrapper repo.

### Phase 2: Rebase, clean, and reorder `W3-1` and `W3-2`

#### `W3-1`: `feat/executor-desktop-placement` (base: rebased `W2-1` and `W1-3`)

1. Build a clean prerequisite base combining rebased `W2-1` and `W1-3` (with
   one clean merge commit on top of `MAIN_SHA` for the review base), then replay
   all **4 commits** (`16816db7d..24a750de0`, 53 files, +3,100 / -278) onto it.
2. Preserve the 4 already-clean sequential commits so browser and desktop
   maintainers can inspect their respective ranges directly:
   - **Commit 1 (`feat(browser): add browser.require_sandbox to enforce Chromium sandboxing`, from `ed5acd3d8`):**
     8 files enforcing required Chromium sandboxing (`browser.require_sandbox`)
     with `tests/tools/test_browser_required_sandbox.py`.
   - **Commit 2 (`feat(browser): add executor-side browser-harness runner`, from `cc69de9ca`):**
     `tools/browser_use_executor_runner.py` and
     `tests/tools/test_browser_use_executor_runner.py`.
   - **Commit 3 (`feat(desktop): add managed bot_desktop.executor_only placement and owner binding`, from `acf427ec8`):**
     19 files covering `tools/bot_desktop/{placement,runtime,sandbox_host,install,thumbnail,browser}.py`,
     `hermes_cli/web_routers/display.py`,
     `hermes_cli/subcommands/computer_use_screen.py`,
     `plugins/computer_use/cua/__init__.py`, `tui_gateway/methods_display.py`,
     `tools/environments/streams.py`, `website/docs/user-guide/managed-scope.md`,
     and the `test_bot_desktop_*.py` tests.
   - **Commit 4 (`feat(browser): run browser_exec in the executor and enforce executor-only`, from `24a750de0`):**
     28 files routing `browser_exec` through the executor harness with
     `browser.executor_python` and `browser.executor_workspace`, config defaults,
     browser user docs, and the 11 `tests/tools/test_browser*.py` and
     `test_managed_executor_desktop.py` tests.
3. Verify `scripts/check --base <W3-1-base>` (0 blocking), `git show --check` on
   all 4 commits, and all 19 touched test files across `tests/tools/` plus
   `tests/ci/test_docs_drift.py` and `tests/ci/test_prompt_surface.py`.
4. Rename `PR3b-executor-desktop-browser.md` ->
   `W3-1-executor-desktop-placement.md` with updated SHAs and the 4-commit
   reviewer map.

#### `W3-2`: `feat/webapp-executor-terminals` (base: rebased `W1-1` and `W1-4`)

1. Build a clean prerequisite base combining rebased `W1-1` and `W1-4`, then
   replay `ab023f305..7ae5fd82c` onto it.
2. **Fix all 12 pre-existing `scripts/check` failures** recorded against
   `ab023f305..7ae5fd82c` (1 `ruff` error and 11 blocking `code_health`
   findings, so `scripts/check` reports 0 errors and 0 blocking findings):
   - **`ruff` (1 error):** `tests/hermes_cli/test_managed_operator_shell.py:65`:
     pass explicit `check=False` to `subprocess.run(...)`.
   - **`gateway/session_shell.py:106` (`ASYNC240`):** Move the blocking path
     call inside `async def _run` into `await asyncio.to_thread(...)`.
   - **`hermes_cli/managed_operator_shell.py:267` (`HX006`):** Wrap async
     subprocess wait and communicate calls properly (or add `# health: allow HX006`
     only if matching the reviewed no-total-work-deadline contract in
     `web_host_terminal.py:273`).
   - **`tests/gateway/fixtures/shell_exec_peer.py:47` (`HX013`):** Replace
     wall-clock `sleep` with an event or condition wait (or `# health: allow HX013`
     only if the delay itself is the behavior under test).
   - **`apps/desktop/src/lib/browser-terminal.ts:165` (`CC` 22 > 20):** Extract
     helper functions from `applyTerminalMetadata` to bring CC <= 20.
   - **`hermes_cli/gateway_chat_view.py:599` (`CC` 21 > 20):** Extract a helper
     from `GatewayChatView.run` to bring CC <= 20.
   - **`tui_gateway/methods_tools.py` (`FILE_LINES` 2003 > 2000) and
     `tests/tui_gateway/test_protocol.py` (`FILE_LINES` 2131 > 2128):** Follow
     upstream's `FILE_LINES` package rule (never create flat `<stem>_<topic>.py`
     siblings; convert `<stem>.py` to a `<stem>/` package or put new protocol
     tests under `tests/tui_gateway/test_protocol/` with `__init__.py`, keeping
     existing over-cap files at or below their `main` line counts).
   - **`ui-tui/src/app/useInputHandlers.ts` (`CC` 121 > 120 and `FUNC_LINES`
     331 > 327), `ui-tui/src/app/useMainApp.ts` (`FUNC_LINES` 440 > 439), and
     `ui-tui/src/app/useSubmission.ts` (`CC` 25 > 20):** Extract the shell
     intent and dispatch helpers into a dedicated helper module under
     `ui-tui/src/app/` so all three functions stay at or below their `main` caps.
3. **Design clarity check:** Confirm and document why `webapp.executor_ssh_config`
   is a WebApp launch-profile override across all profiles (distinct from
   `W2-1`'s per-profile `terminal.ssh_config`), or reconcile if upstream `main`
   changed `web_host_terminal`.
4. **Reorder `W3-2` into 6 clean, sequential commits:**
   - **Commit 1 (`feat(shell): add managed operator shell placement helper and policy`):**
     `hermes_cli/managed_operator_shell.py`, `tools/terminal_scope.py`,
     `agent/runtime_scope.py`, `agent/secret_scope.py`,
     `tests/agent/test_secret_scope.py`, and
     `tests/hermes_cli/test_managed_operator_shell.py`.
   - **Commit 2 (`feat(webapp): support cancellable SSH executor terminals in WebApp backend`):**
     `hermes_cli/config_defaults.py`, `hermes_cli/web_host_terminal*.py`,
     `hermes_cli/web_routers/webapp_relay_proxy.py`,
     `hermes_cli/webapp_relay_target.py`, `hermes_cli/web_server_app.py`,
     `hermes_cli/web_server_dashboard.py`, `hermes_cli/pty_session.py`,
     `tests/hermes_cli/test_executor_terminal.py`,
     `tests/hermes_cli/test_host_terminal_viewer_ownership.py`,
     `tests/hermes_cli/test_web_host_terminal_persistence.py`, and
     `tests/hermes_cli/test_webapp_relay_proxy.py`.
   - **Commit 3 (`feat(webapp): acknowledge executor terminals and pin tab ownership in WebApp UI`):**
     `apps/desktop/src/app/right-sidebar/terminal/*`,
     `apps/desktop/src/lib/browser-terminal.*`,
     `apps/desktop/src/lib/browser-desktop-bridge*`,
     `apps/desktop/src/store/gateway*`, and `apps/desktop/src/global.d.ts`.
   - **Commit 4 (`feat(gateway): route managed chat shells, Code terminal reads, and Agent profile cwd`):**
     `gateway/session_shell.py`, `gateway/session_terminal_cwd.py`,
     `gateway/session_commands.py`, `gateway/session_controls.py`,
     `gateway/session_server_requests.py`, `gateway/local_desktop_ui.py`,
     `gateway/run_inbound_hooks.py`, `tui_gateway/*`,
     `apps/desktop/src/app/session/hooks/use-message-stream/gateway-event/server-requests.{ts,test.ts}`,
     and their gateway and TUI gateway tests.
   - **Commit 5 (`feat(tui): retain shell intent and interrupt managed SSH commands from CLI and TUI`):**
     `cli.py`, `hermes_cli/bang_shell.py`, `hermes_cli/cli_*`,
     `hermes_cli/gateway_chat_view.py`, `hermes_cli/gateway_connection*`,
     `ui-tui/src/*`, and their CLI and TUI tests.
   - **Commit 6 (`chore(webapp): regenerate contracts, serve-handler ledger, and operator shell docs`):**
     `apps/shared/src/gateway-contract.{generated.ts,openrpc.json}`,
     `tests/hermes_cli/serve_handler_ledger.json`,
     `tests/fixtures/resolution_allowlist.json`, `cli-config.yaml.example`, and
     `website/docs/*`.
5. **Verify `W3-2`:**
   - `scripts/check --base <W3-2-base>` passes all 22 checks (0 blocking).
   - Python suites: `test_managed_operator_shell.py`, `test_executor_terminal.py`,
     `test_webapp_relay_proxy.py`, `test_session_shell.py`,
     `test_session_terminal_cwd_owner.py`, `test_serve_handler_ledger.py`,
     `test_canonical_wire_contract.py`, `test_generated.py`, `test_docs_drift.py`,
     and `test_prompt_surface.py`.
   - Desktop `tsc --noEmit` and terminal and gateway Vitest files; `ui-tui`
     `tsc --noEmit` and `submissionDestinationRenderer.test.tsx`.
6. **Rewrite draft:** Rename `PR4b-executor-terminals.md` ->
   `W3-2-webapp-executor-terminals.md` covering the full 6-commit operator-shell
   story (replacing the outdated 2-commit description and replacing the two
   non-template prose em dashes on lines 32-33 with plain ASCII; keep upstream
   PR template boilerplate intact), with a sequential commit guide.
7. **Phase 2 gate:** Both `W3-1` and `W3-2` pass `scripts/check` and Docker
   Python and UI tests, drafts are updated, and the checkpoint table is
   committed.

### Phase 3: Linearize, clean, and split commits inside `W3-3`

Create branch `feat/ssh-executor-isolation` (preserving the old
`backup/88a1c1f4b/*` refs) on a clean prerequisite base combining rebased
`W1-1`, `W1-2`, and `W2-1` (eliminating the two internal merge commits
`7110ca808` and `5ca732033` from the old `feat/ssh-project-workspaces`).

#### Minor review cleanups to fold in during Phase 3

1. **Structured `TerminalPolicyUnavailable` handling:** Catch
   `TerminalPolicyUnavailable` alongside `SshWorkspaceFsError` and `ValueError`
   in `gateway/session_local_migration.py::_legacy_executor_project`,
   `gateway/session_local.py::prepare_local_workspace`, and
   `tui_gateway/prompt_turn.py::_bind_executor_prompt_workspace` so malformed
   profile configs produce structured refusals rather than unhandled exceptions.
2. **Centralized fail-closed `profile_project_access()`:** In
   `tui_gateway/managed_project_queries.py::profile_project_access()`, load
   managed config once, pass it to `managed_project_access(...)`, and return
   `((), {})` centrally when managed SSH roots are active so callers
   (`web_routers/files.py::_managed_fs_project` and `_managed_project_backend`)
   drop duplicated fallback guards without introducing any fail-open path.

#### Target 10-commit sequential structure inside `W3-3`

Order commits so every commit builds cleanly, passes `git show --check`, and
allows any reviewer to inspect a single subsystem range (and allows commits 9
and 10 to split off cleanly into standalone follow-up PRs if maintainers ask):

1. **`feat(ssh): enforce managed SSH write roots, ACL preservation, and project probe`**
   - Files: `tools/file_operations_common.py`,
     `tools/file_operations_ssh_{acl,path,write}.py`,
     `tools/file_tools_{paths,ssh_writes}.py`, `tools/environments/ssh.py`
     (excluding the skill sync hunk for Commit 9), `hermes_cli/ssh_project_probe.py`,
     `hermes_cli/ssh_workspace_fs.py`, and
     `tui_gateway/managed_project_queries.py` (with review cleanup #2).
   - Tests: `tests/tools/test_ssh_project_acl.py`,
     `tests/tools/test_file_tools_cwd_resolution.py`,
     `tests/tools/test_ssh_environment.py`,
     `tests/agent/test_subprocess_env_guard.py`,
     `tests/hermes_cli/test_ssh_project_probe.py`, and
     `tests/hermes_cli/test_ssh_workspace_fs.py`.
2. **`feat(sessions): bind managed SSH project workspaces and legacy session adoption`**
   - Files: `gateway/session_{local,local_inventory,local_migration,policy,policy_refresh,mutation_policy,ancillary,commands,controls,complete_path,managed_worker}.py`,
     `gateway/run_{background,inbound,notifications,turn,turn_runner}.py`,
     `persistence/sqlite/authority/_local.py`,
     `persistence/sqlite/conversation/_store/sessions.py`,
     `session_rules/local_create.py`, `cli.py`,
     `hermes_cli/{main,main_agent_cmds,main_resume_args,main_tui_launch,cli_commands_mixin,gateway_chat,gateway_chat_commands,gateway_session_store,projects_db,goals}.py`,
     `tui_gateway/{methods_complete,methods_config,methods_projects,methods_prompt,methods_slash,methods_tools,project_tree,prompt_attachments,prompt_turn,session_workdir}.py`,
     and `ui-tui/src/{launchOptions.ts,__tests__/canonicalGateway.test.ts}`
     (with review cleanup #1).
   - Tests: session, gateway, contract, and CLI tests (`test_session_policy_remote_cwd.py`,
     `test_managed_turn_contract.py`, `test_managed_turn_text_target_session.py`,
     `test_managed_unstarted_cancel.py`, `test_local_create_alias_retry.py`,
     `test_stored_reads_contract.py`, `test_gateway_chat.py`, `test_goal_gates.py`,
     `test_resume_latest_and_in_dir.py`, and `test_projects_rpc.py`).
3. **`feat(context): load project context, @ references, /init, and /diff over SSH`**
   - Files: `agent/{coding_context,context_file_sources,context_references,conversation_loop,managed_worker,prompt_builder,ssh_context_references,ssh_project_context,ssh_staged_references,subdirectory_hints,system_prompt,verification_evidence}.py`
     (excluding the project skill metadata hunk in `prompt_builder.py` for
     Commit 9), `gateway/session_context_refs.py`, `gateway/slash_commands.py`,
     `hermes_cli/init_command.py`, `hermes_cli/ssh_project_git.py`, and
     `tools/working_diff.py`.
   - Tests: `tests/agent/test_ssh_context_references.py`,
     `tests/gateway/test_context_ref_expansion_runtime.py`, and
     `tests/gateway/test_local_context_ref_*.py`.
4. **`feat(webapp): route workspace files, folder creation, previews, and read-only Git over SSH`**
   - Files: `hermes_cli/web_routers/{chat_workspaces,chat_ws,files,git,session_files}.py`,
     `hermes_cli/{web_git,web_git_executor,web_server_chat,web_server_file_tickets,session_worktree,worktree_cmd,worktree_exit}.py`,
     `apps/desktop/src/*`, `web/src/*`, `tui_gateway/contracts/projects_pets.py`,
     regenerated `apps/shared/src/gateway-contract.{generated.ts,openrpc.json}`,
     and regenerated `tests/hermes_cli/serve_handler_ledger.json`.
   - Tests: `tests/hermes_cli/test_web_git_executor.py`,
     `tests/hermes_cli/test_web_server_chat_workspaces.py`,
     `tests/hermes_cli/test_web_server_fs_session_workspace.py`,
     `tests/hermes_cli/test_web_server_fs_write_guard.py`,
     `tests/hermes_cli/test_worktree_command.py`,
     `tests/hermes_cli/test_serve_handler_ledger.py`,
     `tests/gateway/test_canonical_wire_contract.py`, and
     `tests/tui_gateway/contracts/test_generated.py`.
5. **`feat(delegate): keep delegated child workspaces and image reads on the SSH executor`**
   - Files: `tools/delegate_tool*.py`, `tools/image_source.py`,
     `tools/approval_context.py`, `agent/image_routing.py`, and delegation tests.
6. **`feat(kanban): enforce managed SSH workspace and staged artifact boundaries`**
   - Files: `hermes_cli/kanban*.py`, `gateway/kanban_watchers*.py`,
     `gateway/session_kanban.py`, `plugins/kanban/dashboard/plugin_api.py`, and
     `tests/gateway/test_kanban_notifier.py`.
7. **`feat(tools): route gateway SSH media delivery and remote Python execute_code cwd`**
   - Files: `gateway/ssh_media.py`, `gateway/media_repair.py`,
     `gateway/platforms/base.py`, `tools/code_execution_{env,tool}.py`,
     `tools/code_kernel_remote.py`, `tests/gateway/test_ssh_media.py`, and
     `tests/tools/test_code_kernel_remote.py`.
8. **`docs(ssh): document managed SSH workspace, session, delegation, and Kanban behavior`**
   - Files: `website/docs/user-guide/{managed-scope,sessions,desktop}.md` and
     `website/docs/user-guide/features/{code-execution,delegation,kanban}.md`.
9. **`feat(skills): run managed skill discovery and inline shells on the SSH executor`** *(splittable tail #1)*
   - Files: `agent/prompt_builder.py` (project skill metadata hunk),
     `agent/{skill_commands,skill_preprocessing,skill_utils,ssh_project_skills,ssh_skill_shell}.py`,
     `hermes_cli/commands_platforms.py`,
     `tools/environments/{file_sync,ssh}.py` (`upload_only_remote_roots` hunk),
     `tools/skills_tool.py`, `tests/agent/test_ssh_skill_shell.py`, and
     `website/docs/user-guide/features/skills.md`.
10. **`feat(cron): route managed cron workdirs, scripts, and delivery over SSH`** *(splittable tail #2)*
    - Files: `cron/{executor_script,executor_workspace,job_args,jobs,lifecycle_guard,monitor,scheduler,scheduler_delivery,scheduler_delivery_media,scheduler_script,scheduler_worktree_maintenance}.py`,
      `gateway/session_cron.py`, `hermes_cli/cron.py`, `tools/cronjob_tools.py`,
      `tests/cron/test_executor_script.py`, and
      `website/docs/user-guide/features/cron.md`.

*Exact-tree sanity check:* Before committing the final `W3-3` tip, diff
`W3-3` against the merged pre-split tree (excluding only the 2 intentional
review cleanups and `MAIN_SHA` conflict resolutions) to confirm zero production
lines were accidentally dropped during the 10-commit split.

#### Phase 3 verification and draft

1. Run `scripts/check --base <W3-3-base>` (must report 0 blocking across all
   196+ files) and `git show --check` on each of the 10 commits.
2. Run focused Docker tests for workspaces (31+ files), skills (11 files), and
   full `tests/cron/` with CI checks (201 of 202 files, noting the
   container-only `test_file_permissions.py` artifact if it still reproduces on
   `MAIN_SHA`).
3. Run `apps/desktop` `tsc --noEmit` with 7 Vitest files and `ui-tui`
   `tsc --noEmit` with `canonicalGateway.test.ts` in Docker.
4. Write `upstream_work/submissions/W3-3-ssh-executor-isolation.md` using the
   upstream PR template, including a concise commit-range reviewer map (commits
   1-8 core workspace containment, commit 9 skills, commit 10 cron) and noting
   that commits 9 and 10 can be split cleanly if requested. Remove the old
   `ssh-project-workspaces.md`, `ssh-skill-shell.md`, and `ssh-cron-execution.md`
   drafts once superseded.
5. **Phase 3 gate:** `W3-3` passes `scripts/check`, exact-tree parity check,
   and Python, Desktop, and TUI Docker tests; draft is written; checkpoint table
   is committed.

### Phase 4: Combined native qualification, docs alignment, and independent review

1. **Combined native replay on `MAIN_SHA`:** In a temporary Docker checkout,
   merge all 11 active branches (`W1-1` through `W3-3`), resolving the
   documented shared paths and regenerating OpenRPC contracts and the
   serve-handler ledger if needed. Run:
   - `scripts/check --base MAIN_SHA`
   - Cross-topic Python suite covering all 11 topics (all workspace, skill,
     cron, operator-shell, desktop and browser, URL reference, tool-denial, TTS,
     wire-contract, ledger, docs-drift, and prompt-surface tests)
   - `apps/desktop` `tsc --noEmit` and combined Vitest files
   - `ui-tui` `tsc --noEmit` and combined Vitest files
2. **Wrapper docs alignment:** Update `docs/development.md` and
   `docs/updates-and-plugins.md` to match the final `W1-1` through `W3-3` wave
   naming and `MAIN_SHA` qualification numbers (keeping `v0.23.3` packaged
   evidence intact). Verify local markdown links, anchors, `git diff --check`,
   and `make check`.
3. **Final independent subagent review (covers Phases 1-4, including `W3-2`
   operator-shell refactors and `W3-3` fail-closed cleanups):** Spawn a fresh
   read-only `general` subagent to audit:
   - All 11 rebased branches (`MAIN_SHA..HEAD`) for commit cleanliness,
     `scripts/check` results, absence of unintended merge commits or leaked
     wrapper paths, and exact parity against pre-rebase `backup/88a1c1f4b/*`
     (accounting for `MAIN_SHA` changes, `W3-2` `scripts/check` refactors, and
     the 2 intentional `W3-3` cleanups).
   - All 11 `W*.md` drafts and `deferred-webapp-content-privacy.md` for factual
     accuracy, exact SHAs, ASCII punctuation, and template compliance.
   - All wrapper doc edits (`docs/plans/hermes-upstream-prep.md`,
     `docs/development.md`, and `docs/updates-and-plugins.md`).
4. **Resolve findings and hand off:** Fix any material findings, re-verify
   modified branches, update the checkpoint table to `Done`, commit the wrapper
   updates, and report the exact `git -C upstream_work/hermes-agent push ...`
   command for the operator to run when ready to publish to `fork`.

## 5. Packaged release provenance

### v0.23.3 build provenance

The `stack-patches/v0.23.3/*` refs in `upstream_work/hermes-agent/` preserve the
release-based source history exported into Private Hermes's tracked patch
series (`components/hermes/patches/0001-upstream-candidates.patch`). For a later
official Hermes release, follow
[Rebuild the candidate patch for a new release](../update-workflow.md#rebuild-the-candidate-patch-for-a-new-release).

| Local branch under `stack-patches/v0.23.3/` | Head | Commits from `caafe5389` | Scope |
| --- | --- | ---: | --- |
| `managed-config` | `32abdfde7c1968d4d8ebd6cd3e16a3d35e4b04d7` | 3 | Strict managed YAML reader and dotenv authority |
| `executor-desktop-browser` | `3d38202f915671b5b656900406a04104a6f71616` | 19 | SSH file reads, searches, edits, checkpoint refusal, explicit SSH config, and desktop and browser placement |
| `executor-terminals` | `b886b1b648231e528a174a01c35f733548debf11` | 13 | WebApp terminals, model terminal reads, pinned forwarding, and managed chat shells |
| `url-reference-fetching` | `90a40b357b1c0ed9ba8cafae3fe8209373a098b4` | 5 | Selectable inline `@url:` context fetching |
| `deployment-restrictions` | `a414ff274857412d7d4b42b96596beb7b4cbde10` | 7 | Managed `tools.disabled` policy across discovery, prompts, background review, and dispatch |
| `tts-output-placement` | `9aa64cfdf3e692d097a33c9b70f7b9e86813098b` | 1 | Model speech output inside the active profile audio cache |
| `ssh-project-workspaces` | `761b2893c2e72e13a0908a2f431cd3c278b92e9d` | 21 | Managed SSH write grants and permission-preserving publisher |
| `executor-project-integration` | `1d3dec980055f3bbffaa15e5eabf7a998520d962` | 66 | Exported combined v0.23.3 replay: all upstream candidates, project workspaces, context, Git, skills, cron, legacy session adoption and files, and regression fixes |

- **Exact release base:** Hermes v0.23.3
  `caafe5389ae585ef77387a962aee05b1bcf17029` (multiarch index
  `sha256:3e9fe4c6ef36490f43aa0d0d80f9df64e9c92a576eee3042f1a97c8813c05355`).
- **Exported candidate patch:** `components/hermes/patches/0001-upstream-candidates.patch`
  (318 paths, SHA-256
  `8e9ca5672881552e11f8c546c23ddfcfed7ae5ce7bc956faba77f82c03973e53`).
- **Packaged qualification status:** Cross-engine runtime qualification on macOS
  Docker Desktop 29.9.3, Debian 13 ARM64 native Docker 29.10.0, and Debian 13
  ARM64 rootless Podman 5.4.2 is recorded in
  [Packaged Hermes qualification](../development.md#packaged-hermes-qualification).
- **Note on Phase 2 and Phase 3 changes vs. the v0.23.3 patch:** Pure commit
  reordering, lint and code-health refactors, and `origin/main` rebase
  adjustments do not require rebuilding `0001-upstream-candidates.patch`. Only
  backport to `stack-patches/v0.23.3/executor-project-integration` and
  re-qualify the packaged image on both Docker and rootless Podman if Phase 2 or
  Phase 3 uncovers a runtime or security defect that also affects v0.23.3.
