#!/usr/bin/env python3
import argparse
import struct
from pathlib import Path

from extract_common import (
    REPO_ROOT,
    load_item_names,
    load_monster_names,
    read_u16,
    read_u32,
    write_json_output,
)

INPUT_DEFAULT = REPO_ROOT / "g1_data" / "mhfdat.raw.bin"
OUTPUT_DEFAULT = REPO_ROOT / "site" / "src" / "data" / "generated" / "_partbreak-source.json"
ITEMS_SOURCE_DEFAULT = REPO_ROOT / "site" / "src" / "data" / "generated" / "_items-source.json"
MONSTER_NAMES_JSON_DEFAULT = REPO_ROOT / "g1_data" / "monster_names.json"

DROP_TABLE_POINTER_HEADER_ADDRESS = 0x00000128
MAPPING_POINTER_HEADER_ADDRESS = 0x0000012C

MAPPING_FMT = "<BBHHHH6sH8s"
MAPPING_SIZE = struct.calcsize(MAPPING_FMT)
DROP_FMT = "<HHH"
DROP_SIZE = struct.calcsize(DROP_FMT)

MAPPING_TERMINATOR = b"\xFF\xFF"
DROP_TERMINATOR = 0xFFFF

RANK_COLUMNS = [
    ("lr", "lowRankPDTIndex"),
    ("hr", "highRankPDTIndex"),
    ("arena", "arenaPDTIndex"),
    ("hr100", "hr100PDTIndex"),
    ("gr", "grankPDTIndex"),
]

# Quarzeps (id 105): grank monsters' LR/HR/HR100 slots sometimes reuse its PDT indices as fallbacks;
# drop those rows so only Quarzeps keeps that data
QUARZEPS_MONSTER_ID = 105
QUARZEPS_FALLBACK_RANKS = frozenset({"lr", "hr", "hr100"})


def should_skip_rank_entry(rank: str, pdt_index: int, monster_id: int, mapping_index: int) -> bool:
    # Reverse-engineering note: grank index 0x0000 is usually a "no entry" sentinel.
    # Keep a narrow exception for the first Rathian mapping if it ever uses index 0x0000.
    if rank == "gr" and pdt_index == 0:
        if monster_id == 1 and mapping_index == 0:
            return False
        return True
    return False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract partbreak/capture drop data from mhfdat.raw.bin into JSON."
    )
    parser.add_argument("--input", type=Path, default=INPUT_DEFAULT, help="Path to mhfdat.raw.bin")
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_DEFAULT,
        help="Output JSON path consumed by site/scripts/build-data.mjs",
    )
    parser.add_argument(
        "--items-source",
        type=Path,
        default=ITEMS_SOURCE_DEFAULT,
        help="Path to generated _items-source.json (for item names).",
    )
    parser.add_argument(
        "--monster-names-json",
        type=Path,
        default=MONSTER_NAMES_JSON_DEFAULT,
        help="Optional JSON object mapping monster_id keys to display names.",
    )
    return parser.parse_args()


def parse_drop_table_pointer_array(raw: bytes, pointer_array_base: int) -> list[int]:
    pointers: list[int] = []
    for index in range(0x10000):
        table_offset = pointer_array_base + index * 4
        if table_offset + 4 > len(raw):
            raise ValueError(
                f"Drop pointer table reached file end while reading index {index} at 0x{table_offset:08X}"
            )

        pointer = read_u32(raw, table_offset, f"drop_pointer[{index}]")
        if pointer >= len(raw):
            # First out-of-bounds pointer marks the logical end of this pointer array.
            break
        pointers.append(pointer)
    if not pointers:
        raise ValueError("No valid drop table pointers were decoded")
    return pointers


def parse_single_drop_table(raw: bytes, table_pointer: int, table_index: int) -> list[dict[str, int]]:
    drops: list[dict[str, int]] = []
    offset = table_pointer
    drop_index = 0
    while True:
        percentage = read_u16(raw, offset, f"drop_table[{table_index}] percentage")
        if percentage == DROP_TERMINATOR:
            break
        if offset + DROP_SIZE > len(raw):
            raise ValueError(
                f"Drop table {table_index} record at 0x{offset:08X} exceeds file bounds"
            )
        percentage, item_id, number = struct.unpack_from(DROP_FMT, raw, offset)
        drops.append(
            {
                "drop_index_in_table": drop_index,
                "entry_offset": offset,
                "percentage": percentage,
                "item_id": item_id,
                "quantity": number,
            }
        )
        offset += DROP_SIZE
        drop_index += 1
    return drops


def parse_all_drop_tables(raw: bytes, pointer_array_base: int) -> tuple[list[int], dict[int, list[dict[str, int]]]]:
    pointers = parse_drop_table_pointer_array(raw, pointer_array_base)
    tables: dict[int, list[dict[str, int]]] = {}
    for index, pointer in enumerate(pointers):
        tables[index] = parse_single_drop_table(raw, pointer, index)
    return pointers, tables


def parse_partbreak_mappings(raw: bytes, mapping_base: int) -> list[dict[str, int]]:
    mappings: list[dict[str, int]] = []
    offset = mapping_base
    mapping_index = 0
    while True:
        if offset + 2 > len(raw):
            raise ValueError(
                f"Partbreak mapping terminator check out of bounds at 0x{offset:08X}"
            )
        if raw[offset : offset + 2] == MAPPING_TERMINATOR:
            break
        if offset + MAPPING_SIZE > len(raw):
            raise ValueError(f"Partbreak mapping record at 0x{offset:08X} exceeds file bounds")

        (
            mon_id,
            part_break_type,
            low_rank_pdt_index,
            high_rank_pdt_index,
            arena_pdt_index,
            hr100_pdt_index,
            _padding0,
            grank_pdt_index,
            _padding1,
        ) = struct.unpack_from(MAPPING_FMT, raw, offset)

        mappings.append(
            {
                "mapping_index": mapping_index,
                "mapping_offset": offset,
                "monster_id": mon_id,
                "partbreak_type": part_break_type,
                "lowRankPDTIndex": low_rank_pdt_index,
                "highRankPDTIndex": high_rank_pdt_index,
                "arenaPDTIndex": arena_pdt_index,
                "hr100PDTIndex": hr100_pdt_index,
                "grankPDTIndex": grank_pdt_index,
            }
        )
        mapping_index += 1
        offset += MAPPING_SIZE

    return mappings


def flatten_rows(
    mappings: list[dict[str, int]],
    drop_table_pointers: list[int],
    drop_tables: dict[int, list[dict[str, int]]],
    item_names_by_id: dict[int, str],
    monster_names_by_id: dict[int, str],
) -> list[dict[str, int | str]]:
    rows: list[dict[str, int | str]] = []
    for mapping in mappings:
        monster_id = int(mapping["monster_id"])
        monster_name = monster_names_by_id.get(monster_id, f"Monster {monster_id}")
        partbreak_type = int(mapping["partbreak_type"])
        partbreak_type_raw = f"0x{partbreak_type:02X}"
        drop_mode = "capture" if partbreak_type == 0x80 else "part_break"

        for rank, key in RANK_COLUMNS:
            pdt_index = int(mapping[key])
            if should_skip_rank_entry(
                rank=rank,
                pdt_index=pdt_index,
                monster_id=monster_id,
                mapping_index=int(mapping["mapping_index"]),
            ):
                continue
            if pdt_index < 0 or pdt_index >= len(drop_table_pointers):
                raise ValueError(
                    f"Mapping {mapping['mapping_index']} rank {rank} references invalid PDT index {pdt_index}"
                )
            pdt_pointer = drop_table_pointers[pdt_index]
            drops = drop_tables[pdt_index]
            for drop in drops:
                item_id = int(drop["item_id"])
                rows.append(
                    {
                        "mapping_index": mapping["mapping_index"],
                        "monster_id": monster_id,
                        "monster_name": monster_name,
                        "partbreak_type_raw": partbreak_type_raw,
                        "drop_mode": drop_mode,
                        "rank": rank,
                        "pdt_index": pdt_index,
                        "pdt_pointer": f"0x{pdt_pointer:08X}",
                        "drop_index_in_table": drop["drop_index_in_table"],
                        "entry_offset": f"0x{int(drop['entry_offset']):08X}",
                        "percentage": drop["percentage"],
                        "quantity": drop["quantity"],
                        "item_id": item_id,
                        "item_name": item_names_by_id.get(item_id, f"Item {item_id}"),
                    }
                )
    return rows


def filter_quarzeps_fallback_partbreak_rows(
    rows: list[dict[str, int | str]],
) -> list[dict[str, int | str]]:
    """Remove non-Quarzeps LR/HR/HR100 rows whose PDT index matches a Quarzeps row for that rank."""
    quarzeps_pdt_by_rank: dict[str, set[int]] = {}
    for row in rows:
        monster_id = int(row["monster_id"])
        if monster_id != QUARZEPS_MONSTER_ID:
            continue
        rank = str(row.get("rank", "")).strip().lower()
        if rank not in QUARZEPS_FALLBACK_RANKS:
            continue
        pdt_index = int(row["pdt_index"])
        quarzeps_pdt_by_rank.setdefault(rank, set()).add(pdt_index)

    if not quarzeps_pdt_by_rank:
        return rows

    kept: list[dict[str, int | str]] = []
    removed = 0
    for row in rows:
        monster_id = int(row["monster_id"])
        if monster_id == QUARZEPS_MONSTER_ID:
            kept.append(row)
            continue
        rank = str(row.get("rank", "")).strip().lower()
        if rank not in QUARZEPS_FALLBACK_RANKS:
            kept.append(row)
            continue
        indices = quarzeps_pdt_by_rank.get(rank)
        if not indices:
            kept.append(row)
            continue
        pdt_index = int(row["pdt_index"])
        if pdt_index in indices:
            removed += 1
            continue
        kept.append(row)

    if removed > 0:
        print(f"Filtered {removed} Quarzeps fallback partbreak rows")

    return kept


def main() -> None:
    args = parse_args()
    raw = args.input.read_bytes()

    drop_table_pointer_array_base = read_u32(
        raw, DROP_TABLE_POINTER_HEADER_ADDRESS, "drop_table_pointer_header"
    )
    mapping_base = read_u32(raw, MAPPING_POINTER_HEADER_ADDRESS, "mapping_pointer_header")
    if drop_table_pointer_array_base >= len(raw):
        raise ValueError(
            f"Drop table pointer array base 0x{drop_table_pointer_array_base:08X} outside file bounds"
        )
    if mapping_base >= len(raw):
        raise ValueError(f"Mapping base 0x{mapping_base:08X} outside file bounds")

    drop_table_pointers, drop_tables = parse_all_drop_tables(raw, drop_table_pointer_array_base)
    mappings = parse_partbreak_mappings(raw, mapping_base)

    item_names_by_id = load_item_names(args.items_source)
    monster_names_by_id = load_monster_names(args.monster_names_json)

    rows = flatten_rows(
        mappings=mappings,
        drop_table_pointers=drop_table_pointers,
        drop_tables=drop_tables,
        item_names_by_id=item_names_by_id,
        monster_names_by_id=monster_names_by_id,
    )
    rows = filter_quarzeps_fallback_partbreak_rows(rows)

    write_json_output(args.output, rows)

    print(f"Decoded {len(drop_table_pointers)} PDT pointers and {len(mappings)} mappings")
    print(f"Wrote {len(rows)} flattened partbreak rows")


if __name__ == "__main__":
    main()
