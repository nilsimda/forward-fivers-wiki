#!/usr/bin/python3
"""Rewrite extract_carves_data"""

import argparse
import json
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar, Literal, TypedDict

from extract_common import (
    DEFAULT_DATA_PATHS,
    HEADER_POINTERS,
    REPO_ROOT,
    Rank,
    load_item_names,
    load_monster_names,
    load_valid_monster_ranks,
    load_wiki_hidden_item_ids,
    read_u32,
    write_json_output,
)

ITEM_NAMES = load_item_names()

CarveType = Literal["primary", "secondary"]


@dataclass(slots=True)
class CarveTableItemDrop:
    percentage: int
    item_id: int
    item_name: str

    _STRUCT: ClassVar[struct.Struct] = struct.Struct("<HH")

    @classmethod
    def unpack_from(cls, raw: bytes, offset: int) -> "CarveTableItemDrop":
        unpacked = cls._STRUCT.unpack_from(raw, offset)
        return cls(
            percentage=unpacked[0],
            item_id=unpacked[1],
            item_name=ITEM_NAMES.get(unpacked[1], "unkown"),
        )

    @classmethod
    def size(cls) -> int:
        return cls._STRUCT.size


@dataclass(slots=True)
class CarveTable:
    label: str
    trigger_chance: int | None
    num_carves: int | None
    drops: list[CarveTableItemDrop] = field(default_factory=list)


@dataclass(slots=True)
class MonsterCTsPerRank:
    id: int
    monster_name: str
    lr_cts: list[CarveTable] = field(default_factory=list)
    hr_cts: list[CarveTable] = field(default_factory=list)
    er_cts: list[CarveTable] = field(default_factory=list)
    gr_cts: list[CarveTable] = field(default_factory=list)


@dataclass(slots=True)
class CarveTablesPerRank:
    lr: CarveTable | None
    hr: CarveTable | None
    er: CarveTable | None
    gr: CarveTable | None

    def append_to(self, monster_cts: MonsterCTsPerRank) -> None:
        if self.lr:
            monster_cts.lr_cts.append(self.lr)
        if self.hr:
            monster_cts.hr_cts.append(self.hr)
        if self.er:
            monster_cts.er_cts.append(self.er)
        if self.gr:
            monster_cts.gr_cts.append(self.gr)


class CarveTypeLabels(TypedDict, total=False):
    primary: dict[str, str]
    secondary: dict[str, str]


# top level keyed by monster id (as str, since JSON)
CarveLabels = dict[str, CarveTypeLabels]


@dataclass(slots=True)
class BaseMonsterCTIndices:
    lr_index: int
    hr_index: int
    elite_index: int
    gr_index: int

    @classmethod
    def unpack_from(cls, raw: bytes, offset: int) -> "BaseMonsterCTIndices":
        raise ValueError("BaseMonsterCTIndices is an abstract class")

    @classmethod
    def size(cls) -> int:
        raise ValueError("BaseMonsterCTIndices is an abstract class")


@dataclass(slots=True)
class PrimaryMonsterCTIndices(BaseMonsterCTIndices):
    num_carves: int

    _STRUCT: ClassVar[struct.Struct] = struct.Struct("<HHHHIHHIIHHIII")

    @classmethod
    def unpack_from(cls, raw: bytes, offset: int) -> "PrimaryMonsterCTIndices":
        unpacked = cls._STRUCT.unpack_from(raw, offset)
        return cls(
            unpacked[0],
            unpacked[1],
            unpacked[3],
            unpacked[6],
            9 if unpacked[-5] == 0 else unpacked[-5],
        )

    @classmethod
    def size(cls) -> int:
        return cls._STRUCT.size


@dataclass(slots=True)
class SecondaryMonsterCTIndices(BaseMonsterCTIndices):
    trigger_chance: int

    _STRUCT: ClassVar[struct.Struct] = struct.Struct("<HHHHIHHIIBB")

    @classmethod
    def unpack_from(cls, raw: bytes, offset: int) -> "SecondaryMonsterCTIndices":
        unpacked = cls._STRUCT.unpack_from(raw, offset)
        return cls(unpacked[0], unpacked[1], unpacked[3], unpacked[6], unpacked[-2])

    @classmethod
    def size(cls) -> int:
        return cls._STRUCT.size


WIKI_HIDDEN_ITEM_IDS = load_wiki_hidden_item_ids(DEFAULT_DATA_PATHS["hidden_item_ids"])


@dataclass(slots=True)
class HccRecord:
    monster_id: int
    lr_item_id: int
    hr_item_id: int
    er_item_id: int

    _STRUCT: ClassVar[struct.Struct] = struct.Struct("<HHHHH")

    @classmethod
    def unpack_from(cls, raw: bytes, offset: int) -> "HccRecord":
        unpacked = cls._STRUCT.unpack_from(raw, offset)
        return cls(
            monster_id=unpacked[0],
            lr_item_id=unpacked[1],
            hr_item_id=unpacked[2],
            er_item_id=unpacked[4],
        )

    @classmethod
    def size(cls) -> int:
        return cls._STRUCT.size


def extract_hcc_carves(raw: bytes) -> dict[int, dict[Rank, CarveTable]]:
    hcc_pointer = read_u32(raw, HEADER_POINTERS["hcc_table"])
    hcc_by_monster: dict[int, dict[Rank, CarveTable]] = {}

    while True:
        hcc_record = HccRecord.unpack_from(raw, hcc_pointer)
        hcc_pointer += HccRecord.size()

        if hcc_record.monster_id == 0xFFFF:
            break

        lr_drop = CarveTableItemDrop(
            percentage=2,
            item_id=hcc_record.lr_item_id,
            item_name=ITEM_NAMES.get(hcc_record.lr_item_id, "unkown"),
        )

        lr_hcc_ct = CarveTable(
            label="HC Carve",
            trigger_chance=None,
            num_carves=None,
            drops=[lr_drop],
        )
        hr_drop = CarveTableItemDrop(
            percentage=2,
            item_id=hcc_record.hr_item_id,
            item_name=ITEM_NAMES.get(hcc_record.hr_item_id, "unkown"),
        )

        hr_hcc_ct = CarveTable(
            label="HC Carve",
            trigger_chance=None,
            num_carves=None,
            drops=[hr_drop],
        )

        er_drop = CarveTableItemDrop(
            percentage=2,
            item_id=hcc_record.er_item_id,
            item_name=ITEM_NAMES.get(hcc_record.er_item_id, "unkown"),
        )

        er_hcc_ct = CarveTable(
            label="HC Carve",
            trigger_chance=None,
            num_carves=None,
            drops=[er_drop],
        )

        rank_to_hcc_ct: dict[Rank, CarveTable] = {
            "lr": lr_hcc_ct,
            "hr": hr_hcc_ct,
            "er": er_hcc_ct,
        }
        hcc_by_monster[hcc_record.monster_id] = rank_to_hcc_ct

    return hcc_by_monster


def _extract_carve_table(
    raw: bytes,
    idx: int,
    rank: Rank,
    label: str,
    trigger_chance: int | None,
    num_carves: int | None,
) -> CarveTable:
    ct_pointer = HEADER_POINTERS["carve_tables"] + 0x4 * idx
    ct_offset = read_u32(raw, ct_pointer)
    ct = CarveTable(
        label=label,
        trigger_chance=trigger_chance,
        num_carves=num_carves,
    )
    while True:
        ct_drop = CarveTableItemDrop.unpack_from(raw, ct_offset)
        if ct_drop.percentage == 0xFFFF and ct_drop.item_id == 0x0000:
            break
        if ct_drop.item_id not in WIKI_HIDDEN_ITEM_IDS:
            ct.drops.append(ct_drop)
        ct_offset += CarveTableItemDrop.size()

    return ct


def _is_valid_ct_index(idx: int, monster_id: int, rank: Rank) -> bool:
    """Index 0 is only valid for low-rank Rathian (monster_id=1)."""
    return idx != 0 or (monster_id == 1 and rank == "lr")


def _extract_carve_tables_per_rank(
    raw: bytes,
    ct_indices: BaseMonsterCTIndices,
    label: str,
    valid_ranks: set[Rank],
    monster_id: int,
    trigger_chance: int | None,
    num_carves: int | None,
) -> CarveTablesPerRank:
    ct_lr = (
        _extract_carve_table(
            raw,
            ct_indices.lr_index,
            rank="lr",
            label=label,
            trigger_chance=trigger_chance,
            num_carves=num_carves,
        )
        if "lr" in valid_ranks
        and _is_valid_ct_index(ct_indices.lr_index, monster_id, "lr")
        else None
    )
    ct_hr = (
        _extract_carve_table(
            raw,
            ct_indices.hr_index,
            rank="hr",
            label=label,
            trigger_chance=trigger_chance,
            num_carves=num_carves,
        )
        if "hr" in valid_ranks
        and _is_valid_ct_index(ct_indices.hr_index, monster_id, "hr")
        else None
    )
    ct_er = (
        _extract_carve_table(
            raw,
            ct_indices.elite_index,
            rank="er",
            label=label,
            trigger_chance=trigger_chance,
            num_carves=num_carves,
        )
        if "er" in valid_ranks
        and _is_valid_ct_index(ct_indices.elite_index, monster_id, "er")
        else None
    )
    ct_gr = (
        _extract_carve_table(
            raw,
            ct_indices.gr_index,
            rank="gr",
            label=label,
            trigger_chance=trigger_chance,
            num_carves=num_carves,
        )
        if "gr" in valid_ranks
        and _is_valid_ct_index(ct_indices.gr_index, monster_id, "gr")
        else None
    )

    return CarveTablesPerRank(ct_lr, ct_hr, ct_er, ct_gr)


def _should_skip_ct_entry(
    ct_ids: BaseMonsterCTIndices,
    carve_labels: CarveTypeLabels,
    label_idx: int,
    carve_type: CarveType,
) -> bool:
    labels = carve_labels.get(carve_type, {})
    invalid_key = str(label_idx) not in labels or labels[str(label_idx)] == "__ignore__"

    return invalid_key or (
        ct_ids.lr_index == 0
        and ct_ids.hr_index == 0
        and ct_ids.elite_index == 0
        and ct_ids.gr_index == 0
    )


def _process_ct_entries(
    raw: bytes,
    ct_pointer: int,
    count: int,
    ct_indices_cls: type[BaseMonsterCTIndices],
    carve_labels: CarveTypeLabels,
    carve_type: CarveType,
    rank_cts: MonsterCTsPerRank,
    valid_ranks: set[Rank],
    monster_id: int,
) -> None:
    if ct_pointer != 0:
        for i in range(count):
            ct_indices = ct_indices_cls.unpack_from(raw, ct_pointer)
            if not _should_skip_ct_entry(ct_indices, carve_labels, i, carve_type):
                trigger_chance = getattr(ct_indices, "trigger_chance", None)
                num_carves = getattr(ct_indices, "num_carves", None)
                tables = _extract_carve_tables_per_rank(
                    raw,
                    ct_indices,
                    carve_labels[carve_type][str(i)],
                    valid_ranks,
                    monster_id,
                    trigger_chance=trigger_chance,
                    num_carves=num_carves,
                )
                tables.append_to(rank_cts)
            ct_pointer += ct_indices_cls.size()


def extract_monster_carve_tables(
    raw: bytes,
    mon_id: int,
    mon_name: str,
    all_carve_labels: CarveLabels,
    valid_ranks: set[Rank],
) -> MonsterCTsPerRank:
    monster_ct_pointers_base = HEADER_POINTERS["carve_table_indices"] + mon_id * 0x0C

    carve_labels = all_carve_labels[str(mon_id)]

    primary_ct_pointer = read_u32(raw, monster_ct_pointers_base)
    secondary_ct_pointer = read_u32(
        raw,
        monster_ct_pointers_base + 0x4,
    )
    num_secondary_cts = read_u32(
        raw,
        monster_ct_pointers_base + 0x8,
    )
    rank_cts = MonsterCTsPerRank(id=mon_id, monster_name=mon_name)

    _process_ct_entries(
        raw,
        primary_ct_pointer,
        3,
        PrimaryMonsterCTIndices,
        carve_labels,
        "primary",
        rank_cts,
        valid_ranks,
        mon_id,
    )

    _process_ct_entries(
        raw,
        secondary_ct_pointer,
        num_secondary_cts,
        SecondaryMonsterCTIndices,
        carve_labels,
        "secondary",
        rank_cts,
        valid_ranks,
        mon_id,
    )

    return rank_cts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract carve data from mhfdat")
    parser.add_argument(
        "--monster-names",
        type=Path,
        default=DEFAULT_DATA_PATHS["monster_names"],
        help="Path to monster names file",
    )
    parser.add_argument(
        "--carve-labels",
        type=Path,
        default=DEFAULT_DATA_PATHS["carve_labels"],
        help="Path to carve labels JSON file",
    )
    parser.add_argument(
        "--mhfdat",
        type=Path,
        default=DEFAULT_DATA_PATHS["mhfdat"],
        help="Path to mhfdat binary file",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=REPO_ROOT / "site" / "src" / "data" / "generated" / "carves.json",
        help="Output path for generated carves.json",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    monster_names: dict[int, str] = load_monster_names(args.monster_names)
    carve_labels: CarveLabels = json.loads(args.carve_labels.read_text())
    all_valid_ranks = load_valid_monster_ranks()
    mhfdat_raw = args.mhfdat.read_bytes()

    all_monster_cts: list[MonsterCTsPerRank] = []
    hcc_by_monster = extract_hcc_carves(mhfdat_raw)
    for mon_id, mon_name in monster_names.items():
        monster_cts = extract_monster_carve_tables(
            mhfdat_raw,
            mon_id,
            mon_name,
            carve_labels,
            all_valid_ranks[mon_id],
        )
        if mon_id in hcc_by_monster:
            valid_ranks = all_valid_ranks[mon_id]
            hcc_cts = hcc_by_monster[mon_id]
            if "lr" in valid_ranks:
                monster_cts.lr_cts.append(hcc_cts["lr"])
            if "hr" in valid_ranks:
                monster_cts.hr_cts.append(hcc_cts["hr"])
            if "er" in valid_ranks:
                monster_cts.er_cts.append(hcc_cts["er"])

        all_monster_cts.append(monster_cts)

    write_json_output(args.output, all_monster_cts)


# TODO: start at header pointers

if __name__ == "__main__":
    main()
