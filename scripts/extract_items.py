#!/usr/bin/env python3
import argparse
import json
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, TypedDict

from extract_common import (
    DEFAULT_DATA_PATHS,
    HEADER_POINTERS,
    REPO_ROOT,
    ColorTagSegment,
    decode_c_string,
    is_wiki_hidden_item,
    parse_color_tags,
    read_u16,
    read_u32,
    write_json_output,
)

OUTPUT_DEFAULT = REPO_ROOT / "site" / "src" / "data" / "generated" / "items.json"
CARVES_PATH = REPO_ROOT / "site" / "src" / "data" / "generated" / "carves.json"
PARTBREAKS_PATH = REPO_ROOT / "site" / "src" / "data" / "generated" / "partbreaks.json"
QUESTS_PATH = REPO_ROOT / "site" / "src" / "data" / "generated" / "quests.json"
GATHERING_PATH = REPO_ROOT / "site" / "src" / "data" / "generated" / "gathering.json"

ITEM_DESCRIPTIONS_POINTER_TABLE_OFFSET = 0x60
ITEM_COUNT_OFFSET_FROM_POINTER = 0x0C


class CarveAquisition(TypedDict):
    monster_id: int
    monster_name: str
    rank: str
    label: str
    percentage: int


class PartbreakAquisition(TypedDict):
    monster_id: int
    monster_name: str
    rank: str
    label: str
    percentage: int
    quantity: int


class QuestAquisition(TypedDict):
    quest_id: int
    title: str
    main_objective: str
    rank: str
    percentage: int
    quantity: int
    reward_box_label: str
    guaranteed: bool


class GatheringAquisition(TypedDict):
    map_id: str
    rank: str
    area: int
    point_id: int
    percentage: int
    min_count: int
    max_count: int
    time: str
    season: str


@dataclass(slots=True)
class Item:
    id: int
    rarity: int
    max_stack: int
    icon_id: int
    icon_color: int
    buy_price: int
    sell_price: int
    item_type: int
    deco_id: int
    is_gz: bool
    name: str
    description: str
    descriptionSegments: list[ColorTagSegment]

    carve_aquisitions: list[CarveAquisition] = field(default_factory=list)
    partbreak_aquisitions: list[PartbreakAquisition] = field(default_factory=list)
    quest_aquisitions: list[QuestAquisition] = field(default_factory=list)
    gathering_aquisitions: list[GatheringAquisition] = field(default_factory=list)

    _STRUCT: ClassVar[struct.Struct] = struct.Struct("<BBBBBBBBHHIIHHHBBHBB")

    @classmethod
    def unpack_from(
        cls,
        raw: bytes,
        offset: int,
        item_id: int,
        name_offset: int,
        description_offset: int,
    ) -> "Item":
        unpacked = cls._STRUCT.unpack_from(raw, offset)

        name = decode_c_string(raw, name_offset).strip()
        description = decode_c_string(raw, description_offset).strip()
        parsed_description = parse_color_tags(description)

        return cls(
            id=item_id,
            rarity=unpacked[2],
            max_stack=unpacked[3],
            icon_id=unpacked[5],
            icon_color=unpacked[6],
            buy_price=unpacked[10],
            sell_price=unpacked[11],
            item_type=unpacked[12],
            deco_id=unpacked[13],
            is_gz=bool(unpacked[-2]),
            name=name,
            description=parsed_description.plain,
            descriptionSegments=parsed_description.segments,
        )

    @classmethod
    def size(cls) -> int:
        return cls._STRUCT.size


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract item table + names/descriptions from mhfdat.raw.bin into JSON."
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
        default=REPO_ROOT / "site" / "src" / "data" / "generated" / "items.json",
        help="Output frontend-ready items JSON path.",
    )
    return parser.parse_args()


def extract_items(
    raw: bytes,
) -> list[Item]:
    item_count_base_ptr = read_u32(raw, HEADER_POINTERS["mhfdat_counts"])
    item_count = read_u16(raw, item_count_base_ptr + ITEM_COUNT_OFFSET_FROM_POINTER)

    item_structs_base = read_u32(raw, HEADER_POINTERS["items"], "item_structs_header")
    names_pointer_base = read_u32(raw, HEADER_POINTERS["item_names"])
    desc_pointer_header = read_u32(raw, HEADER_POINTERS["item_descriptions"])
    desc_pointer_base = desc_pointer_header + ITEM_DESCRIPTIONS_POINTER_TABLE_OFFSET

    carve_aquisitions = build_carve_acquisitions(CARVES_PATH)
    partbreak_aquisitions = build_partbreak_acquisitions(PARTBREAKS_PATH)
    quest_aquisitions = build_quest_aquisitions(QUESTS_PATH)
    gathering_aquisitions = build_gathering_aquisitions(GATHERING_PATH)

    items: list[Item] = []
    for item_index in range(item_count):
        offset = item_structs_base + item_index * Item.size()
        name_offset = read_u32(raw, names_pointer_base + item_index * 4)
        description_offset = read_u32(raw, desc_pointer_base + item_index * 4)
        item = Item.unpack_from(
            raw, offset, item_index, name_offset, description_offset
        )
        item.carve_aquisitions = carve_aquisitions.get(item.id, [])
        item.partbreak_aquisitions = partbreak_aquisitions.get(item.id, [])
        item.quest_aquisitions = quest_aquisitions.get(item.id, [])
        item.gathering_aquisitions = gathering_aquisitions.get(item.id, [])
        items.append(item)

    return items


def build_carve_acquisitions(carves_path: Path) -> dict[int, list[CarveAquisition]]:
    carves: list[dict[str, Any]] = json.loads(carves_path.read_text(encoding="utf-8"))
    index: dict[int, list[CarveAquisition]] = {}
    for monster in carves:
        for rank in ["lr", "hr", "er", "gr"]:
            for table in monster[f"{rank}_cts"]:
                for drop in table["drops"]:
                    index.setdefault(drop["item_id"], []).append(
                        CarveAquisition(
                            monster_id=monster["id"],
                            monster_name=monster["monster_name"],
                            rank=rank,
                            label=table["label"],
                            percentage=drop["percentage"],
                        )
                    )
    return index


def build_partbreak_acquisitions(
    partbreaks_path: Path,
) -> dict[int, list[PartbreakAquisition]]:
    partbreaks: list[dict[str, Any]] = json.loads(
        partbreaks_path.read_text(encoding="utf-8")
    )
    index: dict[int, list[PartbreakAquisition]] = {}
    for monster in partbreaks:
        for rank in ["lr", "hr", "er", "gr"]:
            for table in monster[f"{rank}_pts"]:
                for drop in table["drops"]:
                    index.setdefault(drop["item_id"], []).append(
                        PartbreakAquisition(
                            monster_id=monster["id"],
                            monster_name=monster["monster_name"],
                            rank=rank,
                            label=table["partbreak_label"],
                            percentage=drop["percentage"],
                            quantity=drop["quantity"],
                        )
                    )

    return index


def build_quest_aquisitions(quests_path: Path) -> dict[int, list[QuestAquisition]]:
    quests: list[dict[str, Any]] = json.loads(quests_path.read_text(encoding="utf-8"))
    index: dict[int, list[QuestAquisition]] = {}
    for quest in quests:
        for label, reward_box in quest["reward_boxes"].items():
            for drop in reward_box:
                index.setdefault(drop["item_id"], []).append(
                    QuestAquisition(
                        quest_id=quest["id"],
                        title=quest["quest_text"]["title"],
                        main_objective=quest["quest_text"]["main"],
                        rank=quest["rank"],
                        percentage=drop["percentage"],
                        quantity=drop["quantity"],
                        reward_box_label=label,
                        guaranteed=drop["guaranteed"],
                    )
                )
    return index


DropKey = tuple[int, int, int]  # (area, point_id, item_id)
DropVal = dict[str, int]  # percentage, min_count, max_count
TimeLabel = str
SeasonLabel = str


def _collect_drops_by_key(
    areas: list[dict[str, Any]],
) -> dict[DropKey, DropVal]:
    out: dict[DropKey, DropVal] = {}
    for area_data in areas:
        area_id: int = area_data["area"]
        for pi, gp in enumerate(area_data["gps"]):
            point_id = pi + 1
            for drop in gp["drops"]:
                item_id: int = drop["item_id"]
                if item_id == 0xFFFF:
                    continue
                out[(area_id, point_id, item_id)] = {
                    "percentage": drop["percentage"],
                    "min_count": gp["min_count"],
                    "max_count": gp["max_count"],
                }
    return out


def _compress_time_and_season(
    by_slot: dict[tuple[TimeLabel, SeasonLabel], DropVal],
) -> dict[tuple[TimeLabel, SeasonLabel], DropVal]:
    by_time: dict[tuple[TimeLabel, SeasonLabel], DropVal] = {}
    for season in ("spring", "summer", "winter"):
        day = by_slot.get(("day", season))
        night = by_slot.get(("night", season))
        if day and night and day == night:
            by_time[("both", season)] = day
        else:
            if day:
                by_time[("day", season)] = day
            if night:
                by_time[("night", season)] = night

    compressed: dict[tuple[TimeLabel, SeasonLabel], DropVal] = {}
    for time in ("day", "night", "both"):
        spring = by_time.get((time, "spring"))
        summer = by_time.get((time, "summer"))
        winter = by_time.get((time, "winter"))
        if spring and summer and winter and spring == summer == winter:
            compressed[(time, "all")] = spring
        else:
            if spring:
                compressed[(time, "spring")] = spring
            if summer:
                compressed[(time, "summer")] = summer
            if winter:
                compressed[(time, "winter")] = winter
    return compressed


def build_gathering_aquisitions(
    gathering_path: Path,
) -> dict[int, list[GatheringAquisition]]:
    gathering: list[dict[str, Any]] = json.loads(
        gathering_path.read_text(encoding="utf-8")
    )
    index: dict[int, list[GatheringAquisition]] = {}
    for map_data in gathering:
        map_id = map_data["id"]
        for rank, time_slots in map_data["ranks"].items():
            drops_by_slot: dict[
                tuple[TimeLabel, SeasonLabel], dict[DropKey, DropVal]
            ] = {}
            for time in ("day", "night"):
                for season in ("spring", "summer", "winter"):
                    areas = time_slots[time][season]
                    drops_by_slot[(time, season)] = _collect_drops_by_key(areas)

            all_keys: set[DropKey] = set()
            for drops in drops_by_slot.values():
                all_keys |= set(drops)

            for key in all_keys:
                area_id, point_id, item_id = key
                values_by_slot: dict[tuple[TimeLabel, SeasonLabel], DropVal] = {
                    slot: drops[key]
                    for slot, drops in drops_by_slot.items()
                    if key in drops
                }
                for (time, season), vals in _compress_time_and_season(
                    values_by_slot
                ).items():
                    index.setdefault(item_id, []).append(
                        GatheringAquisition(
                            map_id=map_id,
                            rank=rank,
                            area=area_id,
                            point_id=point_id,
                            percentage=vals["percentage"],
                            min_count=vals["min_count"],
                            max_count=vals["max_count"],
                            time=time,
                            season=season,
                        )
                    )
    return index


def partition_hidden_items(
    items: list[Item],
) -> tuple[list[Item], list[int]]:

    kept_items: list[Item] = []
    hidden_ids: list[int] = []
    for item in items:
        if is_wiki_hidden_item(name=item.name, description_plain=item.description):
            hidden_ids.append(item.id)
        else:
            kept_items.append(item)
    return kept_items, hidden_ids


def main() -> None:
    args = parse_args()
    raw = args.input.read_bytes()
    items = extract_items(raw)

    kept_items, hidden_ids = partition_hidden_items(items)

    carve_index = build_carve_acquisitions(CARVES_PATH)
    for item in kept_items:
        item.carve_aquisitions = carve_index.get(item.id, [])

    write_json_output(DEFAULT_DATA_PATHS["hidden_item_ids"], {"itemIds": hidden_ids})
    write_json_output(args.output, kept_items)


if __name__ == "__main__":
    main()
