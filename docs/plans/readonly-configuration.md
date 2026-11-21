# Read-only runtime configuration

Status: proposed; no runtime changes made.
Engine-parity planning baseline: `rootless-podman-support`, `1a6d298`.
Follow the [planning workflow](../planning-workflow.md) before implementation.

## Objective

Prevent runtime agent processes from changing operator-owned deployment policy
while preserving an explicit, usable configuration and upgrade workflow. First
determine which settings can be protected without breaking Hermes's supported
configuration writes or migrations.

This is configuration integrity work, not a claim that all agent state becomes
immutable. Resource and storage limits, a read-only root filesystem, and changes
to the SSH execution boundary are outside scope.

## Current baseline

- `setup init` creates `/opt/data/config.yaml` from the packaged template. With
  Teep enabled, a nonblank `TEEP_INSTALL_MODEL` seeds the initial selection and
  starter catalog. A blank value leaves the selection to Hermes with Teep model
  discovery enabled. Hermes owns saved provider and model choices.
  [Local socket grants](../configuration.md#local-inference-and-http-mcp) and
  Teep startup mode are root deployment settings.
- Hermes owns its writable state under `/opt/data`, including configuration,
  sessions, skills, and memories.
- The networkless `hermes-config` command currently edits that same data volume
  as UID 10000. Setup and configuration commands can also write configuration.
- Hermes configuration code uses atomic replacement. A read-only file mount
  can prevent both intended writes and automatic migration; even a writable
  file mount may conflict with replacement of the mounted inode.
- Provider keys live in teep's environment, outside Hermes and the executor.
  Read-only configuration would not add confidentiality to those keys.
- Optional onion ingress keeps the same trusted proxy and native authentication
  settings. Its generated HAProxy config is separate from agent policy; preserve
  localhost, Funnel HTTPS and onion HTTP origins when protecting configuration.

## Invariants

- Keep the SSH backend, optional Teep route, selected MCP boundaries and
  exact Hermes host/LAN grants intact.
- Keep sessions, memories, and other required runtime state writable.
- Preserve existing configuration and user settings during migration.
- Give the runtime no writable mount or alternate write path to the protected
  authoritative configuration source.
- Keep administrative editing separate from runtime execution. Do not put a
  privileged configuration writer under the agent's tool authority.
- Make rejected runtime edits and migration requirements clear. Do not silently
  ignore a requested change, create a divergent writable config, or temporarily
  make protected policy writable at runtime.

## Design investigation

Inspect the exact pinned Hermes image before choosing a design:

1. Inventory configuration consumers and writers: initial setup, `config set`,
   model selection, MCP installation/authentication, profile management,
   gateway reload, and automatic schema or version migrations.
2. Identify which settings are operator policy and which are ordinary mutable
   preferences. Decide whether protection is required only for the default
   profile or also for every supported additional profile.
3. Evaluate Hermes's managed configuration/policy facilities, if supported by
   the pinned image. Verify which keys they enforce, precedence, failure
   behavior, and whether runtime-owned files can override them. Do not infer
   enforcement merely from a setting's name or documentation in a newer branch.
4. Compare that facility with a complete read-only configuration mount. The
   latter must account for every required write and migration path, not just
   normal chat startup.
5. Select and document one authoritative configuration model before changing
   the deployment. Prefer a mechanism that protects policy while retaining
   normal preference edits when it provides the required enforcement.

### Shared design and engine-specific evidence

Target one policy model, storage layout and administrative workflow for Docker
and rootless Podman. Investigate native managed policy first; do not introduce
engine-specific policy formats, writer services or a generic publication system.
For native policy, trace runtime precedence through profiles, environment and
other writable configuration sources, and verify the protected values actually
govern consumers. Describe the limits of enforcement in a process that can load
operator-authorized writable plugins; a read-only file does not make arbitrary
runtime code obey it.

For a mount-based design, compare a single-file read-only bind with a dedicated
read-only configuration directory whose writable administrative mount supports
atomic replacement. Check which layout the pinned Hermes supports without
changing its home or moving mutable databases onto host binds. A directory bind
may avoid a pinned file inode, but does not establish safe hot reload, prevent
partial multi-file reads or remove the need for a documented application step.
Compare native-volume delivery only if host binds demonstrate a concrete blocker;
any separate policy volume must have a justified owner, publication workflow and
backup scope. Select one approach rather than implementing all candidates.

Measure actual mounts and reads on both engines, including the qualified Docker
Desktop filesystem and native rootless Podman. Inventory container UID/GID 10000,
host/subordinate-ID mappings, parent traversal permissions and any ownership
changes caused by volume initialization. Permissions alone do not establish
runtime immutability: prove the read-only mount and absence of writable aliases,
including an overlapping Hermes-data mount. Avoid recursive ownership repair,
automatic bind relabeling or loosening private-file modes to resolve a mismatch.
Additional host security-label requirements, if encountered, need explicit
target-specific investigation; do not claim untested host support.

Required bind sources must use the existing managed creation checks. On the
qualified Podman API, Compose's `create_host_path: false` alone does not enforce
missing-source refusal. Exercise both engine paths without changing provider or
adding another preflight framework. Keep inspection, shutdown and offline repair
available when unrelated deployment settings are invalid; a missing policy may
block its consumer, not unrelated saved-data access.

Coordinate writer UID/capability requirements with the implemented
[Hermes boundary](../architecture.md#hermes-capability-boundary) and
[executor capability requirements](../architecture.md#executor-capability-requirements).
Do not solve rootless ownership
or read-only mount failures with additional runtime grants, engine sockets,
privileged containers or a switch to rootful operation. Any engine exception must
identify the reproduced operation, affected filesystem/target and simplest
shared alternative before design acceptance.

## Candidate mount-based workflow

If a complete read-only configuration file is the appropriate design:

1. Introduce a dedicated operator-owned configuration source, separate from
   writable agent state. Preserve the existing configuration through an
   explicit export/import step; do not replace it with the example template.
2. Mount the selected configuration read-only into the runtime. Avoid mounting
   its parent directory writable through the data volume or another alias.
3. Adapt `setup init` to validate the mounted configuration and its ownership
   contract without trying to copy, chown, chmod, or migrate that mount.
4. Adapt `hermes-config` for the operator-owned configuration source. It should edit a
   writable staging directory that supports atomic file replacement, validate
   the candidate, and publish it through an operator-controlled action.
5. Define the application step. Recreating runtime containers after publication
   is the conservative default: an existing file bind mount can retain the old
   inode after the operator atomically replaces its source file. Demonstrate
   any supported reload alternative rather than assuming it works.
6. Handle image upgrades and configuration migrations against a staging copy
   before the new runtime starts. Retain the previous image/configuration pair
   for rollback. Never solve a migration failure by making runtime policy
   writable or disabling the migration without understanding its requirements.

Preserve current-format configuration, credentials and operator choices on retries
and interrupted publication. Identify the authoritative source and make individual
publications atomic using the existing operation coordination where needed.
Document any required stop/recreate ordering, particularly when multiple files
must change together; do not add a transaction journal or recovery service.
Backup and restore must include the selected policy source and preserve its
ownership without granting runtime write access.

A managed-policy design needs an equivalent documented editing, validation,
application, migration, and rollback workflow, even if preference files remain
writable.

## Qualification

Use the same disposable fixtures and real production entrypoints on both qualified
engines. Validate effective base/Funnel Compose mounts and actual runtime mount
permissions; rendered `read_only` settings alone are not evidence. Check:

- Fresh provisioning and migration from a populated writable configuration,
  preserving unrelated settings and existing key identities.
- Startup, CLI and gateway operation, supported profiles, and restart behavior.
- An attempted runtime write or atomic replacement of protected configuration
  fails, including attempts through any alternate mounted path. Test runtime
  application processes and retained root supervision separately; include direct
  writes, rename/unlink and permission/ownership changes where applicable.
- Operator edits succeed through the maintenance path, are validated before
  publication, and become the effective configuration after the documented
  application step. Confirm the loaded values, not just the source file.
- Runtime setup, model selection, MCP changes, and other affected writers
  either remain supported or give an actionable maintenance instruction.
- Required sessions, memories, and other mutable state still work.
- Malformed configuration, unsupported policy keys, and incompatible image
  upgrades fail visibly without a writable-policy fallback.
- The existing SSH execution, Tor routing, host/VM isolation, and selected MCP
  integration checks still pass.
- A representative upgrade/migration and rollback preserve configuration and
  data. Do not claim general upgrade compatibility from one startup test.
- Missing required policy sources fail without creating a replacement directory
  or starting the affected service; offline repair and unrelated inspection work.
- Host/admin atomic replacement while a container exists has the documented
  visibility on each engine; recreation loads the new value and rollback restores
  the previous value. Check configured values through the real consuming path.
- Interrupted validation/publication and repeated initialization preserve the
  authoritative configuration, identities and unrelated mutable state. Invalid
  candidates leave the last valid source intact. Backup/restore preserves the
  selected layout and rootless ownership mappings.

Run `make check` and `make test` on both engines for implementation changes,
together with focused initialization, administrative editing and migration checks.
Include desktop/browser policy consumers when the selected protected keys affect
them. Reuse existing storage, bind-mount and maintenance fixtures; serialize tests
sharing deployment resources. Use no operator secrets, paid calls or live Funnel
enrollment. Record image/engine/provider/filesystem versions and unavailable
coverage; current platform limits in the development guide still apply.

## Acceptance and rollout

Implement only after the authoritative configuration mechanism and all affected
user workflows are understood. Document which policy is protected, what remains
mutable, and how to make a legitimate change. If protection requires changing a
supported workflow, provide its concrete replacement as part of the same change.

First commit the pinned-consumer/writer inventory, selected shared design and
focused evidence; obtain fresh independent design review before runtime edits.
Then implement the coherent storage, setup, maintenance and consumer changes with
their tests and updates to configuration/backup and development guides. Obtain
fresh final combined review after both-engine qualification, before acceptance.
Reconcile shared-writer and capability requirements with the implemented
boundaries in [architecture](../architecture.md#hermes-capability-boundary) if
either changes.
This plan-only amendment supplies no runtime qualification or design-gate pass.

The engine-parity amendment against baseline `1a6d298` received fresh independent
read-only review with no material findings. Local-link target checks and
`git diff --check` passed. Runtime tests were not run for this documentation-only
change; design selection, design acceptance and implementation qualification
remain pending.

Rollback must restore the previous image, configuration source, and mount
arrangement while preserving state volumes. Runtime configuration protection
does not replace tool permissions, MCP authorization, credential separation,
or review of writable plugins and skills.
