# Use the SSH executor for chat shells and project work

Status: in progress. The wrapper passes applied project destinations to both
clients. Hermes consumers, Docker tests of the Hermes branches, and packaged
qualification are pending.

- Wrapper branch: `executor-access-consistency`. Compare the complete change
  with `a6a6f642a2a02c9e28f9d660839bd3c869ae6e9e`. The plan under review
  started at `35b8f54517816c44fd4fdfa534db38cb2dd27cac`.
- Packaged Hermes: v0.23.3, source `caafe5389ae585ef77387a962aee05b1bcf17029`.
  The combined release replay starts at `553cd75ac4da1c4e9cef7479d1962a026c593cda`.
- Upstream working clone: `upstream_work/hermes-agent/`. The submission base
  is `88a1c1f4b19d1bc2b9fe8db870dee9ba0803fad5`. Verify the refs against
  the [submission table](hermes-upstream-prep.md#1-branches-to-submit).

## Goal and boundaries

This plan covers shell placement in `make chat`, project discovery and
selection in chat and the WebApp, file and command operations, and scheduled
work that uses executor files. Resolve filesystem paths supplied by a model
or subagent in the executor, including in a chat with no selected project.
Run their commands and code, enabled inline skill shells, and scheduled
scripts as `runner` over managed SSH in both operator terminal modes. If
the executor is unavailable, report the failure before probing a path or
starting a shell in Hermes.

Hermes chooses where it stores profile configuration, project and job
records, transcripts, approvals, and staged uploads. A tool can request a
specific service, such as speech synthesis, while Hermes chooses the cache
file. The operator retains the administrative file API, the Agent terminal,
and plugin management. The model can use an explicitly staged artifact
through its owning interface. Supplying a local pathname cannot grant that
access. An optional operation may refuse a request before any local file
access or command and leave its stored records available.

Executor-only cwd fallback, filesystem races that stay inside the executor,
linked-worktree discovery parity, stale entries after an empty repository
scan, and notebook rendering semantics are outside this work. Preserve the
existing file guards when enabling SSH edits. Broader media support, skill
management interfaces, and delegation recovery diagnostics are separate work.

Keep the deployed mounts, runner permissions, Tor routing, exact network
grants, pinned host key, and disabled SSH forwarding. Preserve authenticated
WebApp access, browser content policy, and operator plugin management. Use
existing SSH file and command operations. Preserve the skill, credential,
cache, and tool RPC boundaries in the
[architecture guide](../architecture.md#code-execution-and-ssh-isolation).

Use local branches and disposable fixtures. Deployment to an operator stack,
publishing, pushing, live financial operations, and destructive changes to
operator data require separate authorization.

## 1. Apply project grants and align shell and file operations

### Deliver the applied destinations to every client

`scripts/stack.py` validates the source and destination pairs at `make up`.
`scripts/project_mounts.py` builds a temporary executor-only Compose overlay.
`make chat` starts a separate Hermes container with `run --rm --no-deps`;
it does not reuse that overlay.

- Give the gateway and one-off CLI the same administrator-owned list of
  executor destinations. At startup derive it from the validated mounts.
  For a new CLI, read the project destinations attached to the running
  executor using the host-side mount inspection in `scripts/stack.py`.
  Serialize paths as data. Keep host source names, the engine socket, and
  bind mounts out of Hermes. Use existing managed configuration and container
  metadata. No second editable project list or persistent grant database is
  needed.
- Include `/workspace` and each exact attached destination, including valid
  nested destination spellings. A grant covers its descendants. A common
  parent, a path with a similar prefix, a project record, and the contents of
  a directory in the executor cannot confer a grant. Distinguish a verified
  empty mount list from unavailable or malformed policy. Gate operations
  that need the list independently of inspection, shutdown, and recovery.
- Apply the documented [share lifecycle](../configuration.md#shared-project-setup).
  Check both clients before and after editing an unapplied setting, adding a
  share, replacing a source, clearing all shares, and recovering a stopped
  executor. Include a nested destination with a similarly named sibling and
  literal dollar signs or spaces. Verify that a profile or dotenv override
  cannot manufacture a destination.
- For a partially stopped or started stack, document the existing
  [whole-stack recovery procedure](../configuration.md#applying-configuration-changes).
  Close one-off chats and run `make down`. If shutdown fails, correct the
  error and repeat it. After shutdown completes, correct any startup error,
  run `make up`, and reopen chat. Check both clients' grants after one
  representative interrupted startup and recovery. Individual service
  reattachment and continued operation through a partial deployment are
  outside the supported workflow.

### Place operator shells

Use the administrator-owned mode derived from `WEBAPP_TERMINAL_ENVIRONMENT`.
Code mode runs operator commands in the executor at the session's executor
directory, defaulting to `/workspace` for a new session. Agent mode keeps
the administrative Hermes shell. An unmanaged upstream CLI keeps its native
behavior even when a profile selects executor terminals for the WebApp.

- Trace the classic CLI's `bang_shell`, the native TUI's `shell.exec` and
  its shared gateway and sidecar handlers. Cover standalone `!cmd` and the
  TUI's `{!cmd}` interpolation. Preserve each interface's approval or
  refusal rules, redaction, exit status, output, and interruption behavior.
  Standalone commands start no model turn. Successful interpolation sends
  the message with the returned output to the session that submitted it.
  Verify the model receives that marker. An RPC refusal cancels the whole
  submission, retains the input for editing, and starts no turn.
  Keep the shell RPC restricted to its authorized local operator session.
  Preserve plugin commands in either mode.
- Check a saved `quick_commands` shortcut of type `exec` through the classic
  CLI and the TUI, including gateway-owned dispatch. These handlers launch
  shells independently of `!`. A project shortcut uses the executor or
  reports that it is unavailable. A saved name and command do not identify
  an administrative request. Use Hermes only when the invocation explicitly
  selects the operator's administrative shell. Otherwise use SSH or refuse.
  Test the same shortcut in both modes and document where it runs.
- Drive both interfaces through `make chat`. Check `!pwd`, `!id -u`, Git
  status and diff against the WebApp Code terminal, and the cwd after a
  project switch and resume. Use the session's remembered executor cwd
  after a model terminal `cd`. Obtain it from the owner of the session when
  the CLI runs in a separate process. Test accepted literal paths with spaces,
  Unicode, and shell metacharacters. Retain stricter input rules on callers
  that document them. Verify denial starts no shell and Ctrl+C stops the
  remote foreground command. Test SSH outage, missing key or SSH config,
  host-key mismatch, invalid cwd, and recovery. In the managed deployment,
  missing or invalid placement must start no shell in either interface.
  Check both unmanaged interfaces against their upstream defaults. Attempt profile YAML
  and dotenv overrides of the mode and `TERMINAL_SSH_*` settings. Verify
  the endpoint, identity, and host-key trust still come from managed policy.
- Edit Code to Agent in `.env` and open a new `make chat` before applying it.
  Use the running deployment's mode or refuse the mismatch before launching
  a shell. An unapplied edit must never open an administrative shell.
  Switch Code -> Agent -> Code with `make up`, reload the WebApp, and reopen
  chat. Check model command placement with a real tool turn in each mode.
  Update [Getting Started](../../README.md#getting-started), the
  `.env.example` comment for `WEBAPP_TERMINAL_ENVIRONMENT`, and its
  [configuration entry](../configuration.md#webapp-terminal-environment)
  with the apply and reopen steps. Update the [executor review commands](../configuration.md#reviewing-changes-in-the-executor)
  and [terminal guide](../webapp.md#terminal-environment) with qualified
  examples for the operator shell and the model's terminal tool.
- In the authenticated WebApp, restrict the model's `read_terminal` call
  to a verified executor terminal available to the requesting chat. Check the
  selected terminal when the renderer answers, including saved gateway tabs.
  Refuse the read if its placement or ownership is unknown. Put different
  markers in Code and Agent terminals, switch tabs, and request both visible
  output and scrollback. Verify the Code read returns its marker and the
  Agent read is refused before the buffer is serialized.
  Preserve the operator's ability to select Agent output and send it to chat.
  Cover the renderer dispatch and update `tests/desktop_tools_smoke.py`
  alongside the terminal guide.

### Protect existing files when enabling structured edits

For SSH file tools, apply the `HERMES_WRITE_SAFE_ROOT` check in the executor's
filesystem using `/workspace` and the exact applied `CODE_EXECUTOR_BIND_MOUNTS`
destinations. Keep the local `/opt/data` write guard for operations that
already have permission to use Hermes storage. Passing that guard does not
authorize a model to select a Hermes path.
Resolve relative paths, file versions, symlinks, and the parent of a new file
on the backend that performs the write. Cover `write_file` and every path in
a patch, including moves. Preserve credential denials, instruction-file
approvals, and local write restrictions. Mounts, permissions, and container
isolation enforce the security boundary.

- Trace `tools/file_tools_write_guards.py`, `file_tools_read_tracking.py`,
  and the pre- and post-edit bookkeeping in `agent/tool_executor.py`.
  A whole-file replacement needs a full, current, unredacted read or the
  existing equivalent write baseline. Use executor metadata and bytes for
  existence, read deduplication, and staleness. An SSH error cannot establish
  that a file is new.
- Apply existing device, credential, and redaction checks to executor paths
  in `read_file` and `search_files`, including individual search results.
  With different symlink targets in the two containers, verify permitted
  executor content remains readable and protected fixture content stays out
  of tool results. A failed SSH lookup cannot select a Hermes path.
- Check new files, blind overwrites, partial and redacted reads, a full read
  followed by an edit, and stale reads. Change the file between calls with
  a host editor or another session, including creating a previously missing
  file. Check symlink escapes, denied siblings, and a differing file at the
  same path in Hermes.
- Replace the old bind-write denial in `tests/project_mount_lifecycle.py`.
  Through both `make chat` and WebApp chat with default approvals, create
  and patch an ordinary project file. Check its bytes on the host and verify
  that neither edit requests approval. Check that editing `AGENTS.md`
  requests approval and that a write to an ungranted sibling is refused.
- Use the shared project permission fixtures for the SSH file tools and the
  WebApp editor. After file creation or replacement, reopen and edit the
  file as the host user. Save a host-owned executable through each writer
  and verify that it retains its executable bits and the two users' intended
  access. On Linux, check the ACL and its effective mask using the native
  Docker runner UID and Podman's mapped UID. In a granted directory where
  the runner lacks write permission, verify the write fails and leaves the
  file intact. Preserve operator permissions when replacing files.
- Update the [README sharing workflow](../../README.md#sharing-directories-with-private-hermes-agents)
  and [shared project permissions](../configuration.md#shared-project-filesystem-permissions)
  to explain when shares take effect and which edits proceed without a
  prompt. Cover protected files and runner permissions. Document the local
  and SSH write guards in the [architecture guide](../architecture.md#hermes-capability-boundary).
  Keep `.env.example` and the setup guide clear that the wrapper derives
  write roots from applied mounts. The operator configures shares once.
- The checkpoint manager uses a container-backend predicate that excludes
  SSH. Unless it can take and restore an executor snapshot through existing
  facilities, explicitly report that SSH checkpoint and rollback are
  unavailable. Cover automatic checkpoints, session diff, and explicit
  restore with checkpoints enabled. Verify both checkouts remain intact on
  refusal. Working-tree Git diffs are covered in phase 2.

## 2. Keep project selection, review, and model work in the same checkout

### Select, switch, discover, and resume

- Discover Git repositories under `/workspace` and the applied destinations
  over SSH. Respect discovery settings and limits. Reconcile scanned,
  client-reported, cached, and session-derived results against the current
  grants. Keep manual registration for non-Git projects. Preserve history
  after removal, mark the folder unavailable for work, and let the operator
  select an available project. Revalidate metadata and instructions after
  a destination is remapped.
- In `tui_gateway/methods_projects.py`, check saved session directories
  against the applied roots before passing them to `git_probe.warm_roots`.
  Use SSH for Git metadata on admitted paths. List projects and sessions
  with a removed destination and different branches at the same path in
  both containers. Verify the sidebar shows the executor branch and that
  `tui_gateway/git_probe.py` never stats or runs Git in the Hermes checkout.
- Trace project creation, primary and additional folders, switching, and
  listing through the WebApp, `desktop_project`, and the session callback.
  Check session creation and turn readiness in `gateway/session_policy.py`,
  runtime cwd resolution, and both CLI and WebApp resume. Validate the
  executor directory before reporting a successful switch. Update only
  that chat's working directory. On failure, report it and preserve the
  previous selection. No placeholder project directories in Hermes.
- Use **New folder** in the WebApp project picker. It lists directories
  through the SSH file API, but sends creation to the Hermes-local
  `/api/files/mkdir` handler. Create a folder under an applied bind through
  the picker, select it, and start a chat there. Verify creation on the host
  and the absence of a write in the Hermes checkout. Keep the administrative
  file API available for Hermes-owned files.
- Use discovered and manually registered projects in two concurrent chats.
  After create, switch, and resume, check the selected project, sidebar
  grouping, branch, and the next relative read, edit, and terminal command.
  Inspect the first prompt sent to a delegated child. Its workspace hint and
  project instructions in `tools/delegate_tool_progress.py` must come from
  its executor project even when only the executor has that directory.
  Continue a delegated child after its parent switches projects. Check
  `tools/delegate_tool_resumable.py` and child startup use the child's
  saved executor directory. Repeat with a removed share and after recovery.
- Trace the worktree probes in `tools/delegate_tool_resumable.py` at child
  creation, progress checkpoints, and stop. They can invoke Git in Hermes
  even with worktree isolation disabled. Collect executor facts through SSH
  or skip unavailable worktree metadata. With different repositories at the
  same path, verify that recording and continuing the child neither probes
  nor runs Git in the Hermes checkout. Preserve its Hermes-owned session record.
- For `delegate_task(images=...)`, trace `_build_child_goal_message` in
  `tools/delegate_tool_child_run.py`. Read model-supplied image paths over
  SSH or refuse them before any Hermes file lookup. Check both the image
  bytes in a vision child's first request and the path hint sent to a
  text-only child. Use different images at the same path, an executor
  outage, and an explicitly staged upload. A Hermes-only file must supply
  neither image bytes nor an existence hint.

### Use the selected project for context, Git, and WebApp files

- Load project instructions only for a selected workspace and within its
  current grant. Preserve upstream trust, precedence, size limits, scanning,
  and safe-mode or skip-context rules. Cover the Git-root-to-cwd instruction
  chain, overrides, nested instructions first visited during a tool call,
  rebinding on switch, and the files listed by `/context`. Check the
  system prompt's Git and manifest facts in `agent/coding_context.py`.
  Keep profile-owned context in Hermes.
- Exercise `/init` through the chat interfaces. Its prompt builder in
  `hermes_cli/init_command.py` checks for and reads `AGENTS.md` separately.
  Inspect the submitted prompt for the executor file's contents and write
  target. An executor project without that file should get a creation prompt
  even if Hermes has a copy. Refuse the operation when SSH is unavailable.
- Completion and submission must agree about `@file`, `@folder`, `@diff`,
  `@staged`, and `@git`. Trace the gateway and TUI prompt paths into
  `agent/context_references.py`. Inspect what the model receives, including
  relative paths, missing files, and out-of-root symlinks. Preserve explicit
  staged uploads, plugin references, and the managed URL no-fetch setting.
- Run project Git inspection and mutations in the executor. Trace the
  browser bridge through `/api/git/*`, `hermes_cli/web_git.py`, and the
  independent CLI `/diff` implementation. Cover status, staged and
  unstaged diffs, staging and unstaging, branch switching, and worktree
  creation and removal through their normal UI. Check paths passed to the
  shared Git runner, including worktree targets. Keep Git's
  ownership checks, hook and filter protections, and existing confirmation
  rules. Surface unavailable Git or provider operations explicitly. Use
  scratch repositories and local remotes for mutations.
- Resolve relative file links, previews, saves, and downloads against the
  requesting chat's executor directory. Check `web_routers/files.py` and
  `ssh_workspace_fs.py` with two chats containing different `note.txt`
  files. Compare the bytes shown, saved, and downloaded with the matching
  checkout in both terminal modes. Preserve ticket ownership, staged-file
  access, and the WebApp external-content ceiling.
- Check ordinary gateway replies as well as scheduled delivery. In
  `gateway/platforms/base.py`, media directives and inferred file paths
  can select a Hermes file before the remote fetch. Resolve model-supplied
  paths in the executor or decline delivery. Preserve explicitly staged
  uploads and Hermes-generated media through their owning interfaces.
  Use a local delivery adapter with no project selected. Inspect delivered
  bytes for a path present on both sides, then verify that a missing
  executor file or SSH outage never delivers the Hermes copy.

### Check optional operations that accept an executor project

These operations have independent implementations. Use an existing SSH
operation where it fits, or refuse the project operation at its entrypoint.

- For `/goal gate`, check the result against a project where the command
  fails in the executor and passes in Hermes. The goal must use the
  executor result or pause before running the Hermes shell.
- For classic `/worktree`, cover the local Git paths for new, list, and
  prune, including exit cleanup. Apply the same placement decision when a
  chat launcher creates or restores a project worktree.
- Trace Kanban board defaults, explicit task workspace paths on a board
  without a project, and paths in saved tasks through dispatch and cleanup.
  Check `hermes_cli/kanban_db_workspace.py` before directory creation or
  Git worktree operations. Use SSH for executor workspaces or refuse the
  task before probing the Hermes path. Verify that a same-named Hermes
  checkout stays untouched and that the operator can still inspect the
  board and task after refusal.
- The Kanban notifier can deliver saved events even with worker dispatch
  disabled. Pass a queued completion or review event through the notifier
  with an executor artifact path present on both sides. Check both event
  attachments and paths extracted from saved task results. Deliver executor
  bytes to the local adapter or decline before probing a Hermes path.
  For supported workers, check the bytes copied by
  `kanban_db._stage_completion_artifacts` before workspace cleanup.
  Preserve delivery of previously staged files through their attachment records.

### Run Python and skill shells in the executor

- In `code_execution.mode: project`, direct Python file access from
  `execute_code` starts in the current executor project. Keep kernel
  control files and RPC material in their private staging directory. Check
  the persistent kernel and per-call fallback against the same working
  directory and document the interpreter actually used. Test relative
  reads and writes, retained kernel state in one project, a project switch,
  two sessions, and the existing temporary directory in strict mode.
- Keep `skills.inline_shell` opt-in. When enabled, eligible inline snippets
  run over managed SSH in the executor, including when the operator
  terminal is in Agent mode. Route the shared skill preprocessor used by
  `skill_view` and slash or preload invocation. Preserve the hosted-worker
  refusal, hub provenance checks, and project skill trust settings. Selecting
  a project or loading its `AGENTS.md` never grants skill execution.
- Use the executor-visible skill directory for the shell cwd, relative
  resources, and `${HERMES_SKILL_DIR}`. Reuse the skill sync mapping for
  profile skills and the selected executor checkout for trusted project
  skills. Use that same directory in the returned skill path and supporting
  file instructions so a subsequent tool call can run the helper. Keep
  profile installation and trust metadata in Hermes. Resolve
  trust before expansion. Refuse an unmappable directory or SSH failure
  before executing the snippet. Preserve the configured timeout, bounded
  output, and exit diagnostics. Do not forward the Hermes process environment.
- For a trusted project skill, scan and read the executor's skill and linked
  files. Viewing a skill with declared dependencies can call `pm.ensure` in
  Hermes even with inline shell disabled. Verify that a project skill with
  a missing executor dependency reports it without preparing packages in
  Hermes.
- Check `_skill_readiness` in `tools/skills_tool.py` before it prompts
  for secrets or registers environment variables and credential files for
  SSH synchronization. A project manifest that the executor can edit
  cannot authorize a transfer from Hermes. With inline shell disabled,
  have a project skill declare a dummy profile file and variable that the
  operator has not approved. Verify no prompt or registration occurs and
  that neither value reaches a subsequent executor session. Check that an
  operator-authorized profile integration still receives its declared inputs.
  Explain this distinction in the architecture guide's SSH isolation section.
- Use an eligible skill with a relative helper and different marker files
  on the two sides. Verify runner identity, cwd, helper output, and
  executor-only side effects via model and operator skill invocation.
  Exercise disabled inline shell, community or untrusted skills, missing
  remote helper, nonzero exit, timeout, outage, and recovery. Confirm each
  snippet runs once per invocation and timeout stops the executor command.
  Verify denied credentials remain inaccessible.
  In [shared project setup](../configuration.md#shared-project-setup),
  explain project selection, resume, and what the operator sees after a
  share is removed. In [WebApp operator authority](../webapp.md#operator-authority),
  distinguish project files and attachments from explicitly staged files.
  In [SSH isolation](../architecture.md#code-execution-and-ssh-isolation),
  describe child and scheduled execution, supported tool access, and the
  refusal behavior for optional operations that cannot use SSH.

## 3. Run scheduled project work and handle its output

- Keep job records, schedules, and run history in Hermes. Resolve a job's
  explicit workdir in the executor on create, edit, and each dispatch.
  `cron/jobs.py` validates locally today and `cron/scheduler.py` can drop
  a missing directory and disable project instructions. A prompt-only job
  with a project must use its executor cwd, instructions, and tools. A
  missing or removed project fails the run visibly. Preserve the default
  behavior of jobs that omit a workdir.
- Check `hermes cron doctor` after copying a script into the executor.
  Its script and workdir probes in `hermes_cli/cron.py` inspect Hermes
  paths. Check the executor or report that its health is unavailable.
  A same-named Hermes file cannot establish job readiness. Keep job and
  history inspection available during an SSH outage.
- Trace the cron tick independently of job dispatch.
  `_worktree_maintenance_repos` collects registered repositories and job
  workdirs for a Hermes-local Git probe and prune. Keep executor-owned
  paths out of the local maintenance registry and sweep. Preserve maintenance
  for Hermes-owned repositories. Trigger the sweep with same-named checkouts
  and verify the executor job causes no local probe, archive, or removal.
- Run script-only jobs, pre-run scripts, and monitor scripts in the executor.
  Use `/workspace/cron/<profile>/scripts` in Private Hermes. Use `default`
  for the default profile and Hermes's validated, normalized profile name
  for a named profile. Derive it from the job's owning profile at each
  dispatch. Keep this deployment path in wrapper configuration. Use the
  same root in tool descriptions, creation, editing, lifecycle guard
  inspection, and execution. Resolve relative script names under that root.
  Check absolute paths, tilde expansion, symlinks, and interpreter paths in
  the executor. Keep scripts confined to that profile's script root. Treat
  an explicit project workdir separately from the location of the script.
- Cover scheduled, manual, and worker runs after restart in both operator
  modes. Use distinct scripts at the same path in both containers. Verify
  script-only delivery, pre-run wake decisions, monitor behavior, ordinary
  prompts, exit failures, missing interpreter, cancellation, timeout,
  remote descendant cleanup, SSH outage, and recovery. Use real model-tool
  cwd and instruction markers for a prompt-only job. Preserve the original
  job and history when a dependency is unavailable.
- In `cron/scheduler_delivery.py`, distinguish executor-produced attachment
  paths from Hermes-generated audio and staged media. Fetch eligible script
  artifacts through the managed backend and apply existing media checks
  before delivery. An executor path must never select a same-named Hermes
  file. Verify delivered bytes, denied and missing files, ordinary stdout,
  and redaction using a local delivery adapter. Keep the model-facing
  speech tool on the profile audio cache and enforce that at dispatch for
  stale calls supplying an output path. Preserve explicit destinations for
  internal voice callers. Test attachment and internal playback with
  controlled audio.
- Document the release that moves script lookup from the Hermes profile
  to the executor. Preserve saved jobs, history, and original profile
  scripts. A due job uses the file at its configured executor path.
  Show operators how to check the destination, place the intended script
  before starting the upgraded gateway if a job is due, and verify its
  interpreter and workdir. If the file is missing, report the expected
  executor path. Operators maintain script contents and paths. Hermes keeps
  its native scheduling behavior. A failed one-shot can consume its
  occurrence. The operator can inspect history before scheduling another.
  Exercise the manual copy on a populated prior-release fixture and link to
  the [backup scope](../configuration.md#backup-scope) for both stores.
  Include a saved absolute script path and a `~`-prefixed monitor path from
  a named profile. Show how to edit the job when its stored path or Python
  interpreter names the old Hermes location. Put the release-specific steps
  in [Apply stack updates](../updates-and-plugins.md#apply-stack-updates)
  and link them before the startup command in [Updates and Backups](../../README.md#updates-and-backups).
  Document the two script locations in [Persistent data layout](../configuration.md#persistent-data-layout).

## Release replay and upstream submissions

Use local worktrees in the working clone. Compare each change on the pinned
release and the submission base. A fix already present on one base needs
its regression check there and a patch only on the base that lacks it.
Keep native tests and upstream user documentation with their owning
commits. Wrapper-only Compose inputs, host path validation, fixed mount
destinations, Dockerfile changes, and deployment defaults belong here.
In Hermes's `website/docs/user-guide/`, update the CLI shell mode and
checkpoint and rollback guides, and the feature guides for code execution,
delegation, Kanban, skills, and cron where their behavior changes. Correct
host-only shell messages in the TUI and tool descriptions where SSH is
supported. Keep generic SSH guidance independent of Private Hermes paths.

| Upstream owner | Changes to place there |
| --- | --- |
| PR4b, `feat/webapp-executor-terminals` at `703b3f869`, based on PR1 and PR4a | Managed operator shell selection and WebApp terminal reads. Reuse terminal placement and SSH trust readers. Keep PR4a scoped to literal SSH and OSC 7 cwd handling. |
| PR2a, `fix/ssh-workspace` at `734837a9f`, based on submission main | SSH file-state checks, overwrite protection, and checkpoint eligibility. Keep deployment grants and project features in their own changes. |
| Proposed `feat/ssh-project-workspaces` | SSH write roots and file permissions, project context and Git, WebApp files, delegation, gateway attachment delivery, Kanban workspaces, and remote Python project cwd. Separate commits by consumer. |
| Proposed `feat/ssh-skill-shell` | Skill shell dispatch, project skill trust, credential passthrough, cwd mapping, and native skill tests. Reuse SSH and skill synchronization. |
| Proposed `feat/ssh-cron-execution` | Cron workdirs, scripts, validation, cancellation, and executor artifact delivery. Reuse session project context where required. |
| Proposed `fix/tts-output-placement` | Model speech schema and dispatch, with coverage for internal callers. Independent of SSH and cron. |

Start proposed topics at submission main unless they use an unmerged
prerequisite. Record the exact dependency and review base before the first
commit. Use PR1 (`fix/managed-config`) for its existing managed configuration
contract and PR2b (`feat/ssh-client-config`) wherever an implementation
consumes its explicit OpenSSH configuration. Keep PR3a and PR3b scoped to
desktop and browser execution, PR5 to URL fetching, PR6 to managed tool
denial, and PR7 deferred. Preserve existing local-backend behavior for
unmanaged Hermes users when adding SSH-specific placement. Test the
dispatcher and skill preprocessor in both configurations.
Check overlapping code on the combined tree.
Add a dependent branch only when its diff requires the prerequisite. Avoid
copying prerequisite commits into sibling review diffs.

Maintain release topic refs under `stack-patches/v0.23.3/`. Put operator
terminal work on `executor-terminals`. The existing release SSH fixes live
on `executor-desktop-browser`. Give new independent topics matching release
refs based on the release pin and the release versions of their dependencies.
Combine each prerequisite once on `combined`. Preserve existing histories
and record exact topic, base, and combined SHAs for both source trees. Follow
the [candidate patch workflow](../update-workflow.md#rebuild-the-candidate-patch-for-a-new-release)
to export the production diff to `0001-upstream-candidates.patch` and check
the full downstream series. Verify every changed runtime module in the
**final** image, particularly `cron/` and any top-level Python modules.
If TUI source changes, rebuild and install the bundle that `make chat`
launches. Check the shipped WebApp assets as well.
Update the [patch inventory and removal conditions](../updates-and-plugins.md#downstream-responsibility-inventory)
and [managed configuration](../updates-and-plugins.md#managed-container-config-and-executor-packaging)
to match the final image. Recheck the documented reason for the empty Hermes
`/workspace` once session validation uses SSH.

## Qualification and completion

### Phase 1 progress

- Wrapper `fa21d048ed165201f0af4be393a37d51e72aed8f` transports the exact
  attached roots through managed config. `make chat` checks the running
  gateway's policy against the executor and uses the applied mode.
- `make check` passed 242 tests, Compose model validation, and Python
  compilation. `make help`, the local Markdown link check, and
  `git diff --check` passed.
- A network-disabled Compose fixture passed on macOS Docker Desktop 29.9.3
  and on Linux ARM64 ext4 with Docker 29.10.0 and rootless Podman 5.4.2.
  Each engine used Docker Compose 5.7.1. The fixture compared the raw Hermes
  policy on both containers for nested paths with spaces, dollar signs, and
  Unicode. It also checked an unapplied mode edit, a concurrent one-off
  container, stopped and mismatched executor refusal, and clearing all shares.
  The fixture exercises the host launcher with a test entrypoint. Full stack,
  actual chat, and browser checks remain pending.
- Independent design and wrapper reviews identified one-off service selection
  and YAML Unicode round-trip failures. Compose now excludes one-off
  containers from service selection, and the two YAML inputs preserve literal
  paths. The Hermes consumer must read the strict raw managed config and
  verify that a conflicting profile dotenv value cannot expand a path.

### Completion checks

1. Obtain independent design review before implementation. Confirm each
   call chain and its upstream owner. For each distinct path that can read,
   write, or run a command on the wrong side, use one stable placement test.
   Use an executor-only directory to expose local existence checks, or put
   different markers at the same path in both containers. Verify the bytes
   read, the file changed, or the command's execution location. Repeat with
   SSH unavailable where a local fallback is possible. Reuse the result
   for callers that share the tested path. Use isolated state, dummy
   credentials, SSH, and local inference, audio, or delivery fixtures.
   Recheck each phase independently before building on it.
2. Build the derived image through the wrapper. Run `make check`, `make test`,
   `make hermes-ui-test`, and `make webapp-test`. Extend the
   [project mount lifecycle tests](../development.md#project-mount-tests)
   and [terminal tests](../development.md#code-terminal-qualification) for
   the actual `make chat` entrypoint and authenticated browser. Exercise
   the changed paths, including lean and desktop mount fixtures, on local
   macOS Docker Desktop with APFS. Via `ssh debvml`, repeat the checks on
   native Linux Docker and rootless Podman (`CONTAINER_ENGINE=podman`)
   using ACL-capable Linux project directories on that host. Make the tested
   wrapper commit and the upgrade fixture's prior revision available to the
   lifecycle test on each host. Drive native TUI chat with a PTY and
   `display.interface: tui` in a disposable profile. Verify the intended
   renderer starts. Exercise classic chat separately. Serialize projects
   sharing networks. Record engine, Compose provider, filesystem, exact commands,
   results, and gaps. Independently review the packaged operator terminal
   change and three-engine evidence before adding it to PR4b.
3. **Run Hermes's own tests inside Docker.** For each changed submission
   tip, each dependent tip whose review base changes, and a combined tree
   built from those exact tips, run `python3 scripts/check` and
   `scripts/run_tests.sh` in a disposable Linux Docker container. Run the
   changed Python modules and nearby regression suites with the upstream
   runner during development and the full runner on the final tips.
   For changed renderer code, use the pinned pnpm and frozen lockfile,
   then run the affected workspace's typecheck and Vitest suites
   (`pnpm --dir ui-tui run typecheck`, `pnpm --dir ui-tui test`, or the
   corresponding `apps/desktop` commands). Use the repository's build
   prerequisites for each workspace. Run affected native regressions on
   the release replay as well, including on the combined release head.
4. Follow the [Docker test environment](../development.md#local-upstream-candidate-qualification):
   use `--init`, the unprivileged `hermes` user, an isolated home, a
   disposable source checkout at the SHA under test, and locked test
   dependencies. Include the history needed for `scripts/check` to find
   its review base, or pass the base commit explicitly. Keep operator data
   and the engine socket out of the test
   container. Record the image identity, architecture, commands, counts,
   skips, and failures per SHA. Reproduce broader failures on the exact
   unchanged review base in the same Docker environment. Resolve new
   failures before treating a tip as qualified. Rerun affected tests after
   a fix or restack, including on the combined tree and in the packaged
   stack if the release replay changes.
5. **After the branches are updated and tested**, update
   [hermes-upstream-prep.md](hermes-upstream-prep.md#1-branches-to-submit)
   in place. Update the submission table, review bases and merge order,
   topic scopes, v0.23.3 build provenance, and qualification results.
   Add rows for new submission and release topics. Reconcile exact SHAs,
   commit counts, included dependencies, and limits with the candidate
   patch header and the local drafts in `upstream_work/submissions/`.
   Update the drafts' branch instructions and Docker test results for every
   affected topic. Keep raw logs in ignored storage and report any missing
   evidence explicitly.
6. Record phase commits, evidence, review findings, and remaining work
   in this plan as implementation proceeds. Obtain fresh combined review
   against the wrapper starting commit and both tested Hermes trees.
   Update the [project mount](../development.md#project-mount-tests) and
   [terminal qualification](../development.md#code-terminal-qualification)
   sections with results and gaps for each engine. Before removing the plan,
   check maintained guides, examples, and CLI help for superseded advice
   about project edits, shell placement, and script paths. Verify local
   links and anchors. Remove the plan after the
   [completion checks](../planning-workflow.md#resolve-findings-and-finish).
