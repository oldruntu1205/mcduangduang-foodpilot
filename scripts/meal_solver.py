#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
meal_solver.py —— 多人冲突需求的配餐求解器（FoodPilot 引擎）

三条硬原则：
1. 求解归求解，表达归表达。本脚本只出结构与可验证的事实理由，不写营销话术。
2. 金额、热量、约束校验全部在这里算死。大模型不得自行加总——这是本作品的红线。
3. 三套方案必须来自三个不同的目标函数。加权打分只会让三套方案长得一样，
   用户一切换就发现"根本没区别"，可解释性立刻崩塌。

算法：每人取候选前 K 项，枚举笛卡尔积（5 人 × 5 项 = 3125 组），
对每组套共享小食、校验预算，再用该方案自己的目标函数选最优。
枚举比加权求和慢一点，但换来的是三套方案目标清晰、差异显著、理由能讲通。

用法：
    python meal_solver.py --menu ../demo/menu_demo.json \
        --people "王磊:nobeef;李婷:nospicy;张敏:lowcal600;陈昊:;赵宇:" --budget 160
"""

import argparse
import itertools
import json
import sys
from collections import Counter
from dataclasses import dataclass, field, asdict

MAIN_CATS = ("combo", "main")
SHARE_CATS = ("side", "drink", "dessert", "veg")
MEAT_CN = {"beef": "牛肉", "chicken": "鸡肉", "fish": "鱼肉", "pork": "猪肉", "veg": "素"}


@dataclass
class Person:
    name: str
    avoid_meats: list[str] = field(default_factory=list)
    no_spicy: bool = False
    kcal_max: int | None = None

    def label(self) -> str:
        bits = []
        if self.avoid_meats:
            bits.append("不吃" + "/".join(MEAT_CN.get(m, m) for m in self.avoid_meats))
        if self.no_spicy:
            bits.append("不吃辣")
        if self.kcal_max:
            bits.append(f"主餐≤{self.kcal_max}kcal")
        return f"{self.name}（{'、'.join(bits)}）" if bits else self.name

    def constraints_text(self) -> str:
        bits = []
        if self.avoid_meats:
            bits.append("不吃" + "/".join(MEAT_CN.get(m, m) for m in self.avoid_meats))
        if self.no_spicy:
            bits.append("不吃辣")
        if self.kcal_max:
            bits.append(f"≤{self.kcal_max}kcal")
        return "、".join(bits)


# 三套方案 = 三种目标函数，不是三组权重
STRATEGIES = [
    {
        "id": "A", "name": "最省钱", "tagline": "压住总价，但至少保住 3 种主餐",
        "share_reserve": 0.22, "share_count": 3, "min_unique": 3,
        "prefer": ["side", "veg", "drink", "dessert"],
    },
    {
        "id": "B", "name": "最不重样", "tagline": "五个人吃到尽量不同的主餐",
        "share_reserve": 0.20, "share_count": 4, "min_unique": 1,
        "prefer": ["veg", "side", "drink", "dessert"],
    },
    {
        "id": "C", "name": "最低热量", "tagline": "整桌摄入最小，低卡的人优先满足，不配甜点",
        "share_reserve": 0.26, "share_count": 3, "min_unique": 3,
        "prefer": ["veg", "drink", "side"],
    },
]


def allowed(item: dict, person: Person) -> bool:
    """硬约束。不满足就是不可行，不折中、不打折。"""
    if item.get("meat") in person.avoid_meats:
        return False
    if person.no_spicy and item.get("spicy"):
        return False
    if person.kcal_max and item.get("kcal", 0) > person.kcal_max:
        return False
    return True


def pre_score(item: dict, person: Person, st: dict, per_person: float) -> float:
    """只用于给候选排序（决定进枚举的前 K 项），不决定最终结果。"""
    ratio = item["price"] / per_person if per_person else 1.0
    s = -abs(ratio - 0.9)
    if person.kcal_max:
        s += 0.5 * (1 - abs(person.kcal_max * 0.8 - item["kcal"]) / max(person.kcal_max, 1))
    if st["id"] == "C":
        s -= item["kcal"] / 1000.0
    if st["id"] == "A":
        s -= item["price"] / 50.0
    return s


def objective(combo: tuple, shared: list[dict], budget: float, st: dict,
              people: list[Person]) -> float:
    """每套方案自己的目标。分数越高越好。多样性下限对所有方案统一生效。"""
    codes = [i["code"] for i in combo]
    uniq = len(set(codes))
    if uniq < st["min_unique"]:
        return -1e9
    total = sum(i["price"] for i in combo) + sum(s["price"] for s in shared)
    # 有热量上限的人，其主餐热量加权——否则"最低热量"方案会把低卡名额让给需要凑数的人
    main_kcal = sum(i["kcal"] * (1.6 if people[idx].kcal_max else 1.0)
                    for idx, i in enumerate(combo))
    kcal = main_kcal + sum(s["kcal"] for s in shared)
    rep_max = max(Counter(codes).values()) if codes else 0

    if st["id"] == "A":
        return -total
    if st["id"] == "B":
        return uniq * 1000 - total
    # C：整桌热量最低；重复份数要罚，否则会退化成"五份同款"
    return -kcal - rep_max * 40 - total * 0.1


def pick_shares(pool: list[dict], budget_left: float, target: int,
                st: dict, exclude: set) -> tuple[list[dict], float]:
    """
    剩余预算内挑共享小食，按类别优先级保证结构（有菜、有喝、有薯）。
    排序口径必须跟方案目标一致：低热量方案按 kcal 挑，否则会补进一份麦旋风
    把整桌热量顶上去，结果"最低热量方案"反而不最低。
    """
    sort_key = (lambda i: (i["kcal"], i["price"])) if st["id"] == "C" else (lambda i: (i["price"], i["kcal"]))
    picked = []
    for cat in st["prefer"]:
        if len(picked) >= target:
            break
        cands = [i for i in pool if i.get("category") == cat
                 and i["code"] not in exclude
                 and i["code"] not in {p["code"] for p in picked}]
        cands.sort(key=sort_key)
        for it in cands:
            if it["price"] > budget_left:
                continue
            picked.append(it)
            budget_left = round(budget_left - it["price"], 2)
            break

    if budget_left > 0 and len(picked) < target:
        rest = [i for i in pool if i.get("category") in SHARE_CATS
                and i["code"] not in exclude
                and i["code"] not in {p["code"] for p in picked}
                and i["price"] <= budget_left]
        rest.sort(key=sort_key)
        for it in rest:
            if len(picked) >= target or it["price"] > budget_left:
                break
            picked.append(it)
            budget_left = round(budget_left - it["price"], 2)

    return picked, round(budget_left, 2)


def build_plan(mains: list[dict], shares_pool: list[dict], people: list[Person],
               budget: float, st: dict, exclude: set) -> dict:
    n = len(people)
    # 多样性下限不能超过人数-1：4 人点 4 种还能做到，3 人点 4 种直接无解
    st = dict(st)
    if st["min_unique"] > 1:
        st["min_unique"] = min(st["min_unique"], max(1, n - 1))
    per_person = budget * (1 - st["share_reserve"]) / n if n else budget
    top_k = 5 if n <= 6 else 3

    full_lists = []
    for p in people:
        cands = [i for i in mains if allowed(i, p) and i["code"] not in exclude]
        if not cands:
            return {"id": st["id"], "name": st["name"], "tagline": st["tagline"],
                    "valid": False, "error": f"{p.label()} 在当前菜单下没有任何可行主餐",
                    "assignments": [], "shared": [], "total": 0.0, "checks": []}
        cands.sort(key=lambda i: pre_score(i, p, st, per_person), reverse=True)
        full_lists.append(cands)

    pool = [c[:top_k] for c in full_lists]
    # 1~2 人时"共享小食"这个概念不成立，硬配 3 份只会让单人单变得又贵又超热量
    share_target = st["share_count"] if n >= 3 else 1
    best = None
    for combo in itertools.product(*pool):
        main_total = sum(i["price"] for i in combo)
        if main_total > budget:
            continue
        # 套餐自带薯条饮料，再按满额配共享小食就是重复浪费，按套餐数量折减
        combo_cover = sum(1 for i in combo if i.get("is_combo"))
        eff_target = max(1, share_target - combo_cover)
        shared, _ = pick_shares(shares_pool, round(budget - main_total, 2),
                                eff_target, st, exclude)
        total = round(main_total + sum(s["price"] for s in shared), 2)
        if total > budget:
            continue
        obj = objective(combo, shared, budget, st, people)
        if obj <= -1e8:
            continue  # 违反多样性下限的组合不能污染 best，否则降级逻辑永远不触发
        if best is None or obj > best["obj"]:
            best = {"obj": obj, "combo": combo, "shared": shared, "total": total}

    if best is None:
        # 多样性下限导致无解时降级重试
        if st.get("min_unique", 1) > 1:
            relaxed = dict(st, min_unique=1)
            return build_plan(mains, shares_pool, people, budget, relaxed, exclude)
        return {"id": st["id"], "name": st["name"], "tagline": st["tagline"],
                "valid": False,
                "error": f"预算 {budget:.0f} 元下凑不出满足全部硬约束的组合",
                "assignments": [], "shared": [], "total": 0.0, "checks": []}

    combo, shared = best["combo"], best["shared"]
    chosen_codes = [i["code"] for i in combo]
    assignments = []
    for idx, (p, item) in enumerate(zip(people, combo)):
        others = [c for j, c in enumerate(combo) if j != idx]
        assignments.append({
            "person": p.name, "person_label": p.label(), "item": item,
            "alternatives": [c for c in full_lists[idx] if c["code"] != item["code"]][:3],
            "reason": explain(st["id"], item, p, full_lists[idx], others, shared, budget, n),
        })

    return finalize(assignments, shared, people, budget, st, chosen_codes)


def explain(plan_id: str, item: dict, p: Person, cands: list[dict],
            others: list[dict], shared: list[dict], budget: float, n: int) -> str:
    """
    理由必须是「为什么是它 + 牺牲了什么」，两者缺一不可。
    模板化形容词（"最匹配"）不算解释，直接删掉。
    """
    parts = []

    # 1. 约束命中：这个选择为他挡住了什么
    hits = []
    if p.avoid_meats:
        hits.append("避开" + "/".join(MEAT_CN.get(m, m) for m in p.avoid_meats))
    if p.no_spicy:
        hits.append("不辣")
    if p.kcal_max:
        hits.append(f"{item['kcal']}kcal 在 {p.kcal_max} 以内")
    if hits:
        parts.append("、".join(hits) + f"，该店只筛出 {len(cands)} 项可选")

    # 2. 按方案目标解释取舍：不仅说选了什么，还要说为什么不是另一个
    if plan_id == "A":
        cheapest = min(cands, key=lambda c: c["price"])
        uniq = len({o["code"] for o in others} | {item["code"]})
        if cheapest["code"] == item["code"]:
            parts.append(f"他名下最低价 ¥{item['price']:.2f}，压总价就靠这一档")
        else:
            gap = item["price"] - cheapest["price"]
            parts.append(f"比最低价的{cheapest['name']}贵 ¥{gap:.2f}，"
                         f"用来凑够 {uniq} 种不同主餐，避免整桌一个味")
    elif plan_id == "B":
        others_codes = {o["code"] for o in others}
        if item["code"] not in others_codes:
            parts.append(f"与另外 {len(others)} 人的选择不重样")
        else:
            same = sum(1 for o in others if o["code"] == item["code"])
            parts.append(f"同类可行项已被占满，与另外 {same} 人同款")
    elif plan_id == "C":
        lowest = min(cands, key=lambda c: c["kcal"])
        if lowest["code"] == item["code"]:
            parts.append(f"候选人里热量最低（{item['kcal']}kcal）")
        else:
            gap = item["kcal"] - lowest["kcal"]
            parts.append(f"比最低卡的{lowest['name']}高 {gap}kcal，"
                         f"用来凑够不同主餐，免得整桌都是一模一样的低卡餐")

    # 3. 价格位置：为什么这个价位可以接受
    if item["price"] <= budget / n * 0.85:
        parts.append(f"¥{item['price']:.2f}，给共享小食留出了空间")
    return "；".join(parts) if parts else "唯一可行项"


def finalize(assignments: list[dict], shared: list[dict], people: list[Person],
             budget: float, st: dict, codes: list[str]) -> dict:
    n = len(people)
    main_total = round(sum(a["item"]["price"] for a in assignments), 2)
    share_total = round(sum(s["price"] for s in shared), 2)
    total = round(main_total + share_total, 2)

    share_kcal = sum(s["kcal"] for s in shared)
    per_share_kcal = round(share_kcal / n, 0) if n else 0

    per_person, checks = [], []
    for a in assignments:
        p = next(x for x in people if x.name == a["person"])
        kcal = a["item"]["kcal"] + per_share_kcal
        per_person.append({"person": p.name, "item_name": a["item"]["name"],
                           "item_code": a["item"]["code"],
                           "price": a["item"]["price"], "kcal": int(kcal)})
        if p.kcal_max and kcal > p.kcal_max * 1.15:
            checks.append({"level": "warn", "code": "kcal_share",
                           "msg": f"{p.name} 主餐已达标，但均摊共享小食后约 {int(kcal)}kcal，建议不分小食"})

        if a["item"].get("meat") in p.avoid_meats:
            checks.append({"level": "error", "code": "avoid_violation",
                           "msg": f"{p.name} 分到 {a['item']['name']}，违反忌口"})
        if p.no_spicy and a["item"].get("spicy"):
            checks.append({"level": "error", "code": "spicy_violation",
                           "msg": f"{p.name} 分到辣味餐品 {a['item']['name']}"})
        if p.kcal_max and a["item"]["kcal"] > p.kcal_max:
            checks.append({"level": "error", "code": "kcal_violation",
                           "msg": f"{p.name} 主餐 {a['item']['kcal']}kcal 超上限"})

    if total > budget:
        checks.append({"level": "error", "code": "over_budget",
                       "msg": f"总价 ¥{total:.2f} 超预算 ¥{budget:.0f}"})

    unknown = [a["item"]["name"] for a in assignments if a["item"].get("meat") == "unknown"]
    if unknown:
        checks.append({"level": "warn", "code": "unknown_meat",
                       "msg": "肉类成分无法自动判定，下单前需复核：" + "、".join(unknown)})

    est = [a["item"]["name"] for a in assignments if a["item"].get("kcal_source") == "estimate"]
    if est:
        checks.append({"level": "warn", "code": "kcal_estimate",
                       "msg": "热量为估算值，不可作为营养依据：" + "、".join(est)})

    valid = not any(c["level"] == "error" for c in checks)
    return {
        "id": st["id"], "name": st["name"], "tagline": st["tagline"], "valid": valid,
        "assignments": assignments, "shared": shared,
        "main_total": main_total, "share_total": share_total, "total": total,
        "budget": budget, "remaining": round(budget - total, 2),
        "unique_mains": len(set(codes)),
        "total_kcal": int(sum(a["item"]["kcal"] for a in assignments) + share_kcal),
        "per_person": per_person, "checks": checks, "share_kcal_each": per_share_kcal,
    }


def solve(menu: dict, people: list[Person], budget: float,
          exclude: set[str] | None = None) -> dict:
    exclude = exclude or set()
    items = [i for i in menu["items"] if i["code"] not in exclude]
    mains = [i for i in items if i.get("category") in MAIN_CATS]
    shares_pool = [i for i in items if i.get("category") in SHARE_CATS]

    plans = [build_plan(mains, shares_pool, people, budget, st, exclude)
             for st in STRATEGIES]
    feasible = [p for p in plans if p.get("valid")]

    return {
        "budget": budget,
        "people": [asdict(p) for p in people],
        "plans": plans,
        "recommended": feasible[0]["id"] if feasible else None,
        "feasible_count": len(feasible),
        "compare": compare_plans(plans),
        "diagnosis": diagnose(plans, people, mains, shares_pool, budget),
    }


def compare_plans(plans: list[dict]) -> list[str]:
    """把三套方案的差异说成一句话，方便用户直接选。"""
    ok = [p for p in plans if p.get("valid")]
    if len(ok) < 2:
        return []
    out = []
    cheapest = min(ok, key=lambda p: p["total"])
    most_uniq = max(ok, key=lambda p: p["unique_mains"])
    lowest_kcal = min(ok, key=lambda p: p["total_kcal"])
    out.append(f"方案 {cheapest['id']} 最便宜（¥{cheapest['total']:.2f}，主餐 {cheapest['unique_mains']} 种）")
    out.append(f"方案 {most_uniq['id']} 最不重样（{most_uniq['unique_mains']} 种主餐，¥{most_uniq['total']:.2f}）")
    out.append(f"方案 {lowest_kcal['id']} 热量最低（约 {lowest_kcal['total_kcal']} kcal，¥{lowest_kcal['total']:.2f}）")
    return out


def diagnose(plans: list[dict], people: list[Person], mains: list[dict],
             shares: list[dict], budget: float) -> list[str]:
    """无解时告诉用户松哪一条约束，而不是干巴巴报错。"""
    tips = []
    for p in plans:
        if p.get("error"):
            tips.append(p["error"])
            break
    if not any(p.get("valid") for p in plans):
        need = 0.0
        for p in people:
            cands = [i for i in mains if allowed(i, p)]
            need += min((i["price"] for i in cands), default=0)
        tips.append(f"该预算下无法满足全部硬约束；只求人人有主餐的最低预算约 ¥{need:.2f}")
        tips.append("可放宽的方向：提高预算 / 提高热量上限 / 换备货更全的门店")
    return tips


def parse_people(spec: str) -> list[Person]:
    people = []
    for chunk in spec.split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        name, _, flags = chunk.partition(":")
        p = Person(name=name.strip())
        for f in [x.strip().lower() for x in flags.split(",") if x.strip()]:
            if f in ("nobeef", "no_beef"):
                p.avoid_meats.append("beef")
            elif f in ("nopork", "no_pork"):
                p.avoid_meats.append("pork")
            elif f in ("nofish", "no_fish"):
                p.avoid_meats.append("fish")
            elif f in ("nochicken", "no_chicken"):
                p.avoid_meats.append("chicken")
            elif f in ("nospicy", "no_spicy", "mild"):
                p.no_spicy = True
            elif f in ("veg", "vegetarian"):
                p.avoid_meats.extend(["beef", "pork", "fish", "chicken"])
            elif f.startswith("lowcal"):
                digits = "".join(ch for ch in f if ch.isdigit())
                p.kcal_max = int(digits) if digits else 600
        people.append(p)
    return people


def render_text(result: dict) -> str:
    line = []
    for p in result["people"]:
        bits = []
        if p["avoid_meats"]:
            bits.append("不吃" + "/".join(MEAT_CN.get(m, m) for m in p["avoid_meats"]))
        if p["no_spicy"]:
            bits.append("不吃辣")
        if p["kcal_max"]:
            bits.append(f"≤{p['kcal_max']}kcal")
        line.append(p["name"] + (f"（{'、'.join(bits)}）" if bits else ""))
    L = [f"预算 ¥{result['budget']:.0f} · {len(result['people'])} 人",
         "用餐人：" + "，".join(line), ""]

    for plan in result["plans"]:
        L.append(f"【方案 {plan['id']} · {plan['name']}】{plan['tagline']}  "
                 f"[{'可行' if plan.get('valid') else '不可行'}]")
        if plan.get("error"):
            L.append(f"  {plan['error']}")
            L.append("")
            continue
        for a in plan["assignments"]:
            it = a["item"]
            L.append(f"  {a['person']:<4} {it['name']}  ¥{it['price']:.2f}  {it['kcal']}kcal")
            L.append(f"       ↳ {a['reason']}")
        if plan["shared"]:
            L.append("  共享    " + "、".join(f"{s['name']}(¥{s['price']:.2f})" for s in plan["shared"]))
        L.append(f"  合计 ¥{plan['total']:.2f} / 预算 ¥{plan['budget']:.0f} / "
                 f"结余 ¥{plan['remaining']:.2f} / 主餐 {plan['unique_mains']} 种 / "
                 f"整桌约 {plan['total_kcal']}kcal")
        for c in plan.get("checks", []):
            L.append(f"  {'×' if c['level'] == 'error' else '!'} {c['msg']}")
        L.append("")

    if result.get("compare"):
        L.append("怎么选：")
        for c in result["compare"]:
            L.append(f"  · {c}")
        L.append("")
    if result.get("diagnosis"):
        L.append("诊断：")
        for d in result["diagnosis"]:
            L.append(f"  - {d}")
    return "\n".join(L)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="多人配餐求解器")
    ap.add_argument("--menu", required=True)
    ap.add_argument("--people", required=True,
                    help='"王磊:nobeef;李婷:nospicy;张敏:lowcal600;陈昊:;赵宇:"')
    ap.add_argument("--budget", type=float, required=True)
    ap.add_argument("--exclude", default="", help="排除餐品编码，逗号分隔")
    ap.add_argument("--add-avoid", action="append", default=[],
                    help="追加忌口用于实时重算：--add-avoid 陈昊:beef")
    ap.add_argument("--format", choices=["text", "json"], default="text")
    ap.add_argument("-o", "--output")
    args = ap.parse_args()

    with open(args.menu, encoding="utf-8") as f:
        menu = json.load(f)

    people = parse_people(args.people)
    for spec in args.add_avoid:
        name, _, meat = spec.partition(":")
        for p in people:
            if p.name == name.strip() and meat.strip() and meat.strip() not in p.avoid_meats:
                p.avoid_meats.append(meat.strip())

    exclude = {c.strip() for c in args.exclude.split(",") if c.strip()}
    result = solve(menu, people, args.budget, exclude)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

    print(json.dumps(result, ensure_ascii=False, indent=2) if args.format == "json"
          else render_text(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
