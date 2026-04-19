#! /usr/bin/env python3

import argparse
import struct
from abc import ABC
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, TypedDict

from extract_common import (
    DEFAULT_DATA_PATHS,
    REPO_ROOT,
    decode_c_string,
    load_item_names,
    read_u32,
    write_json_output,
)

MELEE_WEAPON_DATA_POINTER = 0x0000007C
MELEE_WEAPON_NAMES_POINTER = 0x00000088
MELEE_WEAPON_DESCRIPTIONS_POINTER = 0x0000008C
MELEE_WEAPON_UPGRADES_POINTER = 0x0000003C
RANGED_WEAPON_NAMES_POINTER = 0x00000084
SHARPNESS_POINTER = 0x0AC


def _load_weapon_names(mhfpac_raw: bytes) -> dict[int, str]:
    result = {}
    for i in range(11):
        name_pointer = read_u32(mhfpac_raw, 0x000AF7C0 + i * 4)
        result[i] = decode_c_string(mhfpac_raw, name_pointer)

    return result


def _load_length_names(mhfpac_raw: bytes) -> dict[int, str]:
    result = {}
    for i in range(8):
        name_pointer = read_u32(mhfpac_raw, 0x000BA4F4 + i * 4)
        result[i] = decode_c_string(mhfpac_raw, name_pointer)

    print(result.values())
    return result


# @0x0011ECA8
ELEMENT_NAMES: dict[int, str | None] = {
    0x00: None,
    0x01: "Fire",
    0x02: "Water",
    0x03: "Thunder",
    0x04: "Dragon",
    0x05: "Ice",
    0x06: "Blaze",
    0x07: "Light",
    0x08: "Maglev",
    0x09: "Aether",
    0x0A: "Antinomic",
}

AILMENT_NAMES: dict[int, str | None] = {
    0x00: None,
    0x01: "Poison",
    0x02: "Paralysis",
    0x03: "Sleep",
}

EQUIP_TYPE_NAMES: dict[int, str] = {
    0x00: "Normal",
    0x01: "SP",
    0x02: "Mighty",
    0x04: "Evolution",
    0x08: "HC",
    0x24: "Laviente",
}


@dataclass(slots=True)
class Sharpness:
    red: int
    orange: int
    yellow: int
    green: int
    blue: int
    white: int
    purple: int
    cyan: int

    _STRUCT: ClassVar[struct.Struct] = struct.Struct("<8H")

    @classmethod
    def unpack_from(cls, raw: bytes, offset: int) -> "Sharpness":
        return cls(*cls._STRUCT.unpack_from(raw, offset))

    @classmethod
    def size(cls) -> int:
        return cls._STRUCT.size


@dataclass(slots=True)
class Weapon(ABC):
    name: str
    description: str


@dataclass(slots=True)
class MeleeWeapon(Weapon):
    id: int
    model_id: int  # u16
    rarity: int  # u8
    class_name: str  # u8
    price: int  # u32
    sharpness: Sharpness  # sharpness index u8 into table
    sharpness_cap: int  # u8 tier → cap = 150 + tier*50
    raw_damage: int  # u16
    defense: int  # u16
    affinity: int  # u8
    element: str | None  # u8
    element_damage: int  # u8
    ailment: str | None  # u8
    ailment_damage: int  # u8
    slots: int  # u8
    weapon_attribute: int  # u8, secondary weapon attribute?
    unk1: int  # u8
    upgrade_entry: UpgradeEntry  # u16
    other_model_id: int  # u16
    equip_type: str  # int  # u8, bit level flags for sp, ravi, random weapon etc
    length: str  # u8?
    unk2: int  # u8,
    unk4: int  # u8
    unk5: int  # u16
    weapon_type: int  # u32, bit level flags, mighty, heavenly, hc etc.
    visual_effects: int  # u16
    unk3: int  # u16

    _STRUCT: ClassVar[struct.Struct] = struct.Struct("<HBBIBBHHbBBBBBBBHHBBBBHIHH")

    @classmethod
    def unpack_from(
        cls,
        raw: bytes,
        offset: int,
        idx: int,
        item_names: dict[int, str],
        weapon_names: dict[int, str],
        length_names: dict[int, str],
    ) -> "MeleeWeapon":
        unpacked = cls._STRUCT.unpack_from(raw, offset)
        upgrade_pointer = (
            read_u32(raw, MELEE_WEAPON_UPGRADES_POINTER) + idx * UpgradeEntry.size()
        )
        sharpness_header_pointer = 0x000000AC
        sharpness_base_pointer = read_u32(raw, sharpness_header_pointer)
        sharpness_weapon_pointer = read_u32(
            raw, sharpness_base_pointer + 4 * unpacked[2]
        )
        sharpness = Sharpness.unpack_from(
            raw, sharpness_weapon_pointer + Sharpness.size() * unpacked[4]
        )

        upgrade_entry = UpgradeEntry.unpack_from(raw, upgrade_pointer, item_names)
        return cls(
            id=idx,
            name="",
            description="",
            model_id=unpacked[0],
            rarity=unpacked[1],
            class_name=weapon_names[unpacked[2]],
            price=unpacked[3] // 2,  # for some reason the ingame price is half
            sharpness=sharpness,
            sharpness_cap=150 + unpacked[5] * 50,
            raw_damage=unpacked[6],  # TODO: add weapon mutliplier
            defense=unpacked[7],
            affinity=unpacked[8],
            element=ELEMENT_NAMES[unpacked[9]],
            element_damage=unpacked[10] * 10,
            ailment=AILMENT_NAMES[unpacked[11]],
            ailment_damage=unpacked[12] * 10,
            slots=unpacked[13],
            weapon_attribute=unpacked[14],
            unk1=unpacked[15],
            upgrade_entry=upgrade_entry,
            other_model_id=unpacked[17],
            equip_type=EQUIP_TYPE_NAMES.get(unpacked[18], "Unknown"),
            length=length_names[unpacked[19]],
            unk2=unpacked[20],
            unk4=unpacked[21],
            unk5=unpacked[22],
            weapon_type=unpacked[23],
            visual_effects=unpacked[24],
            unk3=unpacked[25],
        )

    @classmethod
    def size(cls) -> int:
        return cls._STRUCT.size


@dataclass(slots=True)
class RangedWeapon(Weapon):
    pass


class UpgradeMaterialCost(TypedDict):
    item_id: int
    item_name: str
    amount: int


@dataclass(slots=True)
class UpgradeEntry:
    material_costs: tuple[UpgradeMaterialCost, ...]

    upgrades_to: tuple[int, ...]

    _STRUCT: ClassVar[struct.Struct] = struct.Struct("<HHIHHIHHIHHHHI")

    @classmethod
    def unpack_from(
        cls, raw: bytes, offset: int, item_names: dict[int, str]
    ) -> "UpgradeEntry":
        unpacked = cls._STRUCT.unpack_from(raw, offset)
        material_costs = []
        for item_id, amount in (
            (unpacked[0], unpacked[1]),
            (unpacked[3], unpacked[4]),
            (unpacked[6], unpacked[7]),
        ):
            if item_id <= 0 or amount <= 0:
                continue
            material_costs.append(
                UpgradeMaterialCost(
                    item_id=item_id,
                    item_name=item_names[item_id],
                    amount=amount,
                )
            )

        return cls(
            material_costs=tuple(material_costs),
            upgrades_to=tuple(
                upgrade_id
                for upgrade_id in (
                    unpacked[9],
                    unpacked[10],
                    unpacked[11],
                    unpacked[12],
                )
                if upgrade_id > 0
            ),
        )

    @classmethod
    def size(cls) -> int:
        return cls._STRUCT.size


def extract_melee_weapons(
    raw: bytes,
    item_names: dict[int, str],
    weapon_names: dict[int, str],
    length_names: dict[int, str],
) -> list[MeleeWeapon]:
    base_pointer = read_u32(raw, MELEE_WEAPON_DATA_POINTER)
    names_pointer = read_u32(raw, MELEE_WEAPON_NAMES_POINTER)
    # descriptions_pointer = read_u32(raw, MELEE_WEAPON_DESCRIPTIONS_POINTER)
    counter = 0
    result = []
    while True:
        name = decode_c_string(raw, read_u32(raw, names_pointer + counter * 4))
        mw = MeleeWeapon.unpack_from(
            raw, base_pointer, counter, item_names, weapon_names, length_names
        )
        mw.id = counter
        mw.name = name
        base_pointer += MeleeWeapon.size()
        if mw.model_id == 0xFFFF:
            break
        counter += 1
        if name != "ダミー":  # filter out dummy weapons
            result.append(mw)

    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract gathering point data from quest files to JSON"
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_DATA_PATHS["mhfdat"],
        help="Path to unpacked mhfdat file.",
    )
    parser.add_argument(
        "--mhfpac",
        type=Path,
        default=DEFAULT_DATA_PATHS["mhfpac"],
        help="Path to unpacked mhfpac file.",
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "site" / "src" / "data" / "generated" / "weapons.json",
        help="Output gathering JSON path.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    raw = args.input.read_bytes()
    mhfpac_raw = args.mhfpac.read_bytes()

    item_names = load_item_names()
    weapon_names = _load_weapon_names(mhfpac_raw)
    length_names = _load_length_names(mhfpac_raw)

    melee_weapons = extract_melee_weapons(raw, item_names, weapon_names, length_names)
    print(len(melee_weapons))

    write_json_output(args.output, melee_weapons)


if __name__ == "__main__":
    main()
