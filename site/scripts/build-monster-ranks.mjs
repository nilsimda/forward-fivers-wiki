import { access, constants } from 'node:fs/promises';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const siteRoot = path.resolve(__dirname, '..');
const repoRoot = path.resolve(siteRoot, '..');
const generatedDir = path.join(siteRoot, 'src', 'data', 'generated');
const monsterNamesPath = path.join(repoRoot, 'g1_data', 'monster_names.json');
const feriasMonsIndexPath = path.join(repoRoot, 'ferias_reference', 'mons', 'mons_h.htm');
const outPath = path.join(generatedDir, 'monster-ranks.json');

const RANK_KEYS = ['lr', 'hr', 'arena', 'hr100', 'gr'];

/**
 * G1 name -> Ferias carve page basename (without _h.htm), or null if no Ferias page.
 */
const NAME_TO_FERIAS_BASE = {
  Bulluk: 'brook',
  'Aqra Vashim': 'aqura',
  Belkuros: 'beru',
  Abiorg: 'abio',
  Draguros: 'doragyu',
  Grenzebul: 'guren',
  /** Black Fatalis: index lists "Fatalis" as plain text, not a link */
  Fatalis: 'mira',
  'Crimson Fatalis': 'miraval',
  'Old Fatalis': 'miraru',
  MaybeFelyne: 'airu',
  'Yama Tsukami2': 'yama',
  /** Ferias labels this "Unknown (ラ・ロ)" */
  Unknown: 'ra-ro',
  Pugis: null,
  'Veggie Elder': null,
  'Canyon Objects': null,
  'Canyon Rocks': null,
  Alpelo: null,
  Vorsphyroa: null,
  Levidiora: null,
  Falnocatrice: null,
  Argasioth: null,
  Aurisioth: null
};

function normalizeName(s) {
  return s
    .toLowerCase()
    .replace(/［.*?］/g, '')
    .replace(/\[.*?\]/g, '')
    .replace(/（.*?）/g, '')
    .replace(/[・\-']/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

/**
 * @param {string} html
 * @returns {Map<string, string>}
 */
function parseFeriasIndex(html) {
  const map = new Map();
  const re = /href="([a-zA-Z0-9_-]+)_h\.htm"[^>]*>([^<]+)/g;
  let m;
  while ((m = re.exec(html)) !== null) {
    const base = m[1];
    const label = m[2].replace(/^├|^└|^　/, '').trim();
    const key = normalizeName(label);
    if (key && !map.has(key)) {
      map.set(key, base);
    }
  }
  return map;
}

function stripBracketSuffix(monsname) {
  return monsname.replace(/\[[^\]]*\]/g, '').replace(/（[^）]*）/g, '').trim();
}

function thInnerText(raw) {
  return raw.replace(/<[^>]+>/g, '').replace(/&nbsp;/g, ' ').trim();
}

/**
 * Ferias carve pages use a header row with LR / HR / Arena / Elite / GR (and variants).
 * Some pages use broken HTML (duplicate <tr>); scan early <table> rows for rank-like <th> cells.
 *
 * @param {string} html
 * @returns {string[]}
 */
function parseCarveRankHeaders(html) {
  const body = html.split(/<\/body>/i)[0] ?? html;
  const tableMatch = body.match(/<table[^>]*>/i);
  if (!tableMatch || tableMatch.index === undefined) {
    return [];
  }
  const slice = body.slice(tableMatch.index, tableMatch.index + 12000);
  const rankHeader = /^(LR|HR\d*|HR|Arena|Elite|GR|Dual Threat|Zenith)/i;
  const trRe = /<tr[^>]*>([\s\S]*?)<\/tr>/gi;
  let best = [];
  let tr;
  while ((tr = trRe.exec(slice)) !== null) {
    const row = tr[1];
    const thRaw = [...row.matchAll(/<th[^>]*>([\s\S]*?)<\/th>/gi)].map((x) => thInnerText(x[1]));
    const texts = thRaw.filter(Boolean);
    const rankCells = texts.filter((t) => rankHeader.test(t));
    if (rankCells.length > best.length) {
      best = texts;
    }
    if (rankCells.length >= 2) {
      break;
    }
  }
  return best;
}

/**
 * @param {string[]} headers
 */
function headersToRanks(headers) {
  const set = new Set();
  const hasLrCol = headers.some((h) => h.trim() === 'LR');
  for (const h of headers) {
    const u = h.trim();
    if (u === 'LR') {
      set.add('lr');
    }
    if (/^HR\d/.test(u) || u === 'HR') {
      set.add('hr');
      if (hasLrCol) {
        set.add('lr');
      }
    }
    if (u === 'Arena') {
      set.add('arena');
    }
    if (u === 'Elite') {
      set.add('hr100');
    }
    if (u === 'GR') {
      set.add('gr');
    }
  }
  return set;
}

/**
 * @param {Set<string>} fromFerias
 */
function ranksForG1(fromFerias) {
  const out = {};
  for (const k of RANK_KEYS) {
    out[k] = fromFerias.has(k);
  }
  out.gr = false;
  return out;
}

function extractMonsname(html) {
  const m = html.match(/id\s*=\s*["']?monsname["']?\s*>([^<]+)/i);
  return m ? m[1].trim() : '';
}

async function main() {
  try {
    await access(feriasMonsIndexPath, constants.R_OK);
  } catch {
    console.warn(
      'Skipping monster-ranks generation: ferias_reference/mons/mons_h.htm not found (clone MHFZ-Ferias-English-Project into ferias_reference/ to regenerate).'
    );
    return;
  }

  const [namesRaw, indexHtml] = await Promise.all([
    readFile(monsterNamesPath, 'utf8'),
    readFile(feriasMonsIndexPath, 'utf8')
  ]);

  /** @type {Record<string, string>} */
  const monsterNames = JSON.parse(namesRaw);
  const feriasByNormName = parseFeriasIndex(indexHtml);

  /** @type {Record<string, unknown>} */
  const byId = {};

  const ids = Object.keys(monsterNames).sort((a, b) => Number(a) - Number(b));

  for (const id of ids) {
    const name = monsterNames[id];
    let base = NAME_TO_FERIAS_BASE[name];
    if (base === undefined) {
      base = feriasByNormName.get(normalizeName(name)) ?? null;
    }

    /** @type {Record<string, boolean>} */
    let ranks;
    /** @type {string[]} */
    const uncertainty = [];

    if (base === null) {
      ranks = { lr: true, hr: true, arena: true, hr100: true, gr: false };
      uncertainty.push(
        'No Ferias carve index entry in mons_h.htm; kept lr/hr/arena/hr100, gr false (G1 scope).'
      );
    } else {
      const carvePath = path.join(repoRoot, 'ferias_reference', 'mons', `${base}_h.htm`);
      let html;
      try {
        html = await readFile(carvePath, 'utf8');
      } catch {
        ranks = { lr: true, hr: true, arena: true, hr100: true, gr: false };
        uncertainty.push(`Ferias file ${base}_h.htm missing; using fallback ranks.`);
        byId[id] = {
          name,
          feriasCarvePage: `${base}_h.htm`,
          ranks,
          uncertainty
        };
        continue;
      }

      const monsnameRaw = extractMonsname(html);
      const monsname = stripBracketSuffix(monsnameRaw);

      if (
        monsname &&
        normalizeName(monsname) !== normalizeName(name) &&
        !(name === 'Rocks' && monsname === 'Rock')
      ) {
        uncertainty.push(
          `Ferias monsname "${monsnameRaw}" may not match G1 "${name}"; ranks taken from ${base}_h.htm carve columns.`
        );
      }

      const headers = parseCarveRankHeaders(html);
      const fromFerias = headersToRanks(headers);

      if (fromFerias.size === 0) {
        ranks = { lr: true, hr: true, arena: true, hr100: true, gr: false };
        uncertainty.push(
          'No carve rank columns parsed (empty or nonstandard table); assumed all G1 ranks except gr.'
        );
      } else {
        ranks = ranksForG1(fromFerias);
      }
    }

    const entry = {
      name,
      ranks
    };
    if (base !== null) {
      entry.feriasCarvePage = `${base}_h.htm`;
    }
    if (uncertainty.length) {
      entry.uncertainty = uncertainty;
    }
    byId[id] = entry;
  }

  const payload = {
    schema:
      'Per-monster rank flags from MHFZ Ferias English carve tables (mons/*_h.htm). lr/hr from LR and HR columns; arena from Arena when present; hr100 from Elite (HR100); gr is always false for this G1 wiki. Ferias is a newer game — treat as reference only.',
    ranks: RANK_KEYS,
    monsters: byId
  };

  await mkdir(generatedDir, { recursive: true });
  await writeFile(outPath, `${JSON.stringify(payload, null, 2)}\n`, 'utf8');
  console.log(`Wrote ${outPath} (${ids.length} monsters)`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
