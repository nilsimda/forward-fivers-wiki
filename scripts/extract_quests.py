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
    write_json_output,
)

HIDDEN_ITEM_IDS = load_wiki_hidden_item_ids(DEFAULT_DATA_PATHS["hidden_item_ids"])
ITEM_NAMES = load_item_names(DEFAULT_DATA_PATHS["item_names"])

MAP_ID_NAMES: dict[int, str] = {
    1: "Siege Fortress Day",
    2: "Forest and Hills Day",
    3: "Desert Day",
    4: "Swamp Day",
    5: "Volcano Day",
    6: "Jungle Day",
    7: "Castle Schrade",
    8: "Crimson Battleground",
    9: "Arena with Ledge Day",
    10: "Arena with Pillar Day",
    11: "Snowy Mountains Day",
    12: "Town Siege Day",
    13: "Tower 1",
    14: "Tower 2",
    15: "Tower 3",
    16: "Forest and Hills Night",
    17: "Desert Night",
    18: "Swamp Night",
    19: "Volcano Night",
    20: "Jungle Night",
    21: "Snowy Mountains Night",
    22: "Town Siege night",
    23: "Siege Fortress Night",
    24: "Arena with Ledge Night",
    25: "Arena with Pillar Night",
    26: "Great Forest Day",
    27: "Great Forest Night",
    28: "Volcano 2 Day",
    29: "Volcano 2 Night",
    30: "Jungle Dream",
    31: "Canyon Day",
    32: "Canyon Night",
    35: "Battlefield Day",
    44: "Top of Great Forest",
    45: "Caravan Balloon Day",
    46: "Caravan Balloon Night",
    47: "Solitude Isle 1",
    48: "Solitude Isle 2",
    49: "Solitude Isle 3",
    50: "Highlands Day",
    51: "Highlands Night",
    52: "Tower with Nesthole",
    53: "Arena with Moat Day",
    54: "Arena with Moat Night",
    55: "Fortress Day",
    56: "Fortress Night",
    57: "Tidal Island Day",
    58: "Tidal Island Night",
    60: "Polar Sea Day",
    61: "Polar Sea Night",
    62: "World's End",
    63: "Large Airship",
    64: "Flower Field Day",
    65: "Flower Field Night",
    66: "Deep Crater",
    67: "Bamboo Forest Day",
    68: "Bamboo Forest Night",
    69: "Battlefield 2 Day",
    70: "Unimplemented map",
    71: "1st Dist Tower 1",
    72: "1st Dist Tower 2",
    73: "2nd Dist Tower 1",
    74: "2nd Dist Tower 2",
    75: "Urgent Tower",
    76: "3rd Dist Tower",
    77: "3rd Dist Tower 2?",
    78: "4th Dist Tower",
    79: "White Lake Day",
    80: "White Lake Night",
    81: "Solitude Depths Slay 1",
    82: "Solitude Depths Slay 2",
    83: "Solitude Depths Slay 3",
    84: "Solitude Depths Slay 4",
    85: "Solitude Depths Slay 5",
    86: "Solitude Depths Support 1",
    87: "Solitude Depths Support 2",
    88: "Solitude Depths Support 3",
    89: "Solitude Depths Support 4",
    90: "Solitude Depths Support 5",
    91: "Cloud Viewing Fortress",
    92: "Painted Falls Day",
    93: "Painted Falls Night",
    94: "Sanctuary",
    95: "Hunter's Road",
    96: "Sacred Pinnacle",
    97: "Historic Site",
}

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

    _STRUCT: ClassVar[struct.Struct] = struct.Struct("<3H")

    @classmethod
    def unpack_from(cls, raw: bytes, offset: int) -> "QuestReward":
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
    def unpack_from(cls, raw: bytes, offset: int) -> "QuestRewardBox":
        unpacked = cls._STRUCT.unpack_from(raw, offset)
        table_offset = unpacked[3]
        rewards = []
        while True:
            reward = QuestReward.unpack_from(raw, table_offset)
            if reward.percentage == 0xFFFF:
                break
            if reward.item_id not in HIDDEN_ITEM_IDS:
                rewards.append(reward)
            table_offset += QuestReward.size()

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
    rank: Rank | None
    reward_boxes: dict[int, list[QuestReward]]

    _STRUCT: ClassVar[struct.Struct] = struct.Struct("<IIHBB8IHHIHHIHHIHH4H")

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
    def _extract_quest_file(path: Path) -> tuple[int, list[QuestRewardBox]]:
        raw = path.read_bytes()
        rewards_pointer = read_u32(raw, HEADER_POINTERS["quest_rewards"])
        difficulty = read_u16(raw, 0x48)
        if rewards_pointer >= len(raw):
            return difficulty, []
        reward_boxes = []
        while True:
            reward_box = QuestRewardBox.unpack_from(raw, rewards_pointer)
            if reward_box.table_id == 0xFF and reward_box.sentinel == 0xFF:
                break
            reward_boxes.append(reward_box)
            rewards_pointer += QuestRewardBox.size()

        return difficulty, reward_boxes

    _RANK_ORDER: ClassVar[dict[Rank, int]] = {"lr": 0, "hr": 1, "er": 2, "gr": 3}

    @staticmethod
    def _get_quest_rank(difficulty: int, post_min_hr: int) -> Rank:
        difficulty_rank = Quest._rank_from_difficulty(difficulty)
        post_min_hr_rank = Quest._rank_from_min_hr(post_min_hr)
        return max(difficulty_rank, post_min_hr_rank, key=Quest._RANK_ORDER.__getitem__)

    @classmethod
    def unpack_from(cls, raw: bytes, offset: int, quest_files_dir: Path) -> "Quest":
        unpacked = cls._STRUCT.unpack_from(raw, offset)
        quest_id = unpacked[14]
        difficulty, reward_boxes = cls._extract_quest_file(
            quest_files_dir / f"{quest_id:05}d0.bin"
        )
        post_min_rank = unpacked[27]

        reward_boxes_by_id = {box.table_id: box.rewards for box in reward_boxes}

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
            map=MAP_ID_NAMES[unpacked[11]],
            restriction_flags=unpacked[13],
            id=quest_id,
            main_goal=main_goal,
            subA_goal=subA_goal,
            subB_goal=subB_goal,
            join_min_rank=unpacked[25],
            post_min_rank=post_min_rank,
            quest_text=quest_text,
            rank=rank,
            reward_boxes=reward_boxes_by_id,
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
        cls, raw: bytes, offset: int, quest_files_dir: Path
    ) -> "QuestTable":
        unpacked = cls._STRUCT.unpack_from(raw, offset)
        quest_table = cls(quest_count=unpacked[1], pointer_base=unpacked[2])
        for quest_index in range(quest_table.quest_count):
            quest_pointer = read_u32(raw, quest_table.pointer_base + quest_index * 4)
            if not quest_pointer == 0:
                quest = Quest.unpack_from(raw, quest_pointer, quest_files_dir)
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
        "--output",
        type=Path,
        default=REPO_ROOT / "site" / "src" / "data" / "generated" / "quests.json",
        help="Output frontend-ready quests JSON path.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    mhfinf_raw = args.input.read_bytes()
    quest_files_dir = args.quest_files_dir

    qt_offset = read_u32(mhfinf_raw, HEADER_POINTERS["quests"])
    counts_offset = read_u32(mhfinf_raw, HEADER_POINTERS["mhfinf_counts"])
    qt_count = read_u16(mhfinf_raw, counts_offset)

    result: list[Quest] = []
    for _ in range(qt_count):
        qt = QuestTable.unpack_from(mhfinf_raw, qt_offset, quest_files_dir)
        result += qt.quests
        qt_offset += QuestTable.size()

    write_json_output(args.output, result)


if __name__ == "__main__":
    main()
