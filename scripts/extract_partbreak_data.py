#!/usr/bin/env python3
import argparse
import struct
from pathlib import Path

from extract_common import (
    REPO_ROOT,
    default_wiki_hidden_item_ids_path,
    load_item_names,
    load_monster_names,
    load_optional_json_object,
    load_wiki_hidden_item_ids,
    read_u16,
    read_u32,
    write_json_output,
)

INPUT_DEFAULT = REPO_ROOT / "g1_data" / "mhfdat.raw.bin"
OUTPUT_DEFAULT = (
    REPO_ROOT / "site" / "src" / "data" / "generated" / "_partbreak-source.json"
)
ITEMS_SOURCE_DEFAULT = (
    REPO_ROOT / "site" / "src" / "data" / "generated" / "_items-source.json"
)
MONSTER_NAMES_JSON_DEFAULT = REPO_ROOT / "g1_data" / "monster_names.json"
MONSTER_PARTBREAK_LABELS_DEFAULT = (
    REPO_ROOT / "g1_data" / "monster_partbreak_labels.json"
)

DROP_TABLE_POINTER_HEADER_ADDRESS = 0x00000128
MAPPING_POINTER_HEADER_ADDRESS = 0x0000012C

MAPPING_FMT = "<BBHHHH6sH8s"
MAPPING_SIZE = struct.calcsize(MAPPING_FMT)
DROP_FMT = "<HHH"
DROP_SIZE = struct.calcsize(DROP_FMT)

MAPPING_TERMINATOR = b"\xff\xff"
DROP_TERMINATOR = 0xFFFF

RANK_COLUMNS = [
    ("lr", "lowRankPDTIndex"),
    ("hr", "highRankPDTIndex"),
    ("arena", "arenaPDTIndex"),
    ("hr100", "hr100PDTIndex"),
    ("gr", "grankPDTIndex"),
]


def should_skip_rank_entry(
    rank: str,
    pdt_index: int,
) -> bool:
    # grank index 0x0000 is usually a "no entry" sentinel, not first drop table
    return rank == "gr" and pdt_index == 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract partbreak/capture drop data from mhfdat.raw.bin into JSON."
    )
    parser.add_argument(
        "--input", type=Path, default=INPUT_DEFAULT, help="Path to mhfdat.raw.bin"
    )
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
        "--wiki-hidden-item-ids",
        type=Path,
        default=None,
        help="JSON with itemIds to omit from drops (default: sibling of --items-source).",
    )
    parser.add_argument(
        "--monster-names-json",
        type=Path,
        default=MONSTER_NAMES_JSON_DEFAULT,
        help="Optional JSON object mapping monster_id keys to display names.",
    )
    parser.add_argument(
        "--monster-partbreak-labels",
        type=Path,
        default=MONSTER_PARTBREAK_LABELS_DEFAULT,
        help="Optional monster_id -> partbreak_type_raw -> display label; __ignore__ drops part_break rows.",
    )
    return parser.parse_args()


def parse_drop_table_pointer_array(raw: bytes, pointer_array_base: int) -> list[int]:
    pointers: list[int] = []
    for index in range(0x1000):
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


def parse_single_drop_table(
    raw: bytes, table_pointer: int, table_index: int
) -> list[dict[str, int]]:
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


def parse_all_drop_tables(
    raw: bytes, pointer_array_base: int
) -> tuple[list[int], dict[int, list[dict[str, int]]]]:
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
            raise ValueError(
                f"Partbreak mapping record at 0x{offset:08X} exceeds file bounds"
            )

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
    wiki_hidden_item_ids: frozenset[int],
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
                if item_id in wiki_hidden_item_ids:
                    continue
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


def resolve_partbreak_label(
    labels: dict[str, object], monster_id: int, partbreak_type_raw: str
) -> str | None:
    entry = labels.get(str(monster_id))
    if not isinstance(entry, dict):
        return None
    val = entry.get(partbreak_type_raw)
    if not isinstance(val, str):
        return None
    trimmed = val.strip()
    return None if trimmed == "" else trimmed


def apply_partbreak_display_labels(
    rows: list[dict[str, int | str]],
    labels: dict[str, object],
) -> list[dict[str, int | str]]:
    """Set partbreak_type (wiki display); drop part_break rows labeled __ignore__."""
    out: list[dict[str, int | str]] = []
    ignored = 0
    for row in rows:
        raw_type = str(row.get("partbreak_type_raw", "")).strip()
        manual = resolve_partbreak_label(labels, int(row["monster_id"]), raw_type)
        drop_mode = str(row.get("drop_mode", "")).strip().lower()

        if drop_mode == "part_break" and manual == "__ignore__":
            ignored += 1
            continue

        if drop_mode == "part_break":
            partbreak_type: str = (
                (manual if manual and manual != "__ignore__" else None)
                or raw_type
                or "unknown"
            )
        elif raw_type:
            partbreak_type = (
                manual if manual and manual != "__ignore__" else None
            ) or raw_type
        else:
            partbreak_type = (
                manual if manual and manual != "__ignore__" else None
            ) or ""

        new_row = dict(row)
        new_row["partbreak_type"] = partbreak_type
        out.append(new_row)

    if ignored > 0:
        print(f"Dropped {ignored} partbreak rows marked __ignore__ in labels")

    return out


def main() -> None:
    args = parse_args()
    raw = args.input.read_bytes()

    drop_table_pointer_array_base = read_u32(
        raw, DROP_TABLE_POINTER_HEADER_ADDRESS, "drop_table_pointer_header"
    )
    mapping_base = read_u32(
        raw, MAPPING_POINTER_HEADER_ADDRESS, "mapping_pointer_header"
    )
    if drop_table_pointer_array_base >= len(raw):
        raise ValueError(
            f"Drop table pointer array base 0x{drop_table_pointer_array_base:08X} outside file bounds"
        )
    if mapping_base >= len(raw):
        raise ValueError(f"Mapping base 0x{mapping_base:08X} outside file bounds")

    drop_table_pointers, drop_tables = parse_all_drop_tables(
        raw, drop_table_pointer_array_base
    )
    mappings = parse_partbreak_mappings(raw, mapping_base)

    item_names_by_id = load_item_names(args.items_source)
    monster_names_by_id = load_monster_names(args.monster_names_json)
    partbreak_labels = load_optional_json_object(args.monster_partbreak_labels)
    hidden_path = args.wiki_hidden_item_ids or default_wiki_hidden_item_ids_path(
        args.items_source
    )
    wiki_hidden_item_ids = load_wiki_hidden_item_ids(hidden_path)

    rows = flatten_rows(
        mappings=mappings,
        drop_table_pointers=drop_table_pointers,
        drop_tables=drop_tables,
        item_names_by_id=item_names_by_id,
        monster_names_by_id=monster_names_by_id,
        wiki_hidden_item_ids=wiki_hidden_item_ids,
    )
    rows = apply_partbreak_display_labels(rows, partbreak_labels)

    write_json_output(args.output, rows)

    print(
        f"Decoded {len(drop_table_pointers)} PDT pointers and {len(mappings)} mappings"
    )
    print(f"Wrote {len(rows)} flattened partbreak rows")


if __name__ == "__main__":
    main()
