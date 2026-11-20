# Adopt Hermes v0.23.3 and the release-based upstream candidates

Wrapper baseline is `5361088` on `hermes-v0.23.3`. The existing official
v0.23.2 source is `ae2a81ccc00e9b7c06301523e5bb09608397149c`.
The official v0.23.3 index is
`sha256:3e9fe4c6ef36490f43aa0d0d80f9df64e9c92a576eee3042f1a97c8813c05355`.
The reference tag resolves to `caafe5389ae585ef77387a962aee05b1bcf17029`,
which is already the common base of PR1–PR4. Use their combined replay
`087222ccf6cbd04ac89096bab4182e05e2af6b0f` as the source for release patches.
Keep release-based candidate history attributable when preparing later
submission updates. PR5 is deferred. Upstream publication is outside scope.

## Integration

1. Independently review the adoption design. Verify packaged source, native
   renderer receipt and hash, locked dependencies, screenshot helper and stock
   Compose against the official revision. Review the source delta for changes
   to startup, dispatch, SSH and WebApp boundaries.
2. Vendor the candidate replay's packaged changes with exact provenance. Rebase
   private content deployment capture, gateway retrieval, response policy and
   renderer patches. Prefer the candidates' native managed file input for SSH,
   terminal placement, URL references and tool restrictions. Keep Compose's
   existing operator selections and provision their managed values before native
   loading. Retain a small release-specific change where a stack invariant
   requires behavior absent from the candidate implementation. Keep Docker and
   Podman on the shared image and Compose contract.
3. Verify patch application, delivered modules, renderer and affected wrapper
   checks. Exercise native managed authority, real SSH placement/recovery,
   URL bypass and normal turns, the desktop/content matrix, local and simulated
   HTTPS terminals and private images, and repeated setup with populated state.
   Use disposable fixtures on both engines where reachable. Record actual
   results and gaps, obtain independent combined review, update the maintained
   guides and remove this plan after acceptance.

Preserve SSH executor separation, Tor-only application egress, the narrow
inference and MCP grants, operator versus model terminal authority, WebApp
authentication and private raster/consent behavior, and existing private data.
Live ingress, provider attestation and financial actions are outside scope.
