# Private document search: xerj and OpenViking comparison

Status: proposed; no document-search services, ingestion, or paid model calls enabled.
Engine-parity amendment baseline: `rootless-podman-support`, `3f66fa5`.
Follow the [planning workflow](../planning-workflow.md) before implementation.

## Objective and selection requirement

Compare xerj and OpenViking for a personal library of approximately 10 GB of
PDF books, research papers, and other documents. Evaluate both finding cited
passages and helping Hermes discover which books are available and useful.

We are investigating these options specifically because they can use **teep or
a local embedding server for private, accelerated embeddings**. Embedding work
should be able to run on an appropriate accelerated inference service without
requiring an embedding model inside the Hermes process. The first remote target
is NearAI's Qwen3-Embedding-0.6B through teep; a local OpenAI-compatible embedding
server should be an alternative using the same model where practical.

**MediaRAG is currently not under consideration for this reason.** Its documented
implementation uses its own local EmbeddingGemma-2 ONNX model and does not expose
the external embedding endpoint configuration required for this comparison.
This exclusion concerns endpoint and acceleration control, not its supported
formats. Reconsider it only if that requirement becomes supported or changes.

Private here includes control over the destination and transport of document
text. Local embeddings keep that processing on the local machine. Embeddings
through teep send text to the selected provider under teep's attestation and
encryption policy; they are not offline processing. Preserve upstream teep
verification policy and qualify the chosen provider path. Tor alone does not
provide document confidentiality to an embedding or summarization provider.

## Candidates and hypotheses

| Candidate | Search and storage | Additional capabilities to evaluate |
| --- | --- | --- |
| xerj | Integrated keyword, vector, and hybrid retrieval; no separate Qdrant or Elasticsearch service required | PDF page/section provenance, corpus inventory, incremental ingestion, and agent search tools |
| OpenViking | Embedded local vector storage with configurable embedding and optional reranking endpoints; no Qdrant required | Resource directories, generated abstracts/overviews, scoped browsing, and optional conversation memory |

xerj is the initial candidate for focused library retrieval. OpenViking may be
more useful when Hermes needs to orient itself among books, navigate summaries,
and retain reading preferences or research context. Treat these as hypotheses;
do not assume either candidate has better retrieval quality or capacity from
its feature list or published benchmarks.

Record the exact source revisions, build configuration, models, and settings
used in each run. The inspected xerj checkout was `1557de2f5` and identified
itself as `1.0.0-rc.102`; select and record a full revision before building.
Recheck OpenViking's server and Hermes plugin together, since the catalog pin,
server version, reference checkout, and deployed Hermes image can differ.

## Optional comparison deployment

Keep experimental search services out of the default stack during evaluation.
Use an explicit **`compose.xerj.yaml` overlay** to add xerj and its required
integration components only when selected. Provide a corresponding optional
OpenViking overlay so either candidate can be evaluated independently. Running
both together should be an explicit comparison mode, not a startup dependency.

- Keep root `.env` / `.env.example` as the unified operator settings, including
  source-library path, selected embedding endpoint, and model identifiers.
  These model selections are deployment settings; image/source pins remain in
  Compose and component Dockerfiles.
- Put implementation files under `components/xerj/` and
  `components/openviking/`. Editable mounted configuration belongs under
  `config/`, with tracked defaults beside the components.
- Keep candidate indexes, catalogs, generated summaries, and reports in
  separate persistent locations. Prefer explicit experiment directories under
  `data/document-search/` for backup and inspection. Retain original PDFs
  separately; an index is derived data. Existing application volumes remain
  unchanged.
- Mount only the selected library directory read-only into the ingestion
  component. Hermes and its SSH executor do not need direct library mounts.
- Grant the candidate only the internal connections needed for Hermes access
  and teep or the selected local embedding server. Maintain host/VM isolation
  and executor denial of search, administrative, and embedding endpoints.
  Run the embedding server in a selected container where practical. The
  [operator's Hermes grants](../configuration.md#local-inference-and-http-mcp)
  can reach a selected host/LAN embedding endpoint from Hermes. A separate
  search component does not inherit that path and needs its own reviewed grant.
- Leave public endpoints unpublished. Route any separately required public
  fetches through Tor; do not give a search service a direct Internet uplink.
  Teep retains its existing direct provider connection.
- Separate operator ingestion/administration from agent search/read authority.
  Do not expose unrestricted write, delete, or source-import tools merely
  because the upstream MCP server advertises them.
- xerj's native MCP transport is stdio and forwards to its HTTP search node.
  Qualify either a client executable in the Hermes image or a narrow HTTP MCP
  adapter. Do not assume the search port is a Streamable HTTP MCP endpoint,
  and do not mount the Docker socket to launch the client.
- Document overlay startup, shutdown, configuration, backup, and removal.
  Deselecting a candidate must also remove its active Hermes tool connection
  without deleting its stored experiment data.

Do not introduce arbitrary CPU, memory, storage, or time limits as part of this
comparison. Measure usage and document native application limits and rejected
inputs, including xerj's inspected per-PDF limits, rather than silently skipping
material or weakening isolation to make ingestion succeed.

### Cross-engine feasibility and storage qualification

Target the same candidate images, API/tool contract and optional overlay workflow
on Docker and rootless Podman. Recheck native package/binary support for the actual
CPU architecture before building either candidate; record unsupported targets
rather than adding an emulation or engine adapter layer. Validate candidate and
explicit comparison overlays with the selected engine and optional ingress layers.

The experiment-directory preference above does not establish that host-backed
indexes are safe. Identify each candidate's database/locking requirements and
test fresh-file locks, competing writers, restart recovery and index persistence
on the actual filesystem. Docker Desktop binds have failed existing stack lock
qualification. Prefer native named volumes for lock-sensitive state if those
binds fail; keep originals separate and document volume backup/export. Derived
indexes may be rebuildable, but incomplete caches must not trigger automatic paid
re-embedding or make intact originals unavailable for inspection.

Qualify read-only library mounts, missing-source refusal, UID/GID mappings,
ownership and native-volume initialization on each engine. Reuse existing managed
bind checks and storage probes plus application-specific checks; do not broaden
mounts, recursively repair library ownership or expose private PDFs to Hermes or
the executor. Optional ingestion must not run during ordinary stack initialization.

Accelerated embeddings are a separate feasibility axis from search-engine
compatibility. Investigate actual device/runtime support for the selected local
server on each target, including Docker Desktop's VM and rootless Podman device
permissions. Do not assume GPU passthrough or performance equivalence. Keep the
same OpenAI-compatible endpoint contract; an unavailable accelerator is an
explicit target limitation, not permission for privileged mode, broad device or
host-network access, CPU fallback without disclosure, or a remote-provider
fallback. A working CPU fixture can qualify integration without qualifying
accelerated performance.

## Embedding qualification

1. Confirm the actual model identifier exposed by teep. Its source includes
   `neardirect:Qwen/Qwen3-Embedding-0.6B` and `/v1/embeddings` support; endpoint
   availability and provider behavior still need a live qualification.
2. Explicitly select external/proxy embedding mode. In particular, xerj's
   default lexical feature-hash embedder is not the desired neural model.
3. Verify output dimensions, normalization/similarity behavior, batching,
   input-length handling, and provider errors before creating the corpus index.
   Qwen3-Embedding-0.6B supports up to 1024 dimensions; use the dimensions
   actually returned by the configured endpoint.
4. Verify query-versus-document formatting. Qwen supports retrieval query
   instructions; check whether the candidate or an adapter must apply them.
   Use consistent formatting across candidates and record it with the index.
5. Confirm ingestion and queries use the same embedding model and configuration.
   Keep indexes for different model identities separate. Never silently mix
   vectors or truncate embedding inputs without reporting it.
6. Measure throughput, latency, tokens, provider charges, retry behavior, and
   restart/reuse behavior. An interrupted run should not unnecessarily resend
   all previously embedded text. Do not infer embedding volume from PDF bytes.

Configure OpenViking's summary generation separately from embeddings. It needs
an appropriate chat model, which may also use teep. Record the additional text
sent, processing time, and cost. Disable optional third-party reranking during
initial comparison; evaluate a deliberately selected reranker as a separate run.

## Corpus preparation and extraction coverage

Build a deterministic inventory with stable document identifiers, source paths,
content hashes, and available title/author/edition/year metadata. Include
processing status so Hermes can distinguish available originals from documents
that have actually finished indexing. Generated summaries do not replace this
complete inventory.

Start with a representative subset spanning long books, short papers,
multi-column layouts, tables, mathematics, different languages where present,
scans, mixed scanned/text PDFs, duplicates, and encrypted or malformed files.
Choose this subset from the real collection before making a full-corpus run.

Measure each candidate's native PDF extraction and maintain an explicit report
of rejected documents and missing-text pages. xerj has no built-in OCR. Plan an
explicit OCR preprocessing stage for scans as needed, preserving originals and
linking derived text to original pages. Verify equations, reading order, page
numbers, and citations against the actual PDFs.

For retrieval-only comparison, also test a shared normalized text/chunk corpus
so extraction differences are distinguishable from search differences. Retain
source/page provenance in both the native and normalized ingestion paths.

## Retrieval and library-awareness evaluation

Prepare questions and expected evidence before comparing results. Include:

- Exact quotations, author/title searches, technical terms, and identifiers.
- Conceptual questions whose wording differs from the relevant passage.
- Questions requiring evidence from multiple chapters, books, or papers.
- Book-discovery tasks: which books cover a topic, where to start reading,
  and which available sources offer different treatments.
- Complete-inventory requests and questions about unindexed or absent books.
- Unanswerable questions, where the agent should acknowledge missing evidence.

Measure retrieval recall/ranking on known relevant passages, grounded answer
quality, citation accuracy, book coverage, latency, and context supplied to the
answering model. Record ingestion duration, storage and peak/steady-state memory
usage, embedding/summarization cost, and update/restart behavior. Distinguish
cold and warm queries and exact versus approximate search paths where relevant.

Use the same answering model and comparable retrieval settings for baseline
runs. Compare keyword-only, semantic-only, and hybrid retrieval where supported.
Record candidate-specific features separately rather than quietly changing the
workload or enabling additional paid models in one baseline.

For OpenViking, import a useful directory structure with a resource directory
per book where practical. Evaluate directory L0 abstracts, L1 overviews, and L2
content as navigation aids. These summaries describe directories, not necessarily
every individual file. Check summary fidelity and whether Hermes can browse
from the library inventory to the correct book and underlying evidence.

Do not assume OpenViking search always walks the hierarchy: its current docs
describe global vector retrieval, optionally scoped, with separate optional
intent analysis and reranking. Test actual Hermes behavior, including when it
chooses browsing, summary reading, and passage search. Give both candidates a
clear library-discovery instruction so tool-use differences are observable.

## Optional memory investigation

Evaluate OpenViking resource search first. Automatic conversation capture is a
separate feature decision, not required to import the library. If selected for
a later phase, test reading preferences, books already discussed, ongoing
research questions, and useful prior source selections across sessions.

Keep original resources, generated summaries, and learned memories identifiable.
A remembered interpretation or generated overview must not become a citation
for a claim that requires checking a book. Inspect which conversations, tool
results, and profile-memory edits the Hermes plugin sends to OpenViking and
which model receives them. Verify capture timing, recall, update/deletion, and
persistence before enabling this workflow generally.

## Decision and implementation gate

Write a comparison report with measured results, extraction gaps, operational
costs, and unresolved issues. Recommend xerj, OpenViking, or a justified combined
approach only after evaluating the library-discovery tasks as well as retrieval.
A combined system must demonstrate enough benefit to justify duplicate indexes,
processing, storage, and integration work.

Run existing configuration/network/executor checks and focused candidate tests
before full ingestion. Automated tests use fixtures and mocked embedding/model
responses; they must not automatically index the private library or make paid
provider calls. Initial paid qualification and full ingestion are explicit
operator actions. No inferred cost or arbitrary benchmark claim substitutes
for measurements on this collection.

Before comparison deployment, obtain fresh independent design review of the
selected pins, storage, least-privilege ingestion/search split and exact network
grants. In particular, a search service's embedding grant must not make it a
general inference proxy available to the executor. Coordinate selected MCP grants
and authoritative policy writers with the related listener and
read-only-configuration plans, and with the implemented capability boundaries,
without implementing those plans as dependencies.

On both qualified engines, use public synthetic documents and deterministic
embedding/chat fixtures to test ingestion, retrieval/provenance, restart/recreation,
interrupted-ingestion retry, backup/restore and candidate deselection. Prove allowed
Hermes search and selected embedding access, denied executor/private/host/VM
access, no direct Internet fallback, and applicable Tor-loss/recovery behavior.
Exercise ingestion/admin rejection through the agent's actual tool/API authority;
a smaller advertised tool list alone does not prove the write boundary.
Keep real-provider/model quality and acceleration measurements separate from
these integration passes, and do not duplicate paid corpus processing merely to
test another engine. Record native engine/provider/architecture/filesystem limits.
Update operating and development guides with the chosen integration and obtain
fresh final combined review before declaring implemented support. No implementation,
engine qualification or design acceptance is supplied by this plan amendment.

The engine-parity amendment against `3f66fa5` passed fresh independent read-only
review together with the listener and interactive-content amendments, with no
material findings. Local-link targets and `git diff --check` passed; no runtime
tests were run for these documentation-only changes. Future design,
implementation and both-engine qualification remain pending.

## References

- Local checkouts: `reference_repos/xerj`, `reference_repos/hermes-agent`, and
  `reference_repos/teep`.
- [xerj PDF indexing](https://xerj.org/answers/search-all-pdfs-in-a-folder)
- [xerj search and agent integration](https://xerj.org/for-agents)
- [OpenViking context layers](https://docs.openviking.ai/en/concepts/03-context-layers)
- [OpenViking retrieval](https://docs.openviking.ai/en/concepts/07-retrieval)
- [OpenViking model configuration](https://docs.openviking.ai/en/guides/01-configuration)
- [Qwen3-Embedding-0.6B](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B)
- [MediaRAG's inspected implementation](https://github.com/dyiapanis/mediarag/blob/29d47c34f53340eb3a4267792c61f38c34ee8e03/README.md)
