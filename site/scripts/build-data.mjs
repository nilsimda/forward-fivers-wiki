import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const siteRoot = path.resolve(__dirname, '..');
const generatedDir = path.join(siteRoot, 'src', 'data', 'generated');

const itemsPath = path.join(generatedDir, 'items.json');
const partbreakSourcePath = path.join(generatedDir, '_partbreak-source.json');
const hardcoreCarvesSourcePath = path.join(generatedDir, '_hcc-carves-source.json');
const carvesSourcePath = path.join(generatedDir, '_carves-source.json');
const questRewardsPath = path.join(generatedDir, 'quest-rewards.json');
const monsterDropsOutPath = path.join(generatedDir, 'monster-drops.json');
const itemAcquisitionOutPath = path.join(generatedDir, 'item-acquisition.json');

const rankOrder = ['lr', 'hr', 'arena', 'hr100', 'gr'];
const methodOrder = ['capture', 'part_break', 'hardcore_carve', 'quest_reward', 'carve', 'gather', 'shop'];

/**
 * @typedef {'capture' | 'part_break' | 'hardcore_carve' | 'carve' | 'quest_reward'} SupportedMethodType
 *
 * @typedef {{
 *   methodType: SupportedMethodType;
 *   rank: string;
 *   sourceLabel: string;
 *   chance: number;
 *   quantity: number;
 *   monsterId: number;
 *   monsterName: string;
 *   itemId: number;
 *   itemName: string;
 *   partbreakType?: string;
 *   questId?: number;
 *   questSlug?: string;
 *   questTitle?: string;
 *   rewardBoxId?: number;
 *   rewardBoxNumber?: number;
 * }} AcquisitionMethod
 */

async function main() {
  const [items, partbreakMethods, hardcoreCarveMethods, carveMethods, questRewards] = await Promise.all([
    readJson(itemsPath),
    readJson(partbreakSourcePath),
    readJson(hardcoreCarvesSourcePath),
    readJson(carvesSourcePath),
    readJson(questRewardsPath)
  ]);

  const itemNamesById = new Map(items.map((item) => [item.id, item.name]));
  const validItemIds = new Set(items.map((item) => item.id));
  assertQuestRewardsShape(questRewards);
  const questMethods = buildQuestRewardMethods(questRewards, itemNamesById);
  const methods = [
    ...partbreakMethods,
    ...carveMethods,
    ...hardcoreCarveMethods,
    ...questMethods
  ]
    .filter((method) => validItemIds.has(method.itemId))
    .sort(compareMethods);

  const monsterDrops = buildMonsterDrops(methods);
  const itemAcquisition = buildItemAcquisition(methods);

  await mkdir(generatedDir, { recursive: true });
  await Promise.all([
    writeJson(monsterDropsOutPath, monsterDrops),
    writeJson(itemAcquisitionOutPath, itemAcquisition)
  ]);

  console.log(
    [
      `Built ${methods.length} acquisition methods`,
      `Built ${monsterDrops.length} monster drop groups`,
      `Built acquisition entries for ${Object.keys(itemAcquisition).length} items`,
      `Built ${questRewards.length} quest reward pages`
    ].join('\n')
  );
}

/**
 * @param {string} filePath
 */
async function readJson(filePath) {
  const content = await readFile(filePath, 'utf8');
  return JSON.parse(content);
}

/**
 * @param {string} outputPath
 * @param {unknown} value
 */
async function writeJson(outputPath, value) {
  await writeFile(outputPath, `${JSON.stringify(value, null, 2)}\n`, 'utf8');
}

/**
 * @param {unknown} rawQuestRewards
 */
function assertQuestRewardsShape(rawQuestRewards) {
  if (!Array.isArray(rawQuestRewards)) {
    throw new Error('Expected quest-rewards.json to be an array — run scripts/extract_quest_data.py');
  }
  for (const [index, quest] of rawQuestRewards.entries()) {
    if (!quest || typeof quest !== 'object' || !Array.isArray(quest.questRewards)) {
      throw new Error(`Invalid quest-rewards row ${index + 1}: missing questRewards[]`);
    }
  }
}

/**
 * @param {Array<Record<string, unknown>>} questRewards
 * @param {Map<number, string>} itemNamesById
 * @returns {AcquisitionMethod[]}
 */
function buildQuestRewardMethods(questRewards, itemNamesById) {
  const methods = [];

  for (const quest of questRewards) {
    const rewards = Array.isArray(quest.questRewards) ? quest.questRewards : [];
    for (const reward of rewards) {
      methods.push({
        methodType: 'quest_reward',
        rank: String(quest.rank || ''),
        sourceLabel: `${quest.title} - ${formatRewardBoxLabel(reward.rewardBoxNumber)}`,
        chance: reward.percentChance,
        quantity: reward.itemCount,
        itemId: reward.itemId,
        itemName: itemNamesById.get(reward.itemId) || `Item ${reward.itemId}`,
        questId: quest.questId,
        questSlug: quest.slug,
        questTitle: quest.title,
        rewardBoxId: reward.rewardBoxId,
        rewardBoxNumber: reward.rewardBoxNumber
      });
    }
  }

  return methods.sort(compareMethods);
}

/**
 * @param {number} rewardBoxNumber
 * @returns {string}
 */
function formatRewardBoxLabel(rewardBoxNumber) {
  if (rewardBoxNumber === 1) return 'Main Reward';
  if (rewardBoxNumber === 2) return 'Subquest A Reward';
  if (rewardBoxNumber === 3) return 'Subquest B Reward';
  return `Reward Box ${rewardBoxNumber}`;
}

/**
 * @param {AcquisitionMethod[]} methods
 */
function buildMonsterDrops(methods) {
  const byMonster = new Map();

  for (const method of methods) {
    if (!Number.isFinite(method.monsterId)) {
      continue;
    }
    const key = String(method.monsterId);
    if (!byMonster.has(key)) {
      byMonster.set(key, {
        monsterId: method.monsterId,
        monsterLabel: method.monsterName,
        totalEntries: 0,
        dropModes: new Set(),
        ranks: new Set(),
        drops: []
      });
    }

    const group = byMonster.get(key);
    group.totalEntries += 1;
    group.dropModes.add(method.methodType);
    group.ranks.add(method.rank);
    group.drops.push({
      sourceLabel: method.sourceLabel || '',
      monsterName: method.monsterName,
      partbreakType: method.partbreakType || 'unknown',
      dropMode: method.methodType,
      rank: method.rank,
      percentage: method.chance,
      quantity: method.quantity,
      itemId: method.itemId,
      itemName: method.itemName
    });
  }

  return [...byMonster.values()]
    .map((monster) => ({
      monsterId: monster.monsterId,
      monsterLabel: monster.monsterLabel,
      totalEntries: monster.totalEntries,
      dropModes: [...monster.dropModes].sort(sortByMethod),
      ranks: [...monster.ranks].sort(sortByRank),
      drops: monster.drops.sort((a, b) => {
        const rankCompare = sortByRank(a.rank, b.rank);
        if (rankCompare !== 0) return rankCompare;
        const modeCompare = sortByMethod(a.dropMode, b.dropMode);
        if (modeCompare !== 0) return modeCompare;
        if (a.partbreakType !== b.partbreakType) return a.partbreakType.localeCompare(b.partbreakType);
        if (b.percentage !== a.percentage) return b.percentage - a.percentage;
        return a.itemName.localeCompare(b.itemName);
      })
    }))
    .sort((a, b) => a.monsterId - b.monsterId);
}

/**
 * @param {AcquisitionMethod[]} methods
 */
function buildItemAcquisition(methods) {
  const byItemId = new Map();

  for (const method of methods) {
    const key = String(method.itemId);
    if (!byItemId.has(key)) {
      byItemId.set(key, {
        itemId: method.itemId,
        itemName: method.itemName,
        methods: []
      });
    }

    byItemId.get(key).methods.push(method);
  }

  return Object.fromEntries(
    [...byItemId.entries()]
      .sort(([a], [b]) => Number(a) - Number(b))
      .map(([itemId, entry]) => [
        itemId,
        {
          itemId: entry.itemId,
          itemName: entry.itemName,
          methods: entry.methods.sort(compareMethods)
        }
      ])
  );
}

/**
 * @param {AcquisitionMethod} a
 * @param {AcquisitionMethod} b
 */
function compareMethods(a, b) {
  const rankCompare = sortByRank(a.rank, b.rank);
  if (rankCompare !== 0) return rankCompare;

  const methodCompare = sortByMethod(a.methodType, b.methodType);
  if (methodCompare !== 0) return methodCompare;

  if ((a.monsterName || '') !== (b.monsterName || '')) {
    return (a.monsterName || '').localeCompare(b.monsterName || '');
  }
  if ((a.questTitle || '') !== (b.questTitle || '')) {
    return (a.questTitle || '').localeCompare(b.questTitle || '');
  }
  if ((a.rewardBoxId ?? -1) !== (b.rewardBoxId ?? -1)) {
    return (a.rewardBoxId ?? -1) - (b.rewardBoxId ?? -1);
  }
  if ((a.partbreakType || '') !== (b.partbreakType || '')) {
    return (a.partbreakType || '').localeCompare(b.partbreakType || '');
  }
  if (b.chance !== a.chance) return b.chance - a.chance;
  if (b.quantity !== a.quantity) return b.quantity - a.quantity;
  return a.itemId - b.itemId;
}

/**
 * @param {string} a
 * @param {string} b
 */
function sortByRank(a, b) {
  const aIndex = rankOrder.indexOf(a);
  const bIndex = rankOrder.indexOf(b);
  const safeAIndex = aIndex === -1 ? Number.MAX_SAFE_INTEGER : aIndex;
  const safeBIndex = bIndex === -1 ? Number.MAX_SAFE_INTEGER : bIndex;
  if (safeAIndex !== safeBIndex) return safeAIndex - safeBIndex;
  return a.localeCompare(b);
}

/**
 * @param {string} a
 * @param {string} b
 */
function sortByMethod(a, b) {
  const aIndex = methodOrder.indexOf(a);
  const bIndex = methodOrder.indexOf(b);
  const safeAIndex = aIndex === -1 ? Number.MAX_SAFE_INTEGER : aIndex;
  const safeBIndex = bIndex === -1 ? Number.MAX_SAFE_INTEGER : bIndex;
  if (safeAIndex !== safeBIndex) return safeAIndex - safeBIndex;
  return a.localeCompare(b);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
