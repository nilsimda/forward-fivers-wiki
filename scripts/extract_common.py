"""Shared helpers for mhfdat extract scripts."""

from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

WIKI_HIDDEN_ITEM_IDS_FILENAME = "_wiki-hidden-item-ids.json"

U16_FMT = "<H"
U32_FMT = "<I"


def read_u32(raw: bytes, offset: int, label: str) -> int:
    size = struct.calcsize(U32_FMT)
    if offset < 0 or offset + size > len(raw):
        raise ValueError(f"{label}: offset 0x{offset:08X} out of bounds")
    (value,) = struct.unpack_from(U32_FMT, raw, offset)
    return value


def read_u16(raw: bytes, offset: int, label: str) -> int:
    size = struct.calcsize(U16_FMT)
    if offset < 0 or offset + size > len(raw):
        raise ValueError(f"{label}: offset 0x{offset:08X} out of bounds")
    (value,) = struct.unpack_from(U16_FMT, raw, offset)
    return value


def is_dummy_placeholder_description(description_plain: str) -> bool:
    """True when the item's plain description is the game's placeholder (wiki-hidden)."""
    return str(description_plain or "").strip().casefold() == "dummy"


def name_contains_dummy_marker(name: str) -> bool:
    """True when the item name includes the Japanese placeholder substring (ダミー)."""
    return "ダミー" in str(name or "")


def is_wiki_hidden_item(*, name: str, description_plain: str) -> bool:
    """True when this item should be omitted from the wiki (items list and drop tables)."""
    return is_dummy_placeholder_description(description_plain) or name_contains_dummy_marker(name)


def default_wiki_hidden_item_ids_path(items_source: Path) -> Path:
    return items_source.parent / WIKI_HIDDEN_ITEM_IDS_FILENAME


def load_wiki_hidden_item_ids(path: Path) -> frozenset[int]:
    if not path.exists():
        return frozenset()
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {path}")
    raw_ids = data.get("itemIds")
    if raw_ids is None:
        return frozenset()
    if not isinstance(raw_ids, list):
        raise ValueError(f'Expected "itemIds" list in {path}')
    out: set[int] = set()
    for x in raw_ids:
        if not isinstance(x, int):
            raise ValueError(f'Expected integer entries in "itemIds" in {path}')
        out.add(x)
    return frozenset(out)


def load_item_names(items_source_path: Path) -> dict[int, str]:
    if not items_source_path.exists():
        return {}
    data = json.loads(items_source_path.read_text(encoding="utf-8"))
    names_by_id: dict[int, str] = {}
    for row in data:
        item_id = row.get("item_index")
        if not isinstance(item_id, int):
            continue
        name = str(row.get("name", "")).strip()
        if name:
            names_by_id[item_id] = name
    return names_by_id


def load_monster_names(monster_names_json_path: Path) -> dict[int, str]:
    if not monster_names_json_path.exists():
        return {}

    raw = json.loads(monster_names_json_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(
            f"Monster names JSON must be an object mapping ids to names: {monster_names_json_path}"
        )

    names_by_id: dict[int, str] = {}
    for raw_monster_id, raw_name in raw.items():
        if raw_monster_id is None:
            continue
        try:
            monster_id = int(str(raw_monster_id).strip(), 0)
        except ValueError:
            continue
        monster_name = str(raw_name or "").strip()
        if not monster_name:
            continue
        names_by_id[monster_id] = monster_name
    return names_by_id


def load_optional_json_object(path: Path) -> dict[str, Any]:
    """Load a JSON object; missing file yields {}. Non-object JSON raises."""
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return data


def write_json_output(path: Path, data: object, *, ensure_ascii: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=ensure_ascii) + "\n",
        encoding="utf-8",
    )
