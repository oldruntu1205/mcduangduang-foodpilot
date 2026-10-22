#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_compare_page.py —— 把求解器输出渲染成一张可交互的单文件对比页。

三条原则：
1. 页面上的数字只有一个来源。首屏数据来自 meal_solver 的当次输出，交互重算走内嵌的
   JS 版求解器——两者在启动时做一次 baseline 比对，漂移会被抓出来。
2. 求解器翻译成 JS 而不是起本地服务。演示现场最怕端口被占、服务没起来，
   双击即开 / 断网可用比什么都重要。
3. 模板只有一份（在 JS 里）。首屏和重算走同一个渲染函数，不存在两套模板对不上的问题。

页面能力：
  · 日间/夜间双主题（跟随系统 + 手动切换 + 记忆）
  · 演示模式（整体放大、隐藏脚注，适配投影）
  · 400 粒子背景
  · 每套方案的热量堆叠条（主餐 / 小食饮料 / 甜点三段分色）
  · 可展开全部备选菜品，标注换菜价差与热量差
  · 调节台：改忌口 / 改热量上限 / 改预算，点击即重算

用法：
    python meal_solver.py --menu ../demo/menu_demo.json \\
        --people "王磊:nobeef;李婷:nospicy;张敏:lowcal600;陈昊:;赵宇:" \\
        --budget 160 --format json -o ../demo/plan.json

    python build_compare_page.py ../demo/plan.json \\
        --menu ../demo/menu_demo.json -o ../demo/compare.html
"""

import argparse
import datetime
import html
import json
import os
import sys

TITLE = "FoodPilot 方案对比"

SOLVER_CORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "solver_core.js")


def load_solver_js() -> str:
    """求解器只有一份源码（solver_core.js）：页面内嵌它，Node 也用它跑等价性测试。"""
    with open(SOLVER_CORE, encoding="utf-8") as f:
        return f.read()

BASE_CSS = """
*{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#F7F7F5; --card:#FFFFFF; --panel:#FCFCFA; --line:#E5E3DD; --line-soft:#F0EEE9;
  --text:#1F1F1D; --text2:#3C3B37; --muted:#6B6A64; --faint:#9A9992;
  --cA:#5F5E5A; --cB:#A32D2D; --cC:#0F6E56;
  --chip-bg:#FFFFFF; --track:#F2F1EC;
  --con-bg:#FCEBEB; --con-fg:#A32D2D; --con-none-bg:#F2F1EC; --con-none-fg:#8A8983;
  --warn-bg:#FAEEDA; --warn-fg:#633806; --warn-line:#FAC775;
  --err-bg:#FCEBEB; --err-fg:#791F1F;
  --dessert:#D98324; --shadow:rgba(0,0,0,.07);
  --btn-bg:#FFFFFF; --btn-line:#E5E3DD; --btn-active:#1F1F1D; --btn-active-fg:#FFFFFF;
}
html[data-theme="dark"]{
  --bg:#13151A; --card:#1D1F26; --panel:#22252D; --line:#2E313A; --line-soft:#262A32;
  --text:#ECEBE7; --text2:#D2D1CB; --muted:#9A9992; --faint:#7B7A75;
  --cA:#A8A79F; --cB:#E28080; --cC:#4FB99A;
  --chip-bg:#22252D; --track:#2A2E37;
  --con-bg:#3A2323; --con-fg:#F09595; --con-none-bg:#2A2E37; --con-none-fg:#8A8983;
  --warn-bg:#3A2E14; --warn-fg:#FAC775; --warn-line:#5A4520;
  --err-bg:#3A2323; --err-fg:#F7C1C1;
  --dessert:#E8A33D; --shadow:rgba(0,0,0,.4);
  --btn-bg:#22252D; --btn-line:#2E313A; --btn-active:#ECEBE7; --btn-active-fg:#13151A;
}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif;
  background:var(--bg);color:var(--text);line-height:1.6;-webkit-font-smoothing:antialiased;
  transition:background .35s,color .35s}
#bg{position:fixed;inset:0;z-index:0;pointer-events:none;display:block}
.wrap{position:relative;z-index:1;max-width:1260px;margin:0 auto;padding:40px 28px 64px}

.topbtns{position:fixed;top:18px;right:18px;z-index:20;display:flex;gap:8px}
.tbtn{height:40px;padding:0 14px;border-radius:12px;border:1px solid var(--btn-line);
  background:var(--btn-bg);color:var(--muted);cursor:pointer;display:flex;align-items:center;
  gap:7px;font-size:12.5px;font-family:inherit;transition:color .2s,border-color .2s,transform .2s}
.tbtn:hover{color:var(--text);transform:translateY(-1px)}
.tbtn svg{width:16px;height:16px;fill:none;stroke:currentColor;stroke-width:1.6;
  stroke-linecap:round;stroke-linejoin:round}
html[data-theme="light"] .icon-moon{display:none}
html[data-theme="dark"] .icon-sun{display:none}
html[data-present="on"] #presentbtn{background:var(--btn-active);color:var(--btn-active-fg);
  border-color:var(--btn-active)}

.hero{margin-bottom:30px}
.brand{display:flex;align-items:baseline;gap:10px;margin-bottom:14px}
.brand h1{font-size:20px;font-weight:600;letter-spacing:-.2px}
.brand .tag{font-size:12px;color:var(--muted);border:1px solid var(--line);
  border-radius:99px;padding:2px 10px;background:var(--chip-bg)}
.scene{font-size:15px;color:var(--text2);margin-bottom:14px}
.scene b{font-weight:600;color:var(--text)}
.chips{display:flex;flex-wrap:wrap;gap:8px}
.chip{font-size:12.5px;background:var(--chip-bg);border:1px solid var(--line);
  border-radius:99px;padding:4px 11px;color:var(--text2);transition:border-color .25s,background .25s}
.chip i{font-style:normal;color:var(--cB);font-weight:500}
.chip.hit{border-color:var(--cB)}

.panel{background:var(--card);border:1px solid var(--line);border-radius:16px;
  padding:16px 18px;margin-top:18px}
.panel-title{font-size:12px;font-weight:600;color:var(--muted);letter-spacing:.5px;margin-bottom:12px}
.ctrls{display:flex;flex-wrap:wrap;gap:9px;align-items:center}
.sw{display:inline-flex;align-items:center;gap:8px;font-size:12.5px;color:var(--text2);
  border:1px solid var(--line);background:var(--panel);border-radius:10px;padding:7px 12px;
  cursor:pointer;user-select:none;transition:border-color .2s,background .2s,color .2s}
.sw:hover{border-color:var(--muted)}
.sw input{appearance:none;width:30px;height:17px;border-radius:99px;background:var(--track);
  position:relative;cursor:pointer;transition:background .2s;flex-shrink:0;margin:0}
.sw input::after{content:"";position:absolute;top:2px;left:2px;width:13px;height:13px;
  border-radius:50%;background:var(--card);box-shadow:0 1px 2px rgba(0,0,0,.2);transition:transform .2s}
.sw input:checked{background:var(--cB)}
.sw input:checked::after{transform:translateX(13px)}
.sw.on{border-color:var(--cB);color:var(--text)}
.seg{display:flex;border:1px solid var(--line);border-radius:10px;overflow:hidden;margin-left:4px}
.seg button{border:0;background:var(--panel);color:var(--muted);font-family:inherit;font-size:12.5px;
  padding:8px 14px;cursor:pointer;transition:background .2s,color .2s;
  border-right:1px solid var(--line)}
.seg button:last-child{border-right:0}
.seg button.on{background:var(--btn-active);color:var(--btn-active-fg)}
.seg .lb{border:0;background:transparent;cursor:default;color:var(--faint);padding-right:6px}

.sec-title{font-size:12.5px;font-weight:600;color:var(--muted);letter-spacing:.6px;
  margin:32px 0 14px;display:flex;align-items:center;gap:10px}
.sec-title .hint{font-weight:400;letter-spacing:0;color:var(--faint);font-size:11.5px}

.metrics{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:22px 24px}
.mrow{display:grid;grid-template-columns:88px 1fr;align-items:center;gap:16px;
  padding:10px 0;border-bottom:1px dashed var(--line-soft)}
.mrow:last-child{border-bottom:0}
.mlabel{font-size:12.5px;color:var(--muted)}
.mbars{display:flex;flex-direction:column;gap:7px}
.mbar{display:flex;align-items:center;gap:10px}
.mtrack{flex:1;height:20px;background:var(--track);border-radius:5px;overflow:hidden}
.mfill{height:100%;border-radius:5px;transition:width .5s cubic-bezier(.2,.8,.3,1)}
.mval{font-size:12.5px;font-variant-numeric:tabular-nums;width:108px;flex-shrink:0;color:var(--text2)}
.mtag{font-size:11px;font-weight:600;width:14px;flex-shrink:0}

.plans{display:grid;grid-template-columns:repeat(3,1fr);gap:18px;align-items:start}
@media(max-width:1020px){.plans{grid-template-columns:1fr}}
.fade{animation:fadein .32s ease-out}
@keyframes fadein{from{opacity:.35;transform:translateY(3px)}to{opacity:1;transform:none}}

.plan{background:var(--card);border:1px solid var(--line);border-radius:16px;overflow:hidden;
  display:flex;flex-direction:column;transition:box-shadow .2s,transform .2s}
.plan:hover{box-shadow:0 6px 26px var(--shadow);transform:translateY(-2px)}
.plan-head{padding:18px 20px 14px;border-bottom:1px solid var(--line-soft)}
.plan-name{font-size:16px;font-weight:600;display:flex;align-items:center;gap:8px}
.dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}
.plan-desc{font-size:12.5px;color:var(--muted);margin-top:5px;min-height:34px}
.plan-badge{display:inline-block;font-size:11px;font-weight:600;padding:2px 8px;
  border-radius:5px;margin-top:9px}

.price-box{padding:16px 20px 14px;border-bottom:1px solid var(--line-soft);background:var(--panel)}
.big{font-size:30px;font-weight:600;letter-spacing:-1px;font-variant-numeric:tabular-nums}
.big small{font-size:14px;font-weight:400;color:var(--muted);margin-left:2px}
.subrow{display:flex;gap:18px;margin-top:8px;font-size:12.5px;color:var(--muted)}
.subrow b{color:var(--text);font-weight:600;font-variant-numeric:tabular-nums}

.stackbox{padding:14px 20px 16px;border-bottom:1px solid var(--line-soft);background:var(--panel)}
.stack-head{display:flex;justify-content:space-between;align-items:baseline;
  font-size:12px;color:var(--muted);margin-bottom:8px}
.stack-head b{font-size:13px;color:var(--text);font-variant-numeric:tabular-nums}
.stack{display:flex;height:14px;border-radius:4px;overflow:hidden;background:var(--track)}
.seg{height:100%}
.seg.main{background:var(--pc)}
.seg.share{background:var(--pc);opacity:.42}
.seg.dessert{background:var(--dessert)}
.legend{display:flex;flex-wrap:wrap;gap:12px;margin-top:8px;font-size:11px;color:var(--muted)}
.legend span{display:flex;align-items:center;gap:5px}
.legend i{width:8px;height:8px;border-radius:2px;display:inline-block}
.legend i.lm{background:var(--pc)}
.legend i.ls{background:var(--pc);opacity:.42}
.legend i.ld{background:var(--dessert)}
.legend em{font-style:normal;color:var(--text2);font-variant-numeric:tabular-nums}
.nodessert{font-size:11px;color:var(--faint)}

.people{padding:6px 20px 4px;flex:1}
.prow{padding:13px 0;border-bottom:1px solid var(--line-soft)}
.prow:last-child{border-bottom:0}
.pwho{display:flex;align-items:center;gap:7px;margin-bottom:5px;flex-wrap:wrap}
.pname{font-size:13px;font-weight:600}
.pcon{font-size:11px;color:var(--con-fg);background:var(--con-bg);border-radius:4px;padding:1px 6px}
.pcon.none{color:var(--con-none-fg);background:var(--con-none-bg)}
.pitem{display:flex;justify-content:space-between;align-items:baseline;gap:10px}
.pdish{font-size:13px;color:var(--text)}
.pnum{font-size:12.5px;color:var(--muted);font-variant-numeric:tabular-nums;white-space:nowrap}
.preason{font-size:11.5px;color:var(--faint);line-height:1.5;margin-top:4px;
  padding-left:9px;border-left:2px solid var(--line-soft)}

.shared{padding:12px 20px;background:var(--panel);border-top:1px solid var(--line-soft);font-size:12.5px}
.shared .sl{color:var(--muted);margin-bottom:3px}
.shared .sv{color:var(--text2)}

.alts{border-top:1px solid var(--line-soft);background:var(--panel)}
.alts summary{list-style:none;cursor:pointer;padding:12px 20px;font-size:12.5px;
  color:var(--muted);display:flex;align-items:center;gap:8px;user-select:none;transition:color .2s}
.alts summary:hover{color:var(--text)}
.alts summary::-webkit-details-marker{display:none}
.alts summary::before{content:"";width:0;height:0;flex-shrink:0;
  border-left:5px solid currentColor;border-top:4px solid transparent;
  border-bottom:4px solid transparent;transition:transform .2s}
.alts[open] summary::before{transform:rotate(90deg)}
.alts[open] summary{color:var(--text)}
.alt-body{padding:0 20px 16px}
.alt-group{padding:9px 0;border-bottom:1px dashed var(--line-soft)}
.alt-group:last-child{border-bottom:0}
.alt-who{font-size:11.5px;color:var(--muted);margin-bottom:5px}
.alt-who b{color:var(--text2);font-weight:600}
.alt-item{display:flex;justify-content:space-between;gap:8px;font-size:12px;
  padding:3px 0 3px 10px;color:var(--text2)}
.alt-item .d{font-variant-numeric:tabular-nums;color:var(--faint);white-space:nowrap}
.alt-item .up{color:var(--cB)}
.alt-item .down{color:var(--cC)}

.checks{margin:0 20px 18px;padding:11px 13px;border-radius:10px;font-size:11.5px;line-height:1.6}
.checks.warn{background:var(--warn-bg);color:var(--warn-fg)}
.checks.err{background:var(--err-bg);color:var(--err-fg)}
.checks:empty{display:none}
.plan-err{margin:0 20px 18px;padding:12px 14px;border-radius:10px;font-size:12.5px;
  background:var(--err-bg);color:var(--err-fg)}

.why{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:24px 26px}
.why h3{font-size:14px;font-weight:600;margin-bottom:12px}
.why ol{margin-left:18px;font-size:13.5px;color:var(--text2)}
.why li{margin-bottom:7px}
.why code{background:var(--track);padding:1px 6px;border-radius:4px;font-size:12.5px;
  font-family:ui-monospace,Consolas,monospace}
.why p{font-size:13px;color:var(--muted);margin-top:14px}
.concl{display:flex;flex-direction:column;gap:8px}
.concl div{font-size:13.5px;color:var(--text2);background:var(--panel);border:1px solid var(--line-soft);
  border-radius:9px;padding:10px 14px}

footer{margin-top:34px;padding-top:18px;border-top:1px solid var(--line);
  font-size:11.5px;color:var(--faint);line-height:1.7}
.dev{margin-top:10px;font-size:11px;color:var(--faint);font-family:ui-monospace,Consolas,monospace}

/* ---- 演示模式：投影上后排要看得见，所以整体放大并砍掉次要信息 ---- */
html[data-present="on"] body{zoom:1.18}
html[data-present="on"] .wrap{max-width:1080px;padding-top:64px}
html[data-present="on"] footer{display:none}
html[data-present="on"] .sec-title{margin:26px 0 12px}
html[data-present="on"] .plan-desc{min-height:0}
"""

THEME_BTN = """<svg class="icon-sun" viewBox="0 0 24 24"><circle cx="12" cy="12" r="4.2"/>
<path d="M12 2.6v2.4M12 19v2.4M2.6 12h2.4M19 12h2.4M5.3 5.3l1.7 1.7M17 17l1.7 1.7M18.7 5.3L17 7M7 17l-1.7 1.7"/></svg>
<svg class="icon-moon" viewBox="0 0 24 24"><path d="M20.5 14.3A8.6 8.6 0 0 1 9.7 3.5a8.6 8.6 0 1 0 10.8 10.8z"/></svg>"""

PRESENT_BTN = """<svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="12" rx="2"/>
<path d="M12 16v4M8.5 20h7"/></svg>"""

# ---------------------------------------------------------------- 页面交互脚本
# 求解器不在这里：唯一源码是同目录的 solver_core.js。
# build() 时读进来内嵌；Node 侧由 test_parity.js 用它和 Python 版做等价性验证。

UI_JS = r"""
const E=s=>String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const MEAT_LABEL={beef:'牛肉',chicken:'鸡肉',fish:'鱼肉',pork:'猪肉'};

function consChip(p){
  const b=[];
  if(p.avoid_meats&&p.avoid_meats.length){
    if(p.avoid_meats.length===4) b.push('素食');
    else b.push('不吃'+p.avoid_meats.map(m=>MEAT_LABEL[m]||m).join('/'));
  }
  if(p.no_spicy) b.push('不吃辣');
  if(p.kcal_max) b.push('≤'+p.kcal_max+'kcal');
  return {txt:b.join('、'),has:b.length>0};
}

function splitKcal(plan){
  const main=plan.assignments.reduce((s,a)=>s+a.item.kcal,0);
  const dessert=plan.shared.filter(s=>s.category==='dessert').reduce((s,i)=>s+i.kcal,0);
  const share=plan.shared.reduce((s,i)=>s+i.kcal,0)-dessert;
  return [main,share,dessert];
}

function renderChips(people){
  return people.map(p=>{
    const c=consChip(p);
    return c.has
      ? '<span class="chip">'+E(p.name)+' <i>'+E(c.txt)+'</i></span>'
      : '<span class="chip">'+E(p.name)+' 无特殊要求</span>';
  }).join('');
}

function renderMetrics(res,plans){
  const ok=plans.filter(p=>p.valid);
  if(!ok.length) return '<div class="metrics"><div class="mlabel">当前条件下无可行方案</div></div>';
  const rows=[
    ['总价',p=>p.total,v=>'¥'+v.toFixed(2)],
    ['整桌热量',p=>p.total_kcal,v=>v+' kcal'],
    ['主餐种类',p=>p.unique_mains,v=>v+' 种'],
    ['预算结余',p=>p.remaining,v=>'¥'+v.toFixed(2)]
  ];
  return '<div class="metrics">'+rows.map(([label,get,fmt])=>{
    const max=Math.max(...ok.map(get))||1;
    const bars=ok.map(p=>{
      const pct=Math.max(6,Math.round(get(p)/max*100));
      const v=PLAN_VAR[p.id]||'--cA';
      return '<div class="mbar"><span class="mtag" style="color:var('+v+')">'+p.id+'</span>'
        +'<div class="mtrack"><div class="mfill" style="width:'+pct+'%;background:var('+v+')"></div></div>'
        +'<span class="mval">'+fmt(get(p))+'</span></div>';
    }).join('');
    return '<div class="mrow"><span class="mlabel">'+label+'</span><div class="mbars">'+bars+'</div></div>';
  }).join('')+'</div>';
}

function renderPlans(res){
  const plans=res.plans,people=res.people,budget=res.budget;
  const ok=plans.filter(p=>p.valid);
  const badges={};
  if(ok.length){
    const cheap=ok.reduce((a,b)=>a.total<b.total?a:b);
    const uniq=ok.reduce((a,b)=>a.unique_mains>b.unique_mains?a:b);
    const kcal=ok.reduce((a,b)=>a.total_kcal<b.total_kcal?a:b);
    badges[cheap.id]=['最便宜','#EAF3DE','#27500A','#C0DD97'];
    badges[uniq.id]=['最不重样','#FCEBEB','#791F1F','#F7C1C1'];
    badges[kcal.id]=['热量最低','#E1F5EE','#085041','#9FE1CB'];
  }
  const maxKcal=Math.max(1,...ok.map(p=>p.total_kcal));

  return plans.map(plan=>{
    const v=PLAN_VAR[plan.id]||'--cA';
    const bd=badges[plan.id];
    const badge=bd?'<span class="plan-badge" style="background:'+bd[1]+';color:'+bd[2]
      +';border:1px solid '+bd[3]+'">'+bd[0]+'</span>':'';
    const head='<div class="plan-head" style="border-top:3px solid var('+v+')">'
      +'<div class="plan-name"><span class="dot" style="background:var('+v+')"></span>'
      +'方案 '+E(plan.id)+' · '+E(plan.name)+'</div>'
      +'<div class="plan-desc">'+E(plan.tagline)+'</div>'+badge+'</div>';

    if(plan.error) return '<div class="plan">'+head
      +'<div class="price-box"><div class="preason">'+E(plan.error)+'</div></div></div>';

    const price='<div class="price-box"><div class="big">¥'+plan.total.toFixed(2)
      +'<small>/ 预算 ¥'+budget.toFixed(0)+'</small></div>'
      +'<div class="subrow"><span>结余 <b>¥'+plan.remaining.toFixed(2)+'</b></span>'
      +'<span>主餐 <b>'+plan.unique_mains+'</b> 种</span>'
      +'<span>共 <b>'+(1+plan.shared.length)+'</b> 件</span></div></div>';

    const [km,ks,kd]=splitKcal(plan);
    const totalK=km+ks+kd;
    const barW=Math.max(8,Math.round(totalK/maxKcal*100));
    let segs='<div class="seg main" style="flex:'+Math.max(km,0)+'"></div>';
    if(ks>0) segs+='<div class="seg share" style="flex:'+ks+'"></div>';
    if(kd>0) segs+='<div class="seg dessert" style="flex:'+kd+'"></div>';
    let legend='<span><i class="lm"></i>主餐 <em>'+km+'</em></span>';
    if(ks>0) legend+='<span><i class="ls"></i>小食饮料 <em>'+ks+'</em></span>';
    legend+= kd>0
      ? '<span><i class="ld"></i>甜点 <em>'+kd+'</em></span>'
      : '<span class="nodessert">未配甜点</span>';
    const stack='<div class="stackbox" style="--pc:var('+v+')">'
      +'<div class="stack-head"><span>整桌热量分解</span><span><b>'+totalK+'</b> kcal</span></div>'
      +'<div class="stack" style="width:'+barW+'%">'+segs+'</div>'
      +'<div class="legend">'+legend+'</div></div>';

    const rows=plan.assignments.map(a=>{
      const p=people.find(x=>x.name===a.person)||{};
      const c=consChip(p);
      const con=c.has?'<span class="pcon">'+E(c.txt)+'</span>'
                     :'<span class="pcon none">无要求</span>';
      return '<div class="prow"><div class="pwho"><span class="pname">'+E(a.person)+'</span>'+con+'</div>'
        +'<div class="pitem"><span class="pdish">'+E(a.item.name)+'</span>'
        +'<span class="pnum">¥'+a.item.price.toFixed(2)+' · '+a.item.kcal+'kcal</span></div>'
        +'<div class="preason">'+E(a.reason)+'</div></div>';
    }).join('');

    let shared='';
    if(plan.shared.length){
      const items=plan.shared.map(s=>E(s.name)+' ¥'+s.price.toFixed(2)).join(' ・ ');
      shared='<div class="shared"><div class="sl">共享小食（'+plan.shared.length+' 份，人均分摊约 '
        +plan.share_kcal_each+' kcal）</div><div class="sv">'+items+'</div></div>';
    }

    let altGroups='',altTotal=0;
    for(const a of plan.assignments){
      const alts=a.alternatives||[];
      if(!alts.length) continue;
      const cur=a.item;
      const lines=alts.map(t=>{
        altTotal++;
        const dp=t.price-cur.price,dk=t.kcal-cur.kcal;
        const cp=dp>0?'up':(dp<0?'down':''),ck=dk>0?'up':(dk<0?'down':'');
        return '<div class="alt-item"><span>'+E(t.name)+'</span><span class="d">¥'+t.price.toFixed(2)
          +' <span class="'+cp+'">'+(Math.abs(dp)<1e-9?'±0':(dp>0?'+':'')+dp.toFixed(2))+'</span>　'
          +t.kcal+'kcal <span class="'+ck+'">'+(dk===0?'±0':(dk>0?'+':'')+dk)+'</span></span></div>';
      }).join('');
      altGroups+='<div class="alt-group"><div class="alt-who"><b>'+E(a.person)+'</b> 现选 '
        +E(cur.name)+' ¥'+cur.price.toFixed(2)+'</div>'+lines+'</div>';
    }
    const alts=altTotal
      ? '<details class="alts"><summary>展开全部备选菜品（'+altTotal+' 个，标注换菜价差与热量差）</summary>'
        +'<div class="alt-body">'+altGroups+'</div></details>'
      : '';

    const errs=plan.checks.filter(c=>c.level==='error').map(c=>E(c.msg));
    const warns=plan.checks.filter(c=>c.level==='warn').map(c=>E(c.msg));
    let checks='';
    if(errs.length) checks+='<div class="checks err">'+errs.join('<br>')+'</div>';
    if(warns.length) checks+='<div class="checks warn">'+warns.join('<br>')+'</div>';

    return '<div class="plan">'+head+price+stack+'<div class="people">'+rows+'</div>'
      +shared+alts+checks+'</div>';
  }).join('');
}

function renderConcl(res){
  let h=res.compare.map(c=>'<div>'+E(c)+'</div>').join('');
  if(res.diagnosis&&res.diagnosis.length)
    h+=res.diagnosis.map(d=>'<div style="background:var(--warn-bg);border-color:var(--warn-line);'
      +'color:var(--warn-fg)">'+E(d)+'</div>').join('');
  return h;
}

/* ---------------- 调节台 ---------------- */
const DEPTS=[
  {key:'chenBeef',name:'陈昊',label:'陈昊也不吃牛肉',on:p=>{p.avoid_meats.push('beef')},
   avail:people=>people.some(p=>p.name==='陈昊')},
  {key:'liSpicy',name:'李婷',label:'李婷其实能吃微辣',on:p=>{p.no_spicy=false},
   avail:people=>people.some(p=>p.name==='李婷'&&p.no_spicy)},
  {key:'zhangStrict',name:'张敏',label:'张敏收紧到 500kcal',on:p=>{p.kcal_max=500},
   avail:people=>people.some(p=>p.name==='张敏')}
];

function deriveState(){
  const people=JSON.parse(JSON.stringify(PEOPLE_INIT));
  for(const d of DEPTS){
    if(!UI[d.key]) continue;
    const p=people.find(x=>x.name===d.name);
    if(p) d.on(p);
  }
  return {people,budget:UI.budget};
}

function renderAll(){
  const {people,budget}=deriveState();
  const res=solveAll(MENU,people,budget);
  document.getElementById('chips').innerHTML=renderChips(people);
  document.getElementById('metrics').innerHTML=renderMetrics(res,res.plans);
  const box=document.getElementById('plans');
  box.innerHTML=renderPlans(res);
  box.classList.remove('fade'); void box.offsetWidth; box.classList.add('fade');
  document.getElementById('concl').innerHTML=renderConcl(res);
  const n=document.getElementById('fcount');
  if(n) n.textContent=res.feasible_count+' / 3 套可行';
}

function buildControls(){
  const wrap=document.getElementById('ctrls');
  const html=[];
  for(const d of DEPTS){
    if(!d.avail(PEOPLE_INIT)) continue;
    html.push('<label class="sw'+(UI[d.key]?' on':'')+'" data-k="'+d.key+'">'
      +'<input type="checkbox" '+(UI[d.key]?'checked':'')+' data-k="'+d.key+'">'
      +E(d.label)+'</label>');
  }
  const opts=BUDGET_OPTS.map(b=>'<button data-b="'+b+'"'
    +(Math.abs(b-UI.budget)<1e-9?' class="on"':'')+'>¥'+b+'</button>').join('');
  html.push('<div class="seg"><span class="lb" style="padding:8px 6px 8px 12px">预算</span>'+opts+'</div>');
  wrap.innerHTML=html.join('');

  wrap.querySelectorAll('input[type=checkbox]').forEach(cb=>{
    cb.addEventListener('change',()=>{
      UI[cb.dataset.k]=cb.checked;
      cb.closest('.sw').classList.toggle('on',cb.checked);
      renderAll();
    });
  });
  wrap.querySelectorAll('.seg button').forEach(btn=>{
    btn.addEventListener('click',()=>{
      UI.budget=parseFloat(btn.dataset.b);
      wrap.querySelectorAll('.seg button').forEach(b=>b.classList.toggle('on',b===btn));
      renderAll();
    });
  });
}

/* ---------------- baseline 校验 ---------------- */
function checkBaseline(){
  try{
    const res=solveAll(MENU,PEOPLE_INIT,BUDGET_INIT);
    const msgs=[];
    for(const id of Object.keys(BASELINE)){
      const jp=res.plans.find(p=>p.id===id), py=BASELINE[id];
      if(!jp){msgs.push(id+': JS 缺失');continue;}
      if(Math.abs(jp.total-py.total)>0.01) msgs.push(id+' 总价 JS='+jp.total+' Python='+py.total);
      if(jp.unique_mains!==py.unique_mains) msgs.push(id+' 种类 JS='+jp.unique_mains+' Python='+py.unique_mains);
      if(jp.total_kcal!==py.total_kcal) msgs.push(id+' 热量 JS='+jp.total_kcal+' Python='+py.total_kcal);
    }
    if(msgs.length){
      console.warn('[FoodPilot] JS 求解器与 Python 输出不一致：',msgs);
      const dev=document.getElementById('dev');
      if(dev) dev.textContent='⚠ 求解器漂移：'+msgs.join('；');
    }
  }catch(e){console.warn('[FoodPilot] baseline 校验异常',e);}
}

/* ---------------- 主题 / 演示模式 / 粒子 ---------------- */
(function(){
  const root=document.documentElement;
  function store(k,v){try{localStorage.setItem(k,v)}catch(e){}}
  function read(k){try{return localStorage.getItem(k)}catch(e){return null}}

  const qs=new URLSearchParams(location.search);
  const qTheme=qs.get('theme');
  const mq=window.matchMedia('(prefers-color-scheme: dark)');
  const saved=qTheme||read('fp-theme');
  root.setAttribute('data-theme',saved||(mq.matches?'dark':'light'));
  document.getElementById('themebtn').addEventListener('click',()=>{
    const next=root.getAttribute('data-theme')==='dark'?'light':'dark';
    root.setAttribute('data-theme',next); store('fp-theme',next);
  });
  mq.addEventListener('change',e=>{ if(!read('fp-theme')) root.setAttribute('data-theme',e.matches?'dark':'light'); });

  if(qs.get('present')==='1'||read('fp-present')==='on') root.setAttribute('data-present','on');
  const pb=document.getElementById('presentbtn');
  function syncPresent(){
    const on=root.getAttribute('data-present')==='on';
    pb.querySelector('span').textContent=on?'退出演示':'演示模式';
  }
  syncPresent();
  pb.addEventListener('click',()=>{
    const on=root.getAttribute('data-present')==='on';
    if(on){root.removeAttribute('data-present');store('fp-present','off');}
    else{root.setAttribute('data-present','on');store('fp-present','on');}
    syncPresent();
  });

  const cvs=document.getElementById('bg'),ctx=cvs.getContext('2d');
  let W=0,H=0,ps=[],N=400,LINK=118,LINK2=LINK*LINK,IS_DARK=false;
  const reduce=window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function resize(){
    const dpr=Math.min(window.devicePixelRatio||1,2);
    W=window.innerWidth;H=window.innerHeight;
    cvs.width=Math.floor(W*dpr);cvs.height=Math.floor(H*dpr);
    cvs.style.width=W+'px';cvs.style.height=H+'px';
    ctx.setTransform(dpr,0,0,dpr,0,0);
  }
  function seed(){
    ps=[];
    for(let i=0;i<N;i++) ps.push({x:Math.random()*W,y:Math.random()*H,
      vx:(Math.random()-.5)*.20,vy:(Math.random()-.5)*.20,
      r:Math.random()*1.5+.7,a:Math.random()*.55+.3});
  }
  function frame(){
    IS_DARK=root.getAttribute('data-theme')==='dark';
    ctx.clearRect(0,0,W,H);
    const rgb=IS_DARK?'255,255,255':'28,28,26';
    const dotA=IS_DARK?.42:.30, lineK=IS_DARK?.10:.07;
    for(let i=0;i<ps.length;i++){
      const p=ps[i];
      p.x+=p.vx;p.y+=p.vy;
      if(p.x<-12)p.x=W+12;else if(p.x>W+12)p.x=-12;
      if(p.y<-12)p.y=H+12;else if(p.y>H+12)p.y=-12;
      for(let j=i+1;j<ps.length&&j<i+16;j++){
        const q=ps[j],dx=p.x-q.x,dy=p.y-q.y,d2=dx*dx+dy*dy;
        if(d2<LINK2){
          ctx.strokeStyle='rgba('+rgb+','+((1-d2/LINK2)*lineK).toFixed(3)+')';
          ctx.lineWidth=.5;ctx.beginPath();ctx.moveTo(p.x,p.y);ctx.lineTo(q.x,q.y);ctx.stroke();
        }
      }
      ctx.fillStyle='rgba('+rgb+','+(p.a*dotA).toFixed(3)+')';
      ctx.beginPath();ctx.arc(p.x,p.y,p.r,0,6.2832);ctx.fill();
    }
    if(!reduce) requestAnimationFrame(frame);
  }
  resize();seed();frame();
  let rt;
  window.addEventListener('resize',()=>{
    clearTimeout(rt);
    rt=setTimeout(()=>{resize();seed();if(reduce){ctx.clearRect(0,0,W,H);frame();}},180);
  });
})();

/* ---------------- 启动 ---------------- */
const UI={chenBeef:false,liSpicy:false,zhangStrict:false,budget:BUDGET_INIT};
buildControls();
renderAll();
checkBaseline();
"""


def esc(v) -> str:
    return html.escape(str(v))


def build(plan: dict, menu: dict, note: str = "") -> str:
    people = plan["people"]
    budget = plan["budget"]

    # 预算档位：基于初始值派生，四舍五入到 10
    opts = sorted({int(round(budget * 0.875 / 10) * 10), int(budget),
                   int(round(budget * 1.25 / 10) * 10)})

    baseline = {}
    for p in plan["plans"]:
        if p.get("valid"):
            baseline[p["id"]] = {"total": p["total"], "unique_mains": p["unique_mains"],
                                 "total_kcal": p["total_kcal"]}

    data_js = (
        f"const MENU={json.dumps(menu, ensure_ascii=False)};\n"
        f"const PEOPLE_INIT={json.dumps(people, ensure_ascii=False)};\n"
        f"const BUDGET_INIT={budget};\n"
        f"const BUDGET_OPTS={json.dumps(opts)};\n"
        f"const BASELINE={json.dumps(baseline, ensure_ascii=False)};\n"
    )

    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    foot = ("数据来源：首屏为 meal_solver.py 单次输出，交互重算由页面内嵌的同源求解器完成；"
            "两者启动时比对一次，不一致会在此处告警。" + esc(note) + "生成时间 " + stamp + "。")

    return f"""<!DOCTYPE html>
<html lang="zh-CN" data-theme="light"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{TITLE} · {len(people)} 人 ¥{budget:.0f}</title>
<style>{BASE_CSS}</style></head><body>
<canvas id="bg" aria-hidden="true"></canvas>
<div class="topbtns">
  <button class="tbtn" id="presentbtn" type="button" title="投影演示时放大字号">{PRESENT_BTN}<span>演示模式</span></button>
  <button class="tbtn" id="themebtn" type="button" aria-label="切换日夜模式" title="切换日夜模式">{THEME_BTN}</button>
</div>
<div class="wrap">

<div class="hero">
  <div class="brand"><h1>麦duangduang FoodPilot</h1><span class="tag">多人配餐协调</span></div>
  <div class="scene"><b>{len(people)} 人</b> · 总预算 <b>¥{budget:.0f}</b> ·
    三套方案来自三个不同目标函数，不是同一个算法换三个标题</div>
  <div class="chips" id="chips"></div>

  <div class="panel">
    <div class="panel-title">改需求，立刻重算 —— 不用重跑一遍对话</div>
    <div class="ctrls" id="ctrls"></div>
  </div>
</div>

<div class="sec-title">一眼看差异 <span class="hint" id="fcount"></span></div>
<div id="metrics"></div>

<div class="sec-title">逐人明细与取舍理由</div>
<div class="plans" id="plans"></div>

<div class="sec-title">怎么选</div>
<div class="why"><h3>结论（脚本自动生成，随开关实时更新）</h3><div class="concl" id="concl"></div></div>

<div class="sec-title">为什么三套不一样</div>
<div class="why">
  <h3>不是调权重，是换目标</h3>
  <ol>
    <li><b>方案 A</b> 目标函数是 <code>min 总价</code>，附带"至少 3 种主餐"的下限，
      防止退化成五个人全吃同一款。所以它最便宜，但会有人同款。</li>
    <li><b>方案 B</b> 目标函数是 <code>max 主餐种类</code>，同种类下取便宜的。
      它用"多样性"换钱，所以最贵。</li>
    <li><b>方案 C</b> 目标函数是 <code>min 整桌热量</code>，低卡名额加权给有热量限制的人，
      并且不给低卡方案配甜点。它牺牲种类压热量。</li>
  </ol>
  <p>热量堆叠条里<b>甜点单独用一种颜色</b>，就是为了让最后这条决策可见——
    同样五个人，配一份麦旋风就是 280kcal，占整桌的一成。C 方案直接不配。</p>
</div>

<footer>{foot}<div class="dev" id="dev"></div></footer>
</div>
<script>{data_js}{load_solver_js()}{UI_JS}</script>
</body></html>"""


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="生成可交互的方案对比页")
    ap.add_argument("input", help="meal_solver --format json 的输出文件")
    ap.add_argument("--menu", required=True, help="归一化后的菜单 JSON（页面内嵌，用于交互重算）")
    ap.add_argument("-o", "--output", default="compare.html")
    ap.add_argument("--note", default="", help="页脚补充说明")
    args = ap.parse_args()

    with open(args.input, encoding="utf-8") as f:
        plan = json.load(f)
    with open(args.menu, encoding="utf-8") as f:
        menu = json.load(f)

    out = build(plan, menu, args.note)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(out)

    ok = [p for p in plan["plans"] if p.get("valid")]
    print(f"已生成 {os.path.abspath(args.output)}（{len(ok)} 套可行方案，"
          f"{len(plan['people'])} 人 ¥{plan['budget']:.0f}，内嵌菜单 {len(menu['items'])} 项）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
