import GLPK from 'https://cdn.jsdelivr.net/npm/glpk.js@5.0.0/dist/index.js';

const glpkPromise = GLPK();

let DATA = null;

const RANKS = ['G', 'F', 'E', 'D', 'C', 'B', 'A', 'S'];
const RANK_VALUE = Object.fromEntries(RANKS.map((r, i) => [r, i]));
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const HALVES = ['Early', 'Late'];
const YEARS = ['Junior', 'Classic', 'Senior'];
const COUNTRY_WORDS = ['Saudi Arabia', 'Argentina', 'American', 'New Zealand', 'Japan '];
const KANTO_TRACKS = new Set(['Tokyo', 'Nakayama', 'Ooi', 'Oi']);
const WEST_TRACKS = new Set(['Chukyo', 'Chukyu', 'Hanshin', 'Kyoto']);
const TOHOKU_TRACKS = new Set(['Fukushima', 'Niigata']);
const HOKKAIDO_TRACKS = new Set(['Sapporo', 'Hakodate']);
const KOKURA_TRACKS = new Set(['Kokura']);

function isStandardDistance(race) {
  return Number.isFinite(race.length) && race.length > 0 && race.length % 400 === 0;
}

const BASE_REWARD = {
  G1: { stats: 10, sp: 35, fans: 10000 },
  G2: { stats: 8, sp: 25, fans: 6000 },
  G3: { stats: 8, sp: 25, fans: 4500 },
  OP: { stats: 5, sp: 15, fans: 2400 },
  'Pre-OP': { stats: 5, sp: 10, fans: 1300 }
};
const NO_RACE = '[No race]';
const AUTO = 'Auto';

// Default summer training blocks (no-race turns).
// Junior: Early Jul → Early Aug; Classic & Senior: Early Jul → Late Aug.
const DEFAULT_SUMMER_BLOCKS = [
  12, 13, 14,           // Junior Jul-E, Jul-L, Aug-E
  36, 37, 38, 39,       // Classic Jul-E, Jul-L, Aug-E, Aug-L
  60, 61, 62, 63        // Senior Jul-E, Jul-L, Aug-E, Aug-L
];

async function loadData() {
  if (DATA) return DATA;
  const _tbBase = new URL('.', import.meta.url);
  const [races, epithets, debutRaces, glpk] = await Promise.all([
    fetch(new URL('races.json', _tbBase)).then(r => r.json()),
    fetch(new URL('epithets.json', _tbBase)).then(r => r.json()),
    Promise.resolve({}),
    glpkPromise
  ]);

  const epithetByName = Object.fromEntries(epithets.map(e => [e.name, e]));
  const windows = [];
  for (const year of YEARS) {
    for (const month of MONTHS) {
      for (const half of HALVES) {
        const period = `${half} ${month}`;
        const windowRaces = races
          .filter(r => r.year === year && r.period === period)
          .sort((a, b) => {
            const gradeCmp = String(a.grade).localeCompare(String(b.grade));
            return gradeCmp || String(a.name).localeCompare(String(b.name));
          });
        windows.push({
          index: windows.length,
          year,
          month,
          half,
          period,
          label: `${year} ${period}`,
          races: windowRaces
        });
      }
    }
  }

  DATA = { races, epithets, epithetByName, windows, debutRaces, glpk };
  return DATA;
}

// The Junior Late-Jun debut race is auto-run by the player. It is Pre-OP grade
// (so doesn't count toward graded-race epithets), but does contribute to
// distance/surface/Pro Racer/Turf Tussler counters.
function debutRaceFor(settings, data) {
  const preset = settings?.preset;
  if (!preset || !data?.debutRaces) return null;
  const debut = data.debutRaces[preset];
  if (!debut) return null;
  return {
    name: debut.name,
    grade: 'Pre-OP',
    distance: debut.distance,
    surface: debut.surface,
    track: debut.track,
    length: debut.length,
    period: 'Late Jun',
    year: 'Junior',
    fans: 50,
    is_debut: true,
  };
}

function defaultSettings() {
  return {
    preset: '',
    aptitudes: { Sprint: 'A', Mile: 'A', Medium: 'A', Long: 'A', Turf: 'A', Dirt: 'G' },
    threshold: 'C',
    race_bonus_pct: 50.0,
    stat_weight: 1.0,
    sp_weight: 1.0,
    hint_weight: 8.0,
    epithet_multiplier: 1.0,
    three_race_penalty_weight: 3.0,
    max_consecutive_races: 0,
    race_cost: 100,
    fan_bonus_pct: 0,
    forced_epithets: [],
    forced_climax: '',
    include_op: false
  };
}

function normalizeSettings(settings = null) {
  const s = defaultSettings();
  if (settings) {
    Object.assign(s, settings);
    if (settings.aptitudes) {
      s.aptitudes = { ...s.aptitudes, ...settings.aptitudes };
    }
  }
  for (const key of ['race_bonus_pct', 'stat_weight', 'sp_weight', 'hint_weight', 'epithet_multiplier', 'three_race_penalty_weight', 'race_cost', 'fan_bonus_pct']) {
    s[key] = Number(s[key] ?? 0);
  }
  s.max_consecutive_races = Number(s.max_consecutive_races ?? 0);
  return s;
}

const OP_GRADES = new Set(['OP', 'Pre-OP']);

function raceIsEligible(race, settings) {
  if (OP_GRADES.has(race.grade) && !settings.include_op) return false;
  const threshold = RANK_VALUE[settings.threshold];
  const apt = settings.aptitudes;
  return RANK_VALUE[apt[race.distance]] >= threshold && RANK_VALUE[apt[race.surface]] >= threshold;
}

function raceReward(race, raceBonusPct) {
  const base = BASE_REWARD[race.grade];
  if (!base) return { stats: 0, sp: 0 };
  const rb = Math.max(0, raceBonusPct) / 100.0;
  return {
    stats: Math.floor(base.stats * (1 + rb)),
    sp: Math.floor(base.sp * (1 + rb))
  };
}

function g2g3Baseline(settings) {
  const base = BASE_REWARD['G2'];
  const rb = Math.max(0, settings.race_bonus_pct) / 100.0;
  return settings.stat_weight * Math.floor(base.stats * (1 + rb)) + settings.sp_weight * Math.floor(base.sp * (1 + rb));
}

function weightedRaceValue(race, settings) {
  const { stats, sp } = raceReward(race, settings.race_bonus_pct);
  const cost = Number(settings.race_cost || 0) / 100.0 * g2g3Baseline(settings);
  return { stats, sp, value: settings.stat_weight * stats + settings.sp_weight * sp - cost };
}

function epithetStatTotal(epithetName, data) {
  const e = data.epithetByName[epithetName];
  if (!e || e.reward_kind !== 'stat') return 0;
  // epithets.json already stores the total stat value (for example 30 for "+15 to 2 random stats").
  return Number(e.amount || 0);
}

function epithetObjectiveValue(epithetName, settings, data) {
  const e = data.epithetByName[epithetName];
  if (!e) return 0;
  if (e.reward_kind === 'stat') {
    return settings.epithet_multiplier * settings.stat_weight * epithetStatTotal(epithetName, data);
  }
  return settings.epithet_multiplier * settings.hint_weight * Number(e.amount || 0);
}

function hintSkillName(epithetName, data) {
  const rewardText = String(data.epithetByName[epithetName]?.reward_text || '').trim();
  const match = rewardText.match(/^(.*?)\s+hint\b/i);
  return (match ? match[1] : rewardText).trim();
}

function countSelected(selectedRaces, predicate) {
  let count = 0;
  for (const race of selectedRaces) if (predicate(race)) count += 1;
  return count;
}

function selectedCounts(selectedRaces) {
  const byName = new Map();
  const byYearName = new Map();
  const inc = (map, key) => map.set(key, (map.get(key) || 0) + 1);

  for (const r of selectedRaces) {
    inc(byName, r.name);
    inc(byYearName, `${r.year}||${r.name}`);
  }

  return {
    byName,
    byYearName,
    standard: countSelected(selectedRaces, r => isStandardDistance(r)),
    nonstandard: countSelected(selectedRaces, r => !isStandardDistance(r)),
    dirt: countSelected(selectedRaces, r => r.surface === 'Dirt'),
    dirt_g1: countSelected(selectedRaces, r => r.surface === 'Dirt' && r.grade === 'G1'),
    op_plus: countSelected(selectedRaces, r => ['G1', 'G2', 'G3', 'OP', 'Pre-OP'].includes(r.grade)),
    junior_stakes: countSelected(selectedRaces, r => String(r.name).includes('Junior Stakes')),
    country: countSelected(selectedRaces, r => COUNTRY_WORDS.some(word => String(r.name).includes(word))),
    umamusume_stakes: countSelected(selectedRaces, r => String(r.name).includes('Umamusume Stakes')),
    turf_sprint: selectedRaces.some(r => r.surface === 'Turf' && r.distance === 'Sprint'),
    turf_mile: selectedRaces.some(r => r.surface === 'Turf' && r.distance === 'Mile'),
    turf_medium: selectedRaces.some(r => r.surface === 'Turf' && r.distance === 'Medium'),
    turf_long: selectedRaces.some(r => r.surface === 'Turf' && r.distance === 'Long'),
    dirt_sprint: selectedRaces.some(r => r.surface === 'Dirt' && r.distance === 'Sprint'),
    dirt_mile: selectedRaces.some(r => r.surface === 'Dirt' && r.distance === 'Mile'),
    dirt_medium: selectedRaces.some(r => r.surface === 'Dirt' && r.distance === 'Medium'),
    kanto: countSelected(selectedRaces, r => ['G1', 'G2', 'G3'].includes(r.grade) && KANTO_TRACKS.has(r.track)),
    west: countSelected(selectedRaces, r => ['G1', 'G2', 'G3'].includes(r.grade) && WEST_TRACKS.has(r.track)),
    tohoku: countSelected(selectedRaces, r => ['G1', 'G2', 'G3'].includes(r.grade) && TOHOKU_TRACKS.has(r.track)),
    hokkaido: countSelected(selectedRaces, r => ['G1', 'G2', 'G3'].includes(r.grade) && HOKKAIDO_TRACKS.has(r.track)),
    kokura: countSelected(selectedRaces, r => ['G1', 'G2', 'G3'].includes(r.grade) && KOKURA_TRACKS.has(r.track))
  };
}

function hasRaceAny(counts, raceName) {
  return (counts.byName.get(raceName) || 0) >= 1;
}

function hasRaceYear(counts, year, raceName) {
  return (counts.byYearName.get(`${year}||${raceName}`) || 0) >= 1;
}

function completedEpithets(selectedRaces, data) {
  const counts = selectedCounts(selectedRaces);
  const done = new Set();

  const stunning = ['Satsuki Sho', 'Japanese Derby (Tokyo Yushun)', 'Kikuka Sho'].every(n => hasRaceYear(counts, 'Classic', n));
  const lady = ['Oka Sho', 'Japanese Oaks', 'Shuka Sho'].every(n => hasRaceYear(counts, 'Classic', n));
  const springChampion = hasRaceYear(counts, 'Senior', 'Osaka Hai') && hasRaceYear(counts, 'Senior', 'Tenno Sho (Spring)') && hasRaceAny(counts, 'Takarazuka Kinen');
  const fallChampion = ['Tenno Sho (Autumn)', 'Japan Cup', 'Arima Kinen'].every(n => hasRaceYear(counts, 'Senior', n));

  if (stunning) done.add('Stunning');
  if (lady) done.add('Lady');
  if (springChampion) done.add('Spring Champion');
  if (fallChampion) done.add('Fall Champion');
  if (hasRaceYear(counts, 'Senior', 'Tenno Sho (Spring)') && hasRaceYear(counts, 'Senior', 'Tenno Sho (Autumn)')) done.add('Shield Bearer');
  if (stunning && (hasRaceYear(counts, 'Classic', 'Japan Cup') || hasRaceYear(counts, 'Classic', 'Arima Kinen'))) done.add('Incredible');

  const phenomenalCount = ['Tenno Sho (Spring)', 'Takarazuka Kinen', 'Japan Cup', 'Tenno Sho (Autumn)', 'Osaka Hai', 'Arima Kinen']
    .filter(raceName => hasRaceAny(counts, raceName)).length;
  if (stunning && phenomenalCount >= 2) done.add('Phenomenal');

  if (['NHK Mile Cup', 'Yasuda Kinen', 'Mile Championship'].every(raceName => hasRaceAny(counts, raceName))) done.add('Breakneck Miler');
  if (lady && hasRaceYear(counts, 'Classic', 'Queen Elizabeth II Cup')) done.add('Heroine');
  if (
    lady &&
    hasRaceYear(counts, 'Junior', 'Hanshin Juvenile Fillies') &&
    hasRaceYear(counts, 'Senior', 'Victoria Mile') &&
    hasRaceYear(counts, 'Classic', 'Queen Elizabeth II Cup') &&
    hasRaceYear(counts, 'Senior', 'Queen Elizabeth II Cup')
  ) done.add('Goddess');
  if (hasRaceAny(counts, 'Takamatsunomiya Kinen') && hasRaceAny(counts, 'Sprinters Stakes')) done.add('Sprint Go-Getter');
  if (
    hasRaceAny(counts, 'Takamatsunomiya Kinen') &&
    hasRaceAny(counts, 'Sprinters Stakes') &&
    hasRaceAny(counts, 'Yasuda Kinen') &&
    hasRaceAny(counts, 'Mile Championship')
  ) done.add('Sprint Speedster');
  if (
    hasRaceYear(counts, 'Classic', 'Oka Sho') &&
    hasRaceAny(counts, 'NHK Mile Cup') &&
    hasRaceAny(counts, 'Yasuda Kinen') &&
    hasRaceYear(counts, 'Senior', 'Victoria Mile') &&
    hasRaceAny(counts, 'Mile Championship') &&
    (hasRaceYear(counts, 'Junior', 'Hanshin Juvenile Fillies') || hasRaceYear(counts, 'Junior', 'Asahi Hai Futurity Stakes'))
  ) done.add('Mile a Minute');

  if (counts.dirt_g1 >= 3) done.add('Dirt G1 Achiever');
  if (counts.dirt_g1 >= 4) done.add('Dirt G1 Star');
  if (counts.dirt_g1 >= 5) done.add('Dirt G1 Powerhouse');
  if (counts.dirt_g1 >= 9) done.add('Dirt G1 Dominator');
  if (counts.standard >= 10) done.add('Standard Distance Leader');
  if (counts.nonstandard >= 10) done.add('Non-Standard Distance Leader');
  if (counts.dirt >= 5) done.add('Dirty Work');
  if (counts.dirt >= 10) done.add('Playing Dirty');
  if (counts.dirt >= 15) done.add('Eat My Dust');
  if (counts.op_plus >= 10) done.add('Pro Racer');
  if (counts.junior_stakes >= 3) done.add('Junior Jewel');
  if (counts.country >= 3) done.add('Globe-Trotter');
  if (counts.umamusume_stakes >= 3) done.add('Umatastic');
  if (counts.dirt_sprint && counts.dirt_mile && counts.dirt_medium) done.add('Dirt Dancer');
  if (counts.turf_sprint && counts.turf_mile && counts.turf_medium && counts.turf_long) done.add('Turf Tussler');
  if (hasRaceYear(counts, 'Classic', 'JBC Sprint') && hasRaceYear(counts, 'Senior', 'JBC Sprint')) done.add('Dirt Sprinter');
  if (['Unicorn Stakes', 'Leopard Stakes', 'Japan Dirt Derby'].every(raceName => hasRaceYear(counts, 'Classic', raceName))) done.add('Kicking Up Dust');
  if (counts.kanto >= 3) done.add('Kanto Conqueror');
  if (counts.west >= 3) done.add('West Japan Whiz');
  if (counts.tohoku >= 3) done.add('Tohoku Top Dog');
  if (counts.hokkaido >= 3) done.add('Hokkaido Hotshot');
  if (counts.kokura >= 2) done.add('Kokura Constable');
  if (springChampion && fallChampion && (stunning || lady)) done.add('Legendary');

  return data.epithets.filter(e => done.has(e.name)).map(e => e.name);
}

// For each completed epithet, return the predicate that matches contributing races.
function epithetRacePredicates(completedNames) {
  const preds = {};
  const has = name => completedNames.includes(name);

  if (has('Stunning')) preds['Stunning'] = r => r.year === 'Classic' && ['Satsuki Sho', 'Japanese Derby (Tokyo Yushun)', 'Kikuka Sho'].includes(r.name);
  if (has('Lady')) preds['Lady'] = r => r.year === 'Classic' && ['Oka Sho', 'Japanese Oaks', 'Shuka Sho'].includes(r.name);
  if (has('Spring Champion')) preds['Spring Champion'] = r => (r.year === 'Senior' && ['Osaka Hai', 'Tenno Sho (Spring)'].includes(r.name)) || r.name === 'Takarazuka Kinen';
  if (has('Fall Champion')) preds['Fall Champion'] = r => r.year === 'Senior' && ['Tenno Sho (Autumn)', 'Japan Cup', 'Arima Kinen'].includes(r.name);
  if (has('Shield Bearer')) preds['Shield Bearer'] = r => r.year === 'Senior' && ['Tenno Sho (Spring)', 'Tenno Sho (Autumn)'].includes(r.name);
  if (has('Incredible')) preds['Incredible'] = r =>
    (r.year === 'Classic' && ['Satsuki Sho', 'Japanese Derby (Tokyo Yushun)', 'Kikuka Sho', 'Japan Cup', 'Arima Kinen'].includes(r.name));
  if (has('Phenomenal')) preds['Phenomenal'] = r =>
    (r.year === 'Classic' && ['Satsuki Sho', 'Japanese Derby (Tokyo Yushun)', 'Kikuka Sho'].includes(r.name)) ||
    ['Tenno Sho (Spring)', 'Takarazuka Kinen', 'Japan Cup', 'Tenno Sho (Autumn)', 'Osaka Hai', 'Arima Kinen'].includes(r.name);
  if (has('Breakneck Miler')) preds['Breakneck Miler'] = r => ['NHK Mile Cup', 'Yasuda Kinen', 'Mile Championship'].includes(r.name);
  if (has('Heroine')) preds['Heroine'] = r =>
    (r.year === 'Classic' && ['Oka Sho', 'Japanese Oaks', 'Shuka Sho', 'Queen Elizabeth II Cup'].includes(r.name));
  if (has('Goddess')) preds['Goddess'] = r =>
    (r.year === 'Classic' && ['Oka Sho', 'Japanese Oaks', 'Shuka Sho', 'Queen Elizabeth II Cup'].includes(r.name)) ||
    (r.year === 'Junior' && r.name === 'Hanshin Juvenile Fillies') ||
    (r.year === 'Senior' && ['Victoria Mile', 'Queen Elizabeth II Cup'].includes(r.name));
  if (has('Sprint Go-Getter')) preds['Sprint Go-Getter'] = r => ['Takamatsunomiya Kinen', 'Sprinters Stakes'].includes(r.name);
  if (has('Sprint Speedster')) preds['Sprint Speedster'] = r => ['Takamatsunomiya Kinen', 'Sprinters Stakes', 'Yasuda Kinen', 'Mile Championship'].includes(r.name);
  if (has('Mile a Minute')) preds['Mile a Minute'] = r =>
    (r.year === 'Classic' && r.name === 'Oka Sho') ||
    ['NHK Mile Cup', 'Yasuda Kinen', 'Mile Championship'].includes(r.name) ||
    (r.year === 'Senior' && r.name === 'Victoria Mile') ||
    (r.year === 'Junior' && ['Hanshin Juvenile Fillies', 'Asahi Hai Futurity Stakes'].includes(r.name));

  if (has('Dirt G1 Achiever') || has('Dirt G1 Star') || has('Dirt G1 Powerhouse') || has('Dirt G1 Dominator')) {
    const best = has('Dirt G1 Dominator') ? 'Dirt G1 Dominator' : has('Dirt G1 Powerhouse') ? 'Dirt G1 Powerhouse' : has('Dirt G1 Star') ? 'Dirt G1 Star' : 'Dirt G1 Achiever';
    preds[best] = r => r.surface === 'Dirt' && r.grade === 'G1';
    // Remove lesser tiers if the best is set
    for (const n of ['Dirt G1 Achiever','Dirt G1 Star','Dirt G1 Powerhouse','Dirt G1 Dominator']) {
      if (n !== best && has(n)) preds[n] = preds[best];
    }
  }

  if (has('Standard Distance Leader')) preds['Standard Distance Leader'] = r => isStandardDistance(r);
  if (has('Non-Standard Distance Leader')) preds['Non-Standard Distance Leader'] = r => !isStandardDistance(r);
  if (has('Eat My Dust')) preds['Eat My Dust'] = r => r.surface === 'Dirt';
  else if (has('Playing Dirty')) preds['Playing Dirty'] = r => r.surface === 'Dirt';
  else if (has('Dirty Work')) preds['Dirty Work'] = r => r.surface === 'Dirt';
  if (has('Pro Racer')) preds['Pro Racer'] = r => ['G1', 'G2', 'G3', 'OP', 'Pre-OP'].includes(r.grade);
  if (has('Junior Jewel')) preds['Junior Jewel'] = r => String(r.name).includes('Junior Stakes');
  if (has('Globe-Trotter')) preds['Globe-Trotter'] = r => COUNTRY_WORDS.some(w => String(r.name).includes(w));
  if (has('Umatastic')) preds['Umatastic'] = r => String(r.name).includes('Umamusume Stakes');
  if (has('Dirt Dancer')) preds['Dirt Dancer'] = r => r.surface === 'Dirt' && ['Sprint', 'Mile', 'Medium'].includes(r.distance);
  if (has('Turf Tussler')) preds['Turf Tussler'] = r => r.surface === 'Turf' && ['Sprint', 'Mile', 'Medium', 'Long'].includes(r.distance);
  if (has('Dirt Sprinter')) preds['Dirt Sprinter'] = r => r.year && r.name === 'JBC Sprint';
  if (has('Kicking Up Dust')) preds['Kicking Up Dust'] = r => r.year === 'Classic' && ['Unicorn Stakes', 'Leopard Stakes', 'Japan Dirt Derby'].includes(r.name);
  if (has('Kanto Conqueror')) preds['Kanto Conqueror'] = r => ['G1','G2','G3'].includes(r.grade) && KANTO_TRACKS.has(r.track);
  if (has('West Japan Whiz')) preds['West Japan Whiz'] = r => ['G1','G2','G3'].includes(r.grade) && WEST_TRACKS.has(r.track);
  if (has('Tohoku Top Dog')) preds['Tohoku Top Dog'] = r => ['G1','G2','G3'].includes(r.grade) && TOHOKU_TRACKS.has(r.track);
  if (has('Hokkaido Hotshot')) preds['Hokkaido Hotshot'] = r => ['G1','G2','G3'].includes(r.grade) && HOKKAIDO_TRACKS.has(r.track);
  if (has('Kokura Constable')) preds['Kokura Constable'] = r => ['G1','G2','G3'].includes(r.grade) && KOKURA_TRACKS.has(r.track);
  if (has('Legendary')) preds['Legendary'] = r =>
    (r.year === 'Classic' && ['Satsuki Sho','Japanese Derby (Tokyo Yushun)','Kikuka Sho','Oka Sho','Japanese Oaks','Shuka Sho'].includes(r.name)) ||
    (r.year === 'Senior' && ['Osaka Hai','Tenno Sho (Spring)','Takarazuka Kinen','Tenno Sho (Autumn)','Japan Cup','Arima Kinen'].includes(r.name));

  return preds;
}

// Build map: windowIndex → [epithet names this race contributes to] (for ALL contributing races)
function buildFullEpithetMap(scheduleRows, selectedRaces, completedEpithetNames) {
  const preds = epithetRacePredicates(completedEpithetNames);
  const map = {};
  for (const row of scheduleRows) {
    if (row.selected === NO_RACE || row.lost) continue;
    const race = selectedRaces.find(r => r.name === row.selected && r.year === row.year);
    if (!race) continue;
    const matching = [];
    for (const [epName, pred] of Object.entries(preds)) {
      if (pred(race)) matching.push(epName);
    }
    if (matching.length) map[row.index] = matching;
  }
  return map;
}

function removeSelectedRaceOnce(selectedRaces, targetIndex) {
  return selectedRaces.filter((_, idx) => idx !== targetIndex);
}

function linkedEpithetsForSelectedRace(selectedRaces, selectedIndex, solvedEpithets, settings, data) {
  const reduced = removeSelectedRaceOnce(selectedRaces, selectedIndex);
  const reducedEpithets = new Set(completedEpithets(reduced, data));
  const linked = solvedEpithets.filter(name => !reducedEpithets.has(name));
  const linkedValue = linked.reduce((sum, name) => sum + epithetObjectiveValue(name, settings, data), 0);
  return { linked, linkedValue: Number(linkedValue.toFixed(2)) };
}

function epithetsWeightedValue(epithets, settings, data) {
  return Number(epithets.reduce((sum, name) => sum + epithetObjectiveValue(name, settings, data), 0).toFixed(2));
}

function buildActions(settings, windows, forcedChoiceNames = {}) {
  return windows.map(window => {
    const forcedName = forcedChoiceNames[window.index];
    const actions = [{ kind: 'none', choice: NO_RACE, race: null, stats: 0, sp: 0, value: 0 }];
    for (const race of window.races) {
      if (!raceIsEligible(race, settings) && forcedName !== race.name) continue;
      const { stats, sp, value } = weightedRaceValue(race, settings);
      actions.push({ kind: 'race', choice: race.name, race, stats, sp, value });
    }
    return actions;
  });
}

function addConstraint(model, glpk, name, coeffs, kind, lb = 0, ub = 0) {
  model.subjectTo.push({
    name,
    vars: coeffs.map(([varName, coef]) => ({ name: varName, coef })),
    bnds: { type: kind, lb, ub }
  });
}

function statusToText(status, glpk) {
  switch (status) {
    case glpk.GLP_OPT: return 'OPTIMAL';
    case glpk.GLP_FEAS: return 'FEASIBLE';
    case glpk.GLP_INFEAS: return 'INFEASIBLE';
    case glpk.GLP_NOFEAS: return 'NO FEASIBLE SOLUTION';
    case glpk.GLP_UNBND: return 'UNBOUNDED';
    case glpk.GLP_UNDEF:
    default:
      return 'UNDEFINED';
  }
}

function varsToCoeffPairs(varsObj) {
  return Object.entries(varsObj).filter(([, coef]) => Math.abs(coef) > 1e-12);
}

function mergeExprs(...exprs) {
  const merged = {};
  for (const expr of exprs) {
    for (const [k, v] of Object.entries(expr || {})) merged[k] = (merged[k] || 0) + v;
  }
  return merged;
}

async function optimizeSchedule(settingsInput = null, fixedChoices = {}, lostIndices = []) {
  const data = await loadData();
  const { windows, epithets, glpk } = data;
  const settings = normalizeSettings(settingsInput);
  const fixed = Object.fromEntries(Object.entries(fixedChoices || {}).map(([k, v]) => [Number(k), v]));
  const lostSet = new Set((lostIndices || []).map(Number));

  // When forced epithets are active, convert summer "[No race]" locks into soft penalties
  // so the solver can use those slots if needed (summer training is very valuable).
  const summerSet = new Set(DEFAULT_SUMMER_BLOCKS);
  const softenedSummerWindows = new Set();
  if (settings.forced_epithets && settings.forced_epithets.length) {
    for (const idx of summerSet) {
      if (fixed[idx] === NO_RACE) {
        delete fixed[idx];
        softenedSummerWindows.add(idx);
      }
    }
  }

  const actionsByWindow = buildActions(settings, windows, fixed);

  // Mark "lost retry" race actions: they occupy the slot for consecutive-race
  // and climax counting, but contribute no stats/SP and don't count for epithets.
  for (const idx of lostSet) {
    const lockedName = fixed[idx];
    if (!lockedName || lockedName === NO_RACE) continue;
    const bucket = actionsByWindow[idx];
    if (!bucket) continue;
    const match = bucket.find(a => a.race && a.choice === lockedName);
    if (match) {
      match.lost = true;
      match.stats = 0;
      match.sp = 0;
      match.value = 0;
    }
  }

  const xVars = [];
  const actionLookup = new Map();
  for (let i = 0; i < actionsByWindow.length; i += 1) {
    for (let j = 0; j < actionsByWindow[i].length; j += 1) {
      const name = `x_${i}_${j}`;
      xVars.push(name);
      actionLookup.set(name, { window: i, actionIndex: j, ...actionsByWindow[i][j] });
    }
  }

  const yVars = epithets.map(e => `y_${e.name}`);
  const zVars = [];
  for (let start = 0; start < Math.max(0, actionsByWindow.length - 2); start += 1) {
    zVars.push(`z_${start}`);
  }

  // Summer training penalty: racing during summer camp costs heavily because
  // summer is the primary training window in a career. Scale off the G2/G3
  // baseline so the penalty stays proportional to other scoring weights.
  const summerPenalty = softenedSummerWindows.size > 0
    ? g2g3Baseline(settings) * 3
    : 0;

  // Tiny tiebreaker: among solutions with equal primary value, prefer more races.
  // Scaled small enough (0.001) to never override a real scoring difference.
  const RACE_TIEBREAK_EPSILON = 0.001;

  const objectiveVars = [];
  for (const name of xVars) {
    const info = actionLookup.get(name);
    let coef = info.value;
    if (info.race) coef += RACE_TIEBREAK_EPSILON;
    // Apply summer penalty to race actions in softened summer windows
    if (summerPenalty > 0 && softenedSummerWindows.has(info.window) && info.race) {
      coef -= summerPenalty;
    }
    objectiveVars.push({ name, coef });
  }
  for (const e of epithets) {
    objectiveVars.push({ name: `y_${e.name}`, coef: epithetObjectiveValue(e.name, settings, data) });
  }
  // Late Dec windows (last half of each year) don't cause conditioning penalty,
  // so skip the 3-race penalty when the 3rd consecutive race lands there.
  const LATE_DEC_WINDOWS = new Set([23, 47, 71]);
  for (let idx = 0; idx < zVars.length; idx += 1) {
    const thirdWindow = idx + 2;
    const coef = LATE_DEC_WINDOWS.has(thirdWindow) ? 0 : -settings.three_race_penalty_weight;
    objectiveVars.push({ name: zVars[idx], coef });
  }

  const model = {
    name: 'TrackblazerPlanner',
    objective: {
      direction: glpk.GLP_MAX,
      name: 'score',
      vars: objectiveVars
    },
    subjectTo: [],
    bounds: [],
    binaries: [...xVars, ...yVars, ...zVars]
  };

  const varsForWindow = i => actionsByWindow[i].map((_, j) => `x_${i}_${j}`);
  const raceVarsByWindow = Object.fromEntries(actionsByWindow.map((actions, i) => [
    i,
    actions
      .map((action, j) => ({ action, name: `x_${i}_${j}` }))
      .filter(item => item.action.race !== null)
      .map(item => item.name)
  ]));

  function actionSum(predicate) {
    const coeffs = {};
    for (const [varName, info] of actionLookup.entries()) {
      if (info.race && !info.lost && predicate(info.race)) coeffs[varName] = (coeffs[varName] || 0) + 1;
    }
    return coeffs;
  }

  function exprRaceAny(raceName) {
    return actionSum(r => r.name === raceName);
  }

  function exprRaceYear(year, raceName) {
    return actionSum(r => r.year === year && r.name === raceName);
  }

  function exprEpithet(name) {
    return { [`y_${name}`]: 1 };
  }

  // The Junior Late-Jun debut race is auto-run and may satisfy some epithet
  // predicates (distance/surface/Pro Racer counters). Where it does, we reduce
  // the corresponding LP threshold by 1 (or skip a "race must exist" constraint
  // outright) and we prepend it to selectedRaces post-solve.
  const debutRace = debutRaceFor(settings, data);
  function debutBonus(predicate) {
    return debutRace && predicate(debutRace) ? 1 : 0;
  }

  function requireYLeqExpr(yName, exprCoeffs, debutContrib = 0) {
    if (debutContrib >= 1) return;
    const coeffs = { ...exprCoeffs, [`y_${yName}`]: (exprCoeffs[`y_${yName}`] || 0) - 1 };
    addConstraint(model, glpk, `req_${yName}_${model.subjectTo.length}`, varsToCoeffPairs(coeffs), glpk.GLP_LO, 0, 0);
  }

  function requireCountThreshold(yName, exprCoeffs, threshold, debutContrib = 0) {
    const effectiveThreshold = Math.max(0, threshold - debutContrib);
    const coeffs = { ...exprCoeffs, [`y_${yName}`]: (exprCoeffs[`y_${yName}`] || 0) - effectiveThreshold };
    addConstraint(model, glpk, `cnt_${yName}_${model.subjectTo.length}`, varsToCoeffPairs(coeffs), glpk.GLP_LO, 0, 0);
  }

  // Exactly one action per window.
  for (let i = 0; i < actionsByWindow.length; i += 1) {
    addConstraint(model, glpk, `one_action_${i}`, varsForWindow(i).map(name => [name, 1]), glpk.GLP_FX, 1, 1);
  }

  // Max consecutive races hard cap.
  // Locked races count toward the cap — only constrain the remaining non-locked slots.
  const maxConsec = Number(settings.max_consecutive_races || 0);
  if (maxConsec > 0) {
    const fixedRaceIndices = new Set(
      Object.entries(fixed)
        .filter(([, v]) => v !== NO_RACE)
        .map(([k]) => Number(k))
    );
    for (let start = 0; start < actionsByWindow.length - maxConsec; start += 1) {
      // Count how many locked races fall in this sliding window
      let numForced = 0;
      const coeffs = [];
      for (let i = start; i < start + maxConsec + 1; i += 1) {
        if (fixedRaceIndices.has(i)) {
          numForced += 1;
        } else {
          for (const name of raceVarsByWindow[i]) coeffs.push([name, 1]);
        }
      }
      // If locks alone already hit or exceed the cap, allow 0 more races in free slots
      const remaining = Math.max(0, maxConsec - numForced);
      if (coeffs.length > 0) {
        addConstraint(model, glpk, `max_consec_${start}`, coeffs, glpk.GLP_UP, 0, remaining);
      }
    }
  }

  // Sliding three-race windows used only for the soft penalty term.
  for (let start = 0; start < zVars.length; start += 1) {
    const zName = `z_${start}`;
    for (let i = start; i < start + 3; i += 1) {
      const coeffs = [[zName, 1], ...raceVarsByWindow[i].map(name => [name, -1])];
      addConstraint(model, glpk, `z_link_${start}_${i}`, coeffs, glpk.GLP_UP, 0, 0);
    }
    const coeffs = [[zName, -1]];
    for (let i = start; i < start + 3; i += 1) {
      for (const name of raceVarsByWindow[i]) coeffs.push([name, 1]);
    }
    addConstraint(model, glpk, `z_full_${start}`, coeffs, glpk.GLP_UP, 0, 2);
  }

  // Fixed manual or historical choices.
  // Use explicit equality constraints instead of variable bounds because the browser GLPK build
  // can occasionally keep the old selected action visible when only bounds are used on binary vars.
  for (const [windowIndexRaw, choiceName] of Object.entries(fixed)) {
    const windowIndex = Number(windowIndexRaw);
    const chosenIndex = actionsByWindow[windowIndex].findIndex(action => action.choice === choiceName);
    if (chosenIndex === -1) {
      return {
        status: 'INFEASIBLE',
        message: `Fixed choice '${choiceName}' is not available at ${windows[windowIndex].label} under the current race list.`,
        schedule_rows: [],
        epithets: [],
        settings
      };
    }
    addConstraint(
      model,
      glpk,
      `fix_${windowIndex}`,
      [[`x_${windowIndex}_${chosenIndex}`, 1]],
      glpk.GLP_FX,
      1,
      1
    );
  }

  const exprDirtG1 = actionSum(r => r.surface === 'Dirt' && r.grade === 'G1');
  const exprDirt = actionSum(r => r.surface === 'Dirt');
  const exprStandard = actionSum(r => isStandardDistance(r));
  const exprNonStandard = actionSum(r => !isStandardDistance(r));
  const exprOpPlus = actionSum(r => ['G1', 'G2', 'G3', 'OP', 'Pre-OP'].includes(r.grade));
  const exprJuniorStakes = actionSum(r => String(r.name).includes('Junior Stakes'));
  const exprCountry = actionSum(r => COUNTRY_WORDS.some(word => String(r.name).includes(word)));
  const exprUmamusume = actionSum(r => String(r.name).includes('Umamusume Stakes'));
  const exprKanto = actionSum(r => ['G1', 'G2', 'G3'].includes(r.grade) && KANTO_TRACKS.has(r.track));
  const exprWest = actionSum(r => ['G1', 'G2', 'G3'].includes(r.grade) && WEST_TRACKS.has(r.track));
  const exprTohoku = actionSum(r => ['G1', 'G2', 'G3'].includes(r.grade) && TOHOKU_TRACKS.has(r.track));
  const exprHokkaido = actionSum(r => ['G1', 'G2', 'G3'].includes(r.grade) && HOKKAIDO_TRACKS.has(r.track));
  const exprKokura = actionSum(r => ['G1', 'G2', 'G3'].includes(r.grade) && KOKURA_TRACKS.has(r.track));

  for (const raceName of ['Satsuki Sho', 'Japanese Derby (Tokyo Yushun)', 'Kikuka Sho']) requireYLeqExpr('Stunning', exprRaceYear('Classic', raceName));
  for (const raceName of ['Oka Sho', 'Japanese Oaks', 'Shuka Sho']) requireYLeqExpr('Lady', exprRaceYear('Classic', raceName));
  for (const raceName of ['Osaka Hai', 'Tenno Sho (Spring)']) requireYLeqExpr('Spring Champion', exprRaceYear('Senior', raceName));
  requireYLeqExpr('Spring Champion', exprRaceAny('Takarazuka Kinen'));
  for (const raceName of ['Tenno Sho (Autumn)', 'Japan Cup', 'Arima Kinen']) requireYLeqExpr('Fall Champion', exprRaceYear('Senior', raceName));
  requireYLeqExpr('Shield Bearer', exprRaceYear('Senior', 'Tenno Sho (Spring)'));
  requireYLeqExpr('Shield Bearer', exprRaceYear('Senior', 'Tenno Sho (Autumn)'));
  requireYLeqExpr('Incredible', exprEpithet('Stunning'));
  requireYLeqExpr('Incredible', mergeExprs(exprRaceYear('Classic', 'Japan Cup'), exprRaceYear('Classic', 'Arima Kinen')));

  const phenomenalExpr = actionSum(r => ['Tenno Sho (Spring)', 'Takarazuka Kinen', 'Japan Cup', 'Tenno Sho (Autumn)', 'Osaka Hai', 'Arima Kinen'].includes(r.name));
  requireYLeqExpr('Phenomenal', exprEpithet('Stunning'));
  requireCountThreshold('Phenomenal', phenomenalExpr, 2);
  requireYLeqExpr('Heroine', exprEpithet('Lady'));
  requireYLeqExpr('Heroine', exprRaceYear('Classic', 'Queen Elizabeth II Cup'));
  requireYLeqExpr('Goddess', exprEpithet('Lady'));
  for (const expr of [
    exprRaceYear('Junior', 'Hanshin Juvenile Fillies'),
    exprRaceYear('Senior', 'Victoria Mile'),
    exprRaceYear('Classic', 'Queen Elizabeth II Cup'),
    exprRaceYear('Senior', 'Queen Elizabeth II Cup')
  ]) requireYLeqExpr('Goddess', expr);

  requireYLeqExpr('Legendary', exprEpithet('Spring Champion'));
  requireYLeqExpr('Legendary', exprEpithet('Fall Champion'));
  requireYLeqExpr('Legendary', { 'y_Stunning': 1, 'y_Lady': 1 });

  for (const raceName of ['NHK Mile Cup', 'Yasuda Kinen', 'Mile Championship']) requireYLeqExpr('Breakneck Miler', exprRaceAny(raceName));

  const juvenileAlt = { ...exprRaceYear('Junior', 'Hanshin Juvenile Fillies') };
  for (const [k, v] of Object.entries(exprRaceYear('Junior', 'Asahi Hai Futurity Stakes'))) juvenileAlt[k] = (juvenileAlt[k] || 0) + v;
  for (const expr of [
    exprRaceYear('Classic', 'Oka Sho'),
    exprRaceAny('NHK Mile Cup'),
    exprRaceAny('Yasuda Kinen'),
    exprRaceYear('Senior', 'Victoria Mile'),
    exprRaceAny('Mile Championship'),
    juvenileAlt
  ]) requireYLeqExpr('Mile a Minute', expr);

  for (const raceName of ['Takamatsunomiya Kinen', 'Sprinters Stakes']) {
    requireYLeqExpr('Sprint Go-Getter', exprRaceAny(raceName));
    requireYLeqExpr('Sprint Speedster', exprRaceAny(raceName));
  }
  for (const raceName of ['Yasuda Kinen', 'Mile Championship']) requireYLeqExpr('Sprint Speedster', exprRaceAny(raceName));

  for (const raceName of ['Unicorn Stakes', 'Leopard Stakes', 'Japan Dirt Derby']) requireYLeqExpr('Kicking Up Dust', exprRaceYear('Classic', raceName));
  requireYLeqExpr('Dirt Sprinter', exprRaceYear('Classic', 'JBC Sprint'));
  requireYLeqExpr('Dirt Sprinter', exprRaceYear('Senior', 'JBC Sprint'));

  requireCountThreshold('Dirt G1 Achiever', exprDirtG1, 3);
  requireCountThreshold('Dirt G1 Star', exprDirtG1, 4);
  requireCountThreshold('Dirt G1 Powerhouse', exprDirtG1, 5);
  requireCountThreshold('Dirt G1 Dominator', exprDirtG1, 9);
  requireCountThreshold('Standard Distance Leader', exprStandard, 10, debutBonus(r => isStandardDistance(r)));
  requireCountThreshold('Non-Standard Distance Leader', exprNonStandard, 10, debutBonus(r => !isStandardDistance(r)));
  requireCountThreshold('Dirty Work', exprDirt, 5, debutBonus(r => r.surface === 'Dirt'));
  requireCountThreshold('Playing Dirty', exprDirt, 10, debutBonus(r => r.surface === 'Dirt'));
  requireCountThreshold('Eat My Dust', exprDirt, 15, debutBonus(r => r.surface === 'Dirt'));
  requireCountThreshold('Pro Racer', exprOpPlus, 10, debutBonus(r => ['G1', 'G2', 'G3', 'OP', 'Pre-OP'].includes(r.grade)));
  requireCountThreshold('Junior Jewel', exprJuniorStakes, 3);
  requireCountThreshold('Globe-Trotter', exprCountry, 3);
  requireCountThreshold('Umatastic', exprUmamusume, 3);
  requireCountThreshold('Kanto Conqueror', exprKanto, 3);
  requireCountThreshold('West Japan Whiz', exprWest, 3);
  requireCountThreshold('Tohoku Top Dog', exprTohoku, 3);
  requireCountThreshold('Hokkaido Hotshot', exprHokkaido, 3);
  requireCountThreshold('Kokura Constable', exprKokura, 2);
  for (const dist of ['Sprint', 'Mile', 'Medium']) {
    const pred = r => r.surface === 'Dirt' && r.distance === dist;
    requireYLeqExpr('Dirt Dancer', actionSum(pred), debutBonus(pred));
  }
  for (const dist of ['Sprint', 'Mile', 'Medium', 'Long']) {
    const pred = r => r.surface === 'Turf' && r.distance === dist;
    requireYLeqExpr('Turf Tussler', actionSum(pred), debutBonus(pred));
  }

  // Force selected epithets (hard constraint: y = 1).
  for (const epName of (settings.forced_epithets || [])) {
    const yVar = `y_${epName}`;
    if (yVars.includes(yVar)) {
      addConstraint(model, glpk, `force_${epName}`, [[yVar, 1]], glpk.GLP_FX, 1, 1);
    }
  }

  // Force climax type: plurality — the chosen type must lead every rival type
  // by at least 2 races. The +2 buffer covers the untracked debut race, which
  // may itself count toward a rival type.
  // Per rival: count(chosen) - count(rival) >= 2
  const climax = settings.forced_climax || '';
  if (climax) {
    const isDirt = climax === 'Dirt';
    const rivals = isDirt
      ? ['Turf']
      : ['Sprint', 'Mile', 'Medium', 'Long'].filter(d => d !== climax);
    for (const rival of rivals) {
      const matchChosen = isDirt
        ? r => r.surface === 'Dirt'
        : r => r.distance === climax;
      const matchRival = isDirt
        ? r => r.surface === 'Turf'
        : r => r.distance === rival;
      const coeffs = [];
      for (const [varName, info] of actionLookup.entries()) {
        if (info.race) {
          const c = (matchChosen(info.race) ? 1 : 0) - (matchRival(info.race) ? 1 : 0);
          if (c !== 0) coeffs.push([varName, c]);
        }
      }
      if (coeffs.length) {
        addConstraint(model, glpk, `climax_vs_${rival}`, coeffs, glpk.GLP_LO, 2, 0);
      }
    }
  }

  const result = await glpk.solve(model, {
    msglev: glpk.GLP_MSG_OFF,
    presol: true
  });

  const status = statusToText(result.result.status, glpk);
  const solutionVars = result.result.vars || {};

  const chosenActions = [];
  const selectedRaces = [];
  // The debut race runs before any window in our schedule, so it's always
  // first in the selectedRaces list. It contributes to epithet counters but
  // is not a window choice.
  if (debutRace) selectedRaces.push(debutRace);
  for (let i = 0; i < actionsByWindow.length; i += 1) {
    let chosen = actionsByWindow[i][0];
    for (let j = 0; j < actionsByWindow[i].length; j += 1) {
      const value = solutionVars[`x_${i}_${j}`] || 0;
      if (value > 0.5) {
        chosen = actionsByWindow[i][j];
        break;
      }
    }
    chosenActions.push(chosen);
    if (chosen.race && !chosen.lost) selectedRaces.push(chosen.race);
  }

  const solvedEpithets = completedEpithets(selectedRaces, data);
  // selectedRaces[0] is the debut (when present); window choices start at the next slot.
  let raceInstanceCounter = debutRace ? 1 : 0;
  const raceIndicesByWindow = {};
  chosenActions.forEach((chosen, i) => {
    if (chosen.race && !chosen.lost) {
      raceIndicesByWindow[i] = raceInstanceCounter;
      raceInstanceCounter += 1;
    } else {
      raceIndicesByWindow[i] = null;
    }
  });

  const fanMult = 1 + Math.max(0, settings.fan_bonus_pct) / 100;
  const scheduleRows = [];
  const runningSelected = [];
  // Seed the per-window epithet accumulator with the debut race so any epithet
  // that becomes complete partway through the schedule is attributed at the
  // correct window (and the debut isn't double-counted).
  if (debutRace) runningSelected.push(debutRace);
  let previousEpithets = [];
  for (let i = 0; i < chosenActions.length; i += 1) {
    const chosen = chosenActions[i];
    const race = chosen.race;
    const isLost = Boolean(chosen.lost);
    if (race && !isLost) runningSelected.push(race);
    const now = completedEpithets(runningSelected, data);
    const newEpithets = now.filter(e => !previousEpithets.includes(e));
    previousEpithets = now;

    let linkedEpithets = [];
    if (race && !isLost && raceIndicesByWindow[i] !== null) {
      linkedEpithets = linkedEpithetsForSelectedRace(selectedRaces, raceIndicesByWindow[i], solvedEpithets, settings, data).linked;
    }
    const epithetNames = data.epithets
      .map(e => e.name)
      .filter(name => new Set([...linkedEpithets, ...newEpithets]).has(name));
    const epithetValue = epithetsWeightedValue(epithetNames, settings, data);
    const tileValue = Number((chosen.value + epithetValue).toFixed(2));
    const baseFans = (race && !isLost)
      ? (race.fans != null ? race.fans : (BASE_REWARD[race.grade]?.fans || 0))
      : 0;
    const raceFans = Math.floor(baseFans * fanMult);

    scheduleRows.push({
      index: i,
      window: windows[i].label,
      year: windows[i].year,
      month: windows[i].month,
      half: windows[i].half,
      selected: chosen.choice,
      lost: isLost,
      track: race ? race.track : '',
      grade: race ? race.grade : '',
      distance: race ? race.distance : '',
      surface: race ? race.surface : '',
      race_stats: chosen.stats,
      race_sp: chosen.sp,
      race_fans: raceFans,
      race_value: Number(chosen.value.toFixed(2)),
      linked_epithets: linkedEpithets,
      epithet_names: epithetNames,
      epithet_value: epithetValue,
      tile_value: tileValue,
      new_epithets: newEpithets
    });
  }

  // Augment epithet_names with full contribution map (not just marginal)
  const fullMap = buildFullEpithetMap(scheduleRows, selectedRaces, solvedEpithets);
  for (const row of scheduleRows) {
    const full = fullMap[row.index] || [];
    if (full.length) {
      const merged = new Set([...(row.epithet_names || []), ...full]);
      row.epithet_names = [...merged];
    }
  }

  for (const [windowIndexRaw, choiceName] of Object.entries(fixed)) {
    const windowIndex = Number(windowIndexRaw);
    if (scheduleRows[windowIndex] && scheduleRows[windowIndex].selected !== choiceName) {
      return {
        status: 'ERROR',
        message: `Locked choice '${choiceName}' was not applied at ${windows[windowIndex].label}.`,
        schedule_rows: scheduleRows,
        epithets: solvedEpithets,
        settings
      };
    }
  }

  const totalRaceStats = chosenActions.reduce((sum, chosen) => sum + chosen.stats, 0);
  const totalRaceSp = chosenActions.reduce((sum, chosen) => sum + chosen.sp, 0);
  const totalRaceFans = scheduleRows.reduce((sum, row) => sum + (row.race_fans || 0), 0);
  const epithetStatPoints = solvedEpithets.reduce((sum, name) => sum + epithetStatTotal(name, data), 0);
  const epithetHintNames = solvedEpithets.filter(name => data.epithetByName[name].reward_kind === 'hint').map(name => hintSkillName(name, data));
  const weightedRaceValueGross = settings.stat_weight * totalRaceStats + settings.sp_weight * totalRaceSp;
  const raceCostPerRace = Number(settings.race_cost || 0) / 100.0 * g2g3Baseline(settings);
  const raceCostTotal = raceCostPerRace * selectedRaces.length;
  const summerPenaltyCount = chosenActions.reduce((sum, chosen, idx) => (
    sum + ((chosen.race && softenedSummerWindows.has(idx)) ? 1 : 0)
  ), 0);
  const summerPenaltyTotal = summerPenalty * summerPenaltyCount;
  const weightedRaceValueNet = weightedRaceValueGross - raceCostTotal - summerPenaltyTotal;
  const weightedEpithetValueTotal = settings.epithet_multiplier * settings.stat_weight * epithetStatPoints + settings.epithet_multiplier * settings.hint_weight * epithetHintNames.length;
  const triplePenaltyCount = zVars.reduce((sum, zName, idx) => {
    if (LATE_DEC_WINDOWS.has(idx + 2)) return sum;
    return sum + ((solutionVars[zName] || 0) > 0.5 ? 1 : 0);
  }, 0);
  const triplePenaltyTotal = settings.three_race_penalty_weight * triplePenaltyCount;
  const totalValue = weightedRaceValueNet + weightedEpithetValueTotal - triplePenaltyTotal;

  return {
    status,
    message: '',
    schedule_rows: scheduleRows,
    epithets: solvedEpithets,
    selected_choices: scheduleRows.map(row => row.selected),
    total_value: Number(totalValue.toFixed(2)),
    weighted_race_value: Number(weightedRaceValueGross.toFixed(2)),
    weighted_race_value_net: Number(weightedRaceValueNet.toFixed(2)),
    weighted_epithet_value: Number(weightedEpithetValueTotal.toFixed(2)),
    race_cost_total: Number(raceCostTotal.toFixed(2)),
    summer_penalty_count: summerPenaltyCount,
    summer_penalty_total: Number(summerPenaltyTotal.toFixed(2)),
    triple_penalty_count: triplePenaltyCount,
    triple_penalty_total: Number(triplePenaltyTotal.toFixed(2)),
    total_race_stats: totalRaceStats,
    total_race_sp: totalRaceSp,
    total_race_fans: totalRaceFans,
    epithet_stat_points: epithetStatPoints,
    epithet_hint_count: epithetHintNames.length,
    epithet_hint_names: epithetHintNames,
    settings,
    proven_optimal: status === 'OPTIMAL',
    solver_message: ''
  };
}

export async function solveWithManualLocks(settingsInput, currentSelected = [], manualLocks = {}, freezeBeforeIndex = null, lostLocks = {}) {
  const settings = normalizeSettings(settingsInput);
  const locks = Object.fromEntries(
    Object.entries(manualLocks || {})
      .filter(([, v]) => ![null, '', AUTO].includes(v))
      .map(([k, v]) => [Number(k), v])
  );
  const lostIndices = Object.keys(lostLocks || {})
    .filter(k => lostLocks[k])
    .map(Number);
  let fixed = {};
  if (freezeBeforeIndex == null && Object.keys(locks).length && currentSelected.length) {
    // Only use race locks (not "No race" blocks) to determine freeze point
    const raceLockIndices = Object.entries(locks)
      .filter(([, v]) => v !== NO_RACE)
      .map(([k]) => Number(k));
    if (raceLockIndices.length) {
      freezeBeforeIndex = Math.max(...raceLockIndices);
    }
  }
  if (freezeBeforeIndex != null && currentSelected.length) {
    const cutoff = Math.max(0, Number(freezeBeforeIndex));
    for (let idx = 0; idx < cutoff; idx += 1) {
      if (idx < currentSelected.length) fixed[idx] = currentSelected[idx];
    }
  }
  fixed = { ...fixed, ...locks };
  let result = await optimizeSchedule(settings, fixed, lostIndices);

  // If infeasible and forced epithets/climax are active, retry without them
  let droppedEpithets = [];
  let droppedClimax = false;
  if (!['OPTIMAL', 'FEASIBLE'].includes(result.status) && settings.forced_epithets?.length) {
    const allForced = [...settings.forced_epithets];
    const relaxed = { ...settings, forced_epithets: [] };
    result = await optimizeSchedule(relaxed, fixed, lostIndices);
    if (['OPTIMAL', 'FEASIBLE'].includes(result.status)) {
      const completed = new Set(result.epithets || []);
      droppedEpithets = allForced.filter(name => !completed.has(name));
    }
  }
  if (!['OPTIMAL', 'FEASIBLE'].includes(result.status) && settings.forced_climax) {
    const relaxed = { ...settings, forced_epithets: [], forced_climax: '' };
    result = await optimizeSchedule(relaxed, fixed, lostIndices);
    if (['OPTIMAL', 'FEASIBLE'].includes(result.status)) {
      droppedClimax = true;
      if (settings.forced_epithets?.length) {
        const completed = new Set(result.epithets || []);
        droppedEpithets = settings.forced_epithets.filter(name => !completed.has(name));
      }
    }
  }

  const payload = formatPayload(result, manualLocks, result.selected_choices || []);
  if (droppedEpithets.length) payload.dropped_epithets = droppedEpithets;
  if (droppedClimax) payload.dropped_climax = true;
  return payload;
}

function allDropdownChoices(windows, settings) {
  const choiceMap = {};
  const rb = settings ? Math.max(0, settings.race_bonus_pct || 0) / 100 : 0;
  const fanMult = settings ? 1 + Math.max(0, settings.fan_bonus_pct || 0) / 100 : 1;
  for (const w of windows) {
    const eligible = settings
      ? w.races.filter(r => raceIsEligible(r, settings))
      : w.races;
    const raceChoices = eligible.map(r => {
      const base = BASE_REWARD[r.grade] || { stats: 0, sp: 0, fans: 0 };
      const baseFans = r.fans != null ? r.fans : (base.fans || 0);
      return {
        name: r.name,
        grade: r.grade,
        distance: r.distance,
        surface: r.surface,
        track: r.track,
        stats: Math.floor(base.stats * (1 + rb)),
        sp: Math.floor(base.sp * (1 + rb)),
        fans: Math.floor(baseFans * fanMult)
      };
    });
    choiceMap[w.index] = raceChoices;
  }
  return choiceMap;
}

function formatPayload(result, manualLocks = {}, currentSelected = []) {
  const data = DATA;
  const locks = Object.fromEntries(Object.entries(manualLocks || {}).map(([k, v]) => [String(k), v]));
  const selectedChoices = currentSelected || result.selected_choices || [];
  const acquired = (result.epithets || []).map(name => {
    const e = data.epithetByName[name];
    return {
      name,
      reward_text: e.reward_text,
      condition_text: e.condition_text,
      reward_kind: e.reward_kind,
      amount: e.amount,
      weighted_value: Number(epithetObjectiveValue(name, result.settings, data).toFixed(2))
    };
  });

  const choicesByWindow = allDropdownChoices(data.windows, result.settings);
  const windowsPayload = (result.schedule_rows || []).map(row => ({
    ...row,
    lock_value: locks[String(row.index)] || AUTO,
    choices: [AUTO, NO_RACE, ...(choicesByWindow[row.index] || []).map(r => r.name)],
    race_choices: choicesByWindow[row.index] || []
  }));

  return {
    settings: result.settings,
    summary: {
      status: result.status || 'UNKNOWN',
      proven_optimal: Boolean(result.proven_optimal),
      message: result.message || '',
      total_value: result.total_value || 0,
      weighted_race_value: result.weighted_race_value || 0,
      weighted_race_value_net: result.weighted_race_value_net || 0,
      weighted_epithet_value: result.weighted_epithet_value || 0,
      race_cost_total: result.race_cost_total || 0,
      summer_penalty_count: result.summer_penalty_count || 0,
      summer_penalty_total: result.summer_penalty_total || 0,
      triple_penalty_count: result.triple_penalty_count || 0,
      triple_penalty_total: result.triple_penalty_total || 0,
      race_stats: result.total_race_stats || 0,
      race_skill_points: result.total_race_sp || 0,
      race_fans: result.total_race_fans || 0,
      epithet_stat_points: result.epithet_stat_points || 0,
      epithet_hint_count: result.epithet_hint_count || 0,
      epithet_hint_names: result.epithet_hint_names || [],
      scheduled_races: (result.selected_choices || []).filter(s => s !== NO_RACE).length,
      completed_epithets: (result.epithets || []).length
    },
    windows: windowsPayload,
    epithets: acquired,
    manual_locks: locks,
    current_selected: selectedChoices,
    presets: {},
    ranks: RANKS,
    years: YEARS,
    months: MONTHS,
    halves: HALVES
  };
}


export async function summarizeScheduleTrackRaces(trackRaces, settingsInput) {
  await loadData();
  const data = DATA;
  const settings = normalizeSettings(settingsInput);
  const fanMult = 1 + Math.max(0, settings.fan_bonus_pct || 0) / 100;
  let totalStats = 0;
  let totalSp = 0;
  let totalFans = 0;
  for (const race of trackRaces || []) {
    const { stats, sp } = raceReward(race, settings.race_bonus_pct);
    totalStats += stats;
    totalSp += sp;
    const base = BASE_REWARD[race.grade] || { fans: 0 };
    const baseFans = race.fans != null ? race.fans : (base.fans || 0);
    totalFans += Math.floor(baseFans * fanMult);
  }
  const epithetNames = completedEpithets(trackRaces || [], data);
  let epithetStatPoints = 0;
  for (const name of epithetNames) {
    epithetStatPoints += epithetStatTotal(name, data);
  }
  return {
    raceCount: (trackRaces || []).length,
    raceStats: totalStats,
    raceSp: totalSp,
    epithetStatPoints,
    epithetCount: epithetNames.length,
    estimatedFans: totalFans
  };
}


export { NO_RACE, AUTO, defaultSettings };
