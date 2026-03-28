# Forward Fivers Wiki (MHFG G1)

Static, data-driven wiki for Monster Hunter Frontier G1.

## Project goals

- Build a modern static webapp wiki for G1.
- Use extracted G1 data as the canonical source.
- Use Ferias only as structure inspiration, never as game-data truth.

## Repository layout

- `g1_data/`: extracted binary-derived data files and manual mappings
- `site/`: Astro + Tailwind static wiki app

## Data ingestion rules

- Treat extracted `mhfdat.raw.bin` outputs as canonical gameplay/stat sources.
- Keep `g1_data/monster_names.json` as the editable source of truth for monster display names.
- When new extraction data arrives, update transform logic and regenerate JSON.
- Keep transformations deterministic so diffs are reviewable.

## Local development

Requirements: Node 22+, Python 3.11+, and `uv`.

```bash
cd site
npm install
npm run dev
```

The dev/build scripts automatically run the data pipeline first:

1. Extract binary-backed source data using Python (`scripts/extract_item_data.py`, `scripts/extract_partbreak_data.py`, `scripts/extract_hcc_carves.py`, `scripts/extract_carve_data.py`)
2. Build Astro-ready generated JSON (`site/scripts/build-data.mjs`)

Generated outputs currently include:

- `site/src/data/generated/items.json` (core item metadata)
- `site/src/data/generated/monster-drops.json` (monster-centric drop projection)
- `site/src/data/generated/item-acquisition.json` (item-centric obtain methods)

Source note:

- Item source rows are now extracted from `g1_data/mhfdat.raw.bin` into `site/src/data/generated/_items-source.json` as part of the build pipeline.
- Partbreak source rows are now extracted from `g1_data/mhfdat.raw.bin` into `site/src/data/generated/_partbreak-source.json` as part of the build pipeline.
- HCC carve source rows are now extracted from `g1_data/mhfdat.raw.bin` into `site/src/data/generated/_hcc-carves-source.json` as part of the build pipeline.
- Regular carve source rows are now extracted from `g1_data/mhfdat.raw.bin` into `site/src/data/generated/_carves-source.json` as part of the build pipeline.
- Monster name labels for partbreak extraction are loaded from `g1_data/monster_names.json`.
- Monster name labels for carve extraction are loaded from `g1_data/monster_names.json`.

Schema and guardrail details are documented in `site/src/data/generated/README.md`.

## Python quality checks

Install Python tooling and hooks once from the repository root:

```bash
uv sync --group dev
uv run pre-commit install
```

Run checks manually:

```bash
uv run ruff format --check scripts tests
uv run ruff check scripts tests
uv run mypy scripts
uv run pytest
```

## Build and deploy

- `npm run build` in `site/` generates static output at `site/dist`.
- GitHub Actions workflow `.github/workflows/deploy-pages.yml` builds and deploys to GitHub Pages.
- Base path is set from repository name in CI (`/${repo-name}`) for project-pages hosting.


## TODOs:
### Frontend:
1. Display Item icons + colors
2. Monster Names should not be optional

### RE
1. Carve Tables - carve options per mon?
2. Quest Rewards - where are they in g1?
3. Data of different shops
4. Gathering, Mining, Bugs?



