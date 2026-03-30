#!/usr/bin/env python3
import argparse
import struct
import subprocess
import tempfile
from pathlib import Path
from typing import Literal, TypedDict

from extract_common import (
    REPO_ROOT,
    decode_c_string,
    read_pointer_array,
    read_u16,
    read_u32,
    write_json_output,
)

INPUT_DEFAULT = REPO_ROOT / "g1_data" / "mhfinf.raw.bin"
OUTPUT_DEFAULT = (
    REPO_ROOT / "site" / "src" / "data" / "generated" / "_quests-source.json"
)
QUEST_FILES_DIR_DEFAULT = REPO_ROOT / "g1_data" / "quests"

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

GoalTargetKind = Literal["none", "monster", "item", "unknown"]
DayNightKind = Literal["day", "night"]
SeasonKind = Literal["spring", "summer", "winter"]

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

SEASON_BY_INDEX: dict[int, SeasonKind] = {
    0: "spring",
    1: "summer",
    2: "winter",
}

DAY_NIGHT_BY_CODE: dict[str, DayNightKind] = {
    "d": "day",
    "n": "night",
}


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
    goal_type: int
    goal_type_name: str
    goal_target_kind: GoalTargetKind
    goal_target: int | None
    goal_count: int | None
    goal_part: int | None


class QuestRewardItem(TypedDict):
    percent_chance: int
    item_id: int
    item_count: int


class QuestRewardBox(TypedDict):
    reward_box_id: int
    rewards: list[QuestRewardItem]


class QuestRewardVariant(TypedDict):
    variant_code: str
    day_night: DayNightKind
    season: SeasonKind
    rewards_available: bool
    reward_flag: int | None
    reward_boxes: list[QuestRewardBox]


class QuestRow(TypedDict):
    questRank: int
    maxPlayers: int
    questFee: int
    zennyReward: int
    zennyKO: int
    zennySubA: int
    zennySubB: int
    questTimeFrames: int
    mapID: int
    text: QuestText
    restrictionFlags: int
    questId: int
    main_goal: QuestGoal
    sub_a_goal: QuestGoal
    sub_b_goal: QuestGoal
    joinMinRank: int
    postMinRank: int
    reward_variants: list[QuestRewardVariant]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract mhfinf quest table and text pointers into JSON."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=INPUT_DEFAULT,
        help="Path to mhfinf.raw.bin",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_DEFAULT,
        help="Output JSON path",
    )
    parser.add_argument(
        "--quest-files-dir",
        type=Path,
        default=QUEST_FILES_DIR_DEFAULT,
        help="Directory containing quest files (e.g. 00001d0.bin)",
    )
    parser.add_argument(
        "--skip-quest-file-rewards",
        action="store_true",
        help="Skip extracting reward variants from quest files in g1_data/quests",
    )
    return parser.parse_args()


def ensure_slice_in_bounds(raw: bytes, offset: int, size: int, label: str) -> None:
    if offset < 0 or offset + size > len(raw):
        raise ValueError(
            f"{label}: [0x{offset:08X}, 0x{offset + size:08X}) out of bounds "
            f"for file size 0x{len(raw):08X}"
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
            "Invalid mhfinf header_size: expected "
            f"0x{MHF_INF_HEADER_SIZE:08X}, got 0x{header_size:08X}"
        )

    counts_table_offset = unpacked[4]
    quest_table_offset = unpacked[5]
    return counts_table_offset, quest_table_offset


def goal_type_name(goal_type: int) -> str:
    known = GOAL_TYPE_LABELS.get(goal_type)
    if known is not None:
        return known
    return f"Unknown_0x{goal_type:08X}"


def goal_target_kind(goal_type: int) -> GoalTargetKind:
    if goal_type == GOAL_TYPE_NONE:
        return "none"
    if goal_type in GOAL_TYPES_MONSTER_TARGET:
        return "monster"
    if goal_type == GOAL_TYPE_DELIVER:
        return "item"
    return "unknown"


def parse_goal(raw: bytes, goal_offset: int, label: str) -> QuestGoal:
    ensure_slice_in_bounds(raw, goal_offset, 8, label)
    goal_type = read_u32(raw, goal_offset, f"{label}.goal_type")
    target_raw = read_u16(raw, goal_offset + 4, f"{label}.goal_target_raw")
    value_raw = read_u16(raw, goal_offset + 6, f"{label}.goal_value_raw")

    kind = goal_target_kind(goal_type)
    goal_target: int | None = None
    goal_count: int | None = None
    goal_part: int | None = None

    if goal_type != GOAL_TYPE_NONE:
        goal_target = target_raw
        if goal_type == GOAL_TYPE_BREAK_PART:
            goal_part = value_raw
        else:
            goal_count = value_raw

    return {
        "goal_type": goal_type,
        "goal_type_name": goal_type_name(goal_type),
        "goal_target_kind": kind,
        "goal_target": goal_target,
        "goal_count": goal_count,
        "goal_part": goal_part,
    }


def parse_text(raw: bytes, text_offset: int) -> QuestText:
    ensure_slice_in_bounds(raw, text_offset, QUEST_TEXT_SIZE, "QuestText")
    pointers = read_pointer_array(raw, text_offset, 8, "quest_text_pointer")

    keys = (
        "title",
        "text_main",
        "text_sub_a",
        "text_sub_b",
        "success_cond",
        "fail_cond",
        "contractor",
        "description",
    )
    out: dict[str, str] = {}
    for index, key in enumerate(keys):
        pointer = pointers[index]
        out[key] = decode_c_string(raw, pointer)

    return {
        "title": out["title"],
        "text_main": out["text_main"],
        "text_sub_a": out["text_sub_a"],
        "text_sub_b": out["text_sub_b"],
        "success_cond": out["success_cond"],
        "fail_cond": out["fail_cond"],
        "contractor": out["contractor"],
        "description": out["description"],
    }


def reward_box_max_slots(reward_box_id: int) -> int:
    # Mirrors known quest editor behavior.
    if reward_box_id in (0, 1):
        return 24
    if reward_box_id in (2, 3):
        return 4
    return 8


def parse_reward_boxes_from_quest_file(raw: bytes) -> tuple[int, list[QuestRewardBox]]:
    reward_pointer = read_u32(raw, 0x0C, "quest_file.reward_pointer")
    reward_flag = read_u8(raw, 0x150, "quest_file.reward_flag")

    boxes: list[QuestRewardBox] = []
    for box_index in range(8):
        header_offset = reward_pointer + box_index * 8
        ensure_slice_in_bounds(raw, header_offset, 8, f"reward_header[{box_index}]")

        reward_box_id = read_u8(raw, header_offset, f"reward_header[{box_index}].id")
        # Header terminator is first u16 at entry start: 0xFFFF.
        if (
            read_u16(raw, header_offset, f"reward_header[{box_index}].sentinel")
            == 0xFFFF
        ):
            break

        reward_box_addr = read_u32(
            raw,
            header_offset + 4,
            f"reward_header[{box_index}].addr",
        )
        max_slots = reward_box_max_slots(reward_box_id)

        rewards: list[QuestRewardItem] = []
        for item_index in range(max_slots):
            reward_offset = reward_box_addr + item_index * 6
            ensure_slice_in_bounds(
                raw,
                reward_offset,
                6,
                f"reward_box[{box_index}].item[{item_index}]",
            )
            percent_chance = read_u16(
                raw,
                reward_offset,
                f"reward_box[{box_index}].item[{item_index}].percent_chance",
            )
            if percent_chance == 0xFFFF:
                break

            item_id = read_u16(
                raw,
                reward_offset + 2,
                f"reward_box[{box_index}].item[{item_index}].item_id",
            )
            item_count = read_u16(
                raw,
                reward_offset + 4,
                f"reward_box[{box_index}].item[{item_index}].item_count",
            )
            rewards.append(
                {
                    "percent_chance": percent_chance,
                    "item_id": item_id,
                    "item_count": item_count,
                }
            )

        boxes.append(
            {
                "reward_box_id": reward_box_id,
                "rewards": rewards,
            }
        )

    return reward_flag, boxes


def load_unpacked_quest_file(path: Path, workspace: Path) -> tuple[bytes, bool]:
    raw = path.read_bytes()
    if not raw.startswith(b"JKR\x1a"):
        return raw, False

    output_prefix = workspace / "quest_variant_unpacked"
    output_file = workspace / "quest_variant_unpacked.bin"
    if output_file.exists():
        output_file.unlink()

    try:
        subprocess.run(
            [
                "rsfrontier-cli",
                "unpack",
                "-i",
                str(path),
                "-o",
                str(output_prefix),
            ],
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

    return output_file.read_bytes(), True


def extract_reward_variants_for_quest(
    quest_id: int,
    quest_files_dir: Path,
    unpack_workspace: Path,
) -> list[QuestRewardVariant]:
    variants: list[QuestRewardVariant] = []

    for day_night_code, day_night in DAY_NIGHT_BY_CODE.items():
        for season_index, season in SEASON_BY_INDEX.items():
            variant_code = f"{day_night_code}{season_index}"
            source_name = f"{quest_id:05d}{variant_code}.bin"
            source_path = quest_files_dir / source_name

            if not source_path.exists():
                variants.append(
                    {
                        "variant_code": variant_code,
                        "day_night": day_night,
                        "season": season,
                        "rewards_available": False,
                        "reward_flag": None,
                        "reward_boxes": [],
                    }
                )
                continue

            was_unpacked = False
            try:
                unpacked, was_unpacked = load_unpacked_quest_file(
                    source_path,
                    unpack_workspace,
                )
                _quest_file_id = read_u16(unpacked, 0xEE, "quest_file.questFileId")
                reward_flag, reward_boxes = parse_reward_boxes_from_quest_file(unpacked)
                variants.append(
                    {
                        "variant_code": variant_code,
                        "day_night": day_night,
                        "season": season,
                        "rewards_available": len(reward_boxes) > 0,
                        "reward_flag": reward_flag,
                        "reward_boxes": reward_boxes,
                    }
                )
            except Exception as exc:  # preserve extraction for other variants/quests
                _ = exc
                variants.append(
                    {
                        "variant_code": variant_code,
                        "day_night": day_night,
                        "season": season,
                        "rewards_available": False,
                        "reward_flag": None,
                        "reward_boxes": [],
                    }
                )

    return variants


def parse_quest(
    raw: bytes,
    quest_offset: int,
    *,
    quest_files_dir: Path | None,
    unpack_workspace: Path | None,
) -> QuestRow:
    ensure_slice_in_bounds(raw, quest_offset, QUEST_SIZE, "Quest")
    text_offset = read_u32(raw, quest_offset + 0x28, "quest.text_offset")

    max_players_raw = raw[quest_offset + 0x0B]
    max_players_effective = 4 if max_players_raw == 0 else max_players_raw

    reward_variants: list[QuestRewardVariant]
    if quest_files_dir is None or unpack_workspace is None:
        reward_variants = []
    else:
        reward_variants = extract_reward_variants_for_quest(
            read_u16(raw, quest_offset + 0x2E, "quest.questId"),
            quest_files_dir,
            unpack_workspace,
        )

    return {
        "questRank": read_u16(raw, quest_offset + 0x08, "quest.questRank"),
        "maxPlayers": max_players_effective,
        "questFee": read_u32(raw, quest_offset + 0x0C, "quest.questFee"),
        "zennyReward": read_u32(raw, quest_offset + 0x10, "quest.zennyReward"),
        "zennyKO": read_u32(raw, quest_offset + 0x14, "quest.zennyKO"),
        "zennySubA": read_u32(raw, quest_offset + 0x18, "quest.zennySubA"),
        "zennySubB": read_u32(raw, quest_offset + 0x1C, "quest.zennySubB"),
        "questTimeFrames": read_u32(raw, quest_offset + 0x20, "quest.questTime"),
        "mapID": read_u32(raw, quest_offset + 0x24, "quest.mapID"),
        "text": parse_text(raw, text_offset),
        "restrictionFlags": read_u16(
            raw, quest_offset + 0x2C, "quest.restrictionFlags"
        ),
        "questId": read_u16(raw, quest_offset + 0x2E, "quest.questId"),
        "main_goal": parse_goal(raw, quest_offset + 0x30, "quest.main_goal"),
        "sub_a_goal": parse_goal(raw, quest_offset + 0x38, "quest.sub_a_goal"),
        "sub_b_goal": parse_goal(raw, quest_offset + 0x40, "quest.sub_b_goal"),
        "joinMinRank": read_u16(raw, quest_offset + 0x4A, "quest.joinMinRank"),
        "postMinRank": read_u16(raw, quest_offset + 0x4E, "quest.postMinRank"),
        "reward_variants": reward_variants,
    }


def extract_quests(
    raw: bytes,
    *,
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

    table_base = quest_table_offset
    for table_index in range(quest_table_entry_count):
        entry_offset = table_base + table_index * QUEST_TABLE_ENTRY_SIZE
        ensure_slice_in_bounds(
            raw, entry_offset, QUEST_TABLE_ENTRY_SIZE, "QuestTableEntry"
        )

        unknown_prefix, quest_count, quest_pointer_table_offset = struct.unpack_from(
            QUEST_TABLE_ENTRY_FMT, raw, entry_offset
        )
        quest_offsets = read_pointer_array(
            raw,
            quest_pointer_table_offset,
            quest_count,
            f"quest_pointer_table[{table_index}]",
        )

        for pointer_index, quest_offset in enumerate(quest_offsets):
            if quest_offset == 0:
                continue
            _ = pointer_index
            quest_row = parse_quest(
                raw,
                quest_offset,
                quest_files_dir=quest_files_dir,
                unpack_workspace=unpack_workspace,
            )
            quests.append(quest_row)

        _ = table_index
        _ = unknown_prefix

    return quests


def main() -> None:
    args = parse_args()
    raw = args.input.read_bytes()

    quest_files_dir: Path | None
    if args.skip_quest_file_rewards:
        quest_files_dir = None
    else:
        quest_files_dir = args.quest_files_dir

    with tempfile.TemporaryDirectory(prefix="mhf_quest_extract_") as tmp_dir:
        unpack_workspace = Path(tmp_dir)
        quests = extract_quests(
            raw,
            quest_files_dir=quest_files_dir,
            unpack_workspace=unpack_workspace if quest_files_dir is not None else None,
        )

    write_json_output(
        args.output,
        {
            "quests": quests,
        },
    )

    print(f"Decoded {len(quests)} non-null quest rows")
    if args.skip_quest_file_rewards:
        print("Skipped quest-file reward extraction")
    else:
        print(f"Attempted reward extraction from quest files at {args.quest_files_dir}")


if __name__ == "__main__":
    main()
