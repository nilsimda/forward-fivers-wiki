#! /usr/bin/env python3
import argparse
import struct
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import ClassVar, Literal, TypedDict

from extract_common import (
    DEFAULT_DATA_PATHS,
    HEADER_POINTERS,
    REPO_ROOT,
    Rank,
    decode_c_string,
    load_item_names,
    load_wiki_hidden_item_ids,
    read_u16,
    read_u32,
    reward_box_label,
    write_json_output,
)

HIDDEN_ITEM_IDS = load_wiki_hidden_item_ids(DEFAULT_DATA_PATHS["hidden_item_ids"])
ITEM_NAMES = load_item_names()

GoalTargetKind = Literal[
    "Hunt",
    "Capture",
    "Slay",
    "Damage",
    "Slay or Damage",
    "Slay All",
    "Slay Total",
    "Deliver",
    "Break Part",
    "Deliver Flag",
    "Esoteric Action",
]


class QuestObjType(IntEnum):
    NONE = 0x00000000
    HUNT = 0x00000001
    CAPTURE = 0x00000101
    SLAY = 0x00000201
    DAMAGE = 0x00008004
    SLAY_OR_DAMAGE = 0x00018004
    SLAY_ALL = 0x00040000
    SLAY_TOTAL = 0x00020000
    DELIVER = 0x00000002
    BREAK_PART = 0x00004004
    DELIVER_FLAG = 0x00001002
    ESOTERIC_ACTION = 0x00000010


GOAL_TARGET_KIND: dict[int, GoalTargetKind | None] = {
    QuestObjType.NONE: None,
    QuestObjType.HUNT: "Hunt",
    QuestObjType.CAPTURE: "Capture",
    QuestObjType.SLAY: "Slay",
    QuestObjType.DAMAGE: "Damage",
    QuestObjType.SLAY_OR_DAMAGE: "Slay or Damage",
    QuestObjType.SLAY_ALL: "Slay All",
    QuestObjType.SLAY_TOTAL: "Slay Total",
    QuestObjType.DELIVER: "Deliver",
    QuestObjType.BREAK_PART: "Break Part",
    QuestObjType.DELIVER_FLAG: "Deliver Flag",
    QuestObjType.ESOTERIC_ACTION: "Esoteric Action",
}


@dataclass(slots=True)
class QuestReward:
    percentage: int
    item_id: int
    item_name: str
    quantity: int
    guaranteed: bool

    _STRUCT: ClassVar[struct.Struct] = struct.Struct("<3H")

    @staticmethod
    def _is_guaranteed(reward_variant: int, box_id: int, index_in_table: int) -> bool:
        if reward_variant == 4:
            return False
        if reward_variant in (2, 3):
            return True
        if reward_variant == 0:
            return index_in_table == 0 and box_id in (0, 1)
        if reward_variant == 1:
            return index_in_table == 0 and box_id in (0, 1, 2, 3)
        return False

    @classmethod
    def unpack_from(
        cls,
        raw: bytes,
        offset: int,
        reward_variant: int,
        box_id: int,
        index_in_table: int,
    ) -> "QuestReward":
        unpacked = cls._STRUCT.unpack_from(raw, offset)
        return cls(
            percentage=unpacked[0],
            item_id=unpacked[1],
            item_name=ITEM_NAMES.get(unpacked[1], "unkown"),
            quantity=unpacked[2],
            guaranteed=cls._is_guaranteed(reward_variant, box_id, index_in_table),
        )

    @classmethod
    def size(cls) -> int:
        return cls._STRUCT.size


@dataclass(slots=True)
class QuestText:
    title: str
    main: str
    sub_a: str
    sub_b: str
    success_cond: str
    fail_cond: str
    contractor: str
    description: str

    _STRUCT: ClassVar[struct.Struct] = struct.Struct("<8I")

    @classmethod
    def unpack_from(cls, raw: bytes, offset: int) -> "QuestText":
        pointers = cls._STRUCT.unpack_from(raw, offset)
        strings = [decode_c_string(raw, p) for p in pointers]
        return cls(*strings)


@dataclass(slots=True)
class QuestRewardBox:
    table_id: int
    sentinel: int
    table_offset: int
    rewards: list[QuestReward] = field(default_factory=list)

    _STRUCT: ClassVar[struct.Struct] = struct.Struct("<BBHI")

    @classmethod
    def unpack_from(
        cls, raw: bytes, offset: int, reward_variant: int
    ) -> "QuestRewardBox":
        unpacked = cls._STRUCT.unpack_from(raw, offset)
        table_offset = unpacked[3]
        rewards = []
        index_in_table = 0
        while True:
            reward = QuestReward.unpack_from(
                raw, table_offset, reward_variant, unpacked[0], index_in_table
            )
            if reward.percentage == 0xFFFF:
                break
            if reward.item_id not in HIDDEN_ITEM_IDS:
                rewards.append(reward)
            table_offset += QuestReward.size()
            index_in_table += 1

        return cls(
            table_id=unpacked[0],
            sentinel=unpacked[1],
            table_offset=unpacked[3],
            rewards=rewards,
        )

    @classmethod
    def size(cls) -> int:
        return cls._STRUCT.size


class QuestGoal(TypedDict):
    target_kind: GoalTargetKind | None
    target: int | None
    count: int | None


class PreviewItem(TypedDict):
    item_id: int
    item_name: str


@dataclass(slots=True)
class Quest:
    max_players: int
    quest_fee: int
    zenny_reward: int
    zenny_ko: int
    zenny_sub_a: int
    zenny_sub_b: int
    quest_time: int
    map_id: int
    map: str
    restriction_flags: int
    id: int
    main_goal: QuestGoal
    subA_goal: QuestGoal
    subB_goal: QuestGoal
    join_min_rank: int
    post_min_rank: int
    quest_text: QuestText
    rank: Rank
    reward_boxes: dict[str, list[QuestReward]]
    reward_variant: int
    preview_items: list[PreviewItem]

    _STRUCT: ClassVar[struct.Struct] = struct.Struct("<IIHBB8IHHIHHIHHIHH4H")
    _RANK_ORDER: ClassVar[dict[Rank, int]] = {"lr": 0, "hr": 1, "er": 2, "gr": 3}

    @staticmethod
    def _rank_from_difficulty(difficulty: int) -> Rank:
        if 1 <= difficulty <= 11:
            return "lr"
        elif difficulty <= 20:
            return "hr"
        elif difficulty < 53:
            return "er"
        else:
            return "gr"

    @staticmethod
    def _rank_from_min_hr(min_hr: int) -> Rank:
        if min_hr <= 30:
            return "lr"
        elif min_hr <= 99:
            return "hr"
        else:
            return "er"

    @staticmethod
    def _extract_quest_file(
        path: Path,
    ) -> tuple[int, list[QuestRewardBox], int, list[PreviewItem]]:
        raw = path.read_bytes()
        rewards_pointer = read_u32(raw, HEADER_POINTERS["quest_rewards"])
        difficulty = read_u16(raw, 0x48)
        reward_variant = raw[0x150]
        preview_items: list[PreviewItem] = []
        for off in (0x170, 0x172, 0x174):
            item_id = read_u16(raw, off)
            if item_id != 0:
                preview_items.append(
                    PreviewItem(
                        item_id=item_id, item_name=ITEM_NAMES.get(item_id, "unknown")
                    )
                )

        if rewards_pointer >= len(raw):
            return difficulty, [], reward_variant, preview_items
        reward_boxes = []
        while True:
            reward_box = QuestRewardBox.unpack_from(
                raw, rewards_pointer, reward_variant
            )
            if reward_box.table_id == 0xFF and reward_box.sentinel == 0xFF:
                break
            reward_boxes.append(reward_box)
            rewards_pointer += QuestRewardBox.size()

        return difficulty, reward_boxes, reward_variant, preview_items

    @staticmethod
    def _get_quest_rank(difficulty: int, post_min_hr: int) -> Rank:
        difficulty_rank = Quest._rank_from_difficulty(difficulty)
        post_min_hr_rank = Quest._rank_from_min_hr(post_min_hr)
        return max(difficulty_rank, post_min_hr_rank, key=Quest._RANK_ORDER.__getitem__)

    @classmethod
    def unpack_from(
        cls, raw: bytes, offset: int, quest_files_dir: Path, map_names: dict[int, str]
    ) -> "Quest":
        unpacked = cls._STRUCT.unpack_from(raw, offset)
        quest_id = unpacked[14]
        difficulty, reward_boxes, reward_variant, preview_items = (
            cls._extract_quest_file(quest_files_dir / f"{quest_id:05}d0.bin")
        )
        post_min_rank = unpacked[27]

        reward_boxes_by_label = {
            reward_box_label(box.table_id): box.rewards for box in reward_boxes
        }

        quest_text = QuestText.unpack_from(raw, unpacked[12])

        main_goal = QuestGoal(
            target_kind=GOAL_TARGET_KIND[unpacked[15]],
            target=unpacked[16],
            count=unpacked[17],
        )

        subA_goal = QuestGoal(
            target_kind=GOAL_TARGET_KIND[unpacked[18]],
            target=unpacked[19],
            count=unpacked[20],
        )

        subB_goal = QuestGoal(
            target_kind=GOAL_TARGET_KIND[unpacked[21]],
            target=unpacked[22],
            count=unpacked[23],
        )

        rank = cls._get_quest_rank(difficulty, post_min_rank)

        quest = cls(
            max_players=4 if unpacked[4] == 0 else unpacked[4],
            quest_fee=unpacked[5],
            zenny_reward=unpacked[6],
            zenny_ko=unpacked[7],
            zenny_sub_a=unpacked[8],
            zenny_sub_b=unpacked[9],
            quest_time=unpacked[10],
            map_id=unpacked[11],
            map=map_names[unpacked[11]],
            restriction_flags=unpacked[13],
            id=quest_id,
            main_goal=main_goal,
            subA_goal=subA_goal,
            subB_goal=subB_goal,
            join_min_rank=unpacked[25],
            post_min_rank=post_min_rank,
            quest_text=quest_text,
            rank=rank,
            reward_boxes=reward_boxes_by_label,
            reward_variant=reward_variant,
            preview_items=preview_items,
        )
        return quest


@dataclass(slots=True)
class QuestTable:
    quest_count: int
    pointer_base: int
    quests: list[Quest] = field(default_factory=list)

    _STRUCT: ClassVar[struct.Struct] = struct.Struct("<HHI")

    @classmethod
    def unpack_from(
        cls, raw: bytes, offset: int, quest_files_dir: Path, map_names: dict[int, str]
    ) -> "QuestTable":
        unpacked = cls._STRUCT.unpack_from(raw, offset)
        quest_table = cls(quest_count=unpacked[1], pointer_base=unpacked[2])
        for quest_index in range(quest_table.quest_count):
            quest_pointer = read_u32(raw, quest_table.pointer_base + quest_index * 4)
            if not quest_pointer == 0:
                quest = Quest.unpack_from(
                    raw, quest_pointer, quest_files_dir, map_names
                )
                quest_table.quests.append(quest)

        return quest_table

    @classmethod
    def size(cls) -> int:
        return cls._STRUCT.size


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract Quest Data from mhinf and quest files to JSON"
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_DATA_PATHS["mhfinf"],
        help="Path to mhfinf.raw.bin",
    )
    parser.add_argument(
        "--quest-files-dir",
        type=Path,
        default=DEFAULT_DATA_PATHS["quests"],
        help="Directory containing the quest files.",
    )
    parser.add_argument(
        "--event-quests-dir", type=Path, default=DEFAULT_DATA_PATHS["events"]
    )
    parser.add_argument(
        "--mhfpac",
        type=Path,
        default=DEFAULT_DATA_PATHS["mhfpac"],
        help="Path to mhfpac.raw.bin",
    )
    parser.add_argument(
        "--gathering-output",
        type=Path,
        default=REPO_ROOT / "site" / "src" / "data" / "generated" / "gathering.json",
        help="Output gps JSON path.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "site" / "src" / "data" / "generated" / "quests.json",
        help="Output frontend-ready quests JSON path.",
    )
    return parser.parse_args()


def _extract_map_names(mhfpac_raw: bytes) -> dict[int, str]:
    map_names_base = HEADER_POINTERS["map_names"]

    result: dict[int, str] = {}
    map_id = 1
    while True:
        map_name_pointer = read_u32(mhfpac_raw, map_names_base)
        if map_name_pointer == 0:
            break
        map_name = decode_c_string(mhfpac_raw, map_name_pointer)
        result[map_id] = map_name
        map_id += 1
        map_names_base += 4

    return result


def extract_server_side_quests(
    quest_files_dir: Path, map_names: dict[int, str]
) -> list[Quest]:
    result: list[Quest] = []
    for quest_file in sorted(quest_files_dir.rglob("*d0.bin")):
        quest_raw = quest_file.read_bytes()
        quest = Quest.unpack_from(quest_raw, 0xC0, quest_file.parent, map_names)
        result.append(quest)
    return result


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
        0x3304: 0xDB,  # hard armor sphere -> draonite ore
        0x3305: 0xD9,  # heaven armor sphere -> earth crystal
        0x3306: 0xDB,  # true armor sphere -> draonite ore
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
    def _extract_drops(raw: bytes, id: int) -> list[GatheringItemDrop]:
        offset = read_u32(raw, 0x38) + 4 * id
        drops_pointer = read_u32(raw, offset)
        drops = []
        while True:
            item_drop = GatheringItemDrop.unpack_from(raw, drops_pointer)
            if item_drop.percentage == 0xFFFF:
                break
            if not item_drop.percentage == 0:
                drops.append(item_drop)
            drops_pointer += GatheringItemDrop.size()
        return drops

    @classmethod
    def unpack_from(cls, raw: bytes, offset: int) -> "GatheringPoint":
        unpacked = cls._STRUCT.unpack_from(raw, offset)
        return cls(
            x_pos=unpacked[0],
            y_pos=unpacked[1],
            z_pos=unpacked[2],
            range=unpacked[3],
            table_offset=unpacked[4],
            drops=cls._extract_drops(raw, unpacked[4]),
            max_count=unpacked[5],
            min_count=unpacked[7],
        )

    @classmethod
    def size(cls) -> int:
        return cls._STRUCT.size


def _extract_gathering_points_per_area(
    raw: bytes, offset: int, area: int
) -> GatheringArea:
    gps = []
    while True:
        gp = GatheringPoint.unpack_from(raw, offset)
        if gp.x_pos == -1:
            break
        gps.append(gp)
        offset += GatheringPoint.size()
    return GatheringArea(area=area, gps=gps)


class GatheringArea(TypedDict):
    area: int
    gps: list[GatheringPoint]


class GatheringTimeSlots(TypedDict):
    day: list[GatheringArea]
    night: list[GatheringArea]


@dataclass(slots=True)
class MapGatheringPoints:
    id: str
    ranks: dict[Rank, GatheringTimeSlots] = field(default_factory=dict)


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
    return [a for a in areas if any(gp.drops for gp in a["gps"])]


def extract_gathering_tables(
    quest_files_dir: Path, quests: list[Quest]
) -> list[MapGatheringPoints]:
    by_map: dict[str, MapGatheringPoints] = {}
    for quest in quests:
        day_raw = (quest_files_dir / f"{quest.id:05}d0.bin").read_bytes()
        night_raw = (quest_files_dir / f"{quest.id:05}n0.bin").read_bytes()
        day_areas = _extract_areas_from_quest_file(day_raw)
        night_areas = _extract_areas_from_quest_file(night_raw)

        if not day_areas and not night_areas:
            continue

        if quest.map not in by_map:
            by_map[quest.map] = MapGatheringPoints(id=quest.map)

        by_map[quest.map].ranks[quest.rank] = GatheringTimeSlots(
            day=day_areas, night=night_areas
        )

    filtered: list[MapGatheringPoints] = []
    for mgp in by_map.values():
        mgp.ranks = {
            rank: slots
            for rank, slots in mgp.ranks.items()
            if slots["day"] or slots["night"]
        }
        if mgp.ranks:
            filtered.append(mgp)

    return filtered


def _one_quest_per_map_and_rank(quests: list[Quest]) -> list[Quest]:
    seen: dict[tuple[str, Rank], Quest] = {}
    for quest in quests:
        key = (quest.map, quest.rank)
        if (
            key not in seen
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
                or quest.rank == "gr"
            ):
                seen[key] = quest

    return list(seen.values())


def main() -> None:
    args = parse_args()

    mhfinf_raw = args.input.read_bytes()
    quest_files_dir = args.quest_files_dir
    event_quests_dir = args.event_quests_dir
    mhfpac_raw = args.mhfpac.read_bytes()

    map_names = _extract_map_names(mhfpac_raw)

    qt_offset = read_u32(mhfinf_raw, HEADER_POINTERS["quests"])
    counts_offset = read_u32(mhfinf_raw, HEADER_POINTERS["mhfinf_counts"])
    qt_count = read_u16(mhfinf_raw, counts_offset)

    result: list[Quest] = []
    for _ in range(qt_count):
        qt = QuestTable.unpack_from(mhfinf_raw, qt_offset, quest_files_dir, map_names)
        result += qt.quests
        qt_offset += QuestTable.size()

    result += extract_server_side_quests(event_quests_dir, map_names)

    gathering_quests = _one_quest_per_map_and_rank(result)
    gps = extract_gathering_tables(quest_files_dir, gathering_quests)

    write_json_output(args.output, result)
    write_json_output(args.gathering_output, gps)


if __name__ == "__main__":
    main()
