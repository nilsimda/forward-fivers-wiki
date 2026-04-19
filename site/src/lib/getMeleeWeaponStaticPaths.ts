import { getCollection } from "astro:content";

export async function getMeleeWeaponStaticPaths(className: string) {
  const entries = await getCollection("meleeWeapons");
  return entries
    .filter((e) => e.data.id !== 0 && e.data.class_name === className)
    .map((e) => ({
      params: { weaponId: String(e.data.id) },
      props: { weapon: e.data },
    }));
}
