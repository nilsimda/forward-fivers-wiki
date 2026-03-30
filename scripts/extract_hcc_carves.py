#!/usr/bin/env python3
import argparse
import struct
from pathlib import Path

from extract_common import (
    REPO_ROOT,
    default_wiki_hidden_item_ids_path,
    load_item_names,
    load_monster_names,
    load_wiki_hidden_item_ids,
    read_u32,
    write_json_output,
)

POINTER_ADDRESS = 0x0000034C
RECORD_FMT = "<HHHHH"
RECORD_SIZE = struct.calcsize(RECORD_FMT)
TERMINATOR = b"\xff\xff"
FIELDS = ["monster_id", "lr_item_id", "hr_item_id", "hr100_item_id", "gr_item_id"]
ITEM_ID_COLUMNS = ["lr_item_id", "hr_item_id", "hr100_item_id", "gr_item_id"]
ITEMS_JSON_DEFAULT = REPO_ROOT / "site" / "src" / "data" / "generated" / "items.json"
MONSTER_NAMES_JSON_DEFAULT = REPO_ROOT / "g1_data" / "monster_names.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract HCC carve table from mhfdat.raw.bin into JSON."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=REPO_ROOT / "g1_data" / "mhfdat.raw.bin",
        help="Path to mhfdat.raw.bin (default: g1_data/mhfdat.raw.bin).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT
        / "site"
        / "src"
        / "data"
        / "generated"
        / "_hcc-carves-source.json",
        help="Output hardcore carve acquisition-method rows consumed by site/scripts/build-data.mjs.",
    )
    parser.add_argument(
        "--wiki-hidden-item-ids",
        type=Path,
        default=None,
        help="JSON with itemIds to strip from HCC slots (default: sibling of --items-json).",
    )
    parser.add_argument(
        "--items-json",
        type=Path,
        default=ITEMS_JSON_DEFAULT,
        help="Path to generated items.json (for item names).",
    )
    parser.add_argument(
        "--monster-names-json",
        type=Path,
        default=MONSTER_NAMES_JSON_DEFAULT,
        help="JSON object mapping monster ids to display names.",
    )
    return parser.parse_args()


def read_hcc_blob(binary_path: Path) -> bytes:
    raw = binary_path.read_bytes()

    data_address = read_u32(raw, POINTER_ADDRESS, "hcc_table_pointer")
    if data_address >= len(raw):
        raise ValueError(
            f"Pointer target 0x{data_address:08X} outside file bounds ({len(raw)} bytes)"
        )

    end = raw.find(TERMINATOR, data_address)
    if end == -1:
        raise ValueError("Did not find HCC terminator (0xFFFF) in source file")

    return raw[data_address:end]


def decode_records(blob: bytes) -> list[dict[str, int]]:
    if len(blob) % RECORD_SIZE != 0:
        # Keep strict behavior so schema changes fail loudly instead of silently truncating.
        raise ValueError(
            f"HCC blob size {len(blob)} is not divisible by record size {RECORD_SIZE}"
        )

    records: list[dict[str, int]] = []
    for offset in range(0, len(blob), RECORD_SIZE):
        unpacked = struct.unpack_from(RECORD_FMT, blob, offset)
        record = dict(zip(FIELDS, unpacked))
        records.append(record)
    return records


def scrub_wiki_hidden_item_slots(
    records: list[dict[str, int]], hidden: frozenset[int]
) -> list[dict[str, int | None]]:
    out: list[dict[str, int | None]] = []
    for rec in records:
        row: dict[str, int | None] = {"monster_id": int(rec["monster_id"])}
        for col in ITEM_ID_COLUMNS:
            vid = int(rec[col])
            row[col] = None if vid in hidden else vid
        out.append(row)
    return out


def to_acquisition_methods(
    records: list[dict[str, int | None]],
    item_names_by_id: dict[int, str],
    monster_names_by_id: dict[int, str],
) -> list[dict[str, int | str]]:
    methods: list[dict[str, int | str]] = []
    rank_columns = [
        ("lr", "lr_item_id"),
        ("hr", "hr_item_id"),
        ("hr100", "hr100_item_id"),
    ]
    for record in records:
        monster_id_raw = record["monster_id"]
        if monster_id_raw is None:
            raise ValueError("HCC record missing monster_id")
        monster_id = int(monster_id_raw)
        monster_name = monster_names_by_id.get(monster_id, f"Monster {monster_id}")
        for rank, item_col in rank_columns:
            raw_item_id = record[item_col]
            if raw_item_id is None:
                continue
            item_id = int(raw_item_id)
            methods.append(
                {
                    "methodType": "hardcore_carve",
                    "rank": rank,
                    "sourceLabel": monster_name,
                    "chance": 2,
                    "quantity": 1,
                    "monsterId": monster_id,
                    "monsterName": monster_name,
                    "itemId": item_id,
                    "itemName": item_names_by_id.get(item_id, f"Item {item_id}"),
                }
            )
    return methods


def main() -> None:
    args = parse_args()
    blob = read_hcc_blob(args.input)
    records = decode_records(blob)
    item_names_by_id = load_item_names(args.items_json)
    monster_names_by_id = load_monster_names(args.monster_names_json)
    hidden_path = args.wiki_hidden_item_ids or default_wiki_hidden_item_ids_path(
        args.items_json
    )
    hidden = load_wiki_hidden_item_ids(hidden_path)
    scrubbed_records = scrub_wiki_hidden_item_slots(records, hidden)
    methods = to_acquisition_methods(
        scrubbed_records,
        item_names_by_id=item_names_by_id,
        monster_names_by_id=monster_names_by_id,
    )

    write_json_output(args.output, methods)

    print(f"Decoded {len(methods)} hardcore carve methods")


if __name__ == "__main__":
    main()
