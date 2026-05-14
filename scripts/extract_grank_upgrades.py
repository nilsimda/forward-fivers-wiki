#! /usr/bin/env python3
"""
Parse G-rank weapon upgrade records from mhfdat.

Record layout (36 bytes):
  u32 weapon_id
  u16 level_from
  u16 level_to
  u32 zenny_cost
  3x (u16 item_id, u16 amount, u32 padding)    -- material costs

We read sequentially from the base offset until a sentinel weapon_id (0x0000 or 0xFFFF).

Currently G-rank upgrades offer two recipes (A/B) per target level. Those seem to
appear as consecutive records sharing the same (level_from, level_to) with different
material costs. We don't group them yet; we emit flat records for inspection.
"""

import argparse
import json
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from extract_common import (
    DEFAULT_DATA_PATHS,
    REPO_ROOT,
    load_item_names,
    write_json_output,
)

GRANK_UPGRADE_BASE_OFFSET = 0x00660D94
WEAPONS_JSON_PATH = (
    REPO_ROOT / "site" / "src" / "data" / "generated" / "melee_weapons.json"
)


@dataclass(slots=True)
class GRankUpgrade:
    weapon_id: int
    weapon_name: str
    weapon_class: str
    level_from: int
    level_to: int
    zenny_cost: int
    material_costs: list[dict]

    _STRUCT: ClassVar[struct.Struct] = struct.Struct("<IHHIHHIHHIHHI")

    @classmethod
    def size(cls) -> int:
        return cls._STRUCT.size

    @classmethod
    def unpack_from(
        cls,
        raw: bytes,
        offset: int,
        item_names: dict[int, str],
        weapons_by_id: dict[int, dict],
    ) -> "GRankUpgrade":
        u = cls._STRUCT.unpack_from(raw, offset)
        weapon_id = u[0]
        weapon = weapons_by_id.get(weapon_id)
        material_costs = []
        for item_id, amount in ((u[4], u[5]), (u[7], u[8]), (u[10], u[11])):
            if item_id == 0 or amount == 0:
                continue
            material_costs.append(
                {
                    "item_id": item_id,
                    "item_name": item_names.get(item_id, f"<unknown 0x{item_id:04X}>"),
                    "amount": amount,
                }
            )
        return cls(
            weapon_id=weapon_id,
            weapon_name=weapon["name"] if weapon else f"<unknown 0x{weapon_id:08X}>",
            weapon_class=weapon["class_name"] if weapon else "",
            level_from=u[1],
            level_to=u[2],
            zenny_cost=u[3],
            material_costs=material_costs,
        )


def _load_weapons_by_id() -> dict[int, dict]:
    weapons = json.loads(WEAPONS_JSON_PATH.read_text(encoding="utf-8"))
    return {w["id"]: w for w in weapons}


def extract_grank_upgrades(
    raw: bytes,
    item_names: dict[int, str],
    weapons_by_id: dict[int, dict],
) -> list[GRankUpgrade]:
    offset = GRANK_UPGRADE_BASE_OFFSET
    result: list[GRankUpgrade] = []
    while True:
        entry = GRankUpgrade.unpack_from(raw, offset, item_names, weapons_by_id)
        # Sentinel: weapon_id sits outside the melee weapon table, or zero/FFFF.
        if (
            entry.weapon_id in (0x00000000, 0xFFFFFFFF)
            or entry.weapon_id not in weapons_by_id
        ):
            break
        result.append(entry)
        offset += GRankUpgrade.size()
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Parse G-rank weapon upgrade records from mhfdat."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_DATA_PATHS["mhfdat"],
        help="Path to unpacked mhfdat file.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "scratch" / "grank_upgrades.json",
        help="Output JSON path.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    raw = args.input.read_bytes()
    item_names = load_item_names()
    weapons_by_id = _load_weapons_by_id()

    upgrades = extract_grank_upgrades(raw, item_names, weapons_by_id)

    write_json_output(args.output, upgrades)
    print(f"wrote {len(upgrades)} records to {args.output}")


if __name__ == "__main__":
    main()
