#!/usr/bin/env python3
import argparse
import re
import struct
from pathlib import Path

from extract_common import (
    REPO_ROOT,
    WIKI_HIDDEN_ITEM_IDS_FILENAME,
    is_dummy_placeholder_description,
    read_u16,
    read_u32,
    write_json_output,
)

INPUT_DEFAULT = REPO_ROOT / "g1_data" / "mhfdat.raw.bin"
OUTPUT_DEFAULT = REPO_ROOT / "site" / "src" / "data" / "generated" / "_items-source.json"

ITEMS_HEADER_POINTER_ADDRESS = 0x00000100
ITEM_NAMES_HEADER_POINTER_ADDRESS = 0x00000104
ITEM_DESCRIPTIONS_HEADER_POINTER_ADDRESS = 0x00000130
ITEM_DESCRIPTIONS_POINTER_TABLE_OFFSET = 0x60

ITEM_COUNT_POINTER_ADDRESS = 0x00000010
ITEM_COUNT_OFFSET_FROM_POINTER = 0x0C

ITEM_STRUCT_FMT = "<BBBBBBBBHHIIHHHBBHBB"
ITEM_STRUCT_SIZE = struct.calcsize(ITEM_STRUCT_FMT)

_COLOR_TAG_RE = re.compile(r"~C([0-9A-Fa-f]{2})")


def parse_description_segments(description_raw: str) -> tuple[str, list[dict[str, str | None]]]:
    """
    Parse ~CXX color tags the same way as site/scripts/build-data.mjs (parseDescriptionSegments).
    """
    segments: list[dict[str, str | None]] = []
    current_color: str | None = None
    cursor = 0
    for match in _COLOR_TAG_RE.finditer(description_raw):
        if match.start() > cursor:
            segments.append(
                {"text": description_raw[cursor : match.start()], "colorCode": current_color}
            )
        next_code = match.group(1).upper()
        current_color = None if next_code == "00" else next_code
        cursor = match.end()

    if cursor < len(description_raw):
        segments.append({"text": description_raw[cursor:], "colorCode": current_color})

    merged: list[dict[str, str | None]] = []
    for segment in segments:
        if not segment["text"]:
            continue
        previous = merged[-1] if merged else None
        if previous is not None and previous["colorCode"] == segment["colorCode"]:
            previous["text"] += segment["text"]
            continue
        merged.append({"text": segment["text"], "colorCode": segment["colorCode"]})

    description_plain = "".join(s["text"] for s in merged)
    return description_plain, merged


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


def extract_items(
    raw: bytes,
) -> tuple[list[dict[str, int | str | list | None]], int, int, int, int]:
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

    rows: list[dict[str, int | str | list | None]] = []
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

        description = decode_c_string(raw, desc_pointers[item_index])
        description_stripped = description.strip()
        description_plain, description_segments = parse_description_segments(description_stripped)

        rows.append(
            {
                "item_index": item_index,
                "name": decode_c_string(raw, name_pointers[item_index]),
                "description": description,
                "descriptionPlain": description_plain,
                "descriptionSegments": description_segments,
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
    rows, _, _, _, _ = extract_items(raw)

    hidden_ids = {
        int(r["item_index"])
        for r in rows
        if is_dummy_placeholder_description(str(r.get("descriptionPlain", "")))
    }
    kept = [r for r in rows if int(r["item_index"]) not in hidden_ids]

    hidden_path = args.output.parent / WIKI_HIDDEN_ITEM_IDS_FILENAME
    write_json_output(hidden_path, {"itemIds": sorted(hidden_ids)})
    write_json_output(args.output, kept)

    print(
        f"Extracted {len(kept)} items into wiki source ({len(hidden_ids)} dummy-description rows hidden)"
    )

if __name__ == "__main__":
    main()
