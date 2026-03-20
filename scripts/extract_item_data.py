#!/usr/bin/env python3
import argparse
import json
import struct
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

INPUT_DEFAULT = REPO_ROOT / "g1_data" / "mhfdat.raw.bin"
OUTPUT_DEFAULT = REPO_ROOT / "site" / "src" / "data" / "generated" / "_items-source.json"

ITEMS_HEADER_POINTER_ADDRESS = 0x00000100
ITEM_NAMES_HEADER_POINTER_ADDRESS = 0x00000104
ITEM_DESCRIPTIONS_HEADER_POINTER_ADDRESS = 0x00000130
ITEM_DESCRIPTIONS_POINTER_TABLE_OFFSET = 0x60

ITEM_COUNT_POINTER_ADDRESS = 0x00000010
ITEM_COUNT_OFFSET_FROM_POINTER = 0x0C

POINTER_FMT = "<I"
U16_FMT = "<H"
ITEM_STRUCT_FMT = "<BBBBBBBBHHIIHHHBBHBB"
ITEM_STRUCT_SIZE = struct.calcsize(ITEM_STRUCT_FMT)


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


def read_u32(raw: bytes, offset: int, label: str) -> int:
    size = struct.calcsize(POINTER_FMT)
    if offset < 0 or offset + size > len(raw):
        raise ValueError(f"{label}: offset 0x{offset:08X} out of bounds")
    (value,) = struct.unpack_from(POINTER_FMT, raw, offset)
    return value


def read_u16(raw: bytes, offset: int, label: str) -> int:
    size = struct.calcsize(U16_FMT)
    if offset < 0 or offset + size > len(raw):
        raise ValueError(f"{label}: offset 0x{offset:08X} out of bounds")
    (value,) = struct.unpack_from(U16_FMT, raw, offset)
    return value


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


def read_pointer_array(raw: bytes, base: int, count: int, label: str) -> list[int]:
    pointers: list[int] = []
    for index in range(count):
        pointer_offset = base + index * 4
        pointers.append(read_u32(raw, pointer_offset, f"{label}[{index}]"))
    return pointers


def extract_items(raw: bytes) -> tuple[list[dict[str, int | str]], int, int, int, int]:
    item_count_base_ptr = read_u32(raw, ITEM_COUNT_POINTER_ADDRESS, "item_count_pointer")
    item_count = read_u16(
        raw, item_count_base_ptr + ITEM_COUNT_OFFSET_FROM_POINTER, "item_count"
    )

    item_structs_base = read_u32(raw, ITEMS_HEADER_POINTER_ADDRESS, "item_structs_header")
    names_pointer_base = read_u32(raw, ITEM_NAMES_HEADER_POINTER_ADDRESS, "item_names_header")
    desc_pointer_header = read_u32(
        raw, ITEM_DESCRIPTIONS_HEADER_POINTER_ADDRESS, "item_descriptions_header"
    )
    desc_pointer_base = desc_pointer_header + ITEM_DESCRIPTIONS_POINTER_TABLE_OFFSET

    name_pointers = read_pointer_array(raw, names_pointer_base, item_count, "name_pointer")
    desc_pointers = read_pointer_array(raw, desc_pointer_base, item_count, "desc_pointer")

    rows: list[dict[str, int | str]] = []
    for item_index in range(item_count):
        offset = item_structs_base + item_index * ITEM_STRUCT_SIZE
        if offset + ITEM_STRUCT_SIZE > len(raw):
            raise ValueError(
                f"Item struct for index {item_index} out of bounds at 0x{offset:08X}"
            )

        unpacked = struct.unpack_from(ITEM_STRUCT_FMT, raw, offset)
        (
            _unk00,
            _unk01,
            rarity_raw,
            max_stack,
            _unk04,
            icon,
            icon_color,
            _unk07,
            _bottle,
            _unk0A,
            buy_price,
            sell_price,
            item_type,
            _deco_id,
            _unk18,
            _unk1A,
            _unk1B,
            _equip_type,
            _is_gz,
            _unk1F,
        ) = unpacked

        rows.append(
            {
                "item_index": item_index,
                "name": decode_c_string(raw, name_pointers[item_index]),
                "description": decode_c_string(raw, desc_pointers[item_index]),
                "rarity_raw": rarity_raw,
                "rarity_plus_one": rarity_raw + 1,
                "maxStack": max_stack,
                "icon": icon,
                "iconColor": icon_color,
                "buyPrice": buy_price,
                "sellPrice": sell_price,
                "type": item_type,
            }
        )

    return rows, item_count, item_structs_base, names_pointer_base, desc_pointer_base


def main() -> None:
    args = parse_args()
    raw = args.input.read_bytes()
    rows, item_count, items_base, names_base, desc_base = extract_items(raw)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"Input: {args.input}")
    print(f"Output: {args.output}")
    print(f"Items: {item_count}")
    print(f"Item structs base: 0x{items_base:08X}")
    print(f"Names pointer base: 0x{names_base:08X}")
    print(f"Descriptions pointer base (+0x60): 0x{desc_base:08X}")


if __name__ == "__main__":
    main()
