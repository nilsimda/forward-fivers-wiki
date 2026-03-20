#!/usr/bin/env python3
import argparse
import json
import struct
from pathlib import Path

POINTER_ADDRESS = 0x0000034C
POINTER_FMT = "<I"
RECORD_FMT = "<HHHHH"
RECORD_SIZE = struct.calcsize(RECORD_FMT)
TERMINATOR = b"\xFF\xFF"
FIELDS = ["monster_id", "lr_item_id", "hr_item_id", "hr100_item_id", "gr_item_id"]
REPO_ROOT = Path(__file__).resolve().parent.parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract HCC carve table from mhfdat.raw.bin into JSON."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=REPO_ROOT / "g1_data" / "mhfdat.raw.bin",
        help="Path to mhfdat.raw.bin (default: g1_data/mhfdat.raw.bin).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "site" / "src" / "data" / "generated" / "_hcc-carves-source.json",
        help="Output JSON path consumed by site/scripts/build-data.mjs.",
    )
    return parser.parse_args()


def read_hcc_blob(binary_path: Path) -> bytes:
    raw = binary_path.read_bytes()

    pointer_size = struct.calcsize(POINTER_FMT)
    if len(raw) < POINTER_ADDRESS + pointer_size:
        raise ValueError(
            f"File too small for pointer read at 0x{POINTER_ADDRESS:08X}: {binary_path}"
        )

    (data_address,) = struct.unpack_from(POINTER_FMT, raw, POINTER_ADDRESS)
    if data_address >= len(raw):
        raise ValueError(
            f"Pointer target 0x{data_address:08X} outside file bounds ({len(raw)} bytes)"
        )

    end = raw.find(TERMINATOR, data_address)
    if end == -1:
        raise ValueError("Did not find HCC terminator (0xFFFF) in source file")

    return raw[data_address:end]


def decode_records(blob: bytes) -> list[dict[str, int]]:
    if len(blob) % RECORD_SIZE != 0:
        # Keep strict behavior so schema changes fail loudly instead of silently truncating.
        raise ValueError(
            f"HCC blob size {len(blob)} is not divisible by record size {RECORD_SIZE}"
        )

    records: list[dict[str, int]] = []
    for offset in range(0, len(blob), RECORD_SIZE):
        unpacked = struct.unpack_from(RECORD_FMT, blob, offset)
        record = dict(zip(FIELDS, unpacked))
        records.append(record)
    return records


def main() -> None:
    args = parse_args()
    blob = read_hcc_blob(args.input)
    records = decode_records(blob)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")

    print(f"Input: {args.input}")
    print(f"Output: {args.output}")
    print(f"Pointer address: 0x{POINTER_ADDRESS:08X}")
    print(f"Decoded {len(records)} HCC records")


if __name__ == "__main__":
    main()
