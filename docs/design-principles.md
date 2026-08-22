# Design Principles

## Migration-time only, not a permanent ORM

vecparity doesn't try to be a universal query API you build your app
against forever; that's how abstractions like this end up leaky (see
LangChain's `vectorstore` interface, which has to grow special-cases
for every backend's filter syntax and hybrid-search semantics).
`VectorDBAdapter` implements five operations:
`get`, `upsert`, `delete`, `list_changed_since`, `search`, and
nothing more. Resist the urge to add query-language features here;
that scope creep is exactly what turns a migration tool into a fragile,
permanent dependency.

## Incremental by default

`list_changed_since` plus a cursor means re-running a migration only
copies what changed since the last pass, so it's safe to run a
`SyncEngine` alongside a live app instead of requiring a maintenance
window. This is also why change tracking needs *some* timestamp
field: backends without a native change feed (Qdrant, Pinecone) rely
on a metadata field the caller maintains on writes.

## Quality, not just presence

Existing migration tools confirm data *arrived*: row counts match,
ids exist. None of them confirm the new database still *retrieves the
same things*, which is the only thing that actually matters to the app
sitting on top of it. `verify_parity()`, comparing recall@k, result
overlap, and score drift between source and target, is the actual
point of this project; everything else is plumbing to get there.

## Backend quirks are surfaced, not hidden

Real backends disagree in ways that matter. A few examples baked into
the adapters, documented rather than papered over:

- **Qdrant** only accepts unsigned-int or UUID point IDs; arbitrary
  strings are rejected. `QdrantAdapter` maps ids to a deterministic
  UUID5 and keeps the original id in the payload.
- **Qdrant cosine collections** store the *normalized* vector, not the
  one you upserted, so `get()` after `upsert()` won't byte-match.
- **Pinecone** has no native change feed and its `list()` is paginated
  in a way that's easy to get wrong (see `PineconeAdapter`'s module
  docstring).

vecparity doesn't try to hide these differences behind a uniform
abstraction. It documents them, because they're exactly the kind of
thing `verify_parity()` exists to catch if a migration handles them
incorrectly.
