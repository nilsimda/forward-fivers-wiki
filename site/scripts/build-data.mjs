import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const siteRoot = path.resolve(__dirname, '..');
const generatedDir = path.join(siteRoot, 'src', 'data', 'generated');

const itemsSourcePath = path.join(generatedDir, '_items-source.json');
const partbreakSourcePath = path.join(generatedDir, '_partbreak-source.json');
const hardcoreCarvesSourcePath = path.join(generatedDir, '_hcc-carves-source.json');
const carvesSourcePath = path.join(generatedDir, '_carves-source.json');
const questsSourcePath = path.join(generatedDir, '_quests-source.json');
const itemsOutPath = path.join(generatedDir, 'items.json');
const monsterDropsOutPath = path.join(generatedDir, 'monster-drops.json');
const itemAcquisitionOutPath = path.join(generatedDir, 'item-acquisition.json');
const questRewardsOutPath = path.join(generatedDir, 'quest-rewards.json');

const rankOrder = ['lr', 'hr', 'arena', 'hr100', 'gr'];
const methodOrder = ['capture', 'part_break', 'hardcore_carve', 'quest_reward', 'carve', 'gather', 'shop'];
const knownDropModes = new Set(['capture', 'part_break']);

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
  const [itemRows, partbreakRows, hardcoreCarveRows, carveRows, questsSource] = await Promise.all([
    readJson(itemsSourcePath),
    readJson(partbreakSourcePath),
    readJson(hardcoreCarvesSourcePath),
    readJson(carvesSourcePath),
    readJson(questsSourcePath)
  ]);

  const items = buildItems(itemRows);
  const itemNamesById = new Map(items.map((item) => [item.id, item.name]));
  const validItemIds = new Set(items.map((item) => item.id));
  const monsterNamesById = buildMonsterNamesById([...partbreakRows, ...carveRows]);
  const questRewards = buildQuestRewards(questsSource, itemNamesById, monsterNamesById);
  const questMethods = buildQuestRewardMethods(questRewards, itemNamesById);
  const methods = dedupePooledDropMethods(
    [
      ...buildAcquisitionMethods(partbreakRows),
      ...buildCarveMethods(carveRows),
      ...buildHardcoreCarveMethods(hardcoreCarveRows, items, monsterNamesById),
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
    writeJson(itemsOutPath, items),
    writeJson(monsterDropsOutPath, monsterDrops),
    writeJson(itemAcquisitionOutPath, itemAcquisition),
    writeJson(questRewardsOutPath, questRewards)
  ]);

  console.log(
    [
      `Built ${items.length} items`,
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
 * @param {Record<string, string>[]} rows
 */
function buildItems(rows) {
  const items = rows
    .map((row, index) => {
      const id = parseNumber(row.item_index, `items row ${index + 1} item_index`);
      const descriptionRaw = (row.description || '').trim();
      const rarityPlusOne = parseNumber(row.rarity_plus_one, `items row ${index + 1} rarity_plus_one`);
      const rarityRawSource = row.rarity_raw ?? rarityPlusOne - 1;
      if (row.descriptionPlain === undefined || !Array.isArray(row.descriptionSegments)) {
        throw new Error(
          `items row ${index + 1}: missing descriptionPlain/descriptionSegments — run scripts/extract_item_data.py`
        );
      }
      return {
        id,
        slug: String(id),
        name: (row.name || '').trim(),
        description: row.descriptionPlain,
        descriptionRaw,
        descriptionPlain: row.descriptionPlain,
        descriptionSegments: row.descriptionSegments,
        rarityRaw: parseNumber(rarityRawSource, `items row ${index + 1} rarity_raw`),
        rarityPlusOne,
        maxStack: parseNumber(row.maxStack, `items row ${index + 1} maxStack`),
        icon: parseNumber(row.icon, `items row ${index + 1} icon`),
        iconColor: parseNumber(row.iconColor, `items row ${index + 1} iconColor`),
        buyPrice: parseNumber(row.buyPrice, `items row ${index + 1} buyPrice`),
        sellPrice: parseNumber(row.sellPrice, `items row ${index + 1} sellPrice`),
        isGz: parseBoolean(row.isGz, `items row ${index + 1} isGz`, false),
        type: parseNumber(row.type, `items row ${index + 1} type`)
      };
    })
    .sort((a, b) => a.id - b.id);

  const seen = new Set();
  for (const item of items) {
    if (seen.has(item.id)) {
      throw new Error(`Duplicate item id detected: ${item.id}`);
    }
    seen.add(item.id);
  }

  return items;
}

/**
 * @param {Record<string, string | number>[]} rows
 * @returns {AcquisitionMethod[]}
 */
function buildAcquisitionMethods(rows) {
  /** @type {AcquisitionMethod[]} */
  const methods = [];

  for (const [index, row] of rows.entries()) {
    const dropMode = (row.drop_mode || '').trim().toLowerCase();
    if (!knownDropModes.has(dropMode)) {
      throw new Error(`Unknown drop_mode "${row.drop_mode}" at partbreak row ${index + 1}`);
    }

    const methodType = /** @type {SupportedMethodType} */ (dropMode);
    const monsterId = parseNumber(row.monster_id, `partbreak row ${index + 1} monster_id`);
    const monsterName = (row.monster_name || '').trim() || `Monster ${monsterId}`;
    const itemId = parseNumber(row.item_id, `partbreak row ${index + 1} item_id`);
    const itemName = (row.item_name || '').trim() || `Item ${itemId}`;
    const rank = normalizeRank(row.rank);
    const chance = parseNumber(row.percentage, `partbreak row ${index + 1} percentage`);
    const quantity = parseNumber(row.quantity, `partbreak row ${index + 1} quantity`);

    if (row.partbreak_type === undefined || row.partbreak_type === null) {
      throw new Error(
        `partbreak row ${index + 1}: missing partbreak_type — run scripts/extract_partbreak_data.py`
      );
    }

    /** @type {AcquisitionMethod} */
    const method = {
      methodType,
      rank,
      sourceLabel: monsterName,
      chance,
      quantity,
      monsterId,
      monsterName,
      itemId,
      itemName,
      partbreakType: String(row.partbreak_type)
    };

    methods.push(method);
  }

  return methods.sort(compareMethods);
}

/**
 * @param {Record<string, string | number>[]} rows
 */
function buildMonsterNamesById(rows) {
  const namesById = new Map();

  for (const row of rows) {
    const monsterIdRaw = row.monster_id;
    const monsterId =
      typeof monsterIdRaw === 'number'
        ? Math.trunc(monsterIdRaw)
        : Number.parseInt(String(monsterIdRaw ?? '').trim(), 10);
    const monsterName = (row.monster_name || '').trim();
    if (!Number.isFinite(monsterId) || !monsterName) continue;
    if (!namesById.has(monsterId)) {
      namesById.set(monsterId, monsterName);
    }
  }

  return namesById;
}

/**
 * @param {Record<string, string>[]} rows
 * @param {{ id: number; name: string }[]} items
 * @param {Map<number, string>} monsterNamesById
 * @returns {AcquisitionMethod[]}
 */
function buildHardcoreCarveMethods(rows, items, monsterNamesById) {
  const itemNamesById = new Map(items.map((item) => [item.id, item.name]));
  const rankItemColumns = [
    { rank: 'lr', column: 'lr_item_id' },
    { rank: 'hr', column: 'hr_item_id' },
    { rank: 'hr100', column: 'hr100_item_id' }
  ];

  const methods = [];

  for (const [rowIndex, row] of rows.entries()) {
    const monsterId = parseNumber(row.monster_id, `hardcore carve row ${rowIndex + 1} monster_id`);
    const monsterName = monsterNamesById.get(monsterId) || `Monster ${monsterId}`;

    for (const { rank, column } of rankItemColumns) {
      const rawItemId = row[column];
      if (rawItemId === undefined || rawItemId === null || String(rawItemId).trim() === '') {
        continue;
      }

      const itemId = parseNumber(rawItemId, `hardcore carve row ${rowIndex + 1} ${column}`);
      methods.push({
        methodType: 'hardcore_carve',
        rank,
        sourceLabel: monsterName,
        chance: 2,
        quantity: 1,
        monsterId,
        monsterName,
        itemId,
        itemName: itemNamesById.get(itemId) || `Item ${itemId}`
      });
    }
  }

  return methods;
}

/**
 * @param {Record<string, string | number | null>[]} rows
 * @returns {AcquisitionMethod[]}
 */
function buildCarveMethods(rows) {
  /** @type {AcquisitionMethod[]} */
  const methods = [];

  for (const [index, row] of rows.entries()) {
    const monsterId = parseNumber(row.monster_id, `carve row ${index + 1} monster_id`);
    const monsterName = (row.monster_name || '').trim() || `Monster ${monsterId}`;
    const itemId = parseNumber(row.item_id, `carve row ${index + 1} item_id`);
    const itemName = (row.item_name || '').trim() || `Item ${itemId}`;
    const rank = normalizeRank(row.rank_label, 'carve source data');
    const chance = parseNumber(row.percentage, `carve row ${index + 1} percentage`);
    const sourceLabelRaw = String(row.source_label || '').trim();
    const sourceLabel = formatCarveSourceLabel(sourceLabelRaw, row.primary_num_carves, index + 1);
    if (!sourceLabel) {
      throw new Error(`carve row ${index + 1}: missing source_label — run scripts/extract_carve_data.py`);
    }

    methods.push({
      methodType: 'carve',
      rank,
      sourceLabel,
      chance,
      quantity: 1,
      monsterId,
      monsterName,
      itemId,
      itemName
    });
  }

  return methods.sort(compareMethods);
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
 * Body carve records include a primary_num_carves value in the source JSON.
 * Surface it in the UI label so players see expected carve count directly.
 *
 * @param {string} sourceLabel
 * @param {string | number | null | undefined} primaryNumCarvesRaw
 * @param {number} rowNumber
 * @returns {string}
 */
function formatCarveSourceLabel(sourceLabel, primaryNumCarvesRaw, rowNumber) {
  if (sourceLabel !== 'Body Carves') {
    return sourceLabel;
  }

  if (primaryNumCarvesRaw === undefined || primaryNumCarvesRaw === null || String(primaryNumCarvesRaw).trim() === '') {
    return sourceLabel;
  }

  const primaryNumCarves = parseNumber(primaryNumCarvesRaw, `carve row ${rowNumber} primary_num_carves`);
  if (primaryNumCarves <= 0) {
    return sourceLabel;
  }
  return `${sourceLabel} (${primaryNumCarves})`;
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
 * @param {string} [sourceLabel]
 */
function normalizeRank(value, sourceLabel = 'partbreak source data') {
  const rank = (value || '').trim().toLowerCase();
  if (!rank) {
    throw new Error(`Encountered empty rank in ${sourceLabel}`);
  }
  return rank;
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
 * @param {unknown} value
 * @param {string} label
 * @param {boolean} defaultValue
 */
function parseBoolean(value, label, defaultValue) {
  if (typeof value === 'boolean') return value;
  if (typeof value === 'number') return value !== 0;

  const normalized = String(value ?? '').trim().toLowerCase();
  if (!normalized) return defaultValue;
  if (normalized === 'true' || normalized === '1') return true;
  if (normalized === 'false' || normalized === '0') return false;
  throw new Error(`Invalid boolean value "${value}" for ${label}`);
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
