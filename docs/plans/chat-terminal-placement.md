# Use Code and Agent terminal modes in `make chat`

Status: Proposed.

- Planning branch: `bind-mounts`
- Wrapper starting commit: `b0e164db6cc5396be5cc2feafad116e76d8bc186`
- Plan: `docs/plans/chat-terminal-placement.md`
- Packaged Hermes: v0.23.3, source `caafe5389ae585ef77387a962aee05b1bcf17029`
- Release replay starting head: `553cd75ac4da1c4e9cef7479d1962a026c593cda`
- Upstream target: PR4b, `feat/webapp-executor-terminals`, starting at
  `703b3f869152b432e58937b13497c09ac55a3cab`

## Goal and boundaries

Let an operator run `!git status`, `!git diff`, and similar one-shot shell
commands against the live project checkout from `make chat`. The pinned
Hermes CLI runs `!` commands inside Hermes today. The WebApp already reads
the managed terminal mode derived from `WEBAPP_TERMINAL_ENVIRONMENT`.

- `code`, the stack default, runs `!` commands in the SSH executor as
  `runner`. Resolve the working directory in the executor, using the CLI
  session directory when set and the stack's `/workspace` by default.
- `agent` runs `!` commands in the Hermes container with the existing
  operator shell behavior. The
  [plugin management commands](../updates-and-plugins.md#manage-persistent-user-plugins)
  remain available in either mode.
- Upstream CLI sessions without a managed placement setting keep the local
  shell default. A `!` command remains an operator action with no model
  turn. Preserve approval checks, output, exit status, and interruption.
- The selected mode applies to operator terminal commands. Model terminal
  tools continue to use the managed SSH backend. Code mode uses the managed
  SSH endpoint, client identity, OpenSSH config, and pinned host key.
  Missing or invalid managed configuration, an inaccessible working
  directory in Code mode, and SSH failure report errors without running
  the command in Hermes. Keep provider secrets and wallet state outside
  the executor, and keep SSH forwarding disabled.

Read CLI placement from administrator-owned managed configuration. Reuse the
WebApp's mode validation and SSH trust settings where they apply. A WebApp
mode set only by an unmanaged profile does not select a backend for the CLI.
Review this design independently before implementation, including how the
command approval path identifies the selected execution environment and
how interruption stops the remote foreground command.

## 1. Implement and qualify the stack

Implement the feature against the v0.23.3 release replay. Use the local
replay and export steps from the
[candidate patch workflow](../update-workflow.md#rebuild-the-candidate-patch-for-a-new-release)
to regenerate the tracked patch. Record the exact replay head in this
plan and in the patch header. Build the derived Hermes image through the
wrapper and verify that the packaged CLI uses the patch.

Run `make check` and run the same focused fixture on Docker Desktop,
rootless Podman, and native Linux Docker. Use disposable projects, real
SSH, and the supported `make chat` entry point. For each engine:

- With the default Code mode, run `!pwd`, `!id -u`, and the Git review
  commands against a shared project. Verify that the commands see the
  executor checkout and that the WebApp Code terminal sees the same files.
  Check the `/workspace` default and a session directory containing spaces
  and shell metacharacters.
- Set Agent mode, run `make up`, reload the WebApp, and reopen `make chat`.
  Verify that `!` and the WebApp terminal run inside Hermes, and that a
  chat request using the model's terminal tool still reaches the executor.
  Use a local test inference fixture for the chat request.
- Exercise unavailable SSH, missing SSH configuration or client key, a
  host-key mismatch, and an invalid working directory in Code mode. Verify
  that none executes a command in Hermes and that a later command succeeds
  after restoring the dependency.
- Verify that approved commands run in the selected environment and denied
  commands start no shell. Check output, exit status, and that Ctrl+C stops
  the remote foreground command. Check that altered profile and
  `TERMINAL_SSH_*` dotenv settings cannot change managed placement, endpoint,
  or SSH trust, and that missing or invalid managed input starts no shell.
  Use `make test` and the [focused WebApp terminal checks](../development.md#code-terminal-qualification)
  to cover the existing SSH and access boundaries. Record engine versions,
  commands, and any gaps.

Update
[Reviewing changes in the executor](../configuration.md#reviewing-changes-in-the-executor)
to show how to enter commands such as `!git -C /mnt/projects/my-app status`
from `make chat` in Code mode. Keep the WebApp instructions and explain the
shared setting in the
[terminal environment guide](../webapp.md#terminal-environment). Document
`make up`, reloading the WebApp, and reopening `make chat` when changing
the mode.

Obtain independent review of the packaged change and three-engine evidence
before applying the upstream commit.

## 2. Add the upstream change and verify parity

Add the equivalent implementation and native regression tests as a focused
commit on PR4b's `feat/webapp-executor-terminals` branch. Run upstream's
`python3 scripts/check` and `scripts/run_tests.sh` against the updated
branch. Include the CLI shell-mode, managed configuration, SSH, and WebApp
terminal tests. Compare any broader failures with the unchanged PR4b base,
and record the results and skipped coverage. Test the unmanaged local
default with a profile that selects an executor for the WebApp.

Compare the upstream change with the packaged replay. If the upstream work
changes the stack behavior, carry the change into the release replay and
repeat the affected engine checks. Obtain an independent review of the
combined implementation and evidence across both bases.

Update the local submission draft
`upstream_work/submissions/PR4b-executor-terminals.md` with the operator use
case, managed placement behavior, and upstream test results. Refresh the
draft's local branch instructions for the new commit count. Update only the
PR4b branch head in
[Hermes upstream preparation](hermes-upstream-prep.md#1-branches-to-submit).
Keep submission and publication decisions outside this plan.
