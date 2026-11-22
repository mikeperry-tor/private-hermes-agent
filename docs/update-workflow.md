# Hermes update workflow

Use this workflow alongside
[derived Hermes build and patch maintenance](updates-and-plugins.md#derived-hermes-build-and-patch-maintenance)
and the [planning workflow](planning-workflow.md) when upgrading the pinned
Hermes Agent release.

## Review the upstream diff and build inputs

1. **Inspect the full revision range:** Record the wrapper's starting commit and
   the upstream commit range. Review the full upstream diff, including new HTTP
   routes, WebSocket handlers, and tool dispatch paths outside existing patch
   targets; a clean patch apply does not guarantee policy coverage for new code
   paths.
2. **Verify the official image contents:** Resolve the official image digest and
   inspect its source stamp, renderer receipt, and computed source hash. Check
   copied helpers, omitted test fixtures, and executor Python and browser pins
   against that same revision. Keep `reference_repos/` read-only; a checkout tag
   alone does not prove what shipped in the container image.
3. **Update user-facing version links:** Update the Hermes version in `README.md`
   and its stock Compose comparison link together. Inspect upstream's new
   `docker-compose.yml` and update the hardening comparison if upstream defaults
   changed.
4. **Verify the build recipe:** Check upstream's frontend build recipe and
   hash-verified `pnpm` pin in a separate build stage before rebasing patches.
   Confirm every patched Python file and the rebuilt WebApp bundle reach the
   final runtime image.
5. **Trace trust boundaries:** Audit upstream changes against the stack's
   boundaries: SSH execution placement and firewall denials, Teep routing, early
   deployment-policy capture, tool registration and stale-tool dispatch, HTTP
   and WebSocket authentication, browser content headers, and configuration
   loading and migration. Check upstream's own guarantees before adding wrapper
   enforcement.
6. **Map hazards to focused tests:** Reuse existing test suites and add small
   behavioral fixtures for any uncovered route. Testing unrelated upstream
   features is outside this wrapper's scope.

## Rebuild the candidate patch for a new release

`stack-patches/<release>/*` refs on the `fork` remote
([mikeperry-tor/hermes-agent](https://github.com/mikeperry-tor/hermes-agent))
preserve each release's topic commits and combined replay so maintainers can
reproduce `0001-upstream-candidates.patch` even after `upstream-pr/*` submission
branches advance. The local working clone is `upstream_work/hermes-agent/`; see
[v0.23.3 build provenance](plans/hermes-upstream-prep.md#v0233-build-provenance).

When a new Hermes release still needs candidate patches:

1. Start a temporary replay branch from the exact source commit shipped in the
   new official image. Compare the previous release replay against the active
   submission branches (`fix/*` and `feat/*` in `upstream_work/hermes-agent/`)
   to identify which fixes belong on the new base.
2. Replay only the topic commits the new release still lacks, including the
   shared managed-configuration prerequisite (PR1) once and resolving overlaps.
   For any feature upstream has adopted, verify it with upstream's tests and our
   packaged checks, then drop that candidate patch and duplicate tests while
   keeping wrapper tests for configuration, isolation, ingress, and storage. If
   upstream has adopted all candidate changes, remove
   `0001-upstream-candidates.patch` and its build input.
3. Export the diff from the new release base to the combined replay head as
   `0001-upstream-candidates.patch`, excluding upstream Python tests, website
   files, contributor metadata, and Electron-only files. Record the base commit
   and replay head in the patch header, then rebase the downstream deployment
   and privacy patches (`0002`+) on top and verify the full series against the
   packaged source.
4. Record the carried topics, overlap resolutions, and test results in the
   upgrade plan. Push the combined replay to `stack-patches/<release>/combined`
   and keep the active submission branches intact for open PRs.

## Qualification and regression checklist

### Frontend, routes, and dispatch

- Build the frontend with upstream's frozen lockfile and hash-verified `pnpm`
  pin in a separate build stage. The runtime image may omit `pnpm` (its
  missing-binary warning is advisory), while dependency or build errors must
  fail the build. Qualify Python plugin environment setup separately from
  frontend tooling.
- Audit saved-gateway HTTP and WebSocket relays, inline `browser_vault`
  dispatch, peer routes, and backup-transfer routes in addition to patched
  files. Verify authentication, exact host and origin checks, response headers,
  and refusal of unauthorized or invalid requests without state mutation. Test
  unconfigured-provider refusal directly rather than enabling a provider or
  widening grants to exercise a route.
- Preserve ARM64 Chromium discovery, no-follow named-tab marker writes, and
  upstream's restricted-client CDN consumer. Per-hop CDN redirect checks do not
  replace bounded raster retrieval, IP pinning, TLS and credential isolation, or
  origin consent.

### Images, SSH files, and state migrations

- **Image Save and Copy:** Test menu dispatch, cancellation, one-time `ask`
  approval, `off` refusal, original and extensionless filenames, saved-gateway
  behavior, and proxy failure without direct browser fallback, plus CORS and
  size behavior in `browser_native`. (A controlled clipboard sink verifies bytes
  and request placement, not OS clipboard permissions or Electron.)
- **SSH file error classification:** Verify `ENOENT` and HTTP 404 for missing
  files and missing parent directories alongside regular files, directories,
  symlinks, and sensitive paths. GNU `realpath` can succeed on a missing final
  path component, so check the exact status code rather than accepting any
  error.
- **Populated profile upgrades:** Upgrade a populated profile from the prior
  official Hermes release (not just an empty profile) and load it twice. Verify
  settings, transcripts, identities, and `.env`, auth, and plugin files survive
  schema migration. Check upstream defaults (such as `agent.clarify_timeout` in
  [tool discovery default](configuration.md#tool-discovery-default)) against
  documented configuration behavior rather than assuming prior defaults held.
- **Build inputs:** Recheck the Python lockfile, executor browser harness,
  screenshot helper, `tests/fixtures/session-resume-active-turn.json`, `pnpm`
  pin, and stock Compose comparison against the new source before reusing older
  test results.

### Evidence discipline

- Rebuild every image used by a test fixture so stale local tags cannot hide
  changes. Keep build failures, service readiness failures, and application
  failures distinct.
- Serialize tests that share fixed subnets or host ports, using isolated test
  projects and dummy credentials. Test both allowed and forbidden paths, plus
  dependency outage and recovery; source inspection alone does not qualify
  isolation.
- When reusing passed evidence across partial reruns, preserve fixture
  prerequisites (for example, screenshot and download checks depend on artifacts
  from earlier browser steps) and note any skipped phases.
- Record the tested source commit, passing checks, and platform or live-service
  limits in
  [packaged Hermes qualification](development.md#packaged-hermes-qualification).
  Keep execution chronology and phase logs in the upgrade plan, not appended to
  maintained guides, and keep private logs out of Git.
