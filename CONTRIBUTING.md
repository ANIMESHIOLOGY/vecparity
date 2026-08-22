# Contributing to vecparity

Thank you for your interest in contributing!

---

## Dev Environment Setup

```bash
git clone https://github.com/ANIMESHIOLOGY/vecparity
cd vecparity
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -e ".[all,dev]"
pre-commit install
```

## Running Tests

```bash
# Unit tests only — no external services required
pytest tests/ -m "not integration" --ignore=tests/integration

# With coverage
pytest tests/ --cov=vecparity -m "not integration" --ignore=tests/integration

# Integration tests — need real backend instances (pgvector, Qdrant,
# Milvus, Weaviate, Chroma). docker-compose.test.yml spins up all five.
docker compose -f docker-compose.test.yml up -d
pytest tests/integration/ -m integration
docker compose -f docker-compose.test.yml down -v
```

Integration tests are what actually catch backend-specific bugs (wrong SQL,
missing type adapters, wrong client API calls) that the in-memory adapter's
unit tests can't — see `tests/integration/` before assuming a change to an
adapter is safe just because unit tests pass.

## Code Style

- **Formatter**: `black` (line length 100)
- **Linter**: `ruff`
- **Types**: `mypy --strict`

Run all checks:

```bash
black vecparity/ tests/
ruff check vecparity/ tests/
mypy vecparity/
```

## Adding a New Backend Adapter

Implement `vecparity.adapters.base.VectorDBAdapter` — five methods:
`get`, `upsert`, `delete`, `list_changed_since`, `search`, plus `count`.
Deliberately minimal by design (see the module docstring in `base.py`):
resist the urge to grow the interface into a general query API, that's
how this kind of tool ends up a leaky permanent ORM instead of a
migration tool.

1. `vecparity/adapters/memory.py` is the smallest reference implementation — start there.
2. `vecparity/adapters/qdrant.py` or `pgvector.py` show what a real backend with quirks (id-type restrictions, missing native `search()`, type casting) looks like.
3. Add an optional dependency group in `pyproject.toml`.
4. Wire it into `_load_adapter()` in `cli.py`, and document its env vars in `docs/backends.md`.
5. Add integration tests under `tests/integration/` if the backend has a docker image; otherwise unit tests against the in-memory adapter plus manual verification against a real instance.

## Branch Naming

- `adapter/<backend-name>` — new backend adapter
- `fix/<short-description>` — bug fix
- `docs/<topic>` — documentation only

## PR Checklist

- [ ] Tests written and passing (unit, and integration if touching an adapter)
- [ ] `CHANGELOG.md` updated under `## Unreleased`
- [ ] `mypy` passes with no new errors
- [ ] `ruff` and `black` pass

## Docstring Standard

Module and function docstrings are prose-first, not strict Google-style
`Args:`/`Returns:` blocks — explain *why*, not just restate the
signature. See `vecparity/verify/parity.py`'s module docstring for the
target style.

## Building Docs Locally

```bash
pip install -e ".[docs]"
mkdocs serve
```

---

Questions? Open a [Discussion](https://github.com/ANIMESHIOLOGY/vecparity/discussions).
