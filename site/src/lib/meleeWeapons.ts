import { getCollection, type CollectionEntry } from "astro:content";

export type MeleeWeapon = CollectionEntry<"meleeWeapons">["data"];

const meleeWeaponsPromise: Promise<MeleeWeapon[]> = getCollection(
  "meleeWeapons",
).then((entries) => entries.map((entry) => entry.data));

const meleeWeaponsByIdPromise: Promise<Map<number, MeleeWeapon>> =
  meleeWeaponsPromise.then(
    (weapons) => new Map<number, MeleeWeapon>(weapons.map((w) => [w.id, w])),
  );

export const getAllMeleeWeapons = () => meleeWeaponsPromise;

export const getMeleeWeaponsById = () => meleeWeaponsByIdPromise;
