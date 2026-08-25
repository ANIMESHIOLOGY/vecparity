# Cutover Workflow

A live migration doesn't have a single point where it's "done." Once it's
caught up and verified, there's a defined path from there to actually
cutting over, instead of a `migrate run` you either trust blindly or
don't run at all.

## Status

Every migration (a `--from`/`--to` pair) has a persisted operational
status, alongside its checkpoint: `not_started`, `syncing`, `paused`,
`verified`, `cut_over`, `rolled_back`, or `cancelled`.

```bash
vecparity migrate status --from pgvector://docs --to qdrant://docs
```

## Pause and resume

```bash
vecparity migrate pause --from pgvector://docs --to qdrant://docs
```

This is cooperative, not a kill signal: a running `migrate run --live`
process checks for a pause request once per poll and stops cleanly,
checkpointing first. There's no separate daemon process to signal
directly, so this only takes effect while a `--live` run is actually
in progress; otherwise it just records the request until the next run.

Resuming is just re-running `migrate run` (without `--fresh`); it picks
up from the checkpoint automatically.

## Cancel

```bash
vecparity migrate cancel --from pgvector://docs --to qdrant://docs
```

Marks the migration cancelled. The checkpoint itself isn't deleted (use
`vecparity checkpoint clear` for that); a future `migrate run` refuses
to resume a cancelled migration unless you pass `--fresh`.

## Cutover

```bash
vecparity cutover --from pgvector://docs --to qdrant://docs \
    --queries golden_queries.json --min-recall 0.95
```

Runs one final sync pass to close any last gap, then a final parity
check. The migration is only marked `cut_over` if that check passes; if
it fails, the command exits non-zero and the migration's status is left
as-is.

## Rollback

```bash
vecparity rollback --from pgvector://docs --to qdrant://docs
```

Marks a cut-over migration rolled back.

**What this doesn't do:** vecparity has no way to redirect your
application's traffic, and `rollback` doesn't sync data back to the
source, it isn't a two-way replication tool. Both commands track state
and give you evidence, a real final parity check, for a decision you
still make and act on yourself.
