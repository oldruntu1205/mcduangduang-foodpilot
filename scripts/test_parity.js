#!/usr/bin/env node
/*
 * test_parity.js —— Python 求解器 与 JS 求解器 的等价性验证
 *
 * 页面上有两条计算路径：首屏用 Python 的结果，点开关后走 JS 重算。
 * 两者一旦算出不同答案，演示时就会出现"点一下开关，总价莫名其妙变了"的事故。
 * 所以每次改 meal_solver.py 或 solver_core.js，都必须跑这个脚本。
 *
 * 用法：
 *     node test_parity.js
 *     node test_parity.js --plan ../demo/plan.json --menu ../demo/menu_demo.json
 */

const fs = require('fs');
const path = require('path');
const { solveAll } = require('./solver_core.js');

function arg(name, dflt) {
  const i = process.argv.indexOf('--' + name);
  return i > -1 ? process.argv[i + 1] : dflt;
}

const planPath = path.resolve(arg('plan', path.join(__dirname, '..', 'demo', 'plan.json')));
const menuPath = path.resolve(arg('menu', path.join(__dirname, '..', 'demo', 'menu_demo.json')));

const plan = JSON.parse(fs.readFileSync(planPath, 'utf8'));
const menu = JSON.parse(fs.readFileSync(menuPath, 'utf8'));

const res = solveAll(menu, plan.people, plan.budget);

let fail = 0;
const note = (m) => { console.log('  × ' + m); fail++; };

console.log(`菜单 ${menu.items.length} 项 · ${plan.people.length} 人 · ¥${plan.budget}\n`);

for (const py of plan.plans) {
  const js = res.plans.find(p => p.id === py.id);
  if (!js) { note(`方案 ${py.id} 在 JS 侧缺失`); continue; }

  const fields = [
    ['total', py.total, js.total, 0.011],
    ['main_total', py.main_total, js.main_total, 0.011],
    ['share_total', py.share_total, js.share_total, 0.011],
    ['remaining', py.remaining, js.remaining, 0.011],
    ['unique_mains', py.unique_mains, js.unique_mains, 0],
    ['total_kcal', py.total_kcal, js.total_kcal, 0],
    ['share_kcal_each', Math.round(py.share_kcal_each), Math.round(js.share_kcal_each), 0],
  ];

  const diffs = [];
  for (const [k, a, b, tol] of fields) {
    if (Math.abs(a - b) > tol) diffs.push(`${k}: python=${a} js=${b}`);
  }

  // 选品必须完全一致——价格碰巧相等但换了菜，说明打分或排序有偏差
  const pyMain = py.assignments.map(a => a.item.code).join(',');
  const jsMain = js.assignments.map(a => a.item.code).join(',');
  if (pyMain !== jsMain) diffs.push(`主餐选品不同\n      py=[${pyMain}]\n      js=[${jsMain}]`);

  const pyShare = py.shared.map(s => s.code).join(',');
  const jsShare = js.shared.map(s => s.code).join(',');
  if (pyShare !== jsShare) diffs.push(`共享小食不同\n      py=[${pyShare}]\n      js=[${jsShare}]`);

  // 每条理由也要一致，否则交互后文案会"悄悄变形"
  const pyReason = py.assignments.map(a => a.reason).join('|');
  const jsReason = js.assignments.map(a => a.reason).join('|');
  if (pyReason !== jsReason) diffs.push('取舍理由文案不一致');

  if (diffs.length) {
    console.log(`[FAIL] 方案 ${py.id} · ${py.name}`);
    diffs.forEach(d => note(d));
  } else {
    console.log(`[ OK ] 方案 ${py.id} · ${py.name}  ¥${js.total.toFixed(2)}  ` +
      `${js.unique_mains} 种  ${js.total_kcal}kcal`);
  }
}

// 结论行也要一致
const pyCmp = (plan.compare || []).join('\n');
const jsCmp = (res.compare || []).join('\n');
if (pyCmp !== jsCmp) note('compare 结论文案不一致');

console.log('');
if (fail) {
  console.log(`${fail} 处不一致 —— 两个求解器已经漂移，先修再交付`);
  process.exit(1);
}
console.log('等价性通过：JS 求解器与 Python 求解器输出完全一致');
