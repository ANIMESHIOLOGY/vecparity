<p align="center">
  <img src="assets/vecparity_logo.png" alt="vecparity logo" width="320">
</p>

# vecparity

**Live, quality-verified migration between vector databases.**

Every team on a managed vector database eventually wants to switch:
Pinecone got expensive, you want to self-host, a competitor is faster
for your workload. Existing tools stop at "the data arrived":
[vector-io/VDF](https://github.com/AI-Northstar-Tech/vector-io) does
batch export → import → re-embed across backends, and vendor migration
guides only cover moving *into* their own product. None of them check
whether retrieval quality survived the move.

vecparity does two things nothing else does together:

- **Migrates incrementally, without downtime.** A `SyncEngine` that
  polls a source adapter's `list_changed_since` cursor and replays
  changes to the target, so a migration can run alongside a live app.
- **Verifies retrieval parity before you cut over.** `verify_parity()`
  runs a query set against both the source and target and reports
  recall@k, result overlap, and score drift, producing a pass/fail
  `ParityReport` you can gate a deploy on.

## Where to go next

- [Installation](installation.md): install with the backends you need
- [Quick Start](quickstart.md): migrate and verify from the CLI or Python
- [Backends](backends.md): connection details and env vars per backend
- [Design Principles](design-principles.md): why the adapter surface is deliberately small
- [API Reference](api-reference/adapters.md): full module documentation
