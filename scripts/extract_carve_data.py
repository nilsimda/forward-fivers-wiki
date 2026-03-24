#!/usr/bin/env python3
import argparse
import struct
from pathlib import Path

from extract_common import (
    REPO_ROOT,
    load_item_names,
    load_monster_names,
    load_optional_json_object,
    read_u16,
    read_u32,
    write_json_output,
)

INPUT_DEFAULT = REPO_ROOT / "g1_data" / "mhfdat.raw.bin"
OUTPUT_DEFAULT = REPO_ROOT / "site" / "src" / "data" / "generated" / "_carves-source.json"
ITEMS_SOURCE_DEFAULT = REPO_ROOT / "site" / "src" / "data" / "generated" / "_items-source.json"
MONSTER_NAMES_JSON_DEFAULT = REPO_ROOT / "g1_data" / "monster_names.json"
MONSTER_CARVE_LABELS_DEFAULT = REPO_ROOT / "g1_data" / "monster_carve_labels.json"

IMPORTANT_NUMS_POINTER_HEADER_ADDRESS = 0x00000010
CARVE_DT_POINTER_HEADER_ADDRESS = 0x00000124
CARVE_ASSOC_POINTER_HEADER_ADDRESS = 0x0000013C
CARVE_DT_COUNT_OFFSET_IN_IMPORTANT_NUMS = 0x22

CARVE_DROP_FMT = "<HH"
CARVE_DROP_SIZE = struct.calcsize(CARVE_DROP_FMT)
CARVE_DROP_TERMINATOR = 0xFFFF

ASSOC_ENTRY_FMT = "<III"
ASSOC_ENTRY_SIZE = struct.calcsize(ASSOC_ENTRY_FMT)

PRIMARY_RECORD_STRIDE = 0x28
SECONDARY_RECORD_STRIDE = 0x1A
PRIMARY_NUM_CARVES_OFFSET = 0x18
PRIMARY_RECORD_SCAN_HARD_CAP = 0x100

RANK_LABELS = ["lr", "hr", "arena", "hr100", "gr"]
GRANK_DT_INDEX_OFFSET = 0x0E

# Carve DT 801 is a *shared* table (generic supplies: potions, bone, stone). In the data it is
# wired to the **arena** rank slot for monsters 107–117 (Vorsphyroa … Pokara). The same DT is
# also referenced from LR/HR/HR100 for those IDs (bogus fallbacks) and from all four of those
# ranks for Shantien (116). It is not “Shantien’s” table—just one global pool reused for arena
# (and incorrectly for other ranks). We keep one monster’s copy for wiki dedupe: anchor 116
# (same pattern as Quarzeps partbreak).
FRONTIER_SHARED_CARVE_DEDUPE_ANCHOR_MONSTER_ID = 116
FRONTIER_SHARED_CARVE_DEDUPE_RANKS = frozenset({"lr", "hr", "hr100"})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract regular carve table data from mhfdat.raw.bin into flat JSON."
    )
    parser.add_argument("--input", type=Path, default=INPUT_DEFAULT, help="Path to mhfdat.raw.bin")
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_DEFAULT,
        help="Output JSON path consumed by downstream scripts/docs.",
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
        help="JSON object mapping monster ids to display names.",
    )
    parser.add_argument(
        "--monster-carve-labels",
        type=Path,
        default=MONSTER_CARVE_LABELS_DEFAULT,
        help="Optional carve labels (primary/secondary record_index -> label); __ignore__ drops rows.",
    )
    return parser.parse_args()


def parse_carve_dt_pointer_array(raw: bytes, pointer_array_base: int, pointer_count: int) -> list[int]:
    if pointer_count <= 0:
        raise ValueError(f"Invalid carve DT pointer_count={pointer_count}")
    pointers: list[int] = []
    for index in range(pointer_count):
        pointer_offset = pointer_array_base + index * 4
        if pointer_offset + 4 > len(raw):
            raise ValueError(
                f"Carve DT pointer table reached file end while reading index {index} at 0x{pointer_offset:08X}"
            )
        pointer = read_u32(raw, pointer_offset, f"carve_dt_pointer[{index}]")
        if pointer >= len(raw):
            raise ValueError(
                f"Carve DT pointer index {index} -> 0x{pointer:08X} is outside file bounds"
            )
        pointers.append(pointer)
    if not pointers:
        raise ValueError("No valid carve DT pointers were decoded")
    return pointers


def parse_single_carve_table(raw: bytes, table_pointer: int, table_index: int) -> list[dict[str, int]]:
    drops: list[dict[str, int]] = []
    offset = table_pointer
    drop_index = 0
    while True:
        percentage = read_u16(raw, offset, f"carve_dt[{table_index}] percentage")
        if percentage == CARVE_DROP_TERMINATOR:
            break
        if offset + CARVE_DROP_SIZE > len(raw):
            raise ValueError(f"Carve DT {table_index} record at 0x{offset:08X} exceeds file bounds")
        percentage, item_id = struct.unpack_from(CARVE_DROP_FMT, raw, offset)
        drops.append(
            {
                "drop_index_in_table": drop_index,
                "entry_offset": offset,
                "percentage": percentage,
                "item_id": item_id,
            }
        )
        offset += CARVE_DROP_SIZE
        drop_index += 1
    return drops


def parse_all_carve_tables(
    raw: bytes, pointer_array_base: int, pointer_count: int
) -> tuple[list[int], dict[int, list[dict[str, int]]]]:
    pointers = parse_carve_dt_pointer_array(raw, pointer_array_base, pointer_count)
    tables: dict[int, list[dict[str, int]]] = {}
    for index, pointer in enumerate(pointers):
        tables[index] = parse_single_carve_table(raw, pointer, index)
    return pointers, tables


def read_assoc_entry(raw: bytes, assoc_base: int, monster_id: int) -> dict[str, int]:
    entry_offset = assoc_base + monster_id * ASSOC_ENTRY_SIZE
    if entry_offset < 0 or entry_offset + ASSOC_ENTRY_SIZE > len(raw):
        raise ValueError(
            f"Carve assoc entry for monster_id={monster_id} is out of bounds at 0x{entry_offset:08X}"
        )
    primary_ptr, secondary_ptr, secondary_count = struct.unpack_from(ASSOC_ENTRY_FMT, raw, entry_offset)
    return {
        "association_entry_offset": entry_offset,
        "primary_ptr": primary_ptr,
        "secondary_ptr": secondary_ptr,
        "secondary_count": secondary_count,
    }


def is_zero_rank_group(indices: list[int]) -> bool:
    return all(index == 0 for index in indices)


def parse_record_rank_indices(raw: bytes, record_offset: int, label: str) -> list[int]:
    base_rank_indices = [
        read_u16(raw, record_offset + rank_slot * 2, f"{label} rank_slot {rank_slot}")
        for rank_slot in range(4)
    ]
    grank_index = read_u16(raw, record_offset + GRANK_DT_INDEX_OFFSET, f"{label} gr_rank_slot")
    return [*base_rank_indices, grank_index]


def get_primary_record_scan_limit(primary_ptr: int, secondary_ptr: int) -> int:
    """
    Use contiguous primary->secondary distance when it is cleanly aligned;
    otherwise keep a conservative hard cap and rely on zero-rank sentinel stop.
    """
    if secondary_ptr > primary_ptr:
        distance = secondary_ptr - primary_ptr
        if distance % PRIMARY_RECORD_STRIDE == 0:
            return distance // PRIMARY_RECORD_STRIDE
    return PRIMARY_RECORD_SCAN_HARD_CAP


def should_skip_dt_index(monster_id: int, dt_index: int) -> bool:
    """
    DT index 0 is Rathian's LR body carve table.
    In many non-Rathian rank slots the game stores 0 as a fallback/null-like value,
    which otherwise leaks Rathian carve rows into unrelated monsters.
    """
    return dt_index == 0 and monster_id != 1


def flatten_rows(
    *,
    raw: bytes,
    monster_names_by_id: dict[int, str],
    item_names_by_id: dict[int, str],
    assoc_base: int,
    carve_dt_pointers: list[int],
    carve_tables: dict[int, list[dict[str, int]]],
) -> list[dict[str, int | str | None]]:
    rows: list[dict[str, int | str | None]] = []

    for monster_id in sorted(monster_names_by_id.keys()):
        monster_name = monster_names_by_id[monster_id]
        assoc = read_assoc_entry(raw, assoc_base, monster_id)

        primary_ptr = int(assoc["primary_ptr"])
        secondary_ptr = int(assoc["secondary_ptr"])
        secondary_count = int(assoc["secondary_count"])

        # Ignore all-zero/sentinel assoc entries.
        if primary_ptr == 0 and secondary_ptr == 0 and secondary_count == 0:
            continue

        if primary_ptr != 0:
            if primary_ptr >= len(raw):
                raise ValueError(
                    f"monster_id={monster_id}: primary_ptr 0x{primary_ptr:08X} outside file bounds"
                )
            primary_scan_limit = get_primary_record_scan_limit(primary_ptr, secondary_ptr)
            for record_index in range(primary_scan_limit):
                record_offset = primary_ptr + record_index * PRIMARY_RECORD_STRIDE
                if record_offset + PRIMARY_RECORD_STRIDE > len(raw):
                    raise ValueError(
                        f"monster_id={monster_id} primary record {record_index} at 0x{record_offset:08X} exceeds bounds"
                    )

                rank_indices = parse_record_rank_indices(
                    raw, record_offset, f"monster_id={monster_id} primary record={record_index}"
                )
                if is_zero_rank_group(rank_indices):
                    break

                primary_num_carves = read_u16(
                    raw,
                    record_offset + PRIMARY_NUM_CARVES_OFFSET,
                    f"monster_id={monster_id} primary record={record_index} num_carves",
                )

                for rank_slot, dt_index in enumerate(rank_indices):
                    if should_skip_dt_index(monster_id, dt_index):
                        continue
                    if dt_index < 0 or dt_index >= len(carve_dt_pointers):
                        raise ValueError(
                            f"monster_id={monster_id} primary record={record_index} rank_slot={rank_slot} invalid dt_index={dt_index}"
                        )
                    dt_pointer = carve_dt_pointers[dt_index]
                    drops = carve_tables[dt_index]
                    for drop in drops:
                        item_id = int(drop["item_id"])
                        rows.append(
                            {
                                "monster_id": monster_id,
                                "monster_name": monster_name,
                                "path": "primary",
                                "record_index": record_index,
                                "rank_slot": rank_slot,
                                "rank_label": RANK_LABELS[rank_slot],
                                "dt_index": dt_index,
                                "dt_pointer": f"0x{dt_pointer:08X}",
                                "record_offset": f"0x{record_offset:08X}",
                                "entry_offset": f"0x{int(drop['entry_offset']):08X}",
                                "drop_index_in_table": drop["drop_index_in_table"],
                                "percentage": drop["percentage"],
                                "item_id": item_id,
                                "item_name": item_names_by_id.get(item_id, f"Item {item_id}"),
                                "association_entry_offset": f"0x{int(assoc['association_entry_offset']):08X}",
                                "primary_ptr": f"0x{primary_ptr:08X}",
                                "secondary_ptr": f"0x{secondary_ptr:08X}",
                                "secondary_count": secondary_count,
                                "primary_num_carves": primary_num_carves,
                            }
                        )

        if secondary_ptr != 0 and secondary_count != 0:
            if secondary_ptr >= len(raw):
                raise ValueError(
                    f"monster_id={monster_id}: secondary_ptr 0x{secondary_ptr:08X} outside file bounds"
                )
            for record_index in range(secondary_count):
                record_offset = secondary_ptr + record_index * SECONDARY_RECORD_STRIDE
                if record_offset + SECONDARY_RECORD_STRIDE > len(raw):
                    raise ValueError(
                        f"monster_id={monster_id} secondary record {record_index} at 0x{record_offset:08X} exceeds bounds"
                    )

                rank_indices = parse_record_rank_indices(
                    raw, record_offset, f"monster_id={monster_id} secondary record={record_index}"
                )
                if is_zero_rank_group(rank_indices):
                    continue

                for rank_slot, dt_index in enumerate(rank_indices):
                    if should_skip_dt_index(monster_id, dt_index):
                        continue
                    if dt_index < 0 or dt_index >= len(carve_dt_pointers):
                        raise ValueError(
                            f"monster_id={monster_id} secondary record={record_index} rank_slot={rank_slot} invalid dt_index={dt_index}"
                        )
                    dt_pointer = carve_dt_pointers[dt_index]
                    drops = carve_tables[dt_index]
                    for drop in drops:
                        item_id = int(drop["item_id"])
                        rows.append(
                            {
                                "monster_id": monster_id,
                                "monster_name": monster_name,
                                "path": "secondary",
                                "record_index": record_index,
                                "rank_slot": rank_slot,
                                "rank_label": RANK_LABELS[rank_slot],
                                "dt_index": dt_index,
                                "dt_pointer": f"0x{dt_pointer:08X}",
                                "record_offset": f"0x{record_offset:08X}",
                                "entry_offset": f"0x{int(drop['entry_offset']):08X}",
                                "drop_index_in_table": drop["drop_index_in_table"],
                                "percentage": drop["percentage"],
                                "item_id": item_id,
                                "item_name": item_names_by_id.get(item_id, f"Item {item_id}"),
                                "association_entry_offset": f"0x{int(assoc['association_entry_offset']):08X}",
                                "primary_ptr": f"0x{primary_ptr:08X}",
                                "secondary_ptr": f"0x{secondary_ptr:08X}",
                                "secondary_count": secondary_count,
                                "primary_num_carves": None,
                            }
                        )

    return rows


def filter_frontier_shared_carve_pool_duplicates(
    rows: list[dict[str, int | str | None]],
) -> list[dict[str, int | str | None]]:
    """
    Drop duplicate references to the shared arena-rank carve pool (DT 801, etc.): same idea as
    Quarzeps partbreak. Anchor monster defines which dt_index values per rank are treated as
    that pool for deduplication (see FRONTIER_SHARED_CARVE_DEDUPE_* constants).
    """
    anchor_dt_by_rank: dict[str, set[int]] = {}
    for row in rows:
        monster_id = int(row["monster_id"])
        if monster_id != FRONTIER_SHARED_CARVE_DEDUPE_ANCHOR_MONSTER_ID:
            continue
        rank = str(row.get("rank_label", "")).strip().lower()
        if rank not in FRONTIER_SHARED_CARVE_DEDUPE_RANKS:
            continue
        anchor_dt_by_rank.setdefault(rank, set()).add(int(row["dt_index"]))

    if not anchor_dt_by_rank:
        return rows

    kept: list[dict[str, int | str | None]] = []
    removed = 0
    for row in rows:
        monster_id = int(row["monster_id"])
        rank = str(row.get("rank_label", "")).strip().lower()
        if rank not in FRONTIER_SHARED_CARVE_DEDUPE_RANKS:
            kept.append(row)
            continue
        indices = anchor_dt_by_rank.get(rank)
        if not indices:
            kept.append(row)
            continue
        if int(row["dt_index"]) in indices:
            removed += 1
            continue
        kept.append(row)

    if removed > 0:
        print(f"Filtered {removed} Frontier shared carve pool duplicate rows")

    return kept


def _coerce_primary_num_carves(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, str) and value.strip() == "":
        return None
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def format_carve_source_label(
    labels: dict[str, object],
    monster_id: int,
    path_label: str,
    record_index: int,
    primary_num_carves: int | None,
) -> str | None:
    """Match site/scripts/build-data.mjs formatCarveSourceLabel; None means __ignore__."""
    path_lower = path_label.strip().lower()
    suffix = ""
    if primary_num_carves is not None:
        suffix = f" ({primary_num_carves})"

    monster_labels = labels.get(str(monster_id))
    if not isinstance(monster_labels, dict):
        monster_labels = {}

    if path_lower == "primary":
        prim = monster_labels.get("primary")
        if not isinstance(prim, dict):
            prim = {}
        raw_manual = prim.get(str(record_index))
        manual = raw_manual.strip() if isinstance(raw_manual, str) else ""
        if manual == "__ignore__":
            return None
        if manual:
            return manual
        if record_index == 0:
            return f"Body Carves{suffix}"
        return f"Non Body Carve Primary {record_index}{suffix}"

    if path_lower == "secondary":
        sec = monster_labels.get("secondary")
        if not isinstance(sec, dict):
            sec = {}
        raw_manual = sec.get(str(record_index))
        manual = raw_manual.strip() if isinstance(raw_manual, str) else ""
        if manual == "__ignore__":
            return None
        if manual:
            return manual
        return f"Secondary Carve {record_index}"

    return f"Carve {record_index}"


def apply_carve_source_labels(
    rows: list[dict[str, int | str | None]],
    labels: dict[str, object],
) -> list[dict[str, int | str | None]]:
    """Set source_label for each row; drop rows marked __ignore__ in labels."""
    out: list[dict[str, int | str | None]] = []
    ignored = 0
    for row in rows:
        num_carves = _coerce_primary_num_carves(row.get("primary_num_carves"))
        sl = format_carve_source_label(
            labels,
            int(row["monster_id"]),
            str(row.get("path", "")),
            int(row["record_index"]),
            num_carves,
        )
        if sl is None:
            ignored += 1
            continue
        new_row = dict(row)
        new_row["source_label"] = sl
        out.append(new_row)

    if ignored > 0:
        print(f"Dropped {ignored} carve rows marked __ignore__ in labels")

    return out


def dedupe_carve_rows_for_build(
    rows: list[dict[str, int | str | None]],
) -> list[dict[str, int | str | None]]:
    """Same key as former build-data.mjs buildCarveMethods dedupe."""
    seen: set[tuple[object, ...]] = set()
    out: list[dict[str, int | str | None]] = []
    for r in rows:
        key = (
            "carve",
            str(r["rank_label"]).lower(),
            str(r["source_label"]),
            int(r["monster_id"]),
            int(r["item_id"]),
            int(r["percentage"]),
            1,
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def main() -> None:
    args = parse_args()

    raw = args.input.read_bytes()
    important_nums_base = read_u32(raw, IMPORTANT_NUMS_POINTER_HEADER_ADDRESS, "important_nums_pointer")
    carve_dt_pointer_array_base = read_u32(
        raw, CARVE_DT_POINTER_HEADER_ADDRESS, "carve_dt_pointer_header"
    )
    carve_assoc_base = read_u32(raw, CARVE_ASSOC_POINTER_HEADER_ADDRESS, "carve_assoc_pointer_header")
    carve_dt_count = read_u16(
        raw,
        important_nums_base + CARVE_DT_COUNT_OFFSET_IN_IMPORTANT_NUMS,
        "important_nums carve_dt_count",
    )

    if important_nums_base >= len(raw):
        raise ValueError(f"important_nums base 0x{important_nums_base:08X} outside file bounds")
    if carve_dt_pointer_array_base >= len(raw):
        raise ValueError(
            f"Carve DT pointer array base 0x{carve_dt_pointer_array_base:08X} outside file bounds"
        )
    if carve_assoc_base >= len(raw):
        raise ValueError(f"Carve association base 0x{carve_assoc_base:08X} outside file bounds")

    monster_names_by_id = load_monster_names(args.monster_names_json)
    item_names_by_id = load_item_names(args.items_source)
    carve_labels = load_optional_json_object(args.monster_carve_labels)
    carve_dt_pointers, carve_tables = parse_all_carve_tables(
        raw, carve_dt_pointer_array_base, carve_dt_count
    )

    rows = flatten_rows(
        raw=raw,
        monster_names_by_id=monster_names_by_id,
        item_names_by_id=item_names_by_id,
        assoc_base=carve_assoc_base,
        carve_dt_pointers=carve_dt_pointers,
        carve_tables=carve_tables,
    )
    rows = filter_frontier_shared_carve_pool_duplicates(rows)
    rows = apply_carve_source_labels(rows, carve_labels)
    rows = dedupe_carve_rows_for_build(rows)

    write_json_output(args.output, rows)

    print(f"Decoded {len(carve_dt_pointers)} carve DT pointers")
    print(f"Decoded carve rows: {len(rows)}")


if __name__ == "__main__":
    main()
