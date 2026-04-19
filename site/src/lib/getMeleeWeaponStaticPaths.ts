import { getAllMeleeWeapons } from "./meleeWeapons";

export async function getMeleeWeaponStaticPaths(className: string) {
  const weapons = await getAllMeleeWeapons();
  return weapons
    .filter((weapon) => weapon.id !== 0 && weapon.class_name === className)
    .map((weapon) => ({
      params: { weaponId: String(weapon.id) },
      props: { weapon },
    }));
}
