# MHFG1 Wiki

Our goal in this project is to produce a static webapp which serves as a wiki
for Monster Hunter Frontier G1.

## Tech stack

The wiki app lives in the `site/` subfolder and uses a static build pipeline:

- Astro for static site generation and routing
- Tailwind CSS for styling
- TypeScript for page/component logic and data safety
- Node-based data transform scripts to convert extracted JSON into generated JSON
- Deployment: GitHub Pages via `.github/workflows/deploy-pages.yml`

Useful commands (from `site/`):

- `npm run dev` (runs data build first, then starts dev server)
- `npm run build` (runs data build first, then creates static build)

Agent workflow rules:

- Run all npm commands from the `site/` subdirectory (or with `--prefix site`).
- Do not run `npm run build` unless explicitly requested, since it is too slow for normal validation.

## Data Extraction

Done via the python scripts `scripts/` in. Data is taken directly from the game files in `g1_data/game/` where possible.
In rare cases we need access to manual labels these are in `g1_data/labels`.

Run all python scripts through uv. After changing files in `scripts/`, run:

- `uv run ruff check .`
- `uv run mypy scripts`

## Extract script data contracts

- Treat JSON sidecar inputs as required and strict across pipelines (`items.json`, `monster_names.json`, carve/partbreak label files, and `_wiki-hidden-item-ids.json`).
- Do not add fallback behavior for missing files, missing keys, or type coercion in extract loaders; fail loudly instead.
- Keep binary pointer/bounds/sentinel checks strict (these are safety checks, not optional input handling).

## Code Style

This is very important. Keep in mind the concept of negative space. We want to be very minimal and efficient with the lines
of code we add. If you find yourself adding a bunch of auxiliary functions, validation code etc, chances
are our data structures are not what we want them be. In that case instead of writing the code suggest data structure or refactoring changes to the pipeline to me to discuss.

