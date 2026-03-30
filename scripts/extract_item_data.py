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
OUTPUT_DEFAULT = REPO_ROOT / "site" / "src" / "data" / "generated" / "items.json"

ITEMS_HEADER_POINTER_ADDRESS = 0x00000100
ITEM_NAMES_HEADER_POINTER_ADDRESS = 0x00000104
ITEM_DESCRIPTIONS_HEADER_POINTER_ADDRESS = 0x00000130
ITEM_DESCRIPTIONS_POINTER_TABLE_OFFSET = 0x60

ITEM_COUNT_POINTER_ADDRESS = 0x00000010
ITEM_COUNT_OFFSET_FROM_POINTER = 0x0C

ITEM_STRUCT_FMT = "<BBBBBBBBHHIIHHHBBHBB"
ITEM_STRUCT_SIZE = struct.calcsize(ITEM_STRUCT_FMT)


class ItemRecord(TypedDict):
    id: int
    slug: str
    name: str
    description: str
    descriptionSegments: list[ColorTagSegment]
    rarityPlusOne: int
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
        help="Output frontend-ready items JSON path.",
    )
    return parser.parse_args()


def extract_items(
    raw: bytes,
) -> list[ItemRecord]:
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

    items: list[ItemRecord] = []
    seen: set[int] = set()
    for item_index in range(item_count):
        offset = item_structs_base + item_index * ITEM_STRUCT_SIZE
        if offset + ITEM_STRUCT_SIZE > len(raw):
            raise ValueError(
                f"Item struct for index {item_index} out of bounds at 0x{offset:08X}"
            )

        fields = ItemStructFields.from_unpacked(
            struct.unpack_from(ITEM_STRUCT_FMT, raw, offset)
        )

        description = decode_c_string(raw, desc_pointers[item_index]).strip()
        parsed_description = parse_color_tags(description)
        name = decode_c_string(raw, name_pointers[item_index]).strip()
        if item_index in seen:
            raise ValueError(f"Duplicate item id detected: {item_index}")
        seen.add(item_index)

        items.append(
            {
                "id": item_index,
                "slug": str(item_index),
                "name": name,
                "description": parsed_description.plain,
                "descriptionSegments": parsed_description.segments,
                "rarityPlusOne": fields.rarity_raw + 1,
                "maxStack": fields.max_stack,
                "icon": fields.icon,
                "iconColor": fields.icon_color,
                "buyPrice": fields.buy_price,
                "sellPrice": fields.sell_price,
                "type": fields.item_type,
                "isGz": fields.isGz,
            }
        )

    return items


def partition_hidden_items(
    items: list[ItemRecord],
) -> tuple[list[ItemRecord], list[int]]:
    kept_items: list[ItemRecord] = []
    hidden_ids: list[int] = []
    for item in items:
        if is_wiki_hidden_item(
            name=item["name"], description_plain=item["description"]
        ):
            hidden_ids.append(item["id"])
        else:
            kept_items.append(item)
    return kept_items, hidden_ids


def main() -> None:
    args = parse_args()
    raw = args.input.read_bytes()
    items = extract_items(raw)

    kept_items, hidden_ids = partition_hidden_items(items)

    hidden_path = args.output.parent / WIKI_HIDDEN_ITEM_IDS_FILENAME
    write_json_output(hidden_path, {"itemIds": hidden_ids})
    write_json_output(args.output, kept_items)

    print(
        f"Extracted {len(kept_items)} items into {args.output.name} ({len(hidden_ids)} wiki-hidden rows)"
    )


if __name__ == "__main__":
    main()
