---
name: Handle Cpp Color Tags
overview: Normalize inline color control tags in item descriptions at build time while preserving the original extracted text, then render structured segments safely in the item UI.
todos:
  - id: parse-description-tags
    content: Add description parser + structured fields in build-data item projection
    status: completed
  - id: render-segments
    content: Render parsed description segments on item detail page with safe color mapping
    status: completed
  - id: clean-search-text
    content: Switch item index search to plain normalized description text
    status: completed
  - id: document-contract
    content: Document new description fields and parser behavior in generated data README
    status: completed
isProject: false
---

# Handle Cpp Color Tags in Item Descriptions

## Recommendation

Treat `~Cxx(...)`/`~Cxx` tags as **presentation metadata**, not content. Keep the extracted raw string for fidelity, but generate a parsed representation for display/search.

## Why This Approach

- Preserves source truth from extraction for debugging and future parser improvements.
- Avoids leaking engine control syntax into user-visible text.
- Keeps rendering safe (no HTML injection) by using tokenized text segments.
- Lets search/filter use clean text instead of control codes.

## Planned Changes

- In `[/Users/macbeth/fun/mhfg/forward-fivers-wiki/site/scripts/build-data.mjs](/Users/macbeth/fun/mhfg/forward-fivers-wiki/site/scripts/build-data.mjs)`, add a small parser for description control tags:
  - detect open tags like `~C05(` and close/reset tags like `)~C00` / trailing `~C00`
  - output:
    - `descriptionRaw` (original)
    - `descriptionPlain` (tags stripped)
    - `descriptionSegments` (`[{ text, colorCode|null }]`)
- Keep extraction unchanged in `[/Users/macbeth/fun/mhfg/forward-fivers-wiki/scripts/extract_item_data.py](/Users/macbeth/fun/mhfg/forward-fivers-wiki/scripts/extract_item_data.py)` so raw binary decode stays lossless.
- Update item rendering in `[/Users/macbeth/fun/mhfg/forward-fivers-wiki/site/src/pages/items/[slug].astro](/Users/macbeth/fun/mhfg/forward-fivers-wiki/site/src/pages/items/[slug].astro)`:
  - render `descriptionSegments` as text spans with a controlled color map (e.g., `05 -> amber`), fallback to default text if unknown code.
  - never use raw HTML injection.
- Update search indexing in `[/Users/macbeth/fun/mhfg/forward-fivers-wiki/site/src/pages/items/index.astro](/Users/macbeth/fun/mhfg/forward-fivers-wiki/site/src/pages/items/index.astro)` to use `descriptionPlain`.
- Document the contract change in `[/Users/macbeth/fun/mhfg/forward-fivers-wiki/site/src/data/generated/README.md](/Users/macbeth/fun/mhfg/forward-fivers-wiki/site/src/data/generated/README.md)`.

## Parsing Rules (Initial)

- `~Cxx(` starts colored text region (`xx` hex/decimal code captured as string).
- `)~C00` or `~C00` resets to default color.
- Malformed or unmatched tags are treated as literal text (fail-soft).
- Keep newline behavior unchanged.

## Rollout

- First pass supports the codes seen now (`C05`, `C00`) and degrades gracefully for unknown codes.
- If additional codes appear later, only the color map needs expansion; parsed structure remains stable.

