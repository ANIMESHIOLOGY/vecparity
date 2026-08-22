# Installation

```bash
pip install vecparity
```

With backend support: install only the extras for the backends you're
actually migrating between.

```bash
pip install "vecparity[pgvector]"
pip install "vecparity[qdrant]"
pip install "vecparity[pinecone]"
pip install "vecparity[milvus]"
pip install "vecparity[weaviate]"
pip install "vecparity[chroma]"

# All backends
pip install "vecparity[all]"
```

## Requirements

- Python 3.10 or newer. `X | None` union syntax is used throughout,
  including in pydantic models and Typer CLI option types. Both
  resolve annotations at runtime, which needs real interpreter support
  for `|` on types (available from 3.10 on).

## Development install

```bash
git clone https://github.com/ANIMESHIOLOGY/vecparity
cd vecparity
pip install -e ".[all,dev]"
```

See [Contributing](https://github.com/ANIMESHIOLOGY/vecparity/blob/main/CONTRIBUTING.md) for running tests and code style.
