import { defineCollection } from 'astro:content';
import { file } from 'astro/loaders';
import { z } from 'astro/zod';

const monsterIdSchema = z.number().int().min(1).max(120)
const itemIdSchema = z.number().int().min(1).max(7229)
const percentageSchema = z.number().int().min(0).max(100)


// CARVES
const carveDropSchema = z.object({
    percentage: percentageSchema,
    item_id: itemIdSchema,
    item_name: z.string(),
});

const carveTableSchema = z.object({
    label: z.string(),
    drops: z.array(carveDropSchema),
    num_carves: z.nullable(z.number().int().min(0).max(9)),
    trigger_chance: z.nullable(z.number().int().min(0).max(100)),
});

const monsterCarves = defineCollection({
    loader: file("src/data/generated/carves.json"),
    schema: z.object({
        id: monsterIdSchema,
        monster_name: z.string(),
        lr_cts: z.array(carveTableSchema),
        hr_cts: z.array(carveTableSchema),
        er_cts: z.array(carveTableSchema),
        gr_cts: z.array(carveTableSchema),
    }),
});

// PARTBREAKS
const partbreakDropSchema = z.object({
    percentage: percentageSchema,
    item_id: itemIdSchema,
    item_name: z.string(),
    quantity: z.number().int().min(1)
});

const partbreakTableSchema = z.object({
    partbreak_label: z.string(),
    drops: z.array(partbreakDropSchema),
});

const monsterPartbreaks = defineCollection({
    loader: file("src/data/generated/partbreaks.json"),
    schema: z.object({
        id: monsterIdSchema,
        monster_name: z.string(),
        lr_pts: z.array(partbreakTableSchema),
        hr_pts: z.array(partbreakTableSchema),
        er_pts: z.array(partbreakTableSchema),
        gr_pts: z.array(partbreakTableSchema),
    }),
});


// QUESTS
const questGoalSchema = z.object({
    target_kind: z.nullable(z.enum(["Hunt", "Capture", "Slay", "Damage", "Slay or Damage", "Slay All", "Slay Total", "Break Part", "Deliver", "Deliver Flag"])),
    target: z.number().int().min(0),
    count: z.number().int().min(0),

})

const questTextSchema = z.object({
    title: z.string(),
    main: z.string(),
    sub_a: z.string(),
    sub_b: z.string(),
    success_cond: z.string(),
    fail_cond: z.string(),
    contractor: z.string(),
    description: z.string(),

})

const rewardItemSchema = z.object({
    percentage: percentageSchema,
    item_id: itemIdSchema,
    item_name: z.string(),
    quantity: z.number().min(0).max(99),
    guaranteed: z.boolean(),
});

const rewardBoxesSchema = z.record(
    z.string(),
    z.array(rewardItemSchema)
);

const quests = defineCollection({
    loader: file("src/data/generated/quests.json"),
    schema: z.object({
        max_players: z.number().int().min(1).max(4),
        quest_fee: z.number().int().min(0),
        zenny_reward: z.number().int().min(0),
        zenny_ko: z.number().int().min(0),
        zenny_sub_a: z.number().int().min(0),
        zenny_sub_b: z.number().int().min(0),
        quest_time: z.number().int().min(0).max(90000),
        map_id: z.number().int().min(1),
        map: z.string(),
        restriction_flags: z.number().int().min(0),
        id: z.number().int().min(1),
        main_goal: questGoalSchema,
        subA_goal: questGoalSchema,
        subB_goal: questGoalSchema,
        join_min_rank: z.number().int().min(0).max(999),
        post_min_rank: z.number().int().min(0).max(999),
        quest_text: questTextSchema,
        rank: z.nullable(z.enum(["lr", "hr", "er", "gr"])),
        reward_boxes: rewardBoxesSchema,
        reward_variant: z.number().int().min(0),

    })
})


// ITEMS
const colorTagSegmentSchema = z.object({
    text: z.string(),
    colorCode: z.nullable(z.string()),
});

const carveAquisitionSchema = z.object({
    monster_id: monsterIdSchema,
    monster_name: z.string(),
    rank: z.enum(["lr", "hr", "er", "gr"]),
    label: z.string(),
    percentage: percentageSchema,
});

const partbreakAquisitionSchema = z.object({
    monster_id: monsterIdSchema,
    monster_name: z.string(),
    rank: z.enum(["lr", "hr", "er", "gr"]),
    label: z.string(),
    percentage: percentageSchema,
    quantity: z.number().int().min(1),
});

const questAquisitionSchema = z.object({
    quest_id: z.number().int().min(1),
    title: z.string(),
    main_objective: z.string(),
    rank: z.nullable(z.enum(["lr", "hr", "er", "gr"])),
    percentage: percentageSchema,
    quantity: z.number().int().min(0).max(99),
    reward_box_label: z.string(),
    guaranteed: z.boolean(),
});

const items = defineCollection({
    loader: file("src/data/generated/items.json"),
    schema: z.object({
        id: itemIdSchema,
        rarity: z.number().int().min(0),
        max_stack: z.number().int().min(0),
        icon_id: z.number().int().min(0),
        icon_color: z.number().int().min(0),
        buy_price: z.number().int().min(0),
        sell_price: z.number().int().min(0),
        item_type: z.number().int().min(0),
        is_gz: z.boolean(),
        name: z.string(),
        description: z.string(),
        descriptionSegments: z.array(colorTagSegmentSchema),
        carve_aquisitions: z.array(carveAquisitionSchema),
        partbreak_aquisitions: z.array(partbreakAquisitionSchema),
        quest_aquisitions: z.array(questAquisitionSchema),
    })
})

// DECOS
const decoCraftItemSchema = z.object({
    item_id: itemIdSchema,
    name: z.string(),
    quantity: z.number().int().min(1),
    needed_for_unlock: z.boolean(),
});

const decoSkillSchema = z.object({
    id: z.number().int().min(0),
    name: z.string(),
    points: z.number().int(),
});

const decoStatsSchema = z.object({
    n_slots: z.number().int().min(0),
    price: z.number().int().min(0),
    skills: z.array(decoSkillSchema),
});

const decos = defineCollection({
    loader: file("src/data/generated/decos.json"),
    schema: z.object({
        id: itemIdSchema,
        name: z.string(),
        receipt_category: z.number().int().min(0),
        craft_recipes: z.array(z.array(decoCraftItemSchema)),
        stats: decoStatsSchema,
    }),
});

export const collections = { monsterCarves, monsterPartbreaks, quests, items, decos };
