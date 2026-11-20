# Hermes update workflow

Use this procedure with the [build and patch maintenance guide](updates-and-plugins.md#derived-hermes-build-and-patch-maintenance)
and [planning workflow](planning-workflow.md). They describe how to select
integration checks; the maintained component guides own the operating contracts.

## Review the integration, not just patch applicability

1. Record the wrapper baseline and exact upstream revision range. Inspect the
   actual diff, including new routes and dispatch paths outside our patch targets.
   A patch applying cleanly does not establish that its policy still covers every
   relevant consumer.
2. Resolve the official image digest and inspect the downloaded image's source
   stamp, renderer receipt and calculated source hash. Check copied helpers,
   omitted test fixtures and executor dependency pins against that same revision.
   Keep reference checkouts read-only; their tag alone does not prove packaged
   image contents.
   Update the packaged Hermes version in `README.md` and the release tag in its
   stock Compose comparison link together. Inspect that release's Compose file
   and revise the hardening comparison if upstream defaults have changed.
3. Check the native build recipe and toolchain before rebasing patches. Prefer
   upstream's locked installation mechanism in disposable build stages. Verify
   every patched Python target and the rebuilt renderer reach the final image.
4. Trace changes through the accepted boundaries: SSH execution placement and
   forbidden network paths; Teep routing; early deployment-policy capture;
   registration, inline and stale tool dispatch; HTTP and WebSocket auth; content
   responses and browser requests; configuration loading, migration and retries.
   Check native guarantees before adding wrapper enforcement or budgets.
5. Map concrete hazards to focused checks. Reuse existing suites and add a small
   behavioral fixture for an uncovered route. Upstream feature completeness is
   outside this wrapper's qualification scope.

## Rebuild the candidate patch for a new release

Publish the `stack-patches/<release>/*` refs to the `fork` remote to preserve
the release's topic histories. Together with the pinned combined replay, they let
maintainers reproduce the candidate patch and trace each topic to its
release-based checks after the submission branches move. The local working
clone is `upstream_work/hermes-agent/`. See the [fork repository](https://github.com/mikeperry-tor/hermes-agent)
and the [v0.23.3 provenance](plans/hermes-upstream-prep.md#v0233-build-provenance).

Use these steps when the next release still needs candidate changes.

1. Start a temporary replay from the exact source revision shipped in the new
   official image. Use the current release replay to inventory the behavior
   Private Hermes carries. Compare the corresponding `upstream-pr/*` topic
   commits for fixes that belong on the new base.
2. Replay the selected topic changes that the new release still needs. Include
   the shared managed configuration prerequisite once and reconcile overlaps.
   Verify any adopted behavior in the official release through upstream's tests
   and the affected packaged checks. Drop the corresponding candidate patch
   and duplicate feature tests once that release passes. Keep deployment
   checks for the wrapper's configuration, isolation, ingress and storage.
   If the release includes all candidate behavior, remove the candidate patch
   and its build input together.
3. Export the diff from the new release base to the new combined replay as
   `0001-upstream-candidates.patch`. Exclude upstream Python tests, website files,
   contributor metadata and Electron-only files. Record the exact base and replay
   head in the patch header. Rebase the downstream deployment and privacy patches
   separately and verify the complete series against the packaged source.
4. Record the selected topics, overlap resolutions and qualification in the
   upgrade plan. Update the build provenance with the exact combined replay
   SHA and its ref under `stack-patches/<release>/combined`. Keep the
   `upstream-pr/*` branches available for their PRs.

## Keep qualification evidence attributable

- Build every image used by the selected fixture, including unchanged supporting
  images whose local tags may be stale. Keep source/build failures distinct from
  service readiness and application failures.
- Serialize fixtures sharing fixed subnets or ports. Use disposable state and
  dummy credentials. Test allowed paths alongside forbidden paths, dependency
  loss and recovery; source inspection alone cannot qualify isolation.
- Exercise populated configuration, native migration, deliberate CLI edits,
  native profile reload and repeated setup. Check effective settings and
  identity preservation.
- Diagnose failures before changing policy. Tor connection/DNS failures, stale
  images and browser-observation failures need different remedies. Preserve
  failed fixture state when useful; never recover by allowing direct egress.
- Reuse passed evidence when rerunning an affected phase, but retain its fixture
  prerequisites. Screenshot/download checks, for example, need artifacts created
  by earlier browser actions. Record skipped phases and their supporting evidence;
  obtain a complete fixture run when phase dependencies remain uncertain.
- Report implementation, validation and independent review separately. Record
  the tested source/image, checks establishing current behavior and platform/live-
  service limits in the owning guide. Keep execution/review chronology and phase
  identifiers in the plan, not appended guide updates. Keep generated private logs
  and runtime state out of commits.

## Frontend and dispatch contracts

Use upstream's locked frontend recipe and hash-verified package-manager pin in a
disposable build stage. The official runtime can omit pnpm; its passive warning
is advisory, while dependency download or build failures must fail visibly.
Qualify Python plugin environment preparation independently of frontend tooling.

Trace saved-gateway HTTP/WebSocket relays, inline browser-vault dispatch, peer and
backup-transfer routes as well as patched files. Retain native authentication,
exact-host/origin, response enforcement and hosted-tool/argument checks. Test
unauthorized/invalid-input refusal without mutation and unconfigured-provider
refusal; do not enable a provider or widen network grants just to test a route.
Native threaded availability checks own their budgets; test dependency failure
and recovery before adding another wrapper deadline.

Preserve native ARM64 Chromium discovery and no-follow named-tab marker publication.
Per-hop CDN redirect host checks alone do not replace bounded public-raster
retrieval, connection-time destination validation, TLS/credential isolation or
consent. Keep the native restricted-client CDN consumer supported when changing
image routes.

## Image, file and state checks

Qualify Copy and Save through the shared browser image reader, including actual
menu dispatch, cancellation, one-time approval, `off` refusal, original filenames,
saved-gateway behavior and failure without direct-browser fallback. Preserve
native CORS/size handling for `browser_native`. A controlled clipboard sink proves
request placement and bytes, not OS clipboard permission or Electron containment.

Require ENOENT/404 for a missing SSH file or parent alongside regular-file,
directory, symlink and sensitive-path controls. GNU realpath can accept a missing
final component; accepting any error would hide incorrect classification.

Exercise a populated profile from the relevant prior official image, not only
an empty profile or a schema number. Verify settings, sessions, identities and
saved env/auth/plugin state after repeated supported loading. Native schema
migration is not arbitrary database-downgrade support. Inspect clarification and
other native defaults against [configuration semantics](configuration.md#tool-discovery-default)
rather than replaying assumptions from a prior release.

Verify the Python lock, executor harness closure, screenshot helper, omitted
public session fixture, package-manager pin and stock Compose comparison against
the selected packaged source before reusing evidence. The [current packaged
qualification](development.md#packaged-hermes-qualification) records coverage and
limits; it is not a sequence of upgrade reports.
