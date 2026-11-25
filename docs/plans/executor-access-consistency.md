# Use the SSH executor for chat shells and project work

Status: in progress. The integrated Hermes v0.23.3 candidate routes project
work and scheduled scripts through the managed SSH executor. Final release
checks, native submission topics, and combined review remain open.

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
| PR4b, `feat/webapp-executor-terminals` starting at `703b3f869`, based on PR1 and PR4a | Managed operator shell selection and WebApp terminal reads. Reuse terminal placement and SSH trust readers. Keep PR4a scoped to literal SSH and OSC 7 cwd handling. |
| PR2a, `fix/ssh-workspace` starting at `734837a9f`, based on submission main | SSH file-state checks, overwrite protection, and checkpoint eligibility. Keep deployment grants and project features in their own changes. |
| Proposed `feat/ssh-project-workspaces` | SSH write roots and file permissions, project context and Git, WebApp files, delegation, gateway attachment delivery, Kanban workspaces, and remote Python project cwd. Separate commits by consumer. |
| Proposed `feat/ssh-skill-shell` | Skill shell dispatch, project skill trust, credential passthrough, cwd mapping, and native skill tests. Reuse SSH and skill synchronization. |
| Proposed `feat/ssh-cron-execution` | Cron workdirs, scripts, validation, cancellation, and executor artifact delivery. Reuse session project context where required. |
| `fix/tts-output-placement` | Model speech schema and dispatch, with coverage for internal callers. Independent of SSH and cron. |

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
  The fixture exercises the host launcher with a test entrypoint.
- Independent design and wrapper reviews identified one-off service selection
  and YAML Unicode round-trip failures. Compose now excludes one-off
  containers from service selection, and the two YAML inputs preserve literal
  paths. The Hermes consumer must read the strict raw managed config and
  verify that a conflicting profile dotenv value cannot expand a path.
- Native Docker on Linux passed the lean project lifecycle with
  `--prior-ref a6a6f642a2a02c9e28f9d660839bd3c869ae6e9e`. The fixture reads
  the applied policy inside a PTY-launched `make chat`, checks recovery and
  clearing, and opens and writes through an authenticated Code terminal.
  Chat shell behavior and renderer readiness need their own checks. Full
  project lifecycle coverage on Docker Desktop and rootless Podman remains
  open. The Podman run stopped during source admission for `/run`. Its retry
  stopped while creating the Tor uplink network during the prior-release setup.
- Linux Docker passed `make test` and `make hermes-ui-test` (218 renderer
  tests) with the rebuilt checkpoint package. The prior revision and the
  retry after firewall approval both timed out waiting for the browser chat
  to show `ready`. The shared test overlay left the fresh profile's model
  unset. With the deterministic local model selected, `make webapp-test`
  passed on Linux Docker, including authenticated terminal streaming, chat,
  and all four content modes in Chromium, Firefox, and WebKit. The Docker and
  Podman Compose models also select that model with the operator's
  `TEEP_ENABLED=false`.
- The checkpoint changes are in `fix/ssh-workspace` at
  `76f7e68e2a74a3ef021cf446335dd3fa5cb8b600`. The release topic is
  `3aa5db2279f56e891e4e5108028e7603a129e7f1`, and the combined release
  replay is `da4ad13358a0595febabf7dcf8e85fca6a7a0d15`. The focused Python
  suite passed 699 tests on each source tree in Linux ARM64 Docker as UID 10000.
  `scripts/check` passed all 22 checks for the production source change.
  The TUI and Desktop type checks passed with Node 26.12.1 and pnpm 12.15.0.
  The submission TUI passed 2,015 tests and the Desktop UI passed 14,260.
  Whole-branch Python suites and final combined qualification remain open.
- Independent checkpoint reviews checked early refusal, both automatic tool
  hooks, local checkpoint retention, and routed undo. The explicit
  `verification.status` RPC still needs executor-backed project facts in
  phase 2.
- The local operator shell topic is `feat/webapp-executor-terminals` at
  `f5aecfefcf3cb4e747e65af7f80138a71c5a5810`. The release topic is
  `a931426be527c14eeb73e0181d5ea14165d23b42` and the combined release replay is
  `e1d5320d2cd6095f25e67004b1bcd1586258f14a`. Each tree passed 90 focused
  Python tests before the final TUI-only change. The submission TUI passed
  123 focused tests and type-checking with Node 26.12.1 and pnpm 12.15.0.
  The build of replay `259412299` matched the 12 changed shell Python modules
  and passed Node syntax checks for both installed TUI entrypoints. The final
  shell package built successfully and carries matching TUI bundles. The
  disposable OpenSSH fixture on Docker Desktop verified the executor UID,
  literal directories, independent output streams, exit status, invalid
  directory refusal, foreground cancellation, and host-key refusal and
  recovery. Full `make chat` placement and engine checks remain open.
  The test VM's SSH forward at port 2222 refused the connection. Docker
  Desktop was serving the operator's project on the fixed stack networks.
- Independent shell reviews traced the gateway's route and profile checks,
  process cleanup, and placement errors. Follow-up changes protect shell syntax
  in collapsed paste chips, keep renderer updates with the submitting chat,
  keep restored shell drafts for operator review, and share the saved SSH cwd
  with model tools while its project binding holds.
- The WebApp terminal reader is on the local PR4b topic at
  `9fe9764f0c360aa02efb44716acdfe607ee4da79`. The release topic is
  `96adab1f9c9dfb6755e8cfe3bf2ebe4b28fea54b` and the combined replay is
  `de311262cab1760d4b6c63c0c8dd91d3a34be60d`. The native tests passed 147
  Python checks, the renderer type check, and 104 renderer tests. Independent
  review confirmed the focused chat, socket placement, and saved gateway
  checks after fixes for same-address routing edits, OAuth account changes,
  and competing answers from other viewers. The desktop tool matrix passed
  all four content modes with computer use enabled and disabled. The combined
  release passed the same 147 Python tests. The Docker Desktop ARM64 package
  built with matching TUI entrypoints, and all 13 changed Python modules match
  the full patch series. `make hermes-ui-test` passed the renderer type check
  and 271 tests against the packaged WebApp.
- Chromium 156.0.8078.4 on macOS passed the authenticated browser fixture
  against that image on Docker Desktop ARM64. The fixture used a separate
  internal network, OpenSSH executor, deterministic inference service, and
  loopback proxy. It checked both Code tabs, visible and bounded scrollback
  reads, refusal in Agent mode, and explicit sharing of Agent output through
  **Add to chat**. Saved gateway checks covered relay sockets and renderer
  dispatch. Full WebApp qualification on Docker Desktop and rootless Podman
  remains open.
- SSH `read_file` checks the requested and canonical paths on the executor
  and reads the page and digest through the same descriptor. Read baselines
  use the SSH endpoint and file version. The native topic is
  `eb93959ce81702c6156537a53d91b9c82f808546`, the release topic is
  `88e56b429ec2e283e1efd33a96236177de00fc38`, and the combined replay is
  `81c3873f1dee1ef919be6ee1b15870d92cb7a00d`. Both trees passed 129 focused
  tests with eight skips. The image built from this replay passed the Docker
  Desktop ARM64 OpenSSH fixture with separate Hermes and executor filesystems.
  The fixture checked canonical reads, credential and special-file refusal,
  pagination, and programmatic reads. The WebApp and TUI output hashes match
  the preceding shell package. The exported
  patch SHA-256 is `1f247348e2c7fa56b5a90d2e5b2509ed93a1b3b23fd05c22916c3c8d35f59bfc`.
  Managed write roots and shared file permissions remain in the workspace topic.
- SSH `search_files` checks candidate paths on the executor before matching,
  counting, or paging. It keeps filenames and diagnostics separate from
  matching lines. The native topic is `23be2f3b5705cc283dc564d272381d262d004f21`,
  the release topic is `ae43f3bcb093799a9d89d1d9c1d80e300fd12ea5`, and the
  combined replay is `ffc64df1dcd433cfa5efd5962df51f38a30972f1`. The combined
  tree passed 171 focused tests with eight skips. The exported patch SHA-256
  is `a51576f0955acfe5682c0e713e2b5a6f4bdd649896bc7b5f7246343f18e19d32`.
  The image build produced the same WebApp and TUI receipts as the guarded
  reader package. The Docker Desktop ARM64 image passed an isolated OpenSSH
  and BusyBox fixture for literal paths, hidden regular files, protected
  aliases, redaction, pagination, and multiple roots. Guarded recursive content
  search starts a matcher for each permitted file, which adds time on broad
  searches.
- Structured SSH edits inspect and verify executor files before staging changes.
  The native tip is `d4919743c0b0623ca26ca3178460a10283d4ef5c` and the release
  tip is `214381873955bbfef268b7ce69cb0174f3ce551b`. Combined head
  `88fbc94607e9d12e25959a7f13a8fb3f9c7a3d3b` exports 188 runtime paths with
  patch SHA-256 `95ab133bb93cb1496aa8ae564cb216ee3fa810a0101ebed2ea421e5caab70df8`.
  The native tests passed 279 with nine skips and the release tests passed 282
  with nine skips, including the speech placement tests. The Docker Desktop ARM64
  image passed the pinned Alpine OpenSSH probe with separate filesystems and
  the exact packaged modules. The probe checked complete and stale versions,
  instruction approval, protected file refusal, and V4A edits. An independent
  native review accepted the writer after checking entry and referent versions,
  redacted output, instruction aliases, and lint diagnostics. The managed
  grant and shared-permission changes follow in the workspace topic.
- The lean project fixture upgraded populated state on Debian ARM64 with
  native Docker 29.10.0 and rootless Podman 5.4.2. It verified classic chat and
  TUI shell and shortcut placement in Code and Agent modes, an authenticated
  WebApp write to the host project, and the return to Code mode. Docker used
  the guarded search package. Podman used the preceding classic shell package.
- The classic chat now reads the shell directory from its session owner in
  both managed modes. The local topic is `c4700df74951bf75dfb9bc5b2332c7f6397d98cc`,
  the release topic is `b20fe45d957aa561175138cc3e18e6aa220cb20c`, and the
  combined replay is `e814d30ab1180c0e1589f32c30965f2022ba6bc7`. The submission
  and combined release each passed 69 focused Python tests. An isolated
  Docker Desktop run used a separate gateway owner and OpenSSH executor. A
  model terminal `cd` changed the directory for the classic Code shell and
  for saved executor shortcuts in both modes. Linux ARM64 Docker 29.10.0
  passed `make test` and the Chromium, Firefox, and WebKit matrix in
  `make webapp-test` on wrapper `8de44f6f1a69f0717c218f8ec522d28696f89393`.
- Classic Ctrl+C stops the foreground SSH command and preserves the draft.
  Cancelling a wait for the session owner leaves the gateway free to
  reconnect. Ctrl+G sends shell commands and saved shortcuts through the
  REPL worker. Independent reviews checked command-palette and Backtrack
  priority, pending reconnect, and editor submission. The source and release
  both passed 156 focused tests before the follow-up for reconnect deadline
  expiry. The native topic is `506b54bd4afc3693de0a60828d2d0232b9f81903`,
  the release topic is `b886b1b648231e528a174a01c35f733548debf11`, and the
  combined replay is `58f19c2b7d7b98979a705910514567fa1053be80`. The updated
  native and combined trees both passed 45 focused tests. The tracked
  patch SHA-256 is `f88665db0f2aef4d6c204c7964c88e2b79b0343dd1820188e6cca7837ad2dd16`.
  A classic PTY on Docker Desktop ARM64 used the wrapper image and OpenSSH
  to verify foreground process termination, draft retention, and Ctrl+G
  submission for executor shortcuts in both modes and for a Code `!` command.
  The full `make chat` lifecycle test remains open.
- Linux ARM64 rootless Podman 5.4.2 passed `make test` and the Chromium,
  Firefox, and WebKit matrix in `make webapp-test` with the shell package from
  wrapper `1afca1c9a16be48e8940e1271d894aab943b9849`. A Linux Docker lean
  upgrade fixture passed classic and TUI commands in Code and Agent modes
  and a Code WebApp write to a shared project. The gateway remained absent
  from owner discovery after the final Code recreation in that fixture. A
  shorter Code to Agent to Code fixture passed on the same engine.

### Managed project workspace topic

The `feat/ssh-project-workspaces` grant and file-permission changes combine
PR1 `d4aa66920ce76794a580a877b6e4383ffc94b72d` with guarded writes on
PR2a `d4919743c0b0623ca26ca3178460a10283d4ef5c`. The WebApp editor uses the
configured SSH connection from PR2b `db7587772b60966eed365d0cce892be59c6d1273`.
The topics share main `88a1c1f4b19d1bc2b9fe8db870dee9ba0803fad5` and combine
at `0bf150642e637a644696d43c39e10e1cbc136014`. Their release equivalents are
PR1 `32abdfde7c1968d4d8ebd6cd3e16a3d35e4b04d7` and the SSH topic
`214381873955bbfef268b7ce69cb0174f3ce551b`, which carries PR2a and PR2b.

The native grant and editor commit is `b77fb13df8af4eeade3c7139b143801a21ea90da`.
The release topic starts at the SSH topic above and lands at
`999fec97543172e216642e43d2f597d43269da79`. Combined head
`667641fd834f16dff1996dc97df1482fc61d6a19` exports 189 runtime paths.
The candidate patch SHA-256 is
`81786a68d03a496dfc753be1417d6c4d7fa22dc5c39323474382089cf3e95302`.
The native suite passed 58 checks with two skips and all 22 `scripts/check`
checks. The combined release passed 116 focused tests with four skips.
The isolated Docker Desktop ARM64 image used actual SSH and an authenticated
browser to save a host-owned executable and checked host edit access before
and after the editor save. Removing the managed grant from the fixture
produced HTTP 503 and left the bytes intact. A publisher probe under Debian
native Docker and rootless Podman verified executable permissions, a new
file's inherited ACL, both users' effective access, and refusal of a
read-only file. The Debian ARM64 Docker 29.10.0 lean upgrade fixture passed
the full lifecycle for the implementation in `57fda81`. The same fixture
passed on native Docker and rootless Podman 5.4.2 with both lean and desktop
executors. It covered classic and TUI shell placement, managed model writes,
the WebApp approval card and editor, host ACL checks, and recovery after the
executor stopped.

The follow-up writer cleanup `ceb61c4d4c3880ac5482584f706db9d5cc37aa5d`
splits SSH dispatch and tests and narrows handled errors. It passed 280
native tests with nine skips and all 22 upstream checks. Its release commit
is `3d38202f915671b5b656900406a04104a6f71616`. The managed submission topic
includes it at `7110ca808a05cce06d4add92dee88e3f1da9f97f`, and the matching
release topic is `761b2893c2e72e13a0908a2f431cd3c278b92e9d`. Combined head
`3b285164393886d89e36f2e5d3d69f32011ad74b` passed 337 focused tests with
11 skips. The 189-path candidate SHA-256 is
`27d0106002232636d253e31be6c87c1ed785bd69f9406012b9e4e2e7b5fd3b92`.
The Docker Desktop ARM64 image passed the direct SSH file tool and
authenticated editor API probe, including the missing-grant refusal.
`make check` passed 242 tests and all four Compose models.

### Project selection

The project selection work starts from the managed workspace topic at
`7110ca808a05cce06d4add92dee88e3f1da9f97f`. Independent design review traced
canonical and legacy session ownership, root validation, Git metadata, and
the WebApp picker. Keep saved sessions and project records available when a
mount is removed. Resolve work and metadata against applied roots in SSH
before adopting a directory. Reuse the existing transport and directory
and project caches. A Docker Desktop ARM64 diagnostic image verified
classic `hermes chat --in` with an executor-only directory, authenticated
browser creation and moves in two chats, and saved create retries and
history during an executor network outage. Both chats kept their selected
directories after reconnection. History also stayed readable after the
managed backend or roots disappeared from the test config, while create
and move requests were refused. The updated native selection tests passed
90 checks. The test image precedes the change to show a saved executor
directory in session information during an outage.

Native picker commit `fdf6d6c0b7c144a060b8844f6709c476f139be40` passed 31
Python tests with two skips, 25 renderer tests, and all 22 upstream
checks. An authenticated browser created a folder on the host-backed
executor share, selected it, and started a chat there. The model's
terminal returned the new executor path, and the folder stayed absent
from Hermes. Independent review accepted the same-build managed route
and found that older gateways need an update to expose folder creation.

The Docker Desktop ARM64 Python tool fixture used real SSH. It covered
relative reads and writes, retained state across requests and replacement
SSH connections, isolated session owners, project switches, the per-call
fallback, and strict staging with a removed cached cwd. Python read the
executor bytes when a same-name file existed in Hermes. Browser model-loop
and both-engine package checks remain open.

A disposable image built from the pinned release replay passed a real SSH
chat with different files at the same path in Hermes and the executor. The
model received the executor's instructions, file contents, and Git diff.
The same test checked that the executor refused a symlink outside the
project. Independent context review also found that paths in Hermes caches
needed separate ownership checks. The native attachment follow-up binds a
staged handle to the owning session and passed 52 focused tests. The
full context review and runtime checks for `/init` and remapped projects
remain open.

The chat-scoped WebApp files draft passed 200 Python tests with ten Windows
skips and 107 renderer tests. An authenticated Chromium fixture on Docker
Desktop ARM64 created two sessions with different `note.txt` files. In both
Code and Agent modes, it verified each session's text, download, HEAD response,
and editor save. An SSH outage refused the read with a same-named Hermes file
in place. The focused Python suite checks download tickets after a move.

The integrated release replay `07db65a34cfae9fbdee238c8c1bed2d0fb10a936`
uses the v0.23.3 source and the reviewed shell and picker replay. Its tree
passed `scripts/check` (22 checks). An earlier integrated snapshot passed 346
focused Python tests with 14 skips. `make hermes-ui-test` passed TypeScript
checking and 285 renderer tests. Docker on Debian ARM64 passed `make test`
against the earlier integrated image.

The pinned OpenSSH cron fixture created a script-only job through the model
tool, ran it as `runner` in the selected share, and verified cancellation,
timeout, descendant cleanup, and recovery of the same saved job after an SSH
outage. Code and Agent modes passed. The scheduled restart, named profile
upgrade, and delivery fixtures remain open.

The authenticated Git fixture verified status, file diff, stage and unstage,
branch switching, worktree creation and removal, and refusal outside the
applied roots. The OpenSSH skill fixture verified catalog and slash lookup,
nested skill names, one inline helper run as `runner`, and refusal to register
project-requested profile credentials. These are Docker Desktop ARM64 probes.

The follow-up release replay is `c11f741446c39f3a18012463ade8fae8edf728f2`.
The focused Python suite passed 372 tests with eight Windows skips. The full
upstream test run and the final cross-engine lifecycle runs are in progress.

Independent reviews traced the integrated workspace, file, delegation, skills,
cron, Git, and media paths. Follow-up changes bind picker listings to applied
grants, preserve exact POSIX paths, scope same-name previews by session, keep
delegated child cwd checkpoints, validate both cron scripts, and bind local
media approvals to owning interfaces. Recheck the follow-up changes before
the final combined review.

### Speech output topic

The independent `fix/tts-output-placement` topic starts at submission main
`25a1302eacb563c59eb3b7454c1a53f8c89f274c`. The matching release topic starts
at Hermes `v0.23.3` (`caafe5389ae585ef77387a962aee05b1bcf17029`). It has no
SSH or cron prerequisite.

Native head `8ba4892861228e6b593e476c6a06aed7a034a9fb` passed 116 focused
tests with two Windows skips and passed all 22 upstream checks. The speech fixture checks bytes and attachments
from current and populated legacy profile caches with a stale `output_path`
argument. Internal playback still uses and removes its explicit temporary
file. Release head `9aa64cfdf3e692d097a33c9b70f7b9e86813098b` combines at
`e0a3bffe4d3c16e7040da62452ed10d3634ca912`. The exported patch SHA-256 is
`9632d16f5d6256ca8310c370770cde4f0089625732ee2dcf423c45d4bc3cd5bc`.
The combined tree also passed 116 focused tests with two Windows skips.
On Docker Desktop ARM64, the final image used the exact release TTS module
and passed the speech, gateway attachment, and playback probe with networking
disabled. `make check` passed 242 tests and all four Compose models.

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
