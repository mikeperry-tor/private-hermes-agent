# WebApp code terminal in the SSH executor

Status: CT-1 accepted; CT-2 implementation and qualification in progress.
Implementation baseline: branch `code-terminal`, commit
`3fb188167125ba0874a6ff89353d5060a4c474bf`.
Planning baseline: branch `main`, commit
`4f6e0cae6e3b50d4af31251c1801c199b78a74f8`.
Follow the [planning workflow](../planning-workflow.md).
Configuration-choice revision baseline: `38aacd9` on `main`.

## Intent and current behavior

Make the ordinary WebApp terminal useful for working on the same projects as the
agent by default, with an operator-selectable agent administration environment.
Use `WEBAPP_TERMINAL_ENVIRONMENT=code` in root `.env` to open it as `runner` in
the existing SSH executor, including the optional desktop executor when enabled.
Use `agent` to retain the native local shell in the Hermes container. This is a
deployment setting, not a live selector on each terminal tab. Existing operator
administration commands remain available.

The packaged Hermes is v0.23.1, source
`3b421578588243f920886e6fe79a6faa87ea026e`, official image digest
`sha256:276d44685c65c0cb2a25f190b63c65c8906f9dc76486fb1c05ae71b5826bda08`.
`components/hermes/Dockerfile` builds explicit source patches and the WebApp from
that image. The reference checkout currently matches that source; recheck the
packaged revision before implementation.

Observed contracts at this baseline:

- Hermes's `/api/host-terminal` authenticates the browser socket and creates a
  local PTY shell through `web_host_terminal_sessions.py` and
  `web_host_terminal.py`. It does not select the model's execution backend.
- Our WebApp runs in Hermes, while model terminal/Python tools use SSH to
  `runner@10.203.82.3:2222`. Workspace file APIs already use the backend.
- Executor projects persist in `data/executor/workspace`, mounted at `/workspace`.
  Hermes's empty `/workspace` is a separate directory needed by native session
  cwd validation. Browser-terminal files there are currently ephemeral.
- Native shell sessions retain identity/profile ownership, bounded output replay,
  resize handling, explicit close and reconnect behavior. Preserve these owners
  and mechanisms rather than creating a parallel terminal registry.
- Hermes also supports SSH shells for saved remote gateway connections. That
  feature targets a remote Hermes installation; it is not the configured code
  executor and must not be repurposed as a fake gateway registration.
- The browser terminal bridge gets live cwd updates from shell OSC output; its
  `cwd` probe currently returns null. A local SSH process's cwd cannot establish
  the remote shell's working directory.
- `tests/webapp_smoke.py` currently asserts that terminal output is written in
  Hermes and file API output in the executor. Retain that assertion for `agent`
  and add the executor-terminal assertion for the default `code` mode.

## Intended behavior and preserved boundaries

The startup setting accepts exactly these user-facing strings:

| Value | Terminal environment |
| --- | --- |
| `code` (default when unset) | SSH executor, alongside model-created projects and the optional desktop |
| `agent` | Native local shell in the Hermes container, with administrative access to agent state |

Empty or unknown values produce a clear configuration error, without selecting
another environment. Add the setting to `.env.example` and explicitly map it
only to Hermes in Compose; do not load root `.env` wholesale into any service.
Capture the selected mode at WebApp startup so profile/browser input cannot
change it. Apply changes with the documented `make up` recreation workflow;
verify that changed environment values actually recreate the WebApp container.
Existing shells never move between environments. No hot reload or migration of
terminal state is promised. Reconcile any saved browser cwd/tab state against
the new mode so switching does not silently use an agent path as a code path or
vice versa; do not add a persistent backend eligibility record.

In `code` mode, the ordinary terminal opens an interactive executor shell in the
requested project directory, defaulting to `/workspace`. Its files and installed
tools are the same ones available to model execution. With computer use enabled it runs in
the desktop executor as the same user; this does not automatically attach it to
an existing graphical terminal process or promise GUI application environment
variables without verification.

In `agent` mode, retain native local shell selection, cwd resolution and access
to agent state. The workspace file API still follows the model backend and can
therefore display executor files that are not present in the agent shell. Explain
that distinction and the ephemeral agent-side `/workspace`; do not add shared
mounts or redirect the file API to disguise it. Agent-shell creation must not
perform executor readiness or SSH-key checks. This does not change existing
whole-stack startup dependencies.

Label the selected environment clearly as Code or Agent. Retain native
terminal tabs, streaming and supported reconnect behavior. An unavailable
executor or rejected SSH identity in `code` mode produces an actionable terminal
error, never an agent-side fallback. Browser refresh can reattach to a surviving
shell;
backend or executor restarts do not promise process survival. Opening a fresh
terminal after recovery must work without replacing identities or workspace data.

Preserve these contracts:

- Hermes and executor keep separate filesystems, processes and network
  namespaces. The SSH client and key remain in Hermes; the remote shell receives
  no agent state, WebApp credentials, provider secrets, wallet data or SSH key.
- Reuse the exact existing SSH grant, private key and strict known-host checks
  in `components/hermes/ssh-client.conf`. No forwarding, extra listener, engine
  socket, host networking, additional network grant is needed. The native PTY correction below adds only
  CHOWN to the root executor sshd daemon, not runner’s effective capabilities.
- Executor egress remains governed by its existing Tor and private-destination
  policy. A human's interactive commands get no additional network authority.
- Existing authentication, socket tickets, exact host/origin enforcement,
  profile ownership, logout/credential-revocation behavior and terminal cleanup
  must continue to apply. Preserve native semantics; do not add new session limits.
- The authenticated operator still has administrative agent authority through
  the WebApp's other capabilities and the optional `agent` terminal. Selecting
  `code` does not sandbox the whole WebApp or create isolation between sessions,
  profiles or human/model work.
- Existing credentials, configuration, project files and completed setup survive
  ordinary rebuild/recreate. No state migration or compatibility layer is needed.

## Proposed implementation

Use a narrow source patch at native terminal process preparation to select the
native local-shell path for `agent` or launch the existing OpenSSH client for
`code` under the same authenticated PTY lifecycle. In `code`, request a remote
PTY so window sizes, interactive programs and terminal signals reach
the executor shell. Keep using the native WebSocket transport and terminal
registry. Add a small explicit helper under `components/hermes/` only if it makes
the pinned patch smaller and clearer; justify its responsibility before adding it.

Use the stack's existing executor connection inputs and configuration ownership;
do not introduce another address, credential store or backend registry. The
single environment choice above is the only new operator setting. Trace
profile/configuration precedence before choosing the exact read
site so profile selection cannot silently redirect this stack terminal to a
different destination. Unsupported configuration must fail visibly for terminal
creation/serving as appropriate rather than block unrelated inspection, backup,
repair or shutdown. Validate the mode through existing scoped configuration
checks and again at its runtime consumer; do not introduce a validation framework.

Build the local SSH invocation as an argument list. Remote commands still cross
SSH's shell-command boundary: quote remote paths correctly, reject invalid path
representations, and ensure browser-supplied cwd cannot alter SSH options or
target. This protects correct command construction, not a new confinement of
an already authorized operator shell. Use batch authentication and preserve
strict host verification; never prompt for passwords or accept unknown hosts.

For `code`, resolve and validate cwd in the executor, not through
`Path.is_dir()` in Hermes.
Proposed behavior: absent cwd uses `/workspace`; an existing directory is used;
an existing file uses its parent. A nonexistent or inaccessible supplied path
returns a clear error instead of silently starting elsewhere. Preserve spaces,
Unicode and shell metacharacters as path data. Report the actual remote launch
directory in terminal metadata. Use existing remote shell integration for OSC cwd
reporting if available; otherwise add the smallest shell-specific integration
needed for the packaged bash executors, preserving user startup files. Do not
invent a polling service or claim a local PTY process probe tracks remote cwd.

Update any necessary UI wording and metadata without changing unrelated native
desktop behavior or saved remote gateway terminal semantics. Keep the internal
route name if it remains an implementation detail; a broad endpoint rename does
not help users. Document the patch's purpose, pinned applicability, checks and
removal condition: upstream provides equivalent executor-terminal behavior with
the required authentication, lifecycle and connection policy.

Compose needs an explicit environment mapping, with no topology change expected.
If implementation discovers a required grant, service, persistent record or
engine-specific overlay, return to design review with a reproduced need before
adding it.

## Decisions to resolve before runtime implementation

1. Trace terminal creation, attach/close, metadata, default cwd, profile selection
   and shell startup across the pinned Python and browser bridge consumers.
   Select the smallest patch seam and the authoritative existing connection inputs.
2. Verify native PTY resize propagation through OpenSSH, disconnect/close cleanup
   of the remote shell, and whether the packaged shell emits cwd OSC updates.
   Specify any focused helper or shell integration needed; do not assume killing
   the local SSH process alone proves remote children were cleaned up.
3. Verify requested project directories and restored cwd are executor paths,
   including initial session validation. Keep the empty agent-side `/workspace`
   unless its separate session-creation requirement is actually removed.
4. Determine whether optional-desktop shell initialization needs existing display
   environment integration for parity with model commands. Project access is
   required in both executor images; new desktop capabilities are out of scope.
5. Trace default-cwd/tab restoration and environment capture across recreation.
   Choose the smallest handling of mode-specific browser metadata so restored
   tabs cannot mislabel or reattach a shell from the other mode. Keep native
   local-shell behavior for `agent`; do not build generic backend routing.

## Phases and review gates

### CT-1: accept the design

Complete the consumer/failure-path trace above and record the selected patch seam,
cwd behavior and lifecycle contract in this plan. No runtime edits in this phase.
Obtain fresh independent read-only design review of the identified plan snapshot
and relevant source, following the planning workflow. Review must challenge
unnecessary machinery, mode/profile/target selection, SSH quoting, mode-switch
restoration and lifecycle claims.
Resolve material findings and commit the accepted plan before implementation.

### CT-2: implement and qualify the code terminal

Implement the patch, minimal UI changes and focused fixture updates together.
Affected consumers include `.env.example`, `compose.yaml`, existing deployment
validation, `components/hermes/Dockerfile`, its source patches,
native host-terminal preparation/session metadata, browser terminal cwd/restore
handling, and `tests/webapp_browser.py` / `tests/webapp_smoke.py`. Confirm the
existing executor SSH server and both image variants support the selected flow.
Add focused setting/maintenance checks to the existing configuration fixtures.
Provisioning changes require a demonstrated need; Compose changes are limited
to the explicit setting mapping unless the accepted design establishes otherwise.

Update [WebApp operation and authority](../webapp.md),
[architecture and isolation](../architecture.md), and
[development and qualification](../development.md) as behavior lands. Update the
[configuration guide](../configuration.md) with the two values, default,
recreation step, cwd distinction and failure behavior. Keep
any README addition limited to everyday terminal use and a guide link. Retain
historical evidence as historical; replace current behavior claims accurately.

Commit only passing coherent work. Obtain fresh independent read-only review of
the meaningful implementation snapshot with recorded validation. Reviewers inspect
source and supplied evidence without rerunning suites unless a new focused check
is necessary to confirm a suspected finding.

### CT-3: combined acceptance and completion

Resolve material findings, rerun only invalidated checks, and independently review
the final combined change and relevant unchanged boundaries. The CT-2 review may
also satisfy this final gate if its brief covers the complete unchanged snapshot
and acceptance evidence. Record actual review revisions and missing coverage.
After acceptance, move lasting contracts/evidence into maintained guides, resolve
inbound links and remove this completed plan under the planning workflow.

## Focused acceptance and validation

Use disposable projects and fixture credentials through the real production image
and WebApp entrypoint. Serialize fixtures sharing fixed networks. Validate on
Docker and rootless Podman, recording engine/provider/platform and image variant.
Use both lean and desktop executors for affected shell behavior; reuse unchanged
desktop/browser qualification rather than rerunning unrelated computer-use suites.
Exercise both values on both engines. Cover SSH-specific behavior in `code` on
both executor variants; reuse unaffected desktop evidence for the native `agent`
shell rather than duplicating a full Cartesian suite.

- In default `code` mode, authenticated terminal creates a file in executor
  `/workspace`, visible through the backend file API and model execution; it is
  absent in Hermes. Prove remote user identity and absence of
  agent/wallet/credential mounts using fixture markers.
- In `agent`, terminal output is local to Hermes while workspace file API output
  remains in the executor. Confirm the existing local shell/cwd behavior and
  accurate environment label; an executor outage does not break a new local shell
  in an already-running WebApp.
- Unset mode selects `code`; explicit `code` and `agent` reach their intended
  consumers. Empty/unknown values fail clearly. Effective Docker and Podman
  models map the setting only to Hermes. Invalid mode does not block unrelated
  offline inspection, backup, repair or shutdown commands.
- Changing the mode with `make up` recreates the serving process, preserves
  credentials/projects and opens new shells in the selected environment. Check
  restored tabs/cwd and labels in both directions; no old-mode shell is reattached.
- In `code`, default, requested and restored directories work with executor-only
  paths, spaces, Unicode and shell metacharacters. Invalid paths give the specified
  error. `cd` reporting restores the actual remote path when opening a new shell.
- Interactive input/output, resize (`stty size`), Ctrl-C of a foreground command,
  shell exit, explicit tab close and browser reconnect preserve the documented
  behavior. Check remote process cleanup for explicit close and backend loss with
  disposable processes; distinguish detach/replay from starting a new shell.
- Exercise profile/identity ownership and existing unauthenticated, bad-origin,
  wrong-host, ticket, logout and rotation checks for local and simulated HTTPS
  ingress. Verify saved gateway/native desktop consumers are unaffected by scope.
- In `code`, executor unavailable, missing/rejected client identity and changed
  host key fail without an agent-shell fallback or private-value disclosure. Executor restart
  ends affected shells; recovery permits a fresh terminal and preserves projects.
- Existing executor checks demonstrate public Tor access and denial of direct
  Internet, host/private destinations and agent-only inference/MCP/ingress paths.
  Confirm the interactive SSH entrypoint has the same network policy, including
  Tor outage/recovery. Reuse unchanged boundary evidence where applicable.
- Gateway restart and reconnect tests respect the documented namespace-owner
  lifecycle limitation: do not restart a namespace owner and assume reattachment.

Run the affected source/unit checks and reproducible Hermes image build, plus
`make check` and the relevant existing WebApp/native SSH checks on both engines.
Use `make webapp-test` as the principal WebApp fixture; choose additional existing
targets from the actual changed consumers. No blanket unrelated suite reruns are
required. The setting's Compose mapping also requires effective-model validation
and affected native runtime checks. Check documentation links and `git diff --check`.

No live inference, attestation, paid research, funded wallet operations or public
Funnel enrollment is required. Simulated HTTPS does not qualify live public ingress.
Unavailable native engine coverage must remain explicitly missing, not a pass.

## Related plans, deferrals and current evidence

- [Read-only configuration](readonly-configuration.md): preserve its future
  policy ownership; this plan adds no protected configuration source or new writer.
- [Changing MCP listeners](changing-mcp-listeners.md): no listener or executor MCP
  grant changes; terminal failure must not depend on treasury readiness.
- [Document search](document-search.md): projects remain in the executor; add no
  shared agent workspace mount or search/index service for terminal access.
- [Interactive WebApp content](webapp-interactive-content.md): content consent,
  browser rendering and streaming remain separate from shell placement. Reconcile
  any current terminal-authority wording when that plan is implemented; no content
  policy or preview permissions change here.
- [Alternate network topologies](deferred/alternate-network-topologies.md) stays
  deferred; the existing topology already supplies the required SSH capability.

Deferred: a live browser terminal-environment selector, per-project or per-user
isolation, a generic terminal backend UI, new desktop integration features and
upstream saved-gateway redesign. Existing operator administration remains usable.

Current evidence is source inspection only. Runtime implementation, native engine
qualification and final combined review are pending. This request authorizes the
plan; it does not initiate implementation. Next action: complete CT-1 and resolve
its design review before runtime changes when implementation is requested.

Initial planning-artifact review on 2026-11-13 (before the configuration-choice
revision): a fresh independent read-only reviewer inspected the original draft
against the baseline, relevant guides, pinned terminal/cwd
consumers and SSH/executor configuration; no material findings. This establishes
plan readiness only. CT-1's unresolved implementation decisions still require
resolution and design acceptance. No runtime tests were run for this documentation
change; local relative links and whitespace were checked.

Configuration-choice revision review on 2026-11-13: a new independent read-only
reviewer inspected the revised plan against `38aacd9`, relevant guides and
terminal/browser/Compose consumers; no material findings. This covers planning
readiness for both startup modes, not completion of CT-1 or runtime acceptance.
Local link and whitespace checks passed; no runtime tests were run.

## CT-1 selected implementation

The reference revision matches the packaged source. Patch only the ordinary-host branch of `HostTerminalRegistry.create`: code
mode returns the existing OpenSSH client argv, agent mode retains native
`resolve_argv` unchanged. Saved-gateway preparation also calls `resolve_argv`
for local environment setup, so branching inside that shared function would
incorrectly make saved gateways depend on the code executor. A focused `private_code_terminal.py`
helper calls native `resolve_argv` for profile-scoped env and owns SSH command
construction and remote cwd validation, keeping these
stack-specific details out of the pinned native lifecycle. Capture mode and the
existing injected TERMINAL_SSH_HOST/PORT/USER/KEY at bootstrap, before profile
dotenv and runtime scopes; do not use mutable profile backend configuration.
Native saved-gateway `prepare_shell` remains untouched.

Resolve code cwd through an authenticated, non-PTY `python3` SSH probe returning
JSON (Python exists in both executor images). Reject nonabsolute paths, NUL and
line/control characters, which cannot be represented reliably by native cwd OSC
and browser restoration. Preserve spaces, Unicode and metacharacters. No supplied
path means /workspace; files use their parent; missing/inaccessible paths fail.
Use shlex quoting across the remote shell boundary, fixed SSH options, batch auth,
strict known-host checks, disabled forwarding and an establishment-only timeout.
Then run the interactive bash shell through `ssh -tt` under the native local PTY;
report the probe's canonical remote cwd in metadata while spawning the local SSH
process in the profile home. Source native system/user bash rc files through a
small inline rcfile and append an OSC-7 cwd hook without replacing existing prompt
commands. Both images have bash/python3; desktop sshd already supplies its native
runtime/browser environment. No new desktop/display integration is required.

Keep registry ownership, tickets, attach/close and replay unchanged. Add selected
mode to ordinary metadata and Code/Agent shell labels. Native PTY resize signals
reach OpenSSH, which sends SSH window-change messages; Ctrl-C travels as terminal
input. Closing the local SSH transport causes sshd's remote PTY hangup; qualify
ordinary shell/foreground-child cleanup rather than promising cleanup of deliberately
detached jobs. Backend/executor restart does not promise process survival.

Inject the captured mode into the existing HTML bootstrap. Persist it alongside
the native terminal tab layout; discard only serving-local tab/cwd/history entries
when modes differ, preserving saved gateway tabs. Add the mode to local terminal
socket requests and refuse stale-page mode mismatches before ordinary create or
attach. Remote gateway requests retain native behavior. New code terminals default
to /workspace rather than a profile backend's default; explicit project cwd stays
remote. Keep the empty Hermes /workspace for independent chat-session validation.

Host validation uses existing x-deployment/Settings consumers and maintenance
placeholder handling; no proxy enforcement or new state marker. Compose maps the
new input only to Hermes and changes its effective environment, triggering native
Compose recreation. Docker Desktop is available (Engine 29.9.3, Compose 5.7.0,
linux/arm64 VM on macOS); no local Podman command is installed. Podman native
coverage must be reported as missing unless another qualified target is available.

Design review corrections: use the ordinary-only registry branch, since saved
gateway preparation shares native resolve_argv. Perform remote preparation in
asyncio.to_thread before attach_or_spawn (outside its registry lock), analogous
to native warm_tunnel. Recheck profile liveness at spawn and native admission.
This keeps a slow executor probe from blocking other terminal lifecycle work.

CT-1 independent review accepted the baseline-plus-plan snapshot on 2026-11-14
after resolving the shared resolve_argv seam and registry-lock findings above.
Canonical probe targets also receive path-representation validation. Preserve
code-path whitespace through OSC tracking and restored cwd consumers; do not trim
path data. Native bootstrap CSP hashes final rendered HTML, including the mode.
Runtime claims remain pending CT-2 qualification. No suites were rerun by review.

### CT-2 native PTY design correction (2026-11-14)

Docker lean production-image fixture reproduced remote PTY failure: ordinary
non-PTY SSH cwd probes succeed, but both `ssh -tt ... id` and the native local
PtyBridge wrapper exit 255. Executor sshd logs the specific failure:
`chown(/dev/pts/0, 10000, 5) failed: Operation not permitted`.
Current executor grants SETUID/SETGID/SYS_CHROOT qualify non-PTY model commands,
not PTY allocation. This disproves the initial no-grant-needed assumption.

Proposed correction: add only CHOWN to executor sshd's existing Compose capability
set on both engines/image variants. OpenSSH owns PTY setup and subsequent native
UID/capability drop; verify runner has zero effective/permitted/inheritable/ambient
capabilities in both ordinary interactive and model shells. No application gets
NET_ADMIN/NET_RAW, forwarding, additional mounts or additional network access.
The root daemon can change ownership within its existing writable mounts; read-only
root and key mounts stay read-only. A custom runner-side PTY relay or alternate
sshd identity would replace native SSH lifecycle with unnecessary machinery.
Update the architecture capability table and effective-model expectation, then
qualify PTY behavior and runner capability drop on available engines. Native
Podman remains missing. Independent review of this reproduced need is required
before applying the grant.

Fresh independent focused design review accepted the CHOWN correction on
2026-11-14 without material findings. Runtime qualification must verify PTYs and
runner effective/permitted/inheritable/ambient sets; inherited bounding set is
expected to be 0x400c1. This explicitly supersedes the initial no-grant-needed
assumption; no native Podman acceptance is claimed.

CT-2 evidence so far: production Hermes image builds reproducibly; make check
passes 172 tests and effective Docker/Podman overlay models. Initial renderer
TypeScript and 147 focused native tests passed. Source implementation review
found no material findings, including captured mode/SSH inputs, ordinary-only
preparation, quoting, off-lock probe, ownership and mode restoration. It did not
claim runtime acceptance. Fixed nonprivate startup errors now reach native UI
through close code 4411, instead of being lost as premetadata output.

After the independently accepted CHOWN correction, retained Docker Desktop
29.9.3/Compose 5.7.0 linux/arm64 lean production fixture passed code terminals on
local and simulated HTTPS: placement/file API/model parity, zero runner capability
sets in interactive/model commands, denied private destinations, path data/file
parents/OSC, real browser bridge startup and errors, missing/rejected identity and
changed-host-key refusal, resize, Ctrl-C, replay/attach, explicit close/shell-child
cleanup, executor outage/restart and backend-loss recovery. Native shell exit also
passed. The full principal WebApp suite and both-mode/desktop coverage remain in
progress. Podman native coverage is unavailable, not a pass.

Docker lean full `make webapp-test` passed after fixture-only corrections: use
actual Hermes UID for model probes, observe Docker Desktop bind propagation before
identity-failure checks, and use native offline setup mounts for rootless-owned
fixture keys. Full TypeScript and 147 renderer tests passed after the error-close
correction. Existing principal WebApp auth, three-browser content, credentials,
policy mismatch, treasury fixture and teardown checks also passed. Rootless
Podman is available through the existing Debian VM (5.4.2 / Compose 5.7.1), despite
no local macOS podman command; its native suite and both desktop variants are in
progress. This supersedes the earlier missing-target assumption.
