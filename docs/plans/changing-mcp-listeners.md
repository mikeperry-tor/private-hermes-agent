# Configurable x402_treazury MCP listeners

Status: proposed; implementation and independent design review are pending.
This task creates the plan only; it does not change runtime behavior.
Baseline: branch `webapp-private-content`, commit
`e09d5f736c2be3404fc6534a9422567a3d2d28ed`.
Engine-parity amendment baseline: `rootless-podman-support`, `3f66fa5`.
Follow the [planning workflow](../planning-workflow.md) before implementation.

## Intent and current behavior

Let operators add, remove, rename or change ports of x402_treazury MCP listeners
in `config/x402_treazury/research_desk.toml`, with the existing Make workflow
updating Hermes registrations. Operators should not have to duplicate these
changes in webapp settings. This concerns treasury listeners, not arbitrary MCP
services or changes to the separate network MCP allowlist.

Today `components/x402_treazury/endpoints.py` fixes twelve names and ports.
The renderer checks the packaged default against that inventory; onboarding
requires exactly those listeners; registration adds those names and disconnect
removes only those names. The in-Hermes readiness client separately hardcodes
ports 3010–3021. The controller, tests and guides also assume twelve listeners.
Registration rejects changed managed URLs rather than applying operator edits.

The earlier inspected reference revision was
`424f36a814711d542fbff27f139842c9d08d5b76`; the current treasury Dockerfile pins
`7ee0f5e89b5413b8ae55e18ee939c9d26df3652d`. Reinspect native inventory, validation
and serving diagnostics against the packaged revision before implementation.
The earlier inspection found native support for named listeners, validation of
identifiers, references and address uniqueness, and a requirement for at least
one server.
Hermes uses the derived official v0.23.1 image and supports native `reload.mcp`.
No upstream patch or image/source revision change is proposed.

## Intended operator workflow

1. Stop with `make down` before editing a running deployment; retain no-hot-reload
   semantics. Edit the TOML's server declarations and associated native references.
2. Use the existing native configuration preview described in the treasury guide.
3. Run `make up`. For an already prepared treasury, start serving, require all
   currently configured listeners to initialize/list successfully, reconcile
   Hermes registrations, and use its native MCP reload.
4. If activation fails, keep Hermes available and research disconnected. Correct
   the cause and retry with `make x402_treazury-prepare`. Historical preparation
   means this retries activation rather than replaying financial bootstrap.

No new Make rule is needed: `make up` applies the edited policy and
`make x402_treazury-prepare` remains the activation retry. Neither command should
promise to hot-reload edits into an already running treasury. A new wallet still
needs the existing explicit initial preparation. An empty server map receives the
native configuration error; disabling research entirely is not added here.

Removing a listener removes its managed Hermes entry, not any wallet, source,
catalog, key or preparation history. A listener rename changes registration
identity; it is distinct from renaming a wallet group. Keeping a wallet or source
declared may retain native funding/catalog work even without a corresponding
listener. Adding listeners or changing their selections may cause native serving
to fund groups or download catalogs under the existing financial policy.

## Smallest proposed implementation and boundaries

- Treat the effective native `servers` configuration as the runtime inventory.
  Keep the shipped twelve-listener policy as the default, not an operator limit.
  Retain build-time checks of packaged defaults where they detect a real upstream
  integration change; do not use them to restrict a saved operator configuration.
- Have the existing policy-aware admin operation expose only validated listener
  names and loopback MCP URLs for the controller. Reuse native configuration
  loading/validation and a small shared helper for wrapper-owned invariants.
  Do not print or pass the full financial configuration or credentials to Hermes.
  Use an in-memory inventory for activation, readiness and registration; add no
  manifest, receipt, file hash, registry or persistent reconciliation record.
- Retain the exact treasury state/key paths, private Tor UNIX socket, extended
  SOCKS authentication, bearer-token variable and authenticated Host checks.
  Every configured listener must bind `127.0.0.1`, require authentication and keep
  its loopback Host allowlist. Ports and valid native listener names may change.
  Let native validation and binding errors own native constraints and collisions;
  do not invent a permitted port range or duplicate funding/tool-selection rules.
- Pass only the validated inventory to the existing networkless registration job
  and in-Hermes read-only probe. Hermes receives no treasury TOML or wallet mount.
  Review the least-privilege handoff rather than mounting treasury state into a
  new consumer. Preserve stdin-EOF probe cancellation while supplying its inputs.
- Reserve the existing `x402_treazury_` registration prefix for managed entries.
  Reconcile that namespace to the desired inventory: update changed managed URLs,
  add new entries, remove stale entries, and retain the shared token reference.
  Preserve entries outside that namespace, other Hermes configuration and secrets,
  and existing sessions under native reload semantics. Validate all inputs before
  publishing configuration atomically; do not add an ownership ledger or aliases.
  Explain that manual edits under the managed prefix are overwritten on activation.
- Disconnect removes all entries in that managed namespace, even when the policy
  is missing, invalid or no longer contains the old names. It must remain a
  networkless profile-only operation with no config or wallet prerequisite. Token
  provisioning must not unexpectedly register endpoints or need listener policy.
- Require every configured listener, with no partial registration on readiness
  failure. Preserve current-serving-lifetime native failure diagnostics, instance
  identity checks, cancellable probes and regular waiting messages. Replace fixed
  counts with the actual inventory; add no startup deadline or retry cutoff.
  Stop/edit/start is the policy-change contract; concurrent operator edits during
  activation are unsupported, not a reason to add configuration locking/journaling.
- No network grant, published host port or per-port proxy is necessary: treasury
  and Hermes already share the agent network namespace. Preserve executor denial,
  Tor routing, filesystem isolation and absence of direct-egress fallbacks.

## Phases and acceptance

### Shared-engine requirements

Use one native inventory format, reconciliation path and offline maintenance
workflow for both engines. Treasury and Hermes share the agent network namespace
on Docker and rootless Podman; adding listeners requires no engine-specific
network exposure. Verify actual loopback reachability and executor denial on
both, not just effective Compose similarity. Rootless engine operation does not
make a loopback listener shared with the host or another container namespace.

Investigate native binding requirements for operator-selected ports, including
ports below the namespace's unprivileged threshold and collisions with existing
agent listeners. Namespace sysctl defaults may differ; a validated port is not
proof it can bind as UID 10003 with all capabilities dropped. Preserve useful
native failures without arbitrary port ranges or automatic capability, sysctl or
host-publication changes to make a port work. Record supported behavior and any
concrete engine exception before design acceptance.

Retain named wallet state and existing group-102 private Tor socket access. Check
rootless UID/GID mappings and atomic profile publication through the existing
networkless jobs; no wallet or treasury-policy mount is added to Hermes. Reuse
managed bind-source checks for any changed mounts. Disconnect, token provisioning
and saved-state inspection keep their operation-scoped prerequisites.

### P1: coherent inventory and reconciliation change

After independent design review, update onboarding validation/inventory output,
controller inputs, registration and disconnect, readiness client, setup consumers,
and packaging together. Trace `setup init`, `mcp-config token|connect`, the
profile-only disconnect path, direct serve validation and failure cleanup. Remove
runtime fixed-inventory assumptions without removing useful default rendering
checks. Change Compose mounts only if the reviewed handoff requires it.

Include focused tests for a subset, an added name on a nondefault port, port
changes, listener rename/removal, stale managed entries, repeat reconciliation,
and preservation of unrelated entries and profile secrets. Verify invalid policy
does not partially publish desired registrations, disconnect still works with
missing/invalid policy, and token-only operations remain independent. Retain
offline wallet inspection and unchanged identity/preparation after policy edits.
Test native empty/invalid configurations and wrapper rejection of non-loopback,
unauthenticated or weakened Host settings without mirroring the native validator.

Update README operator guidance, `docs/x402_treazury.md`, relevant configuration
and development guidance, and the example Hermes config comment with this change.
Document managed-prefix ownership, stop/edit/start, activation retry, wallet versus
listener removal, native funding consequences and lack of support for an empty map.
Commit coherent implementation and focused evidence; obtain independent review
covering the changed inventory handoff and managed-registration ownership.

### P2: runtime qualification and combined review

Use existing disposable, unfunded real-image fixtures to demonstrate a configured
subset plus an added nondefault listener; authenticate and list each desired
endpoint, apply native Hermes reload and confirm its actual registry. Restart
after removing/renaming/changing a listener: stale registrations must disappear,
desired ones must work, and unrelated MCP entries must survive. Demonstrate a
configured endpoint failure leaves no partial managed registration, retry succeeds,
and delayed startup, cancellation and serving restart retain their existing
semantics without a total deadline.

Run this runtime qualification on both qualified engines, including stdin-EOF
cancellation, serving-instance identity, container restart/recreation and teardown
of stopped profiled namespace users. Include a real port collision and a
representative low-port probe to establish the native binding contract without
weakening grants. Confirm failures preserve wallet/key/preparation state and leave
research disconnected while Hermes and offline repair remain available. Use the
same fixtures and inventory assertions; no engine adapter is proposed.

Verify allowed Hermes loopback access and denied executor access to changed ports,
no new host publication/private-network grants, and unchanged wallet mount scope.
Retain relevant Tor-loss/failure evidence where paths change. Update affected
fixtures and hardcoded count assertions in research, storage, endpoint-readiness
and webapp tests; run affected checks rather than every unrelated suite. Validate
base/Funnel effective Compose models if their definitions change. Serialize tests
sharing fixed networks; use no operator volumes, secrets, payments or live ingress.
Run affected repository checks on both engines and record actual image/provider
versions and target limits; unavailable engine evidence remains pending. The
earlier fixed-listener qualification does not qualify configurable listeners.

Run documentation link checks and `git diff --check`. Record focused results and
limitations here. A fresh independent final reviewer must inspect the combined
change, consumers/failure paths, native contracts and rule conformance, including
unnecessary enforcement or machinery. Resolve material findings, rerun invalidated
checks, commit completed work, and distinguish implementation from qualification.

## Related plans, deferrals and remaining evidence

On implementation, update the fixed-twelve runtime requirements in the maintained
[treasury guide](../x402_treazury.md) and related configuration/development guides.
The completed predecessor plans are preserved in Git history. The maintained
[endpoint diagnostic contract](../development.md#diagnostic-messages) and
[operation-scoped state rules](../../AGENTS.md#scope-enforcement-to-the-operation)
remain in effect.
[Read-only configuration](readonly-configuration.md) stays deferred; future work
there must allow the explicit managed-registration writes described here.
Browser-content work is unaffected; its research fixtures must use the new inputs.

Independent design review must confirm the native effective-listener representation
and smallest inventory handoff across the existing job boundaries before coding.
No implementation or runtime evidence exists for this proposal yet. No new service,
generic MCP management UI/CLI, automatic file watcher, hot reload, compatibility
layer, wallet migration, funding-policy redesign or native readiness API patch is
included. Live funding and destructive private-state operations remain outside
this plan's implementation/qualification authorization.

The engine-parity amendment against `3f66fa5` passed fresh independent read-only
review together with the document-search and interactive-content amendments,
with no material findings. Local-link targets and `git diff --check` passed;
no runtime tests were run for these documentation-only changes. Future design,
implementation and both-engine qualification remain pending.
