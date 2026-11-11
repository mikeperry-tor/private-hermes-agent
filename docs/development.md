# Development and qualification

For operator setup, see [the README](../README.md). For network design and
execution boundaries, see [architecture and isolation](architecture.md).
Read [AGENTS.md](../AGENTS.md) before changing the stack and follow the
[planning workflow](planning-workflow.md) for substantial staged work.

## Repository layout and local configuration

- `components/`: tracked Dockerfiles, container scripts, and component defaults.
- `.env`: private operator settings, selected explicitly for each service.
- `config/`: private editable bind-mount configuration; initialized from defaults.
- `data/`: persistent bind directories for identities and executor work.
- `scripts/`: host-side initialization and checks.
- `tests/fixtures/`: disposable test servers and configuration.

`make init` creates missing local configuration and preserves existing files.
`make up` runs it automatically, then runs cached Compose builds for the selected
base/Funnel deployment and the treasury profile before offline setup or service
changes. Treasury is included even before preparation because its image supplies
the initial policy. `make x402_treazury-prepare` builds only the owning treasury
service before inspecting preparation history or disconnecting/stopping services.
The shared setup/admin image aliases need no separate build definitions.
Build failure aborts the requested operation before those runtime changes.
Docker owns build-input detection and caching; no freshness records are stored.
Inspection, backup and shutdown do not invoke builds. `make build` constructs images only: it does not
initialize operator state or validate deployment policy. Run `make check`
explicitly for source/configuration qualification.

Research policy is seeded from the built image by `make x402_treazury-config`,
managed startup or new-wallet creation; see
[research configuration](x402_treazury.md#edit-the-research-configuration).
Saved-wallet commands do not initialize unrelated state. New-wallet creation
prepares only its Tor/network host inputs. Add new settings explicitly using
`.env.example`; image/source pins remain in Compose and Dockerfiles.

Hermes and wallet state use native named volumes; other persistent files live
in `data/`. Runtime Tor socket IPC also uses a named volume. See
[configuration and backups](configuration.md) before starting.

## Qualification and maintenance

```sh
make check
make test
```

The live test uses a separate disposable Compose project with the actual pinned
Hermes image, the real SSH executor, real Tor, teep with a dummy provider
key, and the x402_treazury server with an unfunded fixture wallet. It performs no
inference or paid research calls. Stop a normal deployment before running it:
projects use the same fixed subnets, and preflight refuses overlaps.

Tests cover actual Hermes terminal and Python execution over SSH, absence of
agent keys/environment in the executor, Tor versus direct inference egress,
forbidden host/VM/RPC/private destinations, actual Streamable HTTP MCP
initialize/list/call with SSE responses, unselected ports, and Tor failure.
Tests use separate project volumes and private temporary bind directories, never
the operator's volumes or `data/` tree. Only disposable test resources are deleted.

References: [Hermes backends](https://hermes-agent.nousresearch.com/docs/user-guide/configuration/#terminal-backend-configuration),
[Hermes security](https://hermes-agent.nousresearch.com/docs/user-guide/security/),
[Dockurr Tor](https://github.com/dockur/tor),
[Docker isolated networks](https://docs.docker.com/engine/network/port-publishing/#gateway-modes),
[teep](https://github.com/13rac1/teep).

`make check` validates the Docker and Podman Compose models on either engine;
`tests/test_engine.py` covers engine selection, Podman network creation, the
proxy firewall rules and the engine floors. The live tests use the same Compose
files as the stack, including the Podman overlays. Run `make test` on each engine
before changing network, ingress or overlay code. On Podman, the live tests need
Compose 2.36+ as the provider of `podman compose`, and `sh tests/podman_paths_smoke.sh`
checks the paths of a running stack, including a client on a network without
isolation.

Component-specific checks and limits are documented in the
[webapp](webapp.md#verification-and-current-limits),
[x402_treazury](x402_treazury.md#stop-and-test), and
[updates and plugins](updates-and-plugins.md) guides.

## Executor desktop qualification

The [architecture guide](architecture.md#executor-capability-requirements) records
OpenSSH capability-removal experiments and their exact failure reasons. The
three existing listener grants are demonstrated requirements for that tested
configuration, not desktop grants. Repeat the affected evidence when replacing
OpenSSH, its account model or privilege-separation setup; do not repeat this
investigation merely because another GUI package is added.

The optional desktop build uses Debian rather than Alpine. Run the packaged
policy checks with `python3 tests/desktop_tools_smoke.py`. Run
`make computer-use-test` to build the selected images and test real desktop
actions over SSH together with the existing Tor/forbidden-path checks.
`python3 tests/computer_use_smoke.py --desktop-only` runs the GUI portion
while diagnosing an affected failure. These fixtures use disposable state,
ephemeral Teep host ports, dummy credentials and no inference or payments.
Serialize them with other fixed-subnet tests and keep the normal stack down.

The desktop executor uses a checked-in Moby seccomp baseline from commit
`7b5ccfab2d6b4e0aa64c6cce401a2705788eafeb`, with one added allow rule for
`clone`, `setns`, and `unshare`. Source:
[default.json](https://github.com/moby/profiles/blob/7b5ccfab2d6b4e0aa64c6cce401a2705788eafeb/seccomp/default.json);
license: `components/executor/seccomp-LICENSE`. The profile is selected only for
the desktop variant by native Compose inheritance in `compose.executor.yaml`.
It retains the baseline's `clone3` ENOSYS behavior and does not allow io_uring.
Playwright's older published full profile was rejected because it changed those
unrelated syscall contracts. Reconcile the baseline with engine updates. Remove
the custom profile when a selected native engine policy permits the qualified
Chromium sandbox without weakening unrelated syscall restrictions.

Enabling user namespaces exposes additional kernel paths to executor code; it
must not grant control of the parent network namespace or bypass Tor. Verify
those forbidden paths and the actual Chromium sandbox layers, alongside runner
capabilities, SSH failure/restart behavior and persistent state. Podman and other
CPU targets require their own evidence; source/manifest inspection is insufficient.
The optional desktop implementation is complete for the qualified scope below.
The stack has only been runtime-qualified on ARM64; AMD64 qualification is not a
completion prerequisite. The pinned desktop image includes Linux AMD64 and ARM64,
Compose imposes no ARM64 restriction, and Chromium discovery retains its AMD64
paths alongside the added ARM64 path. This preserves the ability to qualify AMD64
without claiming that it has passed. Rootless Podman qualification belongs to the
[rootless Podman plan](plans/rootless-podman.md).

The image choice avoids a substantial download and disk footprint when desktop
tools are unused. On 2026-11-11, the pinned desktop index reported compressed
downloads of 1,192,327,731 bytes (ARM64) and 1,203,999,297 bytes (AMD64).
Local ARM64 unpacked images measured 229,682,455 bytes for lean,
4,380,500,982 bytes for the desktop base and 4,429,795,686 bytes for the adapted
desktop executor. Download and unpacked sizes are different measurements; these
local build observations do not establish AMD64 disk or runtime requirements.
Adding the isolated browser harness brought the local ARM64 adapted executor to
4,508,949,695 unpacked bytes; the desktop base and lean target are unchanged.

On 2026-11-11, Docker Desktop ARM64 (Engine 29.9.3) passed 92 unit tests,
effective base/Funnel models, compilation, 12 packaged tool-policy combinations,
lean and desktop SSH/network checks, UID-101 Tor routing/outage/recovery and
desktop capture/click/type/key/scroll. Focused checks also passed native idle
eligibility/stop, human takeover preservation, display restart, lost derived
publication repair, enabled-gateway/lean-executor dependency refusal, SSH outage
and restart, actual root-write rejection on the system/identity mounts, and
on/off/on preservation of SSH identity, workspace, Chromium localStorage and an
HTTP-only fixture cookie. These use no real accounts or funds.

The combined webapp run passed the existing 24 content cases (Chromium, Firefox,
WebKit; four modes; local and simulated HTTPS), plus Chromium screen capture/RFB
pixels on both ingress fixtures in all four modes. Screen checks exercised
wrong-origin, one-use and expired tickets, watch/stale-viewer input denial,
positive takeover input, stop/restart, native cookie-logout lifetimes and no
external HTTP requests from viewing. The existing logout test now observes its
browser response without awaiting a fetch across SPA navigation. DNS/preconnect,
stale consent, Tor retrieval and credential/ingress failure checks also passed.
The GUI tests cover one active default-profile screen and programmatic native
display transport; full visual interaction with the native noVNC pane and other
profile arrangements are not independently qualified. AMD64 and rootless Podman
remain unqualified. Simulated HTTPS does not prove live Funnel ingress, and these
checks do not establish provider attestation or funded settlement.

A fresh independent read-only review accepted combined revision
`4f003190e91358d9908dda87390f8254dbce2ee0` for the implemented and qualified
Docker Desktop ARM64 scope with no material findings. The computer-use plan was
completed after the operator clarified that untested architectures do not block
completion. Full visual noVNC-pane interaction and additional profile arrangements
remain outside the qualified scope; concurrent profile screens remain unsupported.

### Browser harness and results

Browser automation reuses this desktop substrate and adds the pinned harness in
an isolated executor environment. Run `make browser-use-test` for its focused
disposable placement, sessions, cancellation and result checks. Runtime browser
qualification passed remote stdlib/child execution, DOM/navigation/type/download,
named/unnamed tabs, concurrent startup, screenshot staging/native vision, native
selected-cache round-trip with the browser profile excluded, takeover denial,
active/startup cancellation, timeout/retry, daemon crash, owner death and actual
missing-harness refusal/recovery. These fixtures execute the tool as Hermes UID
10000, matching the gateway: root `docker exec` can create native install locks
owned by the wrong account and invalidate restart tests. The complete desktop/
network run also passed image switching and harness Tor outage/recovery. The
actual automation-launched Chromium's `chrome://sandbox` page reported namespace,
PID/network-namespace and seccomp-BPF sandbox layers enabled.
The implementation adds no capability, syscall rule,
published port or internal network grant. The existing three OpenSSH grants and
desktop-only Chromium user-namespace profile remain the owning requirements.

On 2026-11-12, the combined Docker Desktop ARM64 webapp regression passed the
existing 24 content cases across Chromium, Firefox and WebKit, eight screen
mode/ingress cases, and eight browser screenshot/download mode/ingress cases
plus initial authenticated result checks. Actual generated screenshots rendered,
executor downloads transferred, logout denied subsequent file requests, and the
viewing browser made no external requests. Restart, credential rotation, stale
consent, DNS/preconnect, ingress mismatch and Tor failure/recovery checks passed.
The profile archive exclusion also passed actual selected-cache round-trip
without socket/symlink extraction failures. The qualification remains limited to
the single default-profile desktop and tested engine/architecture above; AMD64,
rootless Podman and full visual noVNC-pane interaction remain unqualified.
CDP/dialog/vault tools remain excluded; raw CDP through executor Python does not
qualify their separate native routes.

A fresh independent read-only combined review accepted BU-1 and BU-FINAL at
`db84bcfb8ea879a51db5ab59c0ac6b1a244874b3` for this documented scope, with no
material findings. Final patch-context whitespace cleanup was checked against
the exact packaged source: all seven patches apply and produce identical source
bytes. The completed browser-use plan has been removed; its history remains in Git.

## Diagnostic messages

Explain the affected operation or capability, its impact, the known cause or
uncertainty, and a useful next action when established. Messages must make sense
without decoding implementation stage names or error categories; structured
fields supplement that explanation. Include safe causes and status information,
never credentials, raw protocol responses or credential-bearing upstream prose.

Choose severity at the owner that knows the outcome after applicable recovery:
ERROR for unavailable required service/endpoint functionality, WARN for a terminal
requested-operation failure or unexpected loss of functionality, INFO for useful
lifecycle/progress/recovery messages, and DEBUG/TRACE for routine attempts and
diagnostic detail. An intermediate failure with retry remaining is not a terminal
operation failure. Elapsed time or repetition alone does not promote severity.
Scope errors to the affected capability rather than announcing whole-stack failure.
When outcome is uncertain, say so; do not imply that a payment is safe to repeat.

Endpoint activation follows Docker logs from the serving container's `StartedAt`.
The pinned x402_treazury revision has no public typed endpoint-readiness signal;
the wrapper recognizes its two exact terminal endpoint diagnostic messages from
`deployment.rs` and `deployment/deferred.rs`. This is not a general log-severity
failure policy: recoverable native ERROR events do not fail activation. Recheck
those native messages and their semantics when changing the treasury pin, using
`tests/endpoint_readiness_smoke.py`. Replace this recognition when a native typed
signal provides equivalent behavior; do not add historical-message compatibility
parsers. The observer and read-only authenticated probes add no treasury state.
Closing the controller's input pipe cancels the remote probe, including when the
controller exits unexpectedly. Protocol waits remain cancellable without an
additional startup deadline. Reporting cadence is independent of failure policy.
