#!/usr/bin/env python3
import argparse
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

from extract_common import (
    REPO_ROOT,
    WIKI_HIDDEN_ITEM_IDS_FILENAME,
    ColorTagSegment,
    decode_c_string,
    is_wiki_hidden_item,
    parse_color_tags,
    read_pointer_array,
    read_u16,
    read_u32,
    write_json_output,
)

INPUT_DEFAULT = REPO_ROOT / "g1_data" / "mhfdat.raw.bin"
OUTPUT_DEFAULT = (
    REPO_ROOT / "site" / "src" / "data" / "generated" / "_items-source.json"
)

ITEMS_HEADER_POINTER_ADDRESS = 0x00000100
ITEM_NAMES_HEADER_POINTER_ADDRESS = 0x00000104
ITEM_DESCRIPTIONS_HEADER_POINTER_ADDRESS = 0x00000130
ITEM_DESCRIPTIONS_POINTER_TABLE_OFFSET = 0x60

ITEM_COUNT_POINTER_ADDRESS = 0x00000010
ITEM_COUNT_OFFSET_FROM_POINTER = 0x0C

ITEM_STRUCT_FMT = "<BBBBBBBBHHIIHHHBBHBB"
ITEM_STRUCT_SIZE = struct.calcsize(ITEM_STRUCT_FMT)


class ItemRow(TypedDict):
    item_index: int
    name: str
    description: str
    descriptionPlain: str
    descriptionSegments: list[ColorTagSegment]
    rarity_plus_one: int
    maxStack: int
    icon: int
    iconColor: int
    buyPrice: int
    sellPrice: int
    isGz: bool
    type: int


@dataclass(slots=True)
class ItemStructFields:
    rarity_raw: int
    max_stack: int
    icon: int
    icon_color: int
    buy_price: int
    sell_price: int
    item_type: int
    is_gz_raw: int

    def __post_init__(self) -> None:
        """Basic Sanity check of the field ranges after loading the struct."""
        if self.is_gz_raw not in (0, 1):
            raise ValueError(f"is_gz_raw must be 0 or 1, got {self.is_gz_raw}")
        if not self.icon <= 0x5D:
            raise ValueError(f"icon must be smaller than 0x5D, got {self.icon}")
        if not self.icon_color <= 0x0A:
            raise ValueError(
                f"icon color must be smaller than 0x0A, got {self.icon_color}"
            )
        # TODO: check max rarity (what is it?)

    @property
    def isGz(self) -> bool:
        return self.is_gz_raw == 1

    @classmethod
    def from_unpacked(cls, unpacked: tuple[int, ...]) -> "ItemStructFields":
        return cls(
            rarity_raw=unpacked[2],
            max_stack=unpacked[3],
            icon=unpacked[5],
            icon_color=unpacked[6],
            buy_price=unpacked[10],
            sell_price=unpacked[11],
            item_type=unpacked[12],
            is_gz_raw=unpacked[-2],
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract item table + names/descriptions from mhfdat.raw.bin into JSON."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=INPUT_DEFAULT,
        help="Path to mhfdat.raw.bin",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_DEFAULT,
        help="Output JSON path consumed by site/scripts/build-data.mjs",
    )
    return parser.parse_args()


def extract_items(
    raw: bytes,
) -> list[ItemRow]:
    item_count_base_ptr = read_u32(
        raw, ITEM_COUNT_POINTER_ADDRESS, "item_count_pointer"
    )
    item_count = read_u16(
        raw, item_count_base_ptr + ITEM_COUNT_OFFSET_FROM_POINTER, "item_count"
    )

    item_structs_base = read_u32(
        raw, ITEMS_HEADER_POINTER_ADDRESS, "item_structs_header"
    )
    names_pointer_base = read_u32(
        raw, ITEM_NAMES_HEADER_POINTER_ADDRESS, "item_names_header"
    )
    desc_pointer_header = read_u32(
        raw, ITEM_DESCRIPTIONS_HEADER_POINTER_ADDRESS, "item_descriptions_header"
    )
    desc_pointer_base = desc_pointer_header + ITEM_DESCRIPTIONS_POINTER_TABLE_OFFSET

    name_pointers = read_pointer_array(
        raw, names_pointer_base, item_count, "name_pointer"
    )
    desc_pointers = read_pointer_array(
        raw, desc_pointer_base, item_count, "desc_pointer"
    )

    rows: list[ItemRow] = []
    for item_index in range(item_count):
        offset = item_structs_base + item_index * ITEM_STRUCT_SIZE
        if offset + ITEM_STRUCT_SIZE > len(raw):
            raise ValueError(
                f"Item struct for index {item_index} out of bounds at 0x{offset:08X}"
            )

        fields = ItemStructFields.from_unpacked(
            struct.unpack_from(ITEM_STRUCT_FMT, raw, offset)
        )

        description = decode_c_string(raw, desc_pointers[item_index])
        description_stripped = description.strip()
        parsed_description = parse_color_tags(description_stripped)

        rows.append(
            {
                "item_index": item_index,
                "name": decode_c_string(raw, name_pointers[item_index]),
                "description": description,
                "descriptionPlain": parsed_description.plain,
                "descriptionSegments": parsed_description.segments,
                "rarity_plus_one": fields.rarity_raw + 1,
                "maxStack": fields.max_stack,
                "icon": fields.icon,
                "iconColor": fields.icon_color,
                "buyPrice": fields.buy_price,
                "sellPrice": fields.sell_price,
                "type": fields.item_type,
                "isGz": fields.isGz,
            }
        )

    return rows


def partition_hidden_items(rows: list[ItemRow]) -> tuple[list[ItemRow], list[int]]:
    kept_rows: list[ItemRow] = []
    hidden_ids: list[int] = []
    for row in rows:
        if is_wiki_hidden_item(
            name=row["name"], description_plain=row["descriptionPlain"]
        ):
            hidden_ids.append(row["item_index"])
        else:
            kept_rows.append(row)
    return kept_rows, hidden_ids


def main() -> None:
    args = parse_args()
    raw = args.input.read_bytes()
    rows = extract_items(raw)

    kept, hidden_ids = partition_hidden_items(rows)

    hidden_path = args.output.parent / WIKI_HIDDEN_ITEM_IDS_FILENAME
    write_json_output(hidden_path, {"itemIds": hidden_ids})
    write_json_output(args.output, kept)

    print(
        f"Extracted {len(kept)} items into wiki source ({len(hidden_ids)} wiki-hidden rows)"
    )


if __name__ == "__main__":
    main()
