# Hermes update workflow

Use these notes with the [build and patch maintenance guide](updates-and-plugins.md#derived-hermes-build-and-patch-maintenance)
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

## Keep qualification evidence attributable

- Build every image used by the selected fixture, including unchanged supporting
  images whose local tags may be stale. Keep source/build failures distinct from
  service readiness and application failures.
- Serialize fixtures sharing fixed subnets or ports. Use disposable state and
  dummy credentials. Test allowed paths alongside forbidden paths, dependency
  loss and recovery; source inspection alone cannot qualify isolation.
- Exercise populated configuration, native migration, deliberate CLI edits and
  repeated setup. Verify effective settings and identity preservation, rather
  than only checking that files exist.
- Diagnose failures before changing policy. Tor connection/DNS failures, stale
  images and browser-observation failures need different remedies. Preserve
  failed fixture state when useful; never recover by allowing direct egress.
- Reuse passed evidence when rerunning an affected phase, but retain its fixture
  prerequisites. Screenshot/download checks, for example, need artifacts created
  by earlier browser actions. Record skipped phases and their supporting evidence;
  obtain a complete fixture run when phase dependencies remain uncertain.
- Report implementation, validation and independent review separately. Record
  exact reviewed revisions and platform/live-service limits in maintained guides,
  then remove the completed plan after acceptance. Keep generated private logs
  and runtime state out of commits.

## Lessons from v0.23.0 to v0.23.1

The upgrade had one build break: the native frontend recipe switched to pnpm,
which the official runtime omits. The derived frontend stage now installs it
through upstream's hash-verified PM pin. Only one patch import context needed
refreshing; all seven hardening patches remain necessary.

New saved-gateway relays and browser-vault dispatch required tracing beyond the
changed patch context. Existing response enforcement and tool exclusions covered
them; controlled relay canaries supplied the missing runtime evidence without
new network grants or policy machinery. Native threaded availability probes
required dependency refusal/recovery checks, not another wrapper deadline.

Schema 53 changes the former default clarification timeout from 3600 to 90
seconds. Populated-profile migration preserved other chosen settings and SSH
identities. See [configuration semantics](configuration.md#tool-discovery-default).

Qualification found no major hardening regression in the tested scope. Transient
Tor failures, a stale local proxy image and fixture/observation issues were
resolved separately from the upgrade's build change. The native missing-pnpm
runtime warning is advisory. Detailed results, independent review and remaining
limits are in the [v0.23.1 qualification record](development.md#hermes-v0231-integration-qualification).

## Lessons from v0.23.1 to v0.23.2

Treat this point release as a full integration review: the release spans 5,211
changed files, including policy dispatch, HTTP routes, configuration and browser
consumers. All eleven pre-existing downstream patches touch files changed by the release.
Native ARM64 Chromium discovery replaces the former downstream discovery hunk;
per-hop CDN redirect validation still does not replace the private raster reader
or consent policy. Preserve the native hosted-tool and argument checks when
rebasing deployment exclusions, and native no-follow marker publication when
retaining strict named-tab setup.

The new context-menu Copy image action reaches the shared browser image reader.
That reader now applies the existing authenticated private-image policy, retaining
native CORS/size/time handling for `browser_native`. Qualify Copy alongside Save,
including cancellation, failure without browser fallback and actual menu dispatch.
A controlled clipboard sink establishes request placement and bytes, not OS
clipboard permissions. Newly added peer and backup-transfer routes also need
admission checks beyond patch applicability; do not enable a peer provider merely
to test the unconfigured deployment.

Native schema remains 53. Exercise both older-schema migration and a populated
v0.23.1 schema-53 profile across the selected release, preserving settings, sessions
and identities. The native Python dependency lock, executor harness closure, screenshot
helper, omitted session fixture, pnpm pin and stock Compose comparison are unchanged;
verify those facts against the packaged source before reusing their inputs.

New pre-read inspection also exposed a latent native SSH filesystem defect:
GNU realpath accepts a missing final component, so inspect_file reported
ENOTREG/400 rather than ENOENT/404. Correct the owning adapter's missing-path
classification and retain the browser's negative assertion; accepting any error
response would obscure whether its input-refusal control still works. Regular
file, symlink and directory controls accompany the missing-file regression.
