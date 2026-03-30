#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import struct
import subprocess
import tempfile
from pathlib import Path
from typing import Literal, NotRequired, TypedDict

from extract_common import (
    REPO_ROOT,
    decode_c_string,
    load_item_names,
    load_monster_names,
    read_pointer_array,
    read_u16,
    read_u32,
    write_json_output,
)

INPUT_DEFAULT = REPO_ROOT / "g1_data" / "mhfinf.raw.bin"
OUTPUT_DEFAULT = (
    REPO_ROOT / "site" / "src" / "data" / "generated" / "quest-rewards.json"
)
QUEST_FILES_DIR_DEFAULT = REPO_ROOT / "g1_data" / "quests"
ITEMS_PATH_DEFAULT = REPO_ROOT / "site" / "src" / "data" / "generated" / "items.json"
MONSTER_NAMES_PATH_DEFAULT = REPO_ROOT / "g1_data" / "monster_names.json"

MHF_INF_MAGIC = 0x1A666E69
MHF_INF_VERSION = 6
MHF_INF_HEADER_SIZE = 0x4C

HEADER_FMT = "<10I12s6I"
HEADER_SIZE = struct.calcsize(HEADER_FMT)
QUEST_TABLE_COUNT_BLOCK_SIZE = 2
QUEST_TABLE_ENTRY_FMT = "<HHI"
QUEST_TABLE_ENTRY_SIZE = struct.calcsize(QUEST_TABLE_ENTRY_FMT)
QUEST_SIZE = 0xA0
QUEST_TEXT_SIZE = 0x20

GOAL_TYPE_NONE = 0x00000000
GOAL_TYPE_HUNT = 0x00000001
GOAL_TYPE_CAPTURE = 0x00000101
GOAL_TYPE_SLAY = 0x00000201
GOAL_TYPE_DAMAGE = 0x00008004
GOAL_TYPE_SLAY_OR_DAMAGE = 0x00018004
GOAL_TYPE_SLAY_ALL = 0x00040000
GOAL_TYPE_SLAY_TOTAL = 0x00020000
GOAL_TYPE_DELIVER = 0x00000002
GOAL_TYPE_BREAK_PART = 0x00004004
GOAL_TYPE_DELIVER_FLAG = 0x00001002
GOAL_TYPE_ESOTERIC_ACTION = 0x00000010

REWARD_VARIANT_CODES = ("d0", "d1", "d2", "n0", "n1", "n2")
GoalTargetKind = Literal["none", "monster", "item", "unknown"]

GOAL_TYPE_LABELS: dict[int, str] = {
    GOAL_TYPE_NONE: "None",
    GOAL_TYPE_HUNT: "Hunt",
    GOAL_TYPE_CAPTURE: "Capture",
    GOAL_TYPE_SLAY: "Slay",
    GOAL_TYPE_DAMAGE: "Damage",
    GOAL_TYPE_SLAY_OR_DAMAGE: "SlayOrDamage",
    GOAL_TYPE_SLAY_ALL: "SlayAll",
    GOAL_TYPE_SLAY_TOTAL: "SlayTotal",
    GOAL_TYPE_DELIVER: "Deliver",
    GOAL_TYPE_BREAK_PART: "BreakPart",
    GOAL_TYPE_DELIVER_FLAG: "DeliverFlag",
    GOAL_TYPE_ESOTERIC_ACTION: "Esoteric_Action",
}

GOAL_TYPES_MONSTER_TARGET = frozenset(
    {
        GOAL_TYPE_HUNT,
        GOAL_TYPE_CAPTURE,
        GOAL_TYPE_SLAY,
        GOAL_TYPE_DAMAGE,
        GOAL_TYPE_BREAK_PART,
    }
)


class QuestText(TypedDict):
    title: str
    text_main: str
    text_sub_a: str
    text_sub_b: str
    success_cond: str
    fail_cond: str
    contractor: str
    description: str


class QuestGoal(TypedDict):
    typeName: str
    targetKind: GoalTargetKind
    target: int | None
    targetLabel: str
    count: int | None
    part: int | None


class QuestRewardItem(TypedDict):
    percent_chance: int
    item_id: int
    item_count: int


class QuestRewardBox(TypedDict):
    reward_box_id: int
    rewards: list[QuestRewardItem]


class QuestRewardEntry(TypedDict):
    rewardBoxId: int
    rewardBoxNumber: int
    itemId: int
    itemName: str
    percentChance: int
    itemCount: int


class QuestRow(TypedDict):
    questId: int
    slug: str
    title: str
    rank: str
    questRank: int
    joinMinRank: int
    postMinRank: int
    maxPlayers: int
    questFee: int
    zennyReward: int
    zennyKO: int
    zennySubA: int
    zennySubB: int
    questTimeFrames: int
    mapID: int
    contractor: str
    description: str
    mainObjective: str
    subObjectiveA: str
    subObjectiveB: str
    successCondition: str
    failCondition: str
    mainGoal: QuestGoal
    subAGoal: QuestGoal
    subBGoal: QuestGoal
    questRewards: list[QuestRewardEntry]
    questFileDifficulty: NotRequired[int]
    questFileRequirement: NotRequired[int]


class QuestFileData(TypedDict):
    rewards: list[QuestRewardBox]
    difficulty: int
    requirement: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract mhfinf quests directly into quest-rewards JSON."
    )
    parser.add_argument(
        "--input", type=Path, default=INPUT_DEFAULT, help="Path to mhfinf.raw.bin"
    )
    parser.add_argument(
        "--output", type=Path, default=OUTPUT_DEFAULT, help="Output JSON path"
    )
    parser.add_argument(
        "--quest-files-dir",
        type=Path,
        default=QUEST_FILES_DIR_DEFAULT,
        help="Directory containing quest files (e.g. 00001d0.bin)",
    )
    parser.add_argument(
        "--items",
        type=Path,
        default=ITEMS_PATH_DEFAULT,
        help="Path to generated items.json",
    )
    parser.add_argument(
        "--monster-names",
        type=Path,
        default=MONSTER_NAMES_PATH_DEFAULT,
        help="Path to g1_data/monster_names.json",
    )
    parser.add_argument(
        "--skip-quest-file-rewards",
        action="store_true",
        help="Skip extracting reward rows from quest files in g1_data/quests",
    )
    return parser.parse_args()


def ensure_slice_in_bounds(raw: bytes, offset: int, size: int, label: str) -> None:
    if offset < 0 or offset + size > len(raw):
        raise ValueError(
            f"{label}: [0x{offset:08X}, 0x{offset + size:08X}) out of bounds for file size 0x{len(raw):08X}"
        )


def read_u8(raw: bytes, offset: int, label: str) -> int:
    if offset < 0 or offset >= len(raw):
        raise ValueError(f"{label}: offset 0x{offset:08X} out of bounds")
    return raw[offset]


def parse_header(raw: bytes) -> tuple[int, int]:
    ensure_slice_in_bounds(raw, 0, HEADER_SIZE, "MhfinfHeader")
    unpacked = struct.unpack_from(HEADER_FMT, raw, 0)
    magic = unpacked[0]
    version = unpacked[1]
    header_size = unpacked[3]
    if magic != MHF_INF_MAGIC:
        raise ValueError(
            f"Invalid mhfinf magic: expected 0x{MHF_INF_MAGIC:08X}, got 0x{magic:08X}"
        )
    if version != MHF_INF_VERSION:
        raise ValueError(
            f"Invalid mhfinf version: expected {MHF_INF_VERSION}, got {version}"
        )
    if header_size != MHF_INF_HEADER_SIZE:
        raise ValueError(
            f"Invalid mhfinf header_size: expected 0x{MHF_INF_HEADER_SIZE:08X}, got 0x{header_size:08X}"
        )
    return unpacked[4], unpacked[5]


def goal_type_name(goal_type: int) -> str:
    return GOAL_TYPE_LABELS.get(goal_type, f"Unknown_0x{goal_type:08X}")


def goal_target_kind(goal_type: int) -> GoalTargetKind:
    if goal_type == GOAL_TYPE_NONE:
        return "none"
    if goal_type in GOAL_TYPES_MONSTER_TARGET:
        return "monster"
    if goal_type == GOAL_TYPE_DELIVER:
        return "item"
    return "unknown"


def parse_goal(
    raw: bytes,
    goal_offset: int,
    label: str,
    *,
    item_names_by_id: dict[int, str],
    monster_names_by_id: dict[int, str],
) -> QuestGoal:
    ensure_slice_in_bounds(raw, goal_offset, 8, label)
    goal_type = read_u32(raw, goal_offset, f"{label}.goal_type")
    target_raw = read_u16(raw, goal_offset + 4, f"{label}.goal_target_raw")
    value_raw = read_u16(raw, goal_offset + 6, f"{label}.goal_value_raw")

    target_kind = goal_target_kind(goal_type)
    target: int | None = None
    count: int | None = None
    part: int | None = None
    target_label = ""

    if goal_type != GOAL_TYPE_NONE:
        target = target_raw
        if goal_type == GOAL_TYPE_BREAK_PART:
            part = value_raw
        else:
            count = value_raw

    if target is not None:
        if target_kind == "item":
            target_label = item_names_by_id.get(target, f"Item {target}")
        elif target_kind == "monster":
            target_label = monster_names_by_id.get(target, f"Monster {target}")
        else:
            target_label = f"{target_kind or 'target'} {target}"

    return {
        "typeName": goal_type_name(goal_type),
        "targetKind": target_kind,
        "target": target,
        "targetLabel": target_label,
        "count": count,
        "part": part,
    }


def parse_text(raw: bytes, text_offset: int) -> QuestText:
    ensure_slice_in_bounds(raw, text_offset, QUEST_TEXT_SIZE, "QuestText")
    pointers = read_pointer_array(raw, text_offset, 8, "quest_text_pointer")
    return {
        "title": decode_c_string(raw, pointers[0]),
        "text_main": decode_c_string(raw, pointers[1]),
        "text_sub_a": decode_c_string(raw, pointers[2]),
        "text_sub_b": decode_c_string(raw, pointers[3]),
        "success_cond": decode_c_string(raw, pointers[4]),
        "fail_cond": decode_c_string(raw, pointers[5]),
        "contractor": decode_c_string(raw, pointers[6]),
        "description": decode_c_string(raw, pointers[7]),
    }


def reward_box_max_slots(reward_box_id: int) -> int:
    if reward_box_id in (0, 1):
        return 24
    if reward_box_id in (2, 3):
        return 4
    return 8


def parse_reward_boxes_from_quest_file(raw: bytes) -> list[QuestRewardBox]:
    reward_pointer = read_u32(raw, 0x0C, "quest_file.reward_pointer")
    _reward_flag = read_u8(raw, 0x150, "quest_file.reward_flag")
    boxes: list[QuestRewardBox] = []

    for box_index in range(8):
        header_offset = reward_pointer + box_index * 8
        ensure_slice_in_bounds(raw, header_offset, 8, f"reward_header[{box_index}]")
        if (
            read_u16(raw, header_offset, f"reward_header[{box_index}].sentinel")
            == 0xFFFF
        ):
            break

        reward_box_id = read_u8(raw, header_offset, f"reward_header[{box_index}].id")
        reward_box_addr = read_u32(
            raw, header_offset + 4, f"reward_header[{box_index}].addr"
        )
        max_slots = reward_box_max_slots(reward_box_id)
        rewards: list[QuestRewardItem] = []

        for item_index in range(max_slots):
            reward_offset = reward_box_addr + item_index * 6
            ensure_slice_in_bounds(
                raw, reward_offset, 6, f"reward_box[{box_index}].item[{item_index}]"
            )
            percent_chance = read_u16(
                raw,
                reward_offset,
                f"reward_box[{box_index}].item[{item_index}].percent_chance",
            )
            if percent_chance == 0xFFFF:
                break
            rewards.append(
                {
                    "percent_chance": percent_chance,
                    "item_id": read_u16(
                        raw,
                        reward_offset + 2,
                        f"reward_box[{box_index}].item[{item_index}].item_id",
                    ),
                    "item_count": read_u16(
                        raw,
                        reward_offset + 4,
                        f"reward_box[{box_index}].item[{item_index}].item_count",
                    ),
                }
            )
        boxes.append({"reward_box_id": reward_box_id, "rewards": rewards})
    return boxes


def map_quest_rank_from_difficulty(difficulty: int) -> str | None:
    if 1 <= difficulty <= 11:
        return "lr"
    if 12 <= difficulty <= 20:
        return "hr"
    if difficulty in (26, 31, 42):
        return "hr100"
    if difficulty >= 53:
        return "gr"
    return None


def load_unpacked_quest_file(path: Path, workspace: Path) -> bytes:
    raw = path.read_bytes()
    if not raw.startswith(b"JKR\x1a"):
        return raw

    output_prefix = workspace / "quest_variant_unpacked"
    output_file = workspace / "quest_variant_unpacked.bin"
    if output_file.exists():
        output_file.unlink()

    try:
        subprocess.run(
            ["rsfrontier-cli", "unpack", "-i", str(path), "-o", str(output_prefix)],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "rsfrontier-cli is required to unpack JKR quest files but was not found in PATH"
        ) from exc
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() if exc.stderr is not None else ""
        raise RuntimeError(
            f"rsfrontier-cli unpack failed for {path}: {stderr or 'unknown error'}"
        ) from exc

    if not output_file.exists():
        raise RuntimeError(
            f"Expected unpacked output file was not produced for {path}: {output_file}"
        )
    return output_file.read_bytes()


def extract_selected_quest_file_data(
    quest_id: int,
    quest_files_dir: Path,
    unpack_workspace: Path,
) -> QuestFileData | None:
    selected_path: Path | None = None
    selected_name = ""
    for variant_code in REWARD_VARIANT_CODES:
        source_name = f"{quest_id:05d}{variant_code}.bin"
        source_path = quest_files_dir / source_name
        if source_path.exists():
            selected_path = source_path
            selected_name = source_name
            break
    if selected_path is None:
        return None

    unpacked = load_unpacked_quest_file(selected_path, unpack_workspace)
    quest_file_id = read_u16(unpacked, 0xEE, "quest_file.questFileId")
    if quest_file_id != quest_id:
        raise ValueError(
            f"Quest variant {selected_name} has questFileId={quest_file_id}, expected {quest_id}"
        )
    return {
        "rewards": parse_reward_boxes_from_quest_file(unpacked),
        "difficulty": read_u16(unpacked, 0x48, "quest_file.difficulty"),
        "requirement": read_u16(unpacked, 0xEC, "quest_file.requirement"),
    }


def normalize_quest_rewards(
    reward_boxes: list[QuestRewardBox], item_names_by_id: dict[int, str]
) -> list[QuestRewardEntry]:
    rewards: list[QuestRewardEntry] = []
    for box_index, reward_box in enumerate(reward_boxes):
        reward_box_id = reward_box.get("reward_box_id", box_index)
        for reward in reward_box["rewards"]:
            item_id = reward["item_id"]
            rewards.append(
                {
                    "rewardBoxId": reward_box_id,
                    "rewardBoxNumber": 0,
                    "itemId": item_id,
                    "itemName": item_names_by_id.get(item_id, f"Item {item_id}"),
                    "percentChance": reward["percent_chance"],
                    "itemCount": reward["item_count"],
                }
            )
    rewards.sort(
        key=lambda row: (
            row["rewardBoxId"],
            row["itemId"],
            -row["percentChance"],
            -row["itemCount"],
        )
    )
    reward_box_number_by_id = {
        reward_box_id: index + 1
        for index, reward_box_id in enumerate(
            sorted({row["rewardBoxId"] for row in rewards})
        )
    }
    for reward_row in rewards:
        reward_row["rewardBoxNumber"] = reward_box_number_by_id[
            reward_row["rewardBoxId"]
        ]
    return rewards


def normalize_title(value: str, quest_id: int) -> str:
    title = re.sub(r"\s+", " ", value).strip()
    if title:
        return title
    return f"Quest {quest_id}"


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if slug:
        return slug
    return "quest"


def map_quest_rank(post_min_rank: int) -> str:
    if post_min_rank >= 500:
        return "gr"
    if post_min_rank >= 100:
        return "hr100"
    if post_min_rank >= 31:
        return "hr"
    if post_min_rank <= 0:
        return "arena"
    return "lr"


def parse_quest(
    raw: bytes,
    quest_offset: int,
    *,
    item_names_by_id: dict[int, str],
    monster_names_by_id: dict[int, str],
    quest_files_dir: Path | None,
    unpack_workspace: Path | None,
) -> QuestRow:
    ensure_slice_in_bounds(raw, quest_offset, QUEST_SIZE, "Quest")
    quest_id = read_u16(raw, quest_offset + 0x2E, "quest.questId")
    post_min_rank = read_u16(raw, quest_offset + 0x4E, "quest.postMinRank")
    text = parse_text(raw, read_u32(raw, quest_offset + 0x28, "quest.text_offset"))
    title = normalize_title(text["title"], quest_id)

    max_players_raw = raw[quest_offset + 0x0B]
    max_players = 4 if max_players_raw == 0 else max_players_raw

    quest_rank = map_quest_rank(post_min_rank)
    quest_file_difficulty: int | None = None
    quest_file_requirement: int | None = None
    if quest_files_dir is None or unpack_workspace is None:
        quest_rewards: list[QuestRewardEntry] = []
    else:
        quest_file_data = extract_selected_quest_file_data(
            quest_id, quest_files_dir, unpack_workspace
        )
        if quest_file_data is None:
            quest_rewards = []
        else:
            quest_file_difficulty = quest_file_data["difficulty"]
            quest_file_requirement = quest_file_data["requirement"]
            difficulty_rank = map_quest_rank_from_difficulty(quest_file_difficulty)
            if difficulty_rank is not None:
                quest_rank = difficulty_rank
            quest_rewards = normalize_quest_rewards(
                quest_file_data["rewards"], item_names_by_id
            )

    quest_row: QuestRow = {
        "questId": quest_id,
        "slug": f"{quest_id}-{slugify(title)}",
        "title": title,
        "rank": quest_rank,
        "questRank": read_u16(raw, quest_offset + 0x08, "quest.questRank"),
        "joinMinRank": read_u16(raw, quest_offset + 0x4A, "quest.joinMinRank"),
        "postMinRank": post_min_rank,
        "maxPlayers": max_players,
        "questFee": read_u32(raw, quest_offset + 0x0C, "quest.questFee"),
        "zennyReward": read_u32(raw, quest_offset + 0x10, "quest.zennyReward"),
        "zennyKO": read_u32(raw, quest_offset + 0x14, "quest.zennyKO"),
        "zennySubA": read_u32(raw, quest_offset + 0x18, "quest.zennySubA"),
        "zennySubB": read_u32(raw, quest_offset + 0x1C, "quest.zennySubB"),
        "questTimeFrames": read_u32(raw, quest_offset + 0x20, "quest.questTime"),
        "mapID": read_u32(raw, quest_offset + 0x24, "quest.mapID"),
        "contractor": text["contractor"].strip(),
        "description": text["description"].strip(),
        "mainObjective": text["text_main"].strip(),
        "subObjectiveA": text["text_sub_a"].strip(),
        "subObjectiveB": text["text_sub_b"].strip(),
        "successCondition": text["success_cond"].strip(),
        "failCondition": text["fail_cond"].strip(),
        "mainGoal": parse_goal(
            raw,
            quest_offset + 0x30,
            "quest.main_goal",
            item_names_by_id=item_names_by_id,
            monster_names_by_id=monster_names_by_id,
        ),
        "subAGoal": parse_goal(
            raw,
            quest_offset + 0x38,
            "quest.sub_a_goal",
            item_names_by_id=item_names_by_id,
            monster_names_by_id=monster_names_by_id,
        ),
        "subBGoal": parse_goal(
            raw,
            quest_offset + 0x40,
            "quest.sub_b_goal",
            item_names_by_id=item_names_by_id,
            monster_names_by_id=monster_names_by_id,
        ),
        "questRewards": quest_rewards,
    }
    if quest_file_difficulty is not None:
        quest_row["questFileDifficulty"] = quest_file_difficulty
    if quest_file_requirement is not None:
        quest_row["questFileRequirement"] = quest_file_requirement
    return quest_row


def extract_quests(
    raw: bytes,
    *,
    item_names_by_id: dict[int, str],
    monster_names_by_id: dict[int, str],
    quest_files_dir: Path | None,
    unpack_workspace: Path | None,
) -> list[QuestRow]:
    counts_offset, quest_table_offset = parse_header(raw)
    ensure_slice_in_bounds(
        raw, counts_offset, QUEST_TABLE_COUNT_BLOCK_SIZE, "QuestTableCountBlock"
    )
    quest_table_entry_count = read_u16(
        raw, counts_offset, "QuestTableCountBlock.quest_table_entry_count"
    )
    quests: list[QuestRow] = []

    for table_index in range(quest_table_entry_count):
        entry_offset = quest_table_offset + table_index * QUEST_TABLE_ENTRY_SIZE
        ensure_slice_in_bounds(
            raw, entry_offset, QUEST_TABLE_ENTRY_SIZE, "QuestTableEntry"
        )
        _unknown_prefix, quest_count, quest_pointer_table_offset = struct.unpack_from(
            QUEST_TABLE_ENTRY_FMT, raw, entry_offset
        )
        quest_offsets = read_pointer_array(
            raw,
            quest_pointer_table_offset,
            quest_count,
            f"quest_pointer_table[{table_index}]",
        )
        for quest_offset in quest_offsets:
            if quest_offset == 0:
                continue
            quests.append(
                parse_quest(
                    raw,
                    quest_offset,
                    item_names_by_id=item_names_by_id,
                    monster_names_by_id=monster_names_by_id,
                    quest_files_dir=quest_files_dir,
                    unpack_workspace=unpack_workspace,
                )
            )
    return quests


def main() -> None:
    args = parse_args()
    raw = args.input.read_bytes()
    item_names_by_id = load_item_names(args.items)
    monster_names_by_id = load_monster_names(args.monster_names)

    quest_files_dir: Path | None = (
        None if args.skip_quest_file_rewards else args.quest_files_dir
    )
    with tempfile.TemporaryDirectory(prefix="mhf_quest_extract_") as tmp_dir:
        quests = extract_quests(
            raw,
            item_names_by_id=item_names_by_id,
            monster_names_by_id=monster_names_by_id,
            quest_files_dir=quest_files_dir,
            unpack_workspace=Path(tmp_dir) if quest_files_dir is not None else None,
        )

    write_json_output(args.output, quests)
    print(f"Decoded {len(quests)} non-null quest rows")
    if args.skip_quest_file_rewards:
        print("Skipped quest-file reward extraction")
    else:
        print(f"Attempted reward extraction from quest files at {args.quest_files_dir}")


if __name__ == "__main__":
    main()
