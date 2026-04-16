#!/usr/bin/env python3
import argparse
import json
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, TypedDict, cast

from extract_common import (
    DEFAULT_DATA_PATHS,
    REPO_ROOT,
    Rank,
    read_u32,
    write_json_output,
)
from extract_quests import (
    ITEM_NAMES,
    PreviewItem,
    Quest,
    QuestGoal,
    QuestReward,
    QuestText,
)


@dataclass(slots=True)
class GatheringItemDrop:
    percentage: int
    item_id: int
    item_name: str

    _STRUCT: ClassVar[struct.Struct] = struct.Struct("<2H")
    # remap armor spheres like erupe
    _ARMOR_SPHERES_ID_MAP: ClassVar[dict[int, int]] = {
        0x3301: 0xD7,  # armor sphere -> stone
        0x3302: 0xD8,  # armor sphere+ -> iron ore
        0x3303: 0xD7,  # adv armor sphere -> stone
        0x3304: 0xDB,  # hard armor sphere -> dragonite ore
        0x3305: 0xD9,  # heaven armor sphere -> earth crystal
        0x3306: 0xDB,  # true armor sphere -> dragonite ore
    }

    @classmethod
    def unpack_from(cls, raw: bytes, offset: int) -> "GatheringItemDrop":
        unpacked = cls._STRUCT.unpack_from(raw, offset)
        item_id = cls._ARMOR_SPHERES_ID_MAP.get(unpacked[1], unpacked[1])
        return cls(
            percentage=unpacked[0],
            item_id=item_id,
            item_name=ITEM_NAMES.get(item_id, "Nothing"),
        )

    @classmethod
    def size(cls) -> int:
        return cls._STRUCT.size


@dataclass(slots=True)
class GatheringPoint:
    x_pos: float
    y_pos: float
    z_pos: float
    range: int
    table_offset: int
    drops: list[GatheringItemDrop]
    max_count: int
    min_count: int

    _STRUCT: ClassVar[struct.Struct] = struct.Struct("<4f4H")

    @staticmethod
    def _extract_drops(raw: bytes, table_id: int) -> list[GatheringItemDrop]:
        offset = read_u32(raw, 0x38) + 4 * table_id
        drops_pointer = read_u32(raw, offset)
        drops = []
        while True:
            item_drop = GatheringItemDrop.unpack_from(raw, drops_pointer)
            if item_drop.percentage == 0xFFFF:
                break
            if item_drop.percentage != 0:
                drops.append(item_drop)
            drops_pointer += GatheringItemDrop.size()
        return drops

    @classmethod
    def unpack_from(cls, raw: bytes, offset: int) -> "GatheringPoint":
        unpacked = cls._STRUCT.unpack_from(raw, offset)
        table_id = unpacked[4]
        return cls(
            x_pos=unpacked[0],
            y_pos=unpacked[1],
            z_pos=unpacked[2],
            range=unpacked[3],
            table_offset=table_id,
            drops=cls._extract_drops(raw, table_id),
            max_count=unpacked[5],
            min_count=unpacked[7],
        )

    @classmethod
    def size(cls) -> int:
        return cls._STRUCT.size


class GatheringArea(TypedDict):
    area: int
    gps: list[GatheringPoint]


class GatheringTimeSlots(TypedDict):
    day: "GatheringSeasonSlots"
    night: "GatheringSeasonSlots"


class GatheringSeasonSlots(TypedDict):
    spring: list[GatheringArea]
    summer: list[GatheringArea]
    winter: list[GatheringArea]


@dataclass(slots=True)
class MapGatheringPoints:
    id: str
    ranks: dict[Rank, GatheringTimeSlots] = field(default_factory=dict)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract gathering point data from quest files to JSON"
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=REPO_ROOT / "site" / "src" / "data" / "generated" / "quests.json",
        help="Path to generated quests JSON.",
    )
    parser.add_argument(
        "--quest-files-dir",
        type=Path,
        default=DEFAULT_DATA_PATHS["quests"],
        help="Directory containing the quest files.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "site" / "src" / "data" / "generated" / "gathering.json",
        help="Output gathering JSON path.",
    )
    return parser.parse_args()


def load_quests(path: Path) -> list[Quest]:
    raw_quests: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
    quests: list[Quest] = []
    for quest in raw_quests:
        quests.append(
            Quest(
                max_players=quest["max_players"],
                quest_fee=quest["quest_fee"],
                zenny_reward=quest["zenny_reward"],
                zenny_ko=quest["zenny_ko"],
                zenny_sub_a=quest["zenny_sub_a"],
                zenny_sub_b=quest["zenny_sub_b"],
                quest_time=quest["quest_time"],
                map_id=quest["map_id"],
                map=quest["map"],
                restriction_flags=quest["restriction_flags"],
                id=quest["id"],
                main_goal=cast(QuestGoal, quest["main_goal"]),
                subA_goal=cast(QuestGoal, quest["subA_goal"]),
                subB_goal=cast(QuestGoal, quest["subB_goal"]),
                join_min_rank=quest["join_min_rank"],
                post_min_rank=quest["post_min_rank"],
                quest_text=QuestText(**cast(dict[str, Any], quest["quest_text"])),
                rank=cast(Rank, quest["rank"]),
                reward_boxes=cast(dict[str, list[QuestReward]], quest["reward_boxes"]),
                reward_variant=quest["reward_variant"],
                preview_items=cast(list[PreviewItem], quest["preview_items"]),
            )
        )
    return quests


def _extract_gathering_points_per_area(
    raw: bytes,
    offset: int,
    area: int,
) -> GatheringArea:
    gps = []
    while True:
        gp = GatheringPoint.unpack_from(raw, offset)
        if gp.x_pos == -1:
            break
        gps.append(gp)
        offset += GatheringPoint.size()
    return GatheringArea(area=area, gps=gps)


def _extract_areas_from_quest_file(quest_raw: bytes) -> list[GatheringArea]:
    base_pointer = read_u32(quest_raw, 0x28)
    if base_pointer > len(quest_raw):
        return []
    area_count = struct.unpack_from("<B", quest_raw, 0x7C)[0]
    areas: list[GatheringArea] = []
    for i in range(area_count):
        current_pointer = read_u32(quest_raw, base_pointer + i * 4)
        if current_pointer != 0:
            areas.append(
                _extract_gathering_points_per_area(quest_raw, current_pointer, i)
            )
    return [area for area in areas if any(gp.drops for gp in area["gps"])]


def _extract_seasons_from_quest_file(
    quest_files_dir: Path, quest_id: int, day_or_night: str
) -> GatheringSeasonSlots:
    spring_areas = _extract_areas_from_quest_file(
        (quest_files_dir / f"{quest_id:05}{day_or_night}0.bin").read_bytes()
    )
    summer_areas = _extract_areas_from_quest_file(
        (quest_files_dir / f"{quest_id:05}{day_or_night}1.bin").read_bytes()
    )
    winter_areas = _extract_areas_from_quest_file(
        (quest_files_dir / f"{quest_id:05}{day_or_night}2.bin").read_bytes()
    )
    return GatheringSeasonSlots(
        spring=spring_areas,
        summer=summer_areas,
        winter=winter_areas,
    )


def _has_any_gathering_areas(slots: GatheringTimeSlots) -> bool:
    return any(
        (
            slots["day"]["spring"],
            slots["day"]["summer"],
            slots["day"]["winter"],
            slots["night"]["spring"],
            slots["night"]["summer"],
            slots["night"]["winter"],
        )
    )


def extract_gathering_tables(
    quest_files_dir: Path, quests: list[Quest]
) -> list[MapGatheringPoints]:
    by_map: dict[str, MapGatheringPoints] = {}
    for quest in quests:
        day_slots = _extract_seasons_from_quest_file(quest_files_dir, quest.id, "d")
        night_slots = _extract_seasons_from_quest_file(quest_files_dir, quest.id, "n")
        time_slots = GatheringTimeSlots(day=day_slots, night=night_slots)

        if not _has_any_gathering_areas(time_slots):
            continue

        if quest.map not in by_map:
            by_map[quest.map] = MapGatheringPoints(id=quest.map)

        by_map[quest.map].ranks[quest.rank] = time_slots

    filtered: list[MapGatheringPoints] = []
    for gathering_points in by_map.values():
        gathering_points.ranks = {
            rank: slots
            for rank, slots in gathering_points.ranks.items()
            if _has_any_gathering_areas(slots)
        }
        if gathering_points.ranks:
            filtered.append(gathering_points)

    return filtered


def _one_quest_per_map_and_rank(quests: list[Quest]) -> list[Quest]:
    seen: dict[tuple[str, Rank], Quest] = {}
    for quest in quests:
        key = (quest.map, quest.rank)
        if (
            key not in seen
            and quest.rank != "gr"  # ignore grank because gr drops work differently
            # training quests have weird drops
            and "Training" not in quest.quest_text.title
            and "Note" not in quest.quest_text.title
            and quest.map != "New Great Arena"
        ):
            if (
                quest.map != "Volcano"
                or "Ruler of the Fiery Sea"
                in quest.quest_text.title  # lr volcano quest with all areas
                or "The Red Magma Wyvern"
                in quest.quest_text.title  # hr volcano quest with all areas
                or "Lavasioth of the Volcano"
                in quest.quest_text.title  # er volcano quest with all areas
            ):
                seen[key] = quest

    return list(seen.values())


def main() -> None:
    args = parse_args()
    quests = load_quests(args.input)
    gathering_quests = _one_quest_per_map_and_rank(quests)
    gathering_points = extract_gathering_tables(args.quest_files_dir, gathering_quests)
    write_json_output(args.output, gathering_points)


if __name__ == "__main__":
    main()
