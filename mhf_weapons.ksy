meta:
  id: mhf_weapons
  title: Monster Hunter Frontier Weapon Data (mhfdat)
  endian: le
  license: MIT

doc: |
  Parses melee weapon and upgrade data from the unpacked mhfdat binary.
  Pointer layout mirrors extract_weapons.py. The file contains a flat
  array of melee_weapon records (terminated by model_id == 0xFFFF) and
  a parallel flat array of upgrade_entry records. Both arrays are
  located via 32-bit absolute offsets stored in a small pointer table
  near the file header.

seq:
  - id: header
    type: header_pointers

types:

  # ── Pointer table ─────────────────────────────────────────────────────────
  header_pointers:
    doc: |
      The relevant offsets within the pointer table at the start of the file.
      Unused fields between known pointers are consumed as padding.
    seq:
      - id: pad_0x00
        size: 0x3c
        doc: Skip to MELEE_WEAPON_UPGRADES_POINTER (0x3C)
      - id: melee_weapon_upgrades_ptr
        type: u4
        doc: Absolute file offset to the flat upgrade_entry array.
      - id: pad_0x40
        size: 0x7c - 0x3c - 4
        doc: Skip from 0x40 to MELEE_WEAPON_DATA_POINTER (0x7C)
      - id: melee_weapon_data_ptr
        type: u4
        doc: Absolute file offset to the flat melee_weapon array.
      - id: pad_0x80
        size: 0x88 - 0x7c - 4
        doc: Skip to MELEE_WEAPON_NAMES_POINTER (0x88)
      - id: melee_weapon_names_ptr
        type: u4
        doc: |
          Absolute file offset to a table of u32 string pointers, one per
          weapon. Each pointer is itself an absolute offset to a
          null-terminated UTF-8 weapon name.
      - id: melee_weapon_descriptions_ptr
        type: u4
        doc: Absolute file offset to description string pointer table (0x8C).

  # ── Upgrade entry ──────────────────────────────────────────────────────────
  upgrade_entry:
    doc: |
      Struct layout: "<HHIHHIHHIHHHHI" (34 bytes).
      Holds up to three material costs (item_id, padding u16, amount u32)
      and four weapon IDs this entry can upgrade into.
      Item names are resolved externally via a separate item-name table.
    seq:
      - id: material1_item_id
        type: u2
      - id: material1_padding
        type: u2
        doc: Alignment padding before the u32 amount.
      - id: material1_amount
        type: u4
      - id: material2_item_id
        type: u2
      - id: material2_padding
        type: u2
      - id: material2_amount
        type: u4
      - id: material3_item_id
        type: u2
      - id: material3_padding
        type: u2
      - id: material3_amount
        type: u4
      - id: upgrades_to_0
        type: u2
      - id: upgrades_to_1
        type: u2
      - id: upgrades_to_2
        type: u2
      - id: upgrades_to_3
        type: u2
      - id: trailing_u4
        type: u4
        doc: Final field of the struct format string "…HHHHI".

  # ── Melee weapon ───────────────────────────────────────────────────────────
  melee_weapon:
    doc: |
      Struct layout: "<HBBIBBHHbBBBBBBBHHBBBBHIHH" (38 bytes).
      Sentinel: model_id == 0xFFFF marks end-of-array.
      Names/descriptions are stored as separate parallel string-pointer
      tables and are NOT inlined here.
      upgrade_entry_index is an index into the upgrade_entry array
      (base pointer from header_pointers.melee_weapon_upgrades_ptr).
    seq:
      - id: model_id
        type: u2
        doc: 0xFFFF == sentinel / end of array.
      - id: rarity
        type: u1
      - id: class_id
        type: u1
        doc: Index into the weapon-class name table (loaded from mhfpac).
      - id: price
        type: u4
      - id: sharpness_id
        type: u1
      - id: sharpness_max
        type: u1
      - id: raw_damage
        type: u2
      - id: defense
        type: u2
      - id: affinity
        type: s1
        doc: Signed byte; negative values indicate negative affinity.
      - id: element_id
        type: u1
        doc: |
          0x00 = None, 0x01 = Fire, 0x02 = Water, 0x03 = Thunder,
          0x04 = Dragon, 0x05 = Ice, 0x06 = Flame, 0x07 = Light,
          0x08 = Thunder Pole, 0x09 = Tenshou, 0x0A = Okiko,
          0x0B = Black Flame, 0x0C = Kanade, 0x0D = Darkness,
          0x0E = Crimson Demon, 0x0F = Wind, 0x10 = Sound,
          0x11 = Burning Zero, 0x12 = Emperor's Roar.
        enum: element
      - id: element_damage
        type: u1
      - id: ailment_id
        type: u1
        doc: 0x00 = None, 0x01 = Poison, 0x02 = Paralysis, 0x03 = Sleep, 0x04 = Blast.
        enum: ailment
      - id: ailment_damage
        type: u1
      - id: slots
        type: u1
      - id: weapon_attribute
        type: u1
        doc: Secondary weapon attribute; semantics not fully known.
      - id: unk1
        type: u1
      - id: upgrade_entry_index
        type: u2
        doc: Index into the flat upgrade_entry array.
      - id: other_model_id
        type: u2
      - id: equip_type
        type: u1
        doc: Bit flags for SP / Ravi / random weapon etc.
      - id: length_id
        type: u1
        doc: Index into the blade-length name table (loaded from mhfpac).
      - id: unk2
        type: u1
      - id: unk4
        type: u1
      - id: unk5
        type: u2
      - id: weapon_type
        type: u4
        doc: Bit flags for mighty / heavenly / HC etc.
      - id: visual_effects
        type: u2
      - id: unk3
        type: u2

enums:

  element:
    0x00: none
    0x01: fire
    0x02: water
    0x03: thunder
    0x04: dragon
    0x05: ice
    0x06: flame
    0x07: light
    0x08: thunder_pole
    0x09: tenshou
    0x0a: okiko
    0x0b: black_flame
    0x0c: kanade
    0x0d: darkness
    0x0e: crimson_demon
    0x0f: wind
    0x10: sound
    0x11: burning_zero
    0x12: emperors_roar

  ailment:
    0x00: none
    0x01: poison
    0x02: paralysis
    0x03: sleep
    0x04: blast
