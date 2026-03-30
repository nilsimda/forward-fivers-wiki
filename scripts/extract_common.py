"""Shared helpers for mhfdat extract scripts."""

from __future__ import annotations

import json
import re
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict

REPO_ROOT = Path(__file__).resolve().parent.parent

WIKI_HIDDEN_ITEM_IDS_FILENAME = "_wiki-hidden-item-ids.json"

U16_FMT = "<H"
U32_FMT = "<I"
_COLOR_TAG_RE = re.compile(r"~C([0-9A-Fa-f]{2})")


class ColorTagSegment(TypedDict):
    text: str
    colorCode: str | None


@dataclass(slots=True)
class ParsedColorTaggedText:
    plain: str
    segments: list[ColorTagSegment]


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


def read_pointer_array(raw: bytes, base: int, count: int, label: str) -> list[int]:
    pointers: list[int] = []
    for index in range(count):
        pointer_offset = base + index * 4
        pointers.append(read_u32(raw, pointer_offset, f"{label}[{index}]"))
    return pointers


def parse_color_tags(raw_text: str) -> ParsedColorTaggedText:
    """
    Parse `~CXX` color tags into plain text and colorized segments.

    `~C00` is treated as reset to no color (`None`).
    """
    segments: list[ColorTagSegment] = []
    current_color: str | None = None
    cursor = 0

    for match in _COLOR_TAG_RE.finditer(raw_text):
        if match.start() > cursor:
            segments.append(
                {"text": raw_text[cursor : match.start()], "colorCode": current_color}
            )
        next_code = match.group(1).upper()
        current_color = None if next_code == "00" else next_code
        cursor = match.end()

    if cursor < len(raw_text):
        segments.append({"text": raw_text[cursor:], "colorCode": current_color})

    merged: list[ColorTagSegment] = []
    for segment in segments:
        if not segment["text"]:
            continue
        previous = merged[-1] if merged else None
        if previous is not None and previous["colorCode"] == segment["colorCode"]:
            previous["text"] += segment["text"]
            continue
        merged.append({"text": segment["text"], "colorCode": segment["colorCode"]})

    plain = "".join(segment["text"] for segment in merged)
    return ParsedColorTaggedText(plain=plain, segments=merged)


def is_dummy_placeholder_description(description_plain: str) -> bool:
    """True when the item's plain description is dummy (wiki-hidden)."""
    return str(description_plain or "").strip().casefold() == "dummy"


def name_contains_dummy_marker(name: str) -> bool:
    """True when the item name includes the Japanese placeholder substring ダミー (wiki-hidden)."""
    return "ダミー" in str(name or "")


def is_wiki_hidden_item(*, name: str, description_plain: str) -> bool:
    """True when this item should be omitted from the wiki (items list and drop tables)."""
    return is_dummy_placeholder_description(
        description_plain
    ) or name_contains_dummy_marker(name)


def default_wiki_hidden_item_ids_path(items_json: Path) -> Path:
    return items_json.parent / WIKI_HIDDEN_ITEM_IDS_FILENAME


def load_wiki_hidden_item_ids(path: Path) -> frozenset[int]:
    item_ids: list[int] = json.loads(path.read_text(encoding="utf-8"))["itemIds"]
    return frozenset(item_ids)


def load_item_names(items_json_path: Path) -> dict[int, str]:
    data = json.loads(items_json_path.read_text(encoding="utf-8"))
    return {row["id"]: row["name"] for row in data}


def load_monster_names(monster_names_json_path: Path) -> dict[int, str]:
    raw = json.loads(monster_names_json_path.read_text(encoding="utf-8"))
    return {int(mon_id): mon_name for mon_id, mon_name in raw.items()}


def load_json_object(path: Path) -> dict[str, Any]:
    """Load a required JSON object. Missing file or non-object JSON raises."""
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


def decode_c_string(raw: bytes, pointer: int) -> str:
    if pointer == 0:
        return ""
    if pointer < 0 or pointer >= len(raw):
        raise ValueError(f"String pointer 0x{pointer:08X} out of bounds")

    end = raw.find(b"\x00", pointer)
    if end == -1:
        end = len(raw)
    data = raw[pointer:end]

    for encoding in ("utf-8", "shift_jis", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace")
