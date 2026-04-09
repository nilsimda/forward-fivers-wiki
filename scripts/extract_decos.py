#! /usr/bin/env python3
import argparse
import struct
from dataclasses import dataclass
from itertools import batched
from pathlib import Path
from typing import ClassVar, TypedDict

from extract_common import (
    DEFAULT_DATA_PATHS,
    HEADER_POINTERS,
    REPO_ROOT,
    decode_c_string,
    load_item_names,
    read_u16,
    read_u32,
    write_json_output,
)
from extract_items import Item


def _extract_skill_point_names(mhfpac_raw: bytes) -> dict[int, str]:
    skill_point_names_base = HEADER_POINTERS["skill_point_names"]

    result: dict[int, str] = {}
    skill_id = 0
    while True:
        skill_point_name_pointer = read_u32(mhfpac_raw, skill_point_names_base)
        if skill_point_name_pointer == 0:
            break
        skill_point_name = decode_c_string(mhfpac_raw, skill_point_name_pointer)
        result[skill_id] = skill_point_name
        skill_id += 1
        skill_point_names_base += 4

    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()

    parser.add_argument("--input", type=Path, default=DEFAULT_DATA_PATHS["mhfdat"])
    parser.add_argument(
        "--item-names", type=Path, default=DEFAULT_DATA_PATHS["item_names"]
    )
    parser.add_argument("--mhfpac", type=Path, default=DEFAULT_DATA_PATHS["mhfpac"])
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "site" / "src" / "data" / "generated" / "decos.json",
    )

    return parser.parse_args()


class Skill(TypedDict):
    id: int
    name: str
    points: int


@dataclass(slots=True)
class DecoStats:
    n_slots: int
    price: int
    skills: list[Skill]

    _STRUCT: ClassVar[struct.Struct] = struct.Struct("<BHBHHBbBbBbBbHH")

    @classmethod
    def unpack_from(
        cls, raw: bytes, offset: int, skill_point_names_by_id: dict[int, str]
    ) -> "DecoStats":
        unpacked = cls._STRUCT.unpack_from(raw, offset)
        skills: list[Skill] = []
        for unpacked_skill in batched(unpacked[5:-2], 2):
            sid, pts = unpacked_skill
            if sid == 0 and pts == 0:
                continue
            skills.append(
                Skill(
                    id=sid,
                    name=skill_point_names_by_id.get(sid, f"Unknown ({sid})"),
                    points=pts,
                )
            )

        return cls(
            n_slots=unpacked[0],
            price=unpacked[3],
            skills=skills,
        )

    @classmethod
    def size(cls) -> int:
        return cls._STRUCT.size


class DecoCraftItem(TypedDict):
    item_id: int
    name: str
    quantity: int
    needed_for_unlock: bool


@dataclass(slots=True)
class Deco:
    id: int
    name: str
    receipt_category: int
    craft_recipes: list[list[DecoCraftItem]]
    stats: DecoStats

    _STRUCT: ClassVar[struct.Struct] = struct.Struct("<HHHBBHBBHBBHBB")

    @staticmethod
    def _get_stats_table_offset(raw: bytes, item_id: int) -> int:
        item_data_base = read_u32(raw, HEADER_POINTERS["items"])
        item_data_offset = item_data_base + item_id * Item.size()
        return read_u16(raw, item_data_offset + 22)

    @staticmethod
    def _extract_stats_table(
        raw: bytes, item_id: int, skill_point_names_by_id: dict[int, str]
    ) -> DecoStats:
        st_offset = Deco._get_stats_table_offset(raw, item_id)
        stats_table_base = read_u32(raw, DECO_STATS_TABLE_HEADER_POINTER)
        return DecoStats.unpack_from(
            raw,
            stats_table_base + st_offset * DecoStats.size(),
            skill_point_names_by_id,
        )

    @classmethod
    def _parse_craft_items(
        cls,
        unpacked: tuple[int, ...],
        item_names_by_id: dict[int, str],
    ) -> list[DecoCraftItem]:
        craft_items: list[DecoCraftItem] = []
        for item in batched(unpacked[2:], 3):
            craft_item = DecoCraftItem(
                item_id=item[0],
                name=item_names_by_id.get(item[0], ""),
                quantity=item[1],
                needed_for_unlock=bool(item[2]),
            )
            if craft_item["quantity"] != 0:
                craft_items.append(craft_item)
        return craft_items

    @classmethod
    def unpack_from(
        cls,
        raw: bytes,
        offset: int,
        item_names_by_id: dict[int, str],
        skill_point_names_by_id: dict[int, str],
    ) -> "Deco":
        unpacked = cls._STRUCT.unpack_from(raw, offset)
        return cls(
            id=unpacked[0],
            name=item_names_by_id.get(unpacked[0], ""),
            receipt_category=unpacked[1],
            craft_recipes=[cls._parse_craft_items(unpacked, item_names_by_id)],
            stats=cls._extract_stats_table(raw, unpacked[0], skill_point_names_by_id),
        )

    def add_recipe(self, recipe: list[DecoCraftItem]) -> None:
        self.craft_recipes.append(recipe)

    @classmethod
    def size(cls) -> int:
        return cls._STRUCT.size


DECO_SHOP_HEADER_POINTER = 0x00000044
DECO_STATS_TABLE_HEADER_POINTER = 0x000000FC


def extract_decos(
    raw: bytes,
    item_names_by_id: dict[int, str],
    skill_point_names_by_id: dict[int, str],
) -> list[Deco]:
    decoshop_table_base = read_u32(raw, DECO_SHOP_HEADER_POINTER)
    by_id: dict[int, Deco] = {}
    while True:
        deco = Deco.unpack_from(
            raw, decoshop_table_base, item_names_by_id, skill_point_names_by_id
        )
        decoshop_table_base += Deco.size()
        if deco.id == 0 and deco.receipt_category == 0:
            break
        if deco.id in by_id:
            by_id[deco.id].add_recipe(deco.craft_recipes[0])
        else:
            by_id[deco.id] = deco

    return sorted(by_id.values(), key=lambda d: d.id)


def main() -> None:
    args = parse_args()
    item_names = load_item_names(args.item_names)
    skill_point_names = _extract_skill_point_names(args.mhfpac.read_bytes())
    decos = extract_decos(
        args.input.read_bytes(),
        item_names,
        skill_point_names,
    )
    write_json_output(args.output, decos)


if __name__ == "__main__":
    main()
