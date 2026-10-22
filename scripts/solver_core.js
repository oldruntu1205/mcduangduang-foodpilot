/*
 * solver_core.js —— FoodPilot 求解器（浏览器 / Node 双用）
 *
 * 逐函数对应 scripts/meal_solver.py。改任何一边都必须同步另一边，
 * 然后用 scripts/test_parity.js 跑一次等价性验证：
 *     node scripts/test_parity.js
 *
 * 为什么允许存在两份实现：
 * 页面要做到「双击即开、断网可用、点开关立刻重算」，就不能依赖本地服务。
 * 代价是算法有两份，所以用 parity 测试把漂移挡在交付前。
 */

const MAIN_CATS = ['combo', 'main'];
const SHARE_CATS = ['side', 'drink', 'dessert', 'veg'];
const MEAT_CN = { beef: '牛肉', chicken: '鸡肉', fish: '鱼肉', pork: '猪肉', veg: '素' };
const PLAN_VAR = { A: '--cA', B: '--cB', C: '--cC' };

const STRATEGIES = [
  {
    id: 'A', name: '最省钱', tagline: '压住总价，但至少保住 3 种主餐',
    share_reserve: .22, share_count: 3, min_unique: 3,
    prefer: ['side', 'veg', 'drink', 'dessert']
  },
  {
    id: 'B', name: '最不重样', tagline: '五个人吃到尽量不同的主餐',
    share_reserve: .20, share_count: 4, min_unique: 1,
    prefer: ['veg', 'side', 'drink', 'dessert']
  },
  {
    id: 'C', name: '最低热量', tagline: '整桌摄入最小，低卡的人优先满足，不配甜点',
    share_reserve: .26, share_count: 3, min_unique: 3,
    prefer: ['veg', 'drink', 'side']
  }
];

const r2 = v => Math.round(v * 100) / 100;

function allowed(it, p) {
  if (p.avoid_meats.includes(it.meat)) return false;
  if (p.no_spicy && it.spicy) return false;
  if (p.kcal_max && it.kcal > p.kcal_max) return false;
  return true;
}

/* 只用于给候选排序（决定进枚举的前 K 项），不决定最终结果 */
function preScore(it, p, st, per) {
  const ratio = per ? it.price / per : 1;
  let s = -Math.abs(ratio - .9);
  if (p.kcal_max) s += .5 * (1 - Math.abs(p.kcal_max * .8 - it.kcal) / Math.max(p.kcal_max, 1));
  if (st.id === 'C') s -= it.kcal / 1000;
  if (st.id === 'A') s -= it.price / 50;
  return s;
}

function objective(combo, shared, budget, st, people) {
  const codes = combo.map(i => i.code);
  const uniq = new Set(codes).size;
  if (uniq < st.min_unique) return -1e9;

  const total = combo.reduce((s, i) => s + i.price, 0)
    + shared.reduce((s, i) => s + i.price, 0);
  // 有热量上限的人，其主餐热量加权
  const mainKcal = combo.reduce((s, i, k) => s + i.kcal * (people[k].kcal_max ? 1.6 : 1), 0);
  const kcal = mainKcal + shared.reduce((s, i) => s + i.kcal, 0);

  const cnt = {};
  codes.forEach(c => cnt[c] = (cnt[c] || 0) + 1);
  const rep = Math.max(0, ...Object.values(cnt));

  if (st.id === 'A') return -total;
  if (st.id === 'B') return uniq * 1000 - total;
  return -kcal - rep * 40 - total * .1;
}

function pickShares(pool, left, target, st, exclude) {
  const key = st.id === 'C'
    ? ((a, b) => a.kcal - b.kcal || a.price - b.price)
    : ((a, b) => a.price - b.price || a.kcal - b.kcal);
  const picked = [], seen = new Set();

  for (const cat of st.prefer) {
    if (picked.length >= target) break;
    const cands = pool
      .filter(i => i.category === cat && !exclude.has(i.code) && !seen.has(i.code))
      .sort(key);
    for (const it of cands) {
      if (it.price > left) continue;
      picked.push(it); seen.add(it.code); left = r2(left - it.price); break;
    }
  }
  if (left > 0 && picked.length < target) {
    const rest = pool
      .filter(i => SHARE_CATS.includes(i.category) && !exclude.has(i.code)
        && !seen.has(i.code) && i.price <= left)
      .sort(key);
    for (const it of rest) {
      if (picked.length >= target || it.price > left) break;
      picked.push(it); seen.add(it.code); left = r2(left - it.price);
    }
  }
  return [picked, r2(left)];
}

function product(lists) {
  let res = [[]];
  for (const l of lists) {
    const next = [];
    for (const r of res) for (const x of l) next.push(r.concat([x]));
    res = next;
  }
  return res;
}

function explain(planId, item, p, cands, others, budget, n) {
  const parts = [], hits = [];
  if (p.avoid_meats.length) hits.push('避开' + p.avoid_meats.map(m => MEAT_CN[m] || m).join('/'));
  if (p.no_spicy) hits.push('不辣');
  if (p.kcal_max) hits.push(item.kcal + 'kcal 在 ' + p.kcal_max + ' 以内');
  if (hits.length) parts.push(hits.join('、') + '，该店只筛出 ' + cands.length + ' 项可选');

  if (planId === 'A') {
    const cheap = cands.reduce((a, b) => a.price < b.price ? a : b);
    if (cheap.code === item.code) {
      parts.push('他名下最低价 ¥' + item.price.toFixed(2) + '，压总价就靠这一档');
    } else {
      const uniq = new Set(others.map(o => o.code).concat([item.code])).size;
      parts.push('比最低价的' + cheap.name + '贵 ¥' + (item.price - cheap.price).toFixed(2)
        + '，用来凑够 ' + uniq + ' 种不同主餐，避免整桌一个味');
    }
  } else if (planId === 'B') {
    const codes = new Set(others.map(o => o.code));
    if (!codes.has(item.code)) parts.push('与另外 ' + others.length + ' 人的选择不重样');
    else parts.push('同类可行项已被占满，与另外 '
      + others.filter(o => o.code === item.code).length + ' 人同款');
  } else {
    const low = cands.reduce((a, b) => a.kcal < b.kcal ? a : b);
    if (low.code === item.code) parts.push('候选人里热量最低（' + item.kcal + 'kcal）');
    else parts.push('比最低卡的' + low.name + '高 ' + (item.kcal - low.kcal)
      + 'kcal，用来凑够不同主餐，免得整桌都是一模一样的低卡餐');
  }
  if (item.price <= budget / n * .85) {
    parts.push('¥' + item.price.toFixed(2) + '，给共享小食留出了空间');
  }
  return parts.length ? parts.join('；') : '唯一可行项';
}

function finalize(assignments, shared, people, budget, st, codes) {
  const n = people.length;
  const mainT = r2(assignments.reduce((s, a) => s + a.item.price, 0));
  const shareT = r2(shared.reduce((s, i) => s + i.price, 0));
  const total = r2(mainT + shareT);
  const shareKcal = shared.reduce((s, i) => s + i.kcal, 0);
  const perShare = n ? Math.round(shareKcal / n) : 0;

  const checks = [], per = [];
  for (const a of assignments) {
    const p = people.find(x => x.name === a.person);
    const k = a.item.kcal + perShare;
    per.push({ person: p.name, item_name: a.item.name, price: a.item.price, kcal: k });
    if (p.kcal_max && k > p.kcal_max * 1.15) {
      checks.push({ level: 'warn', msg: p.name + ' 主餐已达标，但均摊共享小食后约 ' + k + 'kcal，建议不分小食' });
    }
    if (p.avoid_meats.includes(a.item.meat)) {
      checks.push({ level: 'error', msg: p.name + ' 分到 ' + a.item.name + '，违反忌口' });
    }
    if (p.no_spicy && a.item.spicy) {
      checks.push({ level: 'error', msg: p.name + ' 分到辣味餐品 ' + a.item.name });
    }
    if (p.kcal_max && a.item.kcal > p.kcal_max) {
      checks.push({ level: 'error', msg: p.name + ' 主餐 ' + a.item.kcal + 'kcal 超上限' });
    }
  }
  if (total > budget) {
    checks.push({ level: 'error', msg: '总价 ¥' + total.toFixed(2) + ' 超预算 ¥' + budget });
  }
  const unk = assignments.filter(a => a.item.meat === 'unknown').map(a => a.item.name);
  if (unk.length) checks.push({ level: 'warn', msg: '肉类成分无法自动判定，下单前需复核：' + unk.join('、') });
  const est = assignments.filter(a => a.item.kcal_source === 'estimate').map(a => a.item.name);
  if (est.length) checks.push({ level: 'warn', msg: '热量为估算值，不可作为营养依据：' + est.join('、') });

  return {
    id: st.id, name: st.name, tagline: st.tagline,
    valid: !checks.some(c => c.level === 'error'),
    assignments, shared,
    main_total: mainT, share_total: shareT, total,
    budget, remaining: r2(budget - total),
    unique_mains: new Set(codes).size,
    total_kcal: Math.round(assignments.reduce((s, a) => s + a.item.kcal, 0) + shareKcal),
    per_person: per, checks, share_kcal_each: perShare
  };
}

function buildPlan(mains, pool, people, budget, stRaw, exclude) {
  const n = people.length;
  const st = Object.assign({}, stRaw);
  if (st.min_unique > 1) st.min_unique = Math.min(st.min_unique, Math.max(1, n - 1));

  const per = n ? budget * (1 - st.share_reserve) / n : budget;
  const topK = n <= 6 ? 5 : 3;

  const full = [];
  for (const p of people) {
    const cands = mains.filter(i => allowed(i, p) && !exclude.has(i.code));
    if (!cands.length) {
      return {
        id: st.id, name: st.name, tagline: st.tagline, valid: false,
        error: p.name + ' 在当前菜单下没有任何可行主餐',
        assignments: [], shared: [], total: 0, checks: [], total_kcal: 0,
        remaining: 0, unique_mains: 0, share_kcal_each: 0, budget
      };
    }
    cands.sort((a, b) => preScore(b, p, st, per) - preScore(a, p, st, per));
    full.push(cands);
  }

  const pools = full.map(c => c.slice(0, topK));
  const shareTarget = n >= 3 ? st.share_count : 1;

  let best = null;
  for (const combo of product(pools)) {
    const mainT = combo.reduce((s, i) => s + i.price, 0);
    if (mainT > budget) continue;
    // 套餐自带薯条饮料，再按满额配共享小食就是重复浪费
    const cover = combo.filter(i => i.is_combo).length;
    const eff = Math.max(1, shareTarget - cover);
    const shared = pickShares(pool, r2(budget - mainT), eff, st, exclude)[0];
    const total = r2(mainT + shared.reduce((s, i) => s + i.price, 0));
    if (total > budget) continue;
    const obj = objective(combo, shared, budget, st, people);
    if (obj <= -1e8) continue;
    if (!best || obj > best.obj) best = { obj, combo, shared, total };
  }

  if (!best) {
    if (st.min_unique > 1) {
      return buildPlan(mains, pool, people, budget,
        Object.assign({}, st, { min_unique: 1 }), exclude);
    }
    return {
      id: st.id, name: st.name, tagline: st.tagline, valid: false,
      error: '预算 ¥' + budget + ' 下凑不出满足全部硬约束的组合',
      assignments: [], shared: [], total: 0, checks: [], total_kcal: 0,
      remaining: 0, unique_mains: 0, share_kcal_each: 0, budget
    };
  }

  const combo = best.combo, shared = best.shared;
  const codes = combo.map(i => i.code);
  const assignments = combo.map((item, idx) => {
    const others = combo.filter((_, j) => j !== idx);
    return {
      person: people[idx].name, item,
      alternatives: full[idx].filter(c => c.code !== item.code).slice(0, 3),
      reason: explain(st.id, item, people[idx], full[idx], others, budget, n)
    };
  });
  return finalize(assignments, shared, people, budget, st, codes);
}

function comparePlans(plans) {
  const ok = plans.filter(p => p.valid);
  if (ok.length < 2) return [];
  const cheap = ok.reduce((a, b) => a.total < b.total ? a : b);
  const uniq = ok.reduce((a, b) => a.unique_mains > b.unique_mains ? a : b);
  const kcal = ok.reduce((a, b) => a.total_kcal < b.total_kcal ? a : b);
  return [
    '方案 ' + cheap.id + ' 最便宜（¥' + cheap.total.toFixed(2) + '，主餐 ' + cheap.unique_mains + ' 种）',
    '方案 ' + uniq.id + ' 最不重样（' + uniq.unique_mains + ' 种主餐，¥' + uniq.total.toFixed(2) + '）',
    '方案 ' + kcal.id + ' 热量最低（约 ' + kcal.total_kcal + ' kcal，¥' + kcal.total.toFixed(2) + '）'
  ];
}

function diagnose(plans, people, mains, budget) {
  const tips = [];
  const bad = plans.find(p => p.error);
  if (bad) tips.push(bad.error);
  if (!plans.some(p => p.valid)) {
    let need = 0;
    for (const p of people) {
      const c = mains.filter(i => allowed(i, p));
      need += c.length ? Math.min(...c.map(i => i.price)) : 0;
    }
    tips.push('该预算下无法满足全部硬约束；只求人人有主餐的最低预算约 ¥' + need.toFixed(2));
    tips.push('可放宽的方向：提高预算 / 提高热量上限 / 换备货更全的门店');
  }
  return tips;
}

function solveAll(MENU, people, budget, exclude) {
  exclude = exclude || new Set();
  const items = MENU.items.filter(i => !exclude.has(i.code));
  const mains = items.filter(i => MAIN_CATS.includes(i.category));
  const pool = items.filter(i => SHARE_CATS.includes(i.category));
  const plans = STRATEGIES.map(st => buildPlan(mains, pool, people, budget, st, exclude));
  const ok = plans.filter(p => p.valid);
  return {
    budget, people, plans,
    compare: comparePlans(plans),
    diagnosis: diagnose(plans, people, mains, budget),
    feasible_count: ok.length,
    recommended: ok.length ? ok[0].id : null
  };
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { solveAll, allowed, STRATEGIES, MAIN_CATS, SHARE_CATS, PLAN_VAR, MEAT_CN };
}
