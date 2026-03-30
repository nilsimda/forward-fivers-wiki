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
const questsSourcePath = path.join(generatedDir, '_quests-source.json');
const monsterDropsOutPath = path.join(generatedDir, 'monster-drops.json');
const itemAcquisitionOutPath = path.join(generatedDir, 'item-acquisition.json');
const questRewardsOutPath = path.join(generatedDir, 'quest-rewards.json');

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
 *   questVariantLabel?: string;
 *   rewardBoxId?: number;
 *   rewardBoxNumber?: number;
 * }} AcquisitionMethod
 */

async function main() {
  const [items, partbreakMethods, hardcoreCarveMethods, carveMethods, questsSource] = await Promise.all([
    readJson(itemsPath),
    readJson(partbreakSourcePath),
    readJson(hardcoreCarvesSourcePath),
    readJson(carvesSourcePath),
    readJson(questsSourcePath)
  ]);

  const itemNamesById = new Map(items.map((item) => [item.id, item.name]));
  const validItemIds = new Set(items.map((item) => item.id));
  const monsterNamesById = buildMonsterNamesById([
    ...partbreakMethods,
    ...carveMethods,
    ...hardcoreCarveMethods
  ]);
  const questRewards = buildQuestRewards(questsSource, itemNamesById, monsterNamesById);
  const questMethods = buildQuestRewardMethods(questRewards, itemNamesById);
  const methods = dedupePooledDropMethods(
    [
      ...partbreakMethods,
      ...carveMethods,
      ...hardcoreCarveMethods,
      ...questMethods
    ]
      .filter((method) => validItemIds.has(method.itemId))
      .sort(compareMethods)
  );

  validateMethods(methods, items);

  const monsterDrops = buildMonsterDrops(methods);
  const itemAcquisition = buildItemAcquisition(methods);

  await mkdir(generatedDir, { recursive: true });
  await Promise.all([
    writeJson(monsterDropsOutPath, monsterDrops),
    writeJson(itemAcquisitionOutPath, itemAcquisition),
    writeJson(questRewardsOutPath, questRewards)
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
 * @param {Record<string, string | number>[]} rows
 */
function buildMonsterNamesById(rows) {
  const namesById = new Map();

  for (const row of rows) {
    const monsterIdRaw = row.monster_id ?? row.monsterId;
    const monsterId =
      typeof monsterIdRaw === 'number'
        ? Math.trunc(monsterIdRaw)
        : Number.parseInt(String(monsterIdRaw ?? '').trim(), 10);
    const monsterName = String(row.monster_name ?? row.monsterName ?? '').trim();
    if (!Number.isFinite(monsterId) || !monsterName) continue;
    if (!namesById.has(monsterId)) {
      namesById.set(monsterId, monsterName);
    }
  }

  return namesById;
}

/**
 * @param {unknown} source
 * @param {Map<number, string>} itemNamesById
 * @param {Map<number, string>} monsterNamesById
 */
function buildQuestRewards(source, itemNamesById, monsterNamesById) {
  if (!source || typeof source !== 'object' || !Array.isArray(source.quests)) {
    throw new Error('Quest source missing quests[] — run scripts/extract_quest_data.py');
  }

  return source.quests.map((quest, questIndex) => {
    const questId = parseNumber(quest.questId, `quest row ${questIndex + 1} questId`);
    const title = normalizeQuestTitle(quest.text?.title, questId);
    const text = normalizeQuestText(quest.text);
    const rewardVariants = Array.isArray(quest.reward_variants) ? quest.reward_variants : [];
    const rewardGroups = buildPrimaryQuestRewardGroup(rewardVariants, questId, itemNamesById);

    return {
      questId,
      slug: buildQuestSlug(questId, title),
      title,
      rank: mapQuestRankToAcquisitionRank(quest),
      questRank: parseNumber(quest.questRank ?? 0, `quest ${questId} questRank`),
      joinMinRank: parseNumber(quest.joinMinRank ?? 0, `quest ${questId} joinMinRank`),
      postMinRank: parseNumber(quest.postMinRank ?? 0, `quest ${questId} postMinRank`),
      maxPlayers: parseNumber(quest.maxPlayers ?? 0, `quest ${questId} maxPlayers`),
      questFee: parseNumber(quest.questFee ?? 0, `quest ${questId} questFee`),
      zennyReward: parseNumber(quest.zennyReward ?? 0, `quest ${questId} zennyReward`),
      zennyKO: parseNumber(quest.zennyKO ?? 0, `quest ${questId} zennyKO`),
      zennySubA: parseNumber(quest.zennySubA ?? 0, `quest ${questId} zennySubA`),
      zennySubB: parseNumber(quest.zennySubB ?? 0, `quest ${questId} zennySubB`),
      questTimeFrames: parseNumber(quest.questTimeFrames ?? 0, `quest ${questId} questTimeFrames`),
      mapID: parseNumber(quest.mapID ?? 0, `quest ${questId} mapID`),
      contractor: text.contractor,
      description: text.description,
      mainObjective: text.main,
      subObjectiveA: text.subA,
      subObjectiveB: text.subB,
      successCondition: text.successCondition,
      failCondition: text.failCondition,
      mainGoal: normalizeGoal(quest.main_goal, itemNamesById, monsterNamesById),
      subAGoal: normalizeGoal(quest.sub_a_goal, itemNamesById, monsterNamesById),
      subBGoal: normalizeGoal(quest.sub_b_goal, itemNamesById, monsterNamesById),
      rewardGroups
    };
  });
}

/**
 * @param {Array<Record<string, unknown>>} rewardVariants
 * @param {number} questId
 * @param {Map<number, string>} itemNamesById
 */
function buildPrimaryQuestRewardGroup(rewardVariants, questId, itemNamesById) {
  const springDayVariant = rewardVariants.find(
    (variant) =>
      variant &&
      String(variant.day_night || '').trim().toLowerCase() === 'day' &&
      String(variant.season || '').trim().toLowerCase() === 'spring'
  );
  if (!springDayVariant) {
    throw new Error(`quest ${questId}: missing spring/day reward variant`);
  }

  const normalizedRewards = normalizeVariantRewards(springDayVariant, questId, itemNamesById);
  if (normalizedRewards.length === 0) {
    return [];
  }

  return [
    {
      variantLabel: 'Rewards',
      variants: [
        {
          variantCode: String(springDayVariant.variant_code || '').trim().toLowerCase(),
          dayNight: 'day',
          season: 'spring'
        }
      ],
      rewards: normalizedRewards
    }
  ];
}

/**
 * @param {Record<string, unknown>} variant
 * @param {number} questId
 * @param {Map<number, string>} itemNamesById
 */
function normalizeVariantRewards(variant, questId, itemNamesById) {
  const rewards = [];
  const rewardBoxes = Array.isArray(variant.reward_boxes) ? variant.reward_boxes : [];
  for (const [boxIndex, rewardBox] of rewardBoxes.entries()) {
    const rewardBoxId = parseNumber(
      rewardBox.reward_box_id ?? boxIndex,
      `quest ${questId} reward box ${boxIndex + 1} reward_box_id`
    );
    if (!Array.isArray(rewardBox.rewards)) continue;

    for (const [rewardIndex, reward] of rewardBox.rewards.entries()) {
      const itemId = parseNumber(
        reward.item_id,
        `quest ${questId} reward box ${rewardBoxId} reward ${rewardIndex + 1} item_id`
      );
      const percentChance = parseNumber(
        reward.percent_chance,
        `quest ${questId} reward box ${rewardBoxId} reward ${rewardIndex + 1} percent_chance`
      );
      const itemCount = parseNumber(
        reward.item_count,
        `quest ${questId} reward box ${rewardBoxId} reward ${rewardIndex + 1} item_count`
      );
      rewards.push({
        rewardBoxId,
        rewardBoxNumber: 0,
        itemId,
        itemName: itemNamesById.get(itemId) || `Item ${itemId}`,
        percentChance,
        itemCount
      });
    }
  }

  const sortedRewards = rewards.sort((a, b) => {
    if (a.rewardBoxId !== b.rewardBoxId) return a.rewardBoxId - b.rewardBoxId;
    if (a.itemId !== b.itemId) return a.itemId - b.itemId;
    if (b.percentChance !== a.percentChance) return b.percentChance - a.percentChance;
    return b.itemCount - a.itemCount;
  });

  const uniqueRewardBoxIds = [...new Set(sortedRewards.map((reward) => reward.rewardBoxId))].sort((a, b) => a - b);
  const rewardBoxNumberById = new Map(uniqueRewardBoxIds.map((rewardBoxId, index) => [rewardBoxId, index + 1]));
  for (const reward of sortedRewards) {
    reward.rewardBoxNumber = rewardBoxNumberById.get(reward.rewardBoxId) ?? reward.rewardBoxId;
  }
  return sortedRewards;
}

/**
 * @param {unknown} rawTitle
 * @param {number} questId
 */
function normalizeQuestTitle(rawTitle, questId) {
  const title = String(rawTitle || '').replace(/\s+/g, ' ').trim();
  return title || `Quest ${questId}`;
}

/**
 * @param {unknown} rawText
 */
function normalizeQuestText(rawText) {
  const text = rawText && typeof rawText === 'object' ? rawText : {};
  return {
    main: normalizeQuestTextField(text.text_main),
    subA: normalizeQuestTextField(text.text_sub_a),
    subB: normalizeQuestTextField(text.text_sub_b),
    successCondition: normalizeQuestTextField(text.success_cond),
    failCondition: normalizeQuestTextField(text.fail_cond),
    contractor: normalizeQuestTextField(text.contractor),
    description: normalizeQuestTextField(text.description)
  };
}

/**
 * @param {unknown} value
 */
function normalizeQuestTextField(value) {
  return String(value || '').trim();
}

/**
 * @param {unknown} rawGoal
 * @param {Map<number, string>} itemNamesById
 * @param {Map<number, string>} monsterNamesById
 */
function normalizeGoal(rawGoal, itemNamesById, monsterNamesById) {
  if (!rawGoal || typeof rawGoal !== 'object') return null;
  const target = rawGoal.goal_target ?? null;
  const targetKind = String(rawGoal.goal_target_kind || '').trim();
  const targetLabel =
    typeof target === 'number'
      ? resolveGoalTargetLabel(targetKind, target, itemNamesById, monsterNamesById)
      : '';
  return {
    typeName: String(rawGoal.goal_type_name || '').trim(),
    targetKind,
    target,
    targetLabel,
    count: rawGoal.goal_count ?? null,
    part: rawGoal.goal_part ?? null
  };
}

/**
 * @param {string} targetKind
 * @param {number} target
 * @param {Map<number, string>} itemNamesById
 * @param {Map<number, string>} monsterNamesById
 */
function resolveGoalTargetLabel(targetKind, target, itemNamesById, monsterNamesById) {
  if (targetKind === 'item') {
    return itemNamesById.get(target) || `Item ${target}`;
  }
  if (targetKind === 'monster') {
    return monsterNamesById.get(target) || `Monster ${target}`;
  }
  return `${targetKind || 'target'} ${target}`;
}

/**
 * @param {number} questId
 * @param {string} title
 */
function buildQuestSlug(questId, title) {
  return `${questId}-${slugify(title)}`;
}

/**
 * @param {string} value
 */
function slugify(value) {
  const normalized = value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
  return normalized || 'quest';
}

/**
 * @param {Record<string, unknown>} quest
 */
function mapQuestRankToAcquisitionRank(quest) {
  const postMinRank = parseNumber(quest.postMinRank ?? 0, `quest ${quest.questId} postMinRank`);
  if (postMinRank >= 500) return 'gr';
  if (postMinRank >= 100) return 'hr100';
  if (postMinRank >= 31) return 'hr';
  if (postMinRank <= 0) return 'arena';
  return 'lr';
}

/**
 * @param {ReturnType<typeof buildQuestRewards>} questRewards
 * @param {Map<number, string>} itemNamesById
 * @returns {AcquisitionMethod[]}
 */
function buildQuestRewardMethods(questRewards, itemNamesById) {
  const methods = [];

  for (const quest of questRewards) {
    for (const rewardGroup of quest.rewardGroups) {
      for (const reward of rewardGroup.rewards) {
        methods.push({
          methodType: 'quest_reward',
          rank: quest.rank,
          sourceLabel: `${quest.title} - ${formatRewardBoxLabel(reward.rewardBoxNumber)}`,
          chance: reward.percentChance,
          quantity: reward.itemCount,
          itemId: reward.itemId,
          itemName: itemNamesById.get(reward.itemId) || `Item ${reward.itemId}`,
          questId: quest.questId,
          questSlug: quest.slug,
          questTitle: quest.title,
          rewardBoxId: reward.rewardBoxId
          ,
          rewardBoxNumber: reward.rewardBoxNumber
        });
      }
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
 * @param {{ id: number }[]} items
 */
function validateMethods(methods, items) {
  const validItemIds = new Set(items.map((item) => item.id));
  for (const method of methods) {
    if (!validItemIds.has(method.itemId)) {
      throw new Error(`Acquisition references unknown item id ${method.itemId}`);
    }
    if (!Number.isFinite(method.chance) || method.chance < 0) {
      throw new Error(`Invalid chance for item ${method.itemId} (${method.chance})`);
    }
    if (!Number.isFinite(method.quantity) || method.quantity < 0) {
      throw new Error(`Invalid quantity for item ${method.itemId} (${method.quantity})`);
    }
    if (!method.rank) {
      throw new Error(`Missing rank for item ${method.itemId}`);
    }
  }
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
  if ((a.questVariantLabel || '') !== (b.questVariantLabel || '')) {
    return (a.questVariantLabel || '').localeCompare(b.questVariantLabel || '');
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
 * Several raw partbreak slots can share one display label (e.g. "Other") with the same PDT;
 * collapse identical acquisition lines so pooled breaks do not repeat in JSON/UI.
 *
 * @param {AcquisitionMethod[]} methods
 * @returns {AcquisitionMethod[]}
 */
function dedupePooledDropMethods(methods) {
  const seen = new Set();
  /** @type {AcquisitionMethod[]} */
  const out = [];

  for (const m of methods) {
    if (m.methodType !== 'part_break' && m.methodType !== 'capture') {
      out.push(m);
      continue;
    }

    const key = [
      m.monsterId,
      m.rank,
      m.methodType,
      m.partbreakType ?? '',
      m.itemId,
      m.chance,
      m.quantity
    ].join('|');

    if (seen.has(key)) continue;
    seen.add(key);
    out.push(m);
  }

  return out;
}

/**
 * @param {string} value
 * @param {string} label
 */
function parseNumber(value, label) {
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) {
      throw new Error(`Invalid numeric value "${value}" for ${label}`);
    }
    return Math.trunc(value);
  }

  const normalized = String(value ?? '').trim();
  if (!normalized) {
    throw new Error(`Missing numeric value for ${label}`);
  }

  const parsed = Number.parseInt(normalized, 0);
  if (Number.isNaN(parsed)) {
    throw new Error(`Invalid numeric value "${value}" for ${label}`);
  }

  return parsed;
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
