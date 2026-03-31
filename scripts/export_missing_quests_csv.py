#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

from extract_common import REPO_ROOT, load_item_names, load_monster_names
from extract_quest_data import (
    INPUT_DEFAULT,
    ITEMS_PATH_DEFAULT,
    MONSTER_NAMES_PATH_DEFAULT,
    REWARD_VARIANT_CODES,
    extract_quests,
)

QUEST_FILES_DIR_DEFAULT = REPO_ROOT / "g1_data" / "quests"
EVENTS_DIR_DEFAULT = REPO_ROOT / "g1_data" / "events"
OUTPUT_DEFAULT = REPO_ROOT / "g1_data" / "missing-quests.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Write quests missing local quest files to CSV, with event matches."
    )
    parser.add_argument(
        "--input", type=Path, default=INPUT_DEFAULT, help="mhfinf.raw.bin"
    )
    parser.add_argument(
        "--quest-files-dir",
        type=Path,
        default=QUEST_FILES_DIR_DEFAULT,
        help="Directory containing standard quest files",
    )
    parser.add_argument(
        "--events-dir",
        type=Path,
        default=EVENTS_DIR_DEFAULT,
        help="Directory containing event quest files",
    )
    parser.add_argument(
        "--items", type=Path, default=ITEMS_PATH_DEFAULT, help="items.json"
    )
    parser.add_argument(
        "--monster-names",
        type=Path,
        default=MONSTER_NAMES_PATH_DEFAULT,
        help="monster_names.json",
    )
    parser.add_argument(
        "--output", type=Path, default=OUTPUT_DEFAULT, help="CSV output path"
    )
    return parser.parse_args()


def has_standard_quest_file(quest_id: int, quest_files_dir: Path) -> bool:
    for variant_code in REWARD_VARIANT_CODES:
        if (quest_files_dir / f"{quest_id:05d}{variant_code}.bin").exists():
            return True
    return False


def collect_event_files_by_quest_id(events_dir: Path) -> dict[int, list[str]]:
    matches: dict[int, list[str]] = {}
    for path in sorted(events_dir.rglob("*.bin")):
        prefix = path.stem.split("_", 1)[0]
        if not prefix.isdigit():
            continue
        quest_id = int(prefix)
        rel_path = path.relative_to(events_dir.parent).as_posix()
        if quest_id not in matches:
            matches[quest_id] = []
        matches[quest_id].append(rel_path)
    return matches


def csv_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def main() -> None:
    args = parse_args()
    raw = args.input.read_bytes()
    item_names_by_id = load_item_names(args.items)
    monster_names_by_id = load_monster_names(args.monster_names)
    quests = extract_quests(
        raw,
        item_names_by_id=item_names_by_id,
        monster_names_by_id=monster_names_by_id,
        quest_files_dir=None,
        unpack_workspace=None,
    )
    event_files_by_quest_id = collect_event_files_by_quest_id(args.events_dir)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(
            [
                "questId",
                "title",
                "mainObjective",
                "subObjectiveA",
                "subObjectiveB",
                "successCondition",
                "failCondition",
                "mainGoalType",
                "mainGoalTarget",
                "mainGoalCount",
                "subAGoalType",
                "subAGoalTarget",
                "subAGoalCount",
                "subBGoalType",
                "subBGoalTarget",
                "subBGoalCount",
                "eventFileMatches",
            ]
        )
        missing_count = 0
        with_event_count = 0
        for quest in sorted(quests, key=lambda row: row["questId"]):
            quest_id = quest["questId"]
            if has_standard_quest_file(quest_id, args.quest_files_dir):
                continue
            missing_count += 1
            event_matches = event_files_by_quest_id.get(quest_id, [])
            if event_matches:
                with_event_count += 1
            writer.writerow(
                [
                    quest_id,
                    csv_text(quest["title"]),
                    csv_text(quest["mainObjective"]),
                    csv_text(quest["subObjectiveA"]),
                    csv_text(quest["subObjectiveB"]),
                    csv_text(quest["successCondition"]),
                    csv_text(quest["failCondition"]),
                    quest["mainGoal"]["typeName"],
                    csv_text(quest["mainGoal"]["targetLabel"]),
                    quest["mainGoal"]["count"],
                    quest["subAGoal"]["typeName"],
                    csv_text(quest["subAGoal"]["targetLabel"]),
                    quest["subAGoal"]["count"],
                    quest["subBGoal"]["typeName"],
                    csv_text(quest["subBGoal"]["targetLabel"]),
                    quest["subBGoal"]["count"],
                    ";".join(event_matches),
                ]
            )

    print(f"Wrote {missing_count} missing quests to {args.output}")
    print(f"Missing quests with event file matches: {with_event_count}")


if __name__ == "__main__":
    main()
