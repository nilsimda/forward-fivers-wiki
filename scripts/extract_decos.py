#! /usr/bin/env python3
import argparse
import struct
from dataclasses import dataclass
from itertools import batched
from pathlib import Path
from typing import ClassVar, TypedDict

from extract_common import (
    DEFAULT_DATA_PATHS,
    REPO_ROOT,
    load_item_names,
    read_u32,
    write_json_output,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()

    parser.add_argument("--input", type=Path, default=DEFAULT_DATA_PATHS["mhfdat"])
    parser.add_argument(
        "--item-names", type=Path, default=DEFAULT_DATA_PATHS["item_names"]
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "site" / "src" / "data" / "generated" / "decos.json",
    )

    return parser.parse_args()


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

    _STRUCT: ClassVar[struct.Struct] = struct.Struct("<HHHBBHBBHBBHBB")

    @classmethod
    def _parse_craft_items(
        cls, unpacked: tuple[int, ...], item_names_by_id: dict[int, str]
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
        cls, raw: bytes, offset: int, item_names_by_id: dict[int, str]
    ) -> "Deco":
        unpacked = cls._STRUCT.unpack_from(raw, offset)
        return cls(
            id=unpacked[0],
            name=item_names_by_id.get(unpacked[0], ""),
            receipt_category=unpacked[1],
            craft_recipes=[cls._parse_craft_items(unpacked, item_names_by_id)],
        )

    def add_recipe(self, recipe: list[DecoCraftItem]) -> None:
        self.craft_recipes.append(recipe)

    @classmethod
    def size(cls) -> int:
        return cls._STRUCT.size


DECO_SHOP_HEADER_POINTER = 0x00000044


def extract_decos(
    raw: bytes,
    item_names_by_id: dict[int, str],
) -> list[Deco]:
    decoshop_table_base = read_u32(raw, DECO_SHOP_HEADER_POINTER)
    by_id: dict[int, Deco] = {}
    while True:
        deco = Deco.unpack_from(raw, decoshop_table_base, item_names_by_id)
        decoshop_table_base += Deco.size()
        if deco.id == 0 and deco.receipt_category == 0:
            break
        if deco.id in by_id:
            by_id[deco.id].add_recipe(deco.craft_recipes[0])
        else:
            by_id[deco.id] = deco

    return list(by_id.values())


def main() -> None:
    args = parse_args()
    item_names = load_item_names(args.item_names)
    decos = extract_decos(
        args.input.read_bytes(),
        item_names,
    )
    write_json_output(args.output, decos)


if __name__ == "__main__":
    main()
