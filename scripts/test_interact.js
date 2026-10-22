#!/usr/bin/env node
/*
 * test_interact.js —— 调节台全组合自检
 *
 * 页面上有 3 个开关 + 3 档预算 = 24 种组合。用户会在演示时随手点，
 * 所以每一种都必须：不抛异常、不出 NaN、可行方案不超预算、不违反忌口。
 * 无解时也要走诊断分支，而不是让页面白屏。
 *
 * 用法：node test_interact.js
 */

const fs = require('fs');
const path = require('path');
const { solveAll } = require('./solver_core.js');

const demo = path.join(__dirname, '..', 'demo');
const plan = JSON.parse(fs.readFileSync(path.join(demo, 'plan.json'), 'utf8'));
const menu = JSON.parse(fs.readFileSync(path.join(demo, 'menu_demo.json'), 'utf8'));

const INIT = plan.people;
const TOGGLES = [
  { key: 'chenBeef', name: '陈昊', label: '陈昊忌牛肉', apply: p => p.avoid_meats.push('beef') },
  { key: 'liSpicy', name: '李婷', label: '李婷能吃辣', apply: p => { p.no_spicy = false; } },
  { key: 'zhangStrict', name: '张敏', label: '张敏500', apply: p => { p.kcal_max = 500; } },
];
const BUDGETS = [140, 160, 200];

function derive(bits, budget) {
  const people = JSON.parse(JSON.stringify(INIT));
  for (const t of TOGGLES) {
    if (!bits[t.key]) continue;
    const p = people.find(x => x.name === t.name);
    if (p) t.apply(p);
  }
  return { people, budget };
}

function check(res, budget, label) {
  const errs = [];
  for (const p of res.plans) {
    if (!p.valid) {
      if (!p.error) errs.push(`${p.id} 不可行但没有给出原因`);
      continue;
    }
    if (!isFinite(p.total) || Number.isNaN(p.total)) errs.push(`${p.id} 总价异常 ${p.total}`);
    if (p.total > budget + 1e-6) errs.push(`${p.id} 超预算 ${p.total} > ${budget}`);
    if (p.assignments.length !== res.people.length) {
      errs.push(`${p.id} 主餐份数 ${p.assignments.length} ≠ 人数 ${res.people.length}`);
    }
    for (const a of p.assignments) {
      const per = res.people.find(x => x.name === a.person);
      if (!per) { errs.push(`${p.id} 未知用餐人 ${a.person}`); continue; }
      if (per.avoid_meats.includes(a.item.meat)) {
        errs.push(`${p.id} ${a.person} 忌口违规：${a.item.name}`);
      }
      if (per.no_spicy && a.item.spicy) errs.push(`${p.id} ${a.person} 辣度违规：${a.item.name}`);
      if (per.kcal_max && a.item.kcal > per.kcal_max) {
        errs.push(`${p.id} ${a.person} 热量违规：${a.item.kcal}>${per.kcal_max}`);
      }
    }
    if (p.assignments.some(x => !x.reason)) errs.push(`${p.id} 有人缺少取舍理由`);
  }
  return errs;
}

let fail = 0, total = 0;
console.log('调节台全组合自检（3 开关 × 3 预算 = 24 组）\n');

for (const budget of BUDGETS) {
  for (let m = 0; m < 8; m++) {
    const bits = {
      chenBeef: !!(m & 1),
      liSpicy: !!(m & 2),
      zhangStrict: !!(m & 4),
    };
    const { people } = derive(bits, budget);
    const label = TOGGLES.filter(t => bits[t.key]).map(t => t.label).join('+') || '默认';

    let res;
    try {
      res = solveAll(menu, people, budget);
    } catch (e) {
      console.log(`[FAIL] ¥${budget} ${label} → 抛异常：${e.message}`);
      fail++; total++;
      continue;
    }
    total++;
    const errs = check(res, budget, label);
    const tag = res.feasible_count === 3 ? 'OK  ' : (res.feasible_count ? 'PART' : 'NONE');
    const brief = res.plans.filter(p => p.valid)
      .map(p => `${p.id} ¥${p.total.toFixed(0)}/${p.unique_mains}种`)
      .join('  ');
    if (errs.length) {
      console.log(`[FAIL] ¥${budget} ${label}`);
      errs.forEach(e => console.log('      × ' + e));
      fail += errs.length;
    } else {
      console.log(`[${tag}] ¥${budget} ${label.padEnd(18)} ${brief || '（无可行方案，走诊断分支）'}`);
    }
  }
}

console.log('');
if (fail) {
  console.log(`${total} 组中 ${fail} 个问题`);
  process.exit(1);
}
console.log(`${total} 组全部通过：无异常、无 NaN、无超预算、无忌口违规，无解时正确降级到诊断`);
