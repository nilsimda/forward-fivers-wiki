"""Shared helpers for mhfdat extract scripts."""

from __future__ import annotations

import dataclasses
import json
import re
import struct
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, TypedDict

REPO_ROOT = Path(__file__).resolve().parent.parent
BASE_DATA_PATH = REPO_ROOT / "g1_data"


DEFAULT_DATA_PATHS = {
    # orginal game data
    "mhfdat": BASE_DATA_PATH / "game" / "mhfdat.raw.bin",
    "mhfinf": BASE_DATA_PATH / "game" / "mhfinf.raw.bin",
    "quests": BASE_DATA_PATH / "game" / "unpacked_quests",
    "mhfpac": BASE_DATA_PATH / "game" / "mhfpac.raw.bin",
    # manual labels
    "monster_names": BASE_DATA_PATH / "labels" / "monster_names.json",
    "carve_labels": BASE_DATA_PATH / "labels" / "monster_carve_labels.json",
    "partbreak_labels": BASE_DATA_PATH / "labels" / "monster_partbreak_labels.json",
    "small_monsters": BASE_DATA_PATH / "labels" / "small_monsters.json",
    # generated
    "hidden_item_ids": BASE_DATA_PATH / "generated" / "wiki-hidden-item-ids.json",
    "item_names": BASE_DATA_PATH / "generated" / "item-labels.json",
}


HEADER_POINTERS = {
    # mhfdat pointers
    "mhfdat_counts": 0x00000010,
    "carve_table_indices": 0x0015B8FC,
    "carve_tables": 0x004D93F4,
    "hcc_table": 0x0000034C,
    "items": 0x00000100,
    "item_names": 0x00000104,
    "item_descriptions": 0x00000130,
    # mhfinf pointers
    "mhfinf_counts": 0x00000010,
    "quests": 0x00000014,
    # quest file pointers
    "quest_rewards": 0x0000000C,
    # mhfpac pointers
    "map_names": 0x000B9D40,
    "skill_point_names": 0x000C09D4,
}

U16_FMT = "<H"
U32_FMT = "<I"
_COLOR_TAG_RE = re.compile(r"~C([0-9A-Fa-f]{2})")

Rank = Literal["lr", "hr", "er", "gr"]


class ColorTagSegment(TypedDict):
    text: str
    colorCode: str | None


@dataclass(slots=True)
class ParsedColorTaggedText:
    plain: str
    segments: list[ColorTagSegment]


class DataclassEncoder(json.JSONEncoder):
    def default(self, obj):
        if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
            return dataclasses.asdict(obj)
        return super().default(obj)


def read_u32(raw: bytes, offset: int, label: str | None = None) -> int:
    size = struct.calcsize(U32_FMT)
    if offset < 0 or offset + size > len(raw):
        raise ValueError(f"{label}: offset 0x{offset:08X} out of bounds")
    (value,) = struct.unpack_from(U32_FMT, raw, offset)
    return value


def read_u16(raw: bytes, offset: int, label: str | None = None) -> int:
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


def is_wiki_hidden_item(name: str, description_plain: str) -> bool:
    return "ダミー" in name or description_plain.strip() == "dummy"


def load_wiki_hidden_item_ids(path: Path) -> frozenset[int]:
    item_ids: list[int] = json.loads(path.read_text(encoding="utf-8"))["itemIds"]
    return frozenset(item_ids)


def load_item_names(items_json_path: Path) -> dict[int, str]:
    raw = json.loads(items_json_path.read_text(encoding="utf-8"))
    return {int(item_id): item_name for item_id, item_name in raw.items()}


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
        json.dumps(data, indent=2, cls=DataclassEncoder, ensure_ascii=ensure_ascii)
        + "\n",
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


def load_small_monster_ids() -> frozenset[int]:
    raw = json.loads(DEFAULT_DATA_PATHS["small_monsters"].read_text(encoding="utf-8"))
    return frozenset(int(k) for k in raw)


def load_valid_monster_ranks() -> dict[int, set[Rank]]:
    quest_rewards = json.loads(
        (REPO_ROOT / "site" / "src" / "data" / "generated" / "quests.json").read_text()
    )
    small_monster_ids = load_small_monster_ids()
    all_ranks: set[Rank] = {"lr", "hr", "er", "gr"}

    monster_target_types = frozenset(
        {
            "Hunt",
            "Capture",
            "Slay",
            "Damage",
            "Slay or Damage",
            "Slay All",
            "Slay Total",
            "Break Part",
        }
    )

    monsterranks: dict[int, set[Rank]] = defaultdict(set)
    for mon_id in small_monster_ids:
        monsterranks[mon_id] = set(all_ranks)

    for quest in quest_rewards:
        mainGoal = quest["main_goal"]
        subGoalA = quest["subA_goal"]
        subGoalB = quest["subB_goal"]
        if mainGoal["target_kind"] in monster_target_types:
            mon_id = mainGoal["target"]
            if mon_id not in small_monster_ids:
                monsterranks[mon_id].add(quest["rank"])
        if subGoalA["target_kind"] in monster_target_types:
            mon_id = subGoalA["target"]
            if mon_id not in small_monster_ids:
                monsterranks[mon_id].add(quest["rank"])
        if subGoalB["target_kind"] in monster_target_types:
            mon_id = subGoalB["target"]
            if mon_id not in small_monster_ids:
                monsterranks[mon_id].add(quest["rank"])

    return monsterranks
