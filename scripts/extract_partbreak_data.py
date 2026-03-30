#!/usr/bin/env python3
import argparse
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypedDict, cast

from extract_common import (
    REPO_ROOT,
    default_wiki_hidden_item_ids_path,
    load_item_names,
    load_json_object,
    load_monster_names,
    load_wiki_hidden_item_ids,
    read_pointer_array,
    read_u16,
    read_u32,
    write_json_output,
)

INPUT_DEFAULT = REPO_ROOT / "g1_data" / "mhfdat.raw.bin"
OUTPUT_DEFAULT = (
    REPO_ROOT / "site" / "src" / "data" / "generated" / "_partbreak-source.json"
)
ITEMS_JSON_DEFAULT = REPO_ROOT / "site" / "src" / "data" / "generated" / "items.json"
MONSTER_NAMES_JSON_DEFAULT = REPO_ROOT / "g1_data" / "monster_names.json"
MONSTER_PARTBREAK_LABELS_DEFAULT = (
    REPO_ROOT / "g1_data" / "monster_partbreak_labels.json"
)

DROP_TABLE_POINTER_HEADER_ADDRESS = 0x00000128
MAPPING_POINTER_HEADER_ADDRESS = 0x0000012C

COUNTS_POINTER_ADDRESS = 0x00000010
OFFSET_FROM_COUNTS_POINTER = 0x24

MAPPING_FMT = "<BBHHHH6sH8s"
MAPPING_SIZE = struct.calcsize(MAPPING_FMT)
DROP_FMT = "<HHH"
DROP_SIZE = struct.calcsize(DROP_FMT)

MAPPING_TERMINATOR = b"\xff\xff"
DROP_TERMINATOR = 0xFFFF

RankCode = Literal["lr", "hr", "arena", "hr100", "gr"]
MappingPDTKey = Literal[
    "lowRankPDTIndex",
    "highRankPDTIndex",
    "arenaPDTIndex",
    "hr100PDTIndex",
    "grankPDTIndex",
]
RANK_COLUMNS_TYPED: tuple[tuple[RankCode, MappingPDTKey], ...] = (
    ("lr", "lowRankPDTIndex"),
    ("hr", "highRankPDTIndex"),
    ("arena", "arenaPDTIndex"),
    ("hr100", "hr100PDTIndex"),
    ("gr", "grankPDTIndex"),
)


class DropEntry(TypedDict):
    drop_index_in_table: int
    entry_offset: int
    percentage: int
    item_id: int
    quantity: int


class PartbreakMapping(TypedDict):
    mapping_index: int
    mapping_offset: int
    monster_id: int
    partbreak_type: int
    lowRankPDTIndex: int
    highRankPDTIndex: int
    arenaPDTIndex: int
    hr100PDTIndex: int
    grankPDTIndex: int


class PartbreakRowBase(TypedDict):
    mapping_index: int
    monster_id: int
    monster_name: str
    partbreak_type_raw: str
    drop_mode: str
    rank: RankCode
    pdt_index: int
    pdt_pointer: str
    drop_index_in_table: int
    entry_offset: str
    percentage: int
    quantity: int
    item_id: int
    item_name: str


class PartbreakRow(PartbreakRowBase):
    partbreak_type: str


class AcquisitionMethodRow(TypedDict):
    methodType: Literal["capture", "part_break"]
    rank: RankCode
    sourceLabel: str
    chance: int
    quantity: int
    monsterId: int
    monsterName: str
    itemId: int
    itemName: str
    partbreakType: str


@dataclass(slots=True)
class MappingFields:
    monster_id: int
    part_break_type: int
    low_rank_pdt_index: int
    high_rank_pdt_index: int
    arena_pdt_index: int
    hr100_pdt_index: int
    grank_pdt_index: int

    @classmethod
    def from_unpacked(cls, unpacked: tuple[int, ...]) -> "MappingFields":
        return cls(
            monster_id=unpacked[0],
            part_break_type=unpacked[1],
            low_rank_pdt_index=unpacked[2],
            high_rank_pdt_index=unpacked[3],
            arena_pdt_index=unpacked[4],
            hr100_pdt_index=unpacked[5],
            grank_pdt_index=unpacked[7],
        )

    def to_mapping(
        self, *, mapping_index: int, mapping_offset: int
    ) -> PartbreakMapping:
        return {
            "mapping_index": mapping_index,
            "mapping_offset": mapping_offset,
            "monster_id": self.monster_id,
            "partbreak_type": self.part_break_type,
            "lowRankPDTIndex": self.low_rank_pdt_index,
            "highRankPDTIndex": self.high_rank_pdt_index,
            "arenaPDTIndex": self.arena_pdt_index,
            "hr100PDTIndex": self.hr100_pdt_index,
            "grankPDTIndex": self.grank_pdt_index,
        }


def should_skip_rank_entry(
    rank: RankCode,
    pdt_index: int,
) -> bool:
    # grank index 0x0000 is usually a "no entry" sentinel, not first drop table
    return rank == "gr" and pdt_index == 0


def ensure_pointer_in_bounds(raw: bytes, pointer: int, label: str) -> None:
    if pointer >= len(raw):
        raise ValueError(f"{label} 0x{pointer:08X} outside file bounds")


def read_pdt_count(raw: bytes) -> int:
    counts_base_ptr = read_u32(raw, COUNTS_POINTER_ADDRESS, "counts_base_pointer")
    return read_u16(raw, counts_base_ptr + OFFSET_FROM_COUNTS_POINTER, "pdt_count")


def monster_name_for(monster_names_by_id: dict[int, str], monster_id: int) -> str:
    return monster_names_by_id[monster_id]


def item_name_for(item_names_by_id: dict[int, str], item_id: int) -> str:
    return item_names_by_id[item_id]


def drop_mode_for(partbreak_type: int) -> str:
    return "capture" if partbreak_type == 0x80 else "part_break"


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
        help="Output acquisition-method rows consumed by site/scripts/build-data.mjs",
    )
    parser.add_argument(
        "--items-json",
        type=Path,
        default=ITEMS_JSON_DEFAULT,
        help="Path to generated items.json (for item names).",
    )
    parser.add_argument(
        "--wiki-hidden-item-ids",
        type=Path,
        default=None,
        help="JSON with itemIds to omit from drops (default: sibling of --items-json).",
    )
    parser.add_argument(
        "--monster-names-json",
        type=Path,
        default=MONSTER_NAMES_JSON_DEFAULT,
        help="JSON object mapping monster_id keys to display names.",
    )
    parser.add_argument(
        "--monster-partbreak-labels",
        type=Path,
        default=MONSTER_PARTBREAK_LABELS_DEFAULT,
        help="monster_id -> partbreak_type_raw -> display label; __ignore__ drops part_break rows.",
    )
    return parser.parse_args()


def parse_single_drop_table(
    raw: bytes, table_pointer: int, table_index: int
) -> list[DropEntry]:
    drops: list[DropEntry] = []
    offset = table_pointer
    drop_index = 0
    while True:
        if offset + DROP_SIZE > len(raw):
            raise ValueError(
                f"Drop table {table_index} record at 0x{offset:08X} exceeds file bounds"
            )
        percentage, item_id, quantity = struct.unpack_from(DROP_FMT, raw, offset)
        if percentage == DROP_TERMINATOR:
            break
        drops.append(
            {
                "drop_index_in_table": drop_index,
                "entry_offset": offset,
                "percentage": percentage,
                "item_id": item_id,
                "quantity": quantity,
            }
        )
        offset += DROP_SIZE
        drop_index += 1
    return drops


def parse_all_drop_tables(
    raw: bytes, pointer_array_base: int
) -> tuple[list[int], dict[int, list[DropEntry]]]:
    pdt_count = read_pdt_count(raw)
    pointers = read_pointer_array(
        raw, pointer_array_base, pdt_count, "pdt_pointer_array"
    )
    tables: dict[int, list[DropEntry]] = {}
    for index, pointer in enumerate(pointers):
        ensure_pointer_in_bounds(raw, pointer, f"Drop table pointer[{index}]")
        tables[index] = parse_single_drop_table(raw, pointer, index)
    return pointers, tables


def parse_partbreak_mappings(raw: bytes, mapping_base: int) -> list[PartbreakMapping]:
    mappings: list[PartbreakMapping] = []
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

        fields = MappingFields.from_unpacked(
            struct.unpack_from(MAPPING_FMT, raw, offset)
        )
        mappings.append(
            fields.to_mapping(mapping_index=mapping_index, mapping_offset=offset)
        )
        mapping_index += 1
        offset += MAPPING_SIZE

    return mappings


def build_partbreak_rows(
    mappings: list[PartbreakMapping],
    drop_table_pointers: list[int],
    drop_tables: dict[int, list[DropEntry]],
    item_names_by_id: dict[int, str],
    monster_names_by_id: dict[int, str],
    wiki_hidden_item_ids: frozenset[int],
) -> list[PartbreakRowBase]:
    rows: list[PartbreakRowBase] = []
    for mapping in mappings:
        monster_id = mapping["monster_id"]
        monster_name = monster_name_for(monster_names_by_id, monster_id)
        partbreak_type = mapping["partbreak_type"]
        partbreak_type_raw = f"0x{partbreak_type:02X}"
        drop_mode = drop_mode_for(partbreak_type)

        for rank, key in RANK_COLUMNS_TYPED:
            pdt_index = mapping[key]
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
                item_id = drop["item_id"]
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
                        "entry_offset": f"0x{drop['entry_offset']:08X}",
                        "percentage": drop["percentage"],
                        "quantity": drop["quantity"],
                        "item_id": item_id,
                        "item_name": item_name_for(item_names_by_id, item_id),
                    }
                )
    return rows


def apply_partbreak_display_labels(
    rows: list[PartbreakRowBase],
    labels: dict[str, dict[str, str]],
) -> list[PartbreakRow]:
    """Set partbreak_type (wiki display); drop part_break rows labeled __ignore__."""
    out: list[PartbreakRow] = []
    ignored = 0
    for row in rows:
        raw_type = row["partbreak_type_raw"]
        manual = labels[str(row["monster_id"])][raw_type]
        drop_mode = row["drop_mode"]

        if drop_mode == "part_break" and manual == "__ignore__":
            ignored += 1
            continue

        partbreak_type = raw_type if manual == "__ignore__" else manual

        new_row: PartbreakRow = {**row, "partbreak_type": partbreak_type}
        out.append(new_row)

    if ignored > 0:
        print(f"Dropped {ignored} partbreak rows marked __ignore__ in labels")

    return out


def extract_partbreak_rows(
    raw: bytes,
    *,
    item_names_by_id: dict[int, str],
    monster_names_by_id: dict[int, str],
    wiki_hidden_item_ids: frozenset[int],
    partbreak_labels: dict[str, dict[str, str]],
) -> tuple[list[PartbreakRow], int, int]:
    drop_table_pointer_array_base = read_u32(
        raw, DROP_TABLE_POINTER_HEADER_ADDRESS, "drop_table_pointer_header"
    )
    mapping_base = read_u32(
        raw, MAPPING_POINTER_HEADER_ADDRESS, "mapping_pointer_header"
    )

    ensure_pointer_in_bounds(
        raw, drop_table_pointer_array_base, "Drop table pointer array base"
    )
    ensure_pointer_in_bounds(raw, mapping_base, "Mapping base")

    drop_table_pointers, drop_tables = parse_all_drop_tables(
        raw, drop_table_pointer_array_base
    )
    mappings = parse_partbreak_mappings(raw, mapping_base)

    base_rows = build_partbreak_rows(
        mappings=mappings,
        drop_table_pointers=drop_table_pointers,
        drop_tables=drop_tables,
        item_names_by_id=item_names_by_id,
        monster_names_by_id=monster_names_by_id,
        wiki_hidden_item_ids=wiki_hidden_item_ids,
    )
    labeled_rows = apply_partbreak_display_labels(base_rows, partbreak_labels)
    return labeled_rows, len(drop_table_pointers), len(mappings)


def to_acquisition_methods(rows: list[PartbreakRow]) -> list[AcquisitionMethodRow]:
    methods: list[AcquisitionMethodRow] = []
    for row in rows:
        methods.append(
            {
                "methodType": cast(Literal["capture", "part_break"], row["drop_mode"]),
                "rank": row["rank"],
                "sourceLabel": row["monster_name"],
                "chance": row["percentage"],
                "quantity": row["quantity"],
                "monsterId": row["monster_id"],
                "monsterName": row["monster_name"],
                "itemId": row["item_id"],
                "itemName": row["item_name"],
                "partbreakType": row["partbreak_type"],
            }
        )
    return methods


def main() -> None:
    args = parse_args()
    raw = args.input.read_bytes()

    item_names_by_id = load_item_names(args.items_json)
    monster_names_by_id = load_monster_names(args.monster_names_json)
    partbreak_labels = cast(
        dict[str, dict[str, str]], load_json_object(args.monster_partbreak_labels)
    )
    hidden_path = args.wiki_hidden_item_ids or default_wiki_hidden_item_ids_path(
        args.items_json
    )
    wiki_hidden_item_ids = load_wiki_hidden_item_ids(hidden_path)

    rows, pdt_count, mapping_count = extract_partbreak_rows(
        raw,
        item_names_by_id=item_names_by_id,
        monster_names_by_id=monster_names_by_id,
        wiki_hidden_item_ids=wiki_hidden_item_ids,
        partbreak_labels=partbreak_labels,
    )

    methods = to_acquisition_methods(rows)
    write_json_output(args.output, methods)

    print(f"Decoded {pdt_count} PDT pointers and {mapping_count} mappings")
    print(f"Wrote {len(methods)} partbreak acquisition methods")


if __name__ == "__main__":
    main()
