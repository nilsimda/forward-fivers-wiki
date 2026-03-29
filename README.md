# Forward Fivers Wiki (MHFG G1)

Static, data-driven wiki for Monster Hunter Frontier G1.
Specifically the Forward Fivers Client and Quest Files are used,
including the translations.

## Repository layout

- `scripts/`: python extraction scripts which use game files such as mhfdat,
mhfinf and quest files to produce formatted json of the game data.
- `site/`: Astro + Tailwind static wiki app which uses these json files as its source of truth

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

Build scripts use committed generated source JSON and then produce Astro-ready JSON:

1. Read committed source JSON in `site/src/data/generated` (for example `_items-source.json`, `_quests-source.json`)
2. Build projections used by pages (`site/scripts/build-data.mjs`)

Generated outputs currently include:

- `site/src/data/generated/items.json` (core item metadata)
- `site/src/data/generated/monster-drops.json` (monster-centric drop projection)
- `site/src/data/generated/item-acquisition.json` (item-centric obtain methods)

Extraction note:

- Extraction is a local maintainer workflow and requires local `g1_data` inputs.
- The repository commits generated source JSON (for example `_items-source.json`, `_partbreak-source.json`, `_carves-source.json`, `_hcc-carves-source.json`, `_quests-source.json`) rather than raw game binaries/quest files.
- Normal `npm run dev` and `npm run build` do not run extraction.

To refresh extraction outputs locally from repository root:

```bash
cd site
npm run data:extract:all
npm run data:build
```

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
