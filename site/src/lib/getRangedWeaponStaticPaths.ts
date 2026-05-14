import { getAllRangedWeapons } from "./rangedWeapons";

export async function getRangedWeaponStaticPaths(className: string) {
  const weapons = await getAllRangedWeapons();
  return weapons
    .filter((weapon) => weapon.id !== 0 && weapon.class_name === className)
    .map((weapon) => ({
      params: { weaponId: String(weapon.id) },
      props: { weapon },
    }));
}
