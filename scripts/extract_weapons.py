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
    ColorTagSegment,
    decode_c_string,
    load_item_names,
    parse_color_tags,
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
    0x04: "Evolving",
    0x08: "HC",
    0x12: "Meowty",
    0x24: "Evolving",
    0x40: "G-rank",
}

# Mighty weapons carry a description tag distinguishing the three sub-tiers.
# Some descriptions have been translated and use the English bracket form.
MIGHTY_DESCRIPTION_TAGS: dict[str, str] = {
    "≪剛種武器≫": "Mighty",
    "<Mighty>": "Mighty",
    "≪天嵐武器≫": "Heavenly",
    "<Heavenly>": "Heavenly",
    "≪覇種武器≫": "Supreme",
    "<Supreme>": "Supreme",
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
    descriptionSegments: list[ColorTagSegment]
    crafting: WeaponCraftingEntry | None


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
    equip_id: int
    equip_type: str  # int  # u8, bit level flags for sp, ravi, random weapon etc
    length: str  # u8?
    unk2: int  # u8,
    unk4: int  # u8
    unk5: int  # u16
    weapon_type: int  # u32, bit level flags, mighty, heavenly, hc etc.
    visual_effects: int  # u16
    unk3: int  # u16
    grank_upgrades: "GrankUpgrades | None" = None

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
        weapon_crafting: dict[tuple[str, int], WeaponCraftingEntry],
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
            descriptionSegments=[],
            crafting=weapon_crafting["melee", idx]
            if ("melee", idx) in weapon_crafting
            else None,
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
            equip_id=unpacked[18],
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


class MaterialCost(TypedDict):
    item_id: int
    item_name: str
    amount: int


@dataclass(slots=True)
class WeaponCraftingEntry:
    kind: str
    purchasable: bool
    weapon_id: int
    material_costs: tuple[MaterialCost, ...]

    _STRUCT: ClassVar[struct.Struct] = struct.Struct("<BBH2HI2HI2HI2HI12B")
    # 0x00884B95
    # 0x3E0

    @classmethod
    def unpack_from(cls, raw: bytes, offset: int, item_names) -> "WeaponCraftingEntry":
        unpacked = cls._STRUCT.unpack_from(raw, offset)
        material_costs = []
        for item_id, amount in (
            (unpacked[3], unpacked[4]),
            (unpacked[6], unpacked[7]),
            (unpacked[9], unpacked[10]),
            (unpacked[12], unpacked[13]),
        ):
            if item_id <= 0 or amount <= 0:
                continue
            material_costs.append(
                MaterialCost(
                    item_id=item_id,
                    item_name=item_names[item_id],
                    amount=amount,
                )
            )

        kind = "unkown"
        if unpacked[0] == 6:
            kind = "melee"
        if unpacked[0] == 7:
            kind = "ranged"

        return cls(
            kind=kind,
            purchasable=bool(unpacked[1]),
            weapon_id=unpacked[2],
            material_costs=tuple(material_costs),
        )

    @classmethod
    def size(cls) -> int:
        return cls._STRUCT.size


@dataclass(slots=True)
class UpgradeEntry:
    material_costs: tuple[MaterialCost, ...]

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
                MaterialCost(
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


def _extract_weapon_crafting(
    raw: bytes, item_names: dict[int, str]
) -> dict[tuple[str, int], WeaponCraftingEntry]:
    base_pointer = read_u32(raw, 0x00000038)
    result: dict[tuple[str, int], WeaponCraftingEntry] = {}
    while True:
        wce = WeaponCraftingEntry.unpack_from(raw, base_pointer, item_names)
        base_pointer += WeaponCraftingEntry.size()
        if wce.weapon_id == 0:
            break
        if (wce.kind, wce.weapon_id) not in result:
            result[(wce.kind, wce.weapon_id)] = wce
        else:
            print(f"Duplicate WCE {wce}")

    # grank weapon crafting
    grank_base_pointer = read_u32(raw, 0x0000060C)
    grank_end_pointer = read_u32(raw, 0x00000610)
    n_grank_crafts = (
        grank_end_pointer - grank_base_pointer
    ) // WeaponCraftingEntry.size()

    print(f"n_grank_crafts: {n_grank_crafts}")
    for i in range(n_grank_crafts):
        wce = WeaponCraftingEntry.unpack_from(
            raw, grank_base_pointer + i * WeaponCraftingEntry.size(), item_names
        )
        if wce.weapon_id == 0:
            break
        result[(wce.kind, wce.weapon_id)] = wce

    return result


def extract_melee_weapons(
    raw: bytes,
    item_names: dict[int, str],
    weapon_names: dict[int, str],
    length_names: dict[int, str],
) -> list[MeleeWeapon]:
    base_pointer = read_u32(raw, MELEE_WEAPON_DATA_POINTER)
    names_pointer = read_u32(raw, MELEE_WEAPON_NAMES_POINTER)
    descriptions_pointer = read_u32(raw, 0x0000008C)  # 0x003C06D4  # 0x003C06E4
    weapon_crafting = _extract_weapon_crafting(raw, item_names)
    counter = 0
    description_counter = 0
    result = []
    while True:
        name = decode_c_string(raw, read_u32(raw, names_pointer + counter * 4))
        description = decode_c_string(
            raw, read_u32(raw, descriptions_pointer + description_counter * 4)
        )
        description += " " + decode_c_string(
            raw, read_u32(raw, descriptions_pointer + description_counter * 4 + 4)
        )
        description += " " + decode_c_string(
            raw, read_u32(raw, descriptions_pointer + description_counter * 4 + 8)
        )
        mw = MeleeWeapon.unpack_from(
            raw,
            base_pointer,
            counter,
            item_names,
            weapon_names,
            length_names,
            weapon_crafting,
        )
        mw.name = name
        parsed = parse_color_tags(description.strip())
        mw.description = parsed.plain
        mw.descriptionSegments = parsed.segments
        if mw.equip_type == "Mighty":
            for tag, sub_tier in MIGHTY_DESCRIPTION_TAGS.items():
                if tag in mw.description:
                    mw.equip_type = sub_tier
                    break
        base_pointer += MeleeWeapon.size()
        if mw.model_id == 0xFFFF:
            break
        counter += 1
        description_counter += 4
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


@dataclass(slots=True)
class GrankRecipe1Entry:
    level: int
    price: int
    material_costs: tuple[MaterialCost, ...]


@dataclass(slots=True)
class GrankRecipe2:
    level_min: int
    level_max: int
    price: int
    material_costs: tuple[MaterialCost, ...]


@dataclass(slots=True)
class GrankUpgrades:
    recipe1: tuple[GrankRecipe1Entry, ...]
    recipe2: GrankRecipe2 | None


@dataclass(slots=True)
class _RawGrankUpgrade:
    weapon_id: int
    level1: int
    level2: int
    price: int
    material_costs: tuple[MaterialCost, ...]

    STRUCT: ClassVar[struct.Struct] = struct.Struct("<IHHI2HI2HI2HI")

    @classmethod
    def unpack_from(
        cls, raw: bytes, offset: int, item_names: dict[int, str]
    ) -> "_RawGrankUpgrade":
        unpacked = cls.STRUCT.unpack_from(raw, offset)
        material_costs = []
        for item_id, amount in (
            (unpacked[4], unpacked[5]),
            (unpacked[7], unpacked[8]),
            (unpacked[10], unpacked[11]),
        ):
            if item_id <= 0 or amount <= 0:
                continue
            material_costs.append(
                MaterialCost(
                    item_id=item_id,
                    item_name=item_names[item_id],
                    amount=amount,
                )
            )

        return cls(
            weapon_id=unpacked[0],
            level1=unpacked[1],
            level2=unpacked[2],
            price=unpacked[3],
            material_costs=tuple(material_costs),
        )

    @classmethod
    def size(cls) -> int:
        return cls.STRUCT.size


def extract_grank_upgrades(
    raw: bytes, item_names: dict[int, str]
) -> dict[int, GrankUpgrades]:
    base_pointer = read_u32(raw, 0x00000614)
    end_pointer = read_u32(raw, 0x00000618)

    num_grank_upgrades = (end_pointer - base_pointer) // _RawGrankUpgrade.size()
    print(f"num_grank_upgrades: {num_grank_upgrades}")

    by_weapon: dict[int, dict] = {}
    for i in range(num_grank_upgrades):
        gru = _RawGrankUpgrade.unpack_from(
            raw, base_pointer + i * _RawGrankUpgrade.size(), item_names
        )
        bucket = by_weapon.setdefault(gru.weapon_id, {"recipe1": [], "recipe2": None})
        if gru.level1 == gru.level2:
            bucket["recipe1"].append(
                GrankRecipe1Entry(
                    level=gru.level1,
                    price=gru.price,
                    material_costs=gru.material_costs,
                )
            )
        else:
            bucket["recipe2"] = GrankRecipe2(
                level_min=gru.level1,
                level_max=gru.level2,
                price=gru.price,
                material_costs=gru.material_costs,
            )

    return {
        weapon_id: GrankUpgrades(
            recipe1=tuple(sorted(bucket["recipe1"], key=lambda e: e.level)),
            recipe2=bucket["recipe2"],
        )
        for weapon_id, bucket in by_weapon.items()
    }


def main() -> None:
    args = parse_args()
    raw = args.input.read_bytes()
    mhfpac_raw = args.mhfpac.read_bytes()

    item_names = load_item_names()
    weapon_names = _load_weapon_names(mhfpac_raw)
    length_names = _load_length_names(mhfpac_raw)

    melee_weapons = extract_melee_weapons(
        raw,
        item_names,
        weapon_names,
        length_names,
    )
    gr_upgrades = extract_grank_upgrades(raw, item_names)
    for weapon in melee_weapons:
        weapon.grank_upgrades = gr_upgrades.get(weapon.id)

    write_json_output(args.output, melee_weapons)


if __name__ == "__main__":
    main()
