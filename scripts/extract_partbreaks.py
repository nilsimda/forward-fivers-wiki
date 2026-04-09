#!/usr/bin/env python3
import argparse
import json
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

from extract_common import (
    DEFAULT_DATA_PATHS,
    REPO_ROOT,
    Rank,
    load_item_names,
    load_monster_names,
    load_valid_monster_ranks,
    load_wiki_hidden_item_ids,
    read_u32,
    write_json_output,
)

INPUT_DEFAULT = REPO_ROOT / "g1_data" / "mhfdat.raw.bin"
OUTPUT_DEFAULT = REPO_ROOT / "site" / "src" / "data" / "generated" / "partbreaks.json"

DROP_TABLE_POINTER_HEADER_ADDRESS = 0x00000128
MAPPING_POINTER_HEADER_ADDRESS = 0x0000012C

COUNTS_POINTER_ADDRESS = 0x00000010
OFFSET_FROM_COUNTS_POINTER = 0x24

DROP_TERMINATOR = 0xFFFF

ITEM_NAMES = load_item_names()


@dataclass(slots=True)
class PartbreakTableItemDrop:
    percentage: int
    item_id: int
    item_name: str
    quantity: int

    _STRUCT: ClassVar[struct.Struct] = struct.Struct("<HHH")

    @classmethod
    def unpack_from(cls, raw: bytes, offset: int) -> "PartbreakTableItemDrop":
        unpacked = cls._STRUCT.unpack_from(raw, offset)
        return cls(
            percentage=unpacked[0],
            item_id=unpacked[1],
            item_name=ITEM_NAMES.get(unpacked[1], "unkown"),
            quantity=unpacked[2],
        )

    @classmethod
    def size(cls) -> int:
        return cls._STRUCT.size


@dataclass(slots=True)
class PartbreakTable:
    partbreak_label: str
    drops: list[PartbreakTableItemDrop] = field(default_factory=list)


@dataclass(slots=True)
class MonsterPTsPerRank:
    id: int
    monster_name: str
    lr_pts: list[PartbreakTable] = field(default_factory=list)
    hr_pts: list[PartbreakTable] = field(default_factory=list)
    er_pts: list[PartbreakTable] = field(default_factory=list)
    gr_pts: list[PartbreakTable] = field(default_factory=list)


@dataclass(slots=True)
class PartbreakTablesPerRank:
    lr: PartbreakTable | None
    hr: PartbreakTable | None
    er: PartbreakTable | None
    gr: PartbreakTable | None

    def append_to(self, monster_cts: MonsterPTsPerRank) -> None:
        if self.lr:
            monster_cts.lr_pts.append(self.lr)
        if self.hr:
            monster_cts.hr_pts.append(self.hr)
        if self.er:
            monster_cts.er_pts.append(self.er)
        if self.gr:
            monster_cts.gr_pts.append(self.gr)


@dataclass(slots=True)
class MappingFields:
    monster_id: int
    part_break_type: int
    low_rank_pdt_index: int
    high_rank_pdt_index: int
    arena_pdt_index: int
    elite_rank_pdt_index: int
    grank_pdt_index: int

    _STRUCT: ClassVar[struct.Struct] = struct.Struct("<BBHHHH6sH8s")

    @classmethod
    def unpack_from(cls, raw: bytes, offset: int) -> "MappingFields":
        unpacked = cls._STRUCT.unpack_from(raw, offset)
        return cls(
            monster_id=unpacked[0],
            part_break_type=unpacked[1],
            low_rank_pdt_index=unpacked[2],
            high_rank_pdt_index=unpacked[3],
            arena_pdt_index=unpacked[4],
            elite_rank_pdt_index=unpacked[5],
            grank_pdt_index=unpacked[7],
        )

    @classmethod
    def size(cls) -> int:
        return cls._STRUCT.size


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract partbreak/capture drop data from mhfdat.raw.bin into JSON."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_DATA_PATHS["mhfdat"],
        help="Path to mhfdat.raw.bin",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_DEFAULT,
        help="Output acquisition-method rows consumed by site/scripts/build-data.mjs",
    )
    parser.add_argument(
        "--wiki-hidden-item-ids",
        type=Path,
        default=DEFAULT_DATA_PATHS["hidden_item_ids"],
        help="JSON with itemIds to omit from drops.",
    )
    parser.add_argument(
        "--monster-names-json",
        type=Path,
        default=DEFAULT_DATA_PATHS["monster_names"],
        help="JSON object mapping monster_id keys to display names.",
    )
    parser.add_argument(
        "--monster-partbreak-labels",
        type=Path,
        default=DEFAULT_DATA_PATHS["partbreak_labels"],
        help="monster_id -> partbreak_type_raw -> display label; __ignore__ drops part_break rows.",
    )
    return parser.parse_args()


def _extract_pt(
    raw, pt_index, wiki_hidden_item_ids: frozenset[int], label: str
) -> PartbreakTable:
    base_pointer = read_u32(raw, DROP_TABLE_POINTER_HEADER_ADDRESS)
    pt_offset = read_u32(raw, base_pointer + 0x4 * pt_index)
    pt = PartbreakTable(partbreak_label=label)
    while True:
        item_drop = PartbreakTableItemDrop.unpack_from(raw, pt_offset)
        pt_offset += PartbreakTableItemDrop.size()
        if item_drop.percentage == 0xFFFF:
            return pt
        if item_drop.item_id not in wiki_hidden_item_ids:
            pt.drops.append(item_drop)


def extract_pt_per_rank(
    raw: bytes,
    monster_map: MappingFields,
    wiki_hidden_item_ids: frozenset[int],
    valid_monster_ranks: set[Rank],
    label: str,
) -> PartbreakTablesPerRank:
    lr_pt = (
        _extract_pt(raw, monster_map.low_rank_pdt_index, wiki_hidden_item_ids, label)
        if "lr" in valid_monster_ranks
        else None
    )
    hr_pt = (
        _extract_pt(raw, monster_map.high_rank_pdt_index, wiki_hidden_item_ids, label)
        if "hr" in valid_monster_ranks
        else None
    )
    er_pt = (
        _extract_pt(raw, monster_map.elite_rank_pdt_index, wiki_hidden_item_ids, label)
        if "er" in valid_monster_ranks
        else None
    )
    gr_pt = (
        _extract_pt(raw, monster_map.grank_pdt_index, wiki_hidden_item_ids, label)
        if "gr" in valid_monster_ranks
        else None
    )

    return PartbreakTablesPerRank(lr_pt, hr_pt, er_pt, gr_pt)


def main() -> None:
    args = parse_args()
    raw = args.input.read_bytes()

    monster_names_by_id = load_monster_names(args.monster_names_json)
    all_partbreak_labels = json.loads(args.monster_partbreak_labels.read_text())
    hidden_path = args.wiki_hidden_item_ids
    wiki_hidden_item_ids = load_wiki_hidden_item_ids(hidden_path)
    mapping_base_offset = read_u32(raw, MAPPING_POINTER_HEADER_ADDRESS)
    all_valid_ranks = load_valid_monster_ranks()

    monster_partbreaks: dict[int, MonsterPTsPerRank] = {}
    while True:
        monster_map = MappingFields.unpack_from(raw, mapping_base_offset)
        mapping_base_offset += MappingFields.size()

        if monster_map.monster_id == 0xFF and monster_map.part_break_type == 0xFF:
            break

        mon_id = monster_map.monster_id
        monster_labels = all_partbreak_labels[str(mon_id)]
        label = monster_labels[f"0x{monster_map.part_break_type:02X}"]

        if label is None or label == "__ignore__":
            continue

        if mon_id not in monster_partbreaks:
            monster_partbreaks[mon_id] = MonsterPTsPerRank(
                id=mon_id,
                monster_name=monster_names_by_id[mon_id],
            )

        pts = extract_pt_per_rank(
            raw, monster_map, wiki_hidden_item_ids, all_valid_ranks[mon_id], label
        )
        pts.append_to(monster_partbreaks[mon_id])

    all_monster_pts = list(monster_partbreaks.values())
    write_json_output(args.output, all_monster_pts)


if __name__ == "__main__":
    main()
