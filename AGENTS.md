# MHFG1 Wiki

Our goal in this project is to produce a static webapp which serves as a wiki
for Monster Hunter Frontier G1.

## Tech stack

The wiki app lives in the `site/` subfolder and uses a static build pipeline:

- Astro for static site generation and routing
- Tailwind CSS for styling
- TypeScript for page/component logic and data safety
- Node-based data transform scripts to convert extracted JSON into generated JSON

Build/data flow:

- Source data: `g1_data/mhfdat.raw.bin` + `g1_data/monster_names.json`
- Transform script: `site/scripts/build-data.mjs`
- Generated data output: `site/src/data/generated/*.json`
- Static output: `site/dist/`
- Deployment: GitHub Pages via `.github/workflows/deploy-pages.yml`

Useful commands (from `site/`):

- `npm run dev` (runs data build first, then starts dev server)
- `npm run build` (runs data build first, then creates static build)

## Ferias Reference

For a reference on structure (not necessarily style, we can make it more modern)
we use the Ferias Wiki for ZZ a newer version of the game. The Ferias static webapp
is in the ferias_reference/ subfolder. G1 has different stats all around, less
monsters and other features so we can NEVER use Data from Ferias directly.

## Extracted G1 data

Instead we extracted some data from the G1 game files directly. This process is
ongoing and currently we only have a small subset. You can find the currently
available data in the g1_data/ subfolder. Currently available is:

- extracted item metadata from binary sources
- extracted monster part break and drop rows from binary sources
- editable `monster_id -> monster_name` mappings in `g1_data/monster_names.json`

## Python script checks

After changing files in `scripts/`, run:

- `uv run ruff check .`
- `uv run mypy scripts`

## Extract script data contracts

- Treat JSON sidecar inputs as required and strict across pipelines (`items.json`, `monster_names.json`, carve/partbreak label files, and `_wiki-hidden-item-ids.json`).
- Do not add fallback behavior for missing files, missing keys, or type coercion in extract loaders; fail loudly instead.
- Keep binary pointer/bounds/sentinel checks strict (these are safety checks, not optional input handling).
