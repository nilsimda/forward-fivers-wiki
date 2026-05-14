import { getCollection, type CollectionEntry } from "astro:content";

export type RangedWeapon = CollectionEntry<"rangedWeapons">["data"];

const rangedWeaponsPromise: Promise<RangedWeapon[]> = getCollection(
  "rangedWeapons",
).then((entries) => entries.map((entry) => entry.data));

const rangedWeaponsByIdPromise: Promise<Map<number, RangedWeapon>> =
  rangedWeaponsPromise.then(
    (weapons) => new Map<number, RangedWeapon>(weapons.map((w) => [w.id, w])),
  );

export const getAllRangedWeapons = () => rangedWeaponsPromise;

export const getRangedWeaponsById = () => rangedWeaponsByIdPromise;
