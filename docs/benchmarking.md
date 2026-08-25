# Benchmarking

```bash
vecparity benchmark --from memory://bench-source --to qdrant://mycollection \
    --num-records 200000 --dimension 128 --batch-size 500
```

`vecparity benchmark` seeds synthetic vectors into `--from`, then times a
real `SyncEngine` run into `--to`, reporting throughput, batch count, and
peak memory during the sync. Only the sync itself is timed; seeding is
reported separately since it isn't part of what a real migration measures.

By default it seeds an in-memory source and syncs into an in-memory
target, useful for exercising the harness itself. Point `--to` (or
`--from`) at a real backend to measure something meaningful; the target
collection/table needs to already exist with a matching dimension.

## What this doesn't tell you

This is a synthetic, single-machine benchmark, not a substitute for
testing at your actual data scale on your actual infrastructure. A
number from a laptop against a single local Docker container and a
number from a production migration between two managed services in the
same region are not comparable. Treat this as a tool for producing your
own numbers under your own conditions, not a source of numbers to quote.

It also doesn't count individual backend API calls, only sync batches
(`SyncEngine.stats.batches`, one `upsert()` call per batch). Getting an
exact network-call count would mean instrumenting six different SDKs
individually; the batch count is a reasonable proxy without that cost.

## A real run, for context

One data point, not a benchmark claim: 200,000 synthetic 128-dimension
vectors, in-memory source, target a single local Docker Qdrant
container (`qdrant/qdrant:latest`) over localhost, `--batch-size 500`.

| | |
|---|---|
| Machine | 13th Gen Intel Core i5-1335U, 15.7 GB RAM |
| Sync time | 98.5s |
| Throughput | ~2,030 records/sec |
| Batches | 400 |
| Peak memory during sync | 462.6 MB |

Re-run it yourself before trusting a number for anything that matters.
