#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
smoke_test.py —— 求解器自检。每次改完算法必跑，跑不过不许交付。

检查的是"不变量"，不是"结果好看不好看"：
  1. 预算不超（硬）
  2. 忌口不违反（硬）
  3. 辣度不违反（硬）
  4. 热量上限不违反（硬）
  5. 每人恰好一份主餐（硬）
  6. 方案自报 valid 与实际情况一致（防止 finalize 漏判）

另外覆盖 5 个极端场景，模拟真实用户能说出的话。

用法：python smoke_test.py
"""

import os
import sys

from meal_solver import parse_people, solve

# 基于脚本自身位置定位，保证从任何 cwd 都能跑
DEFAULT_MENU = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "demo", "menu_demo.json"))


def load_menu(path: str | None = None) -> dict:
    import json
    with open(path or DEFAULT_MENU, encoding="utf-8") as f:
        return json.load(f)


def check_invariants(result: dict, label: str) -> list[str]:
    errs = []
    people = {p["name"]: p for p in result["people"]}
    budget = result["budget"]

    for plan in result["plans"]:
        pid = f"{label}/方案{plan['id']}"
        if plan.get("error"):
            continue
        if len(plan["assignments"]) != len(people):
            errs.append(f"{pid}: 主餐份数 {len(plan['assignments'])} ≠ 人数 {len(people)}")

        if (plan["total"] > budget + 1e-6) and plan.get("valid"):
            errs.append(f"{pid}: 总价 {plan['total']} 超预算 {budget} 却标记为可行")

        for a in plan["assignments"]:
            it = a["item"]
            p = people.get(a["person"])
            if p is None:
                errs.append(f"{pid}: 出现未知用餐人 {a['person']}")
                continue
            if it.get("meat") in p["avoid_meats"]:
                errs.append(f"{pid}: {a['person']} 忌口 {p['avoid_meats']} 却分到 {it['name']}")
            if p["no_spicy"] and it.get("spicy"):
                errs.append(f"{pid}: {a['person']} 不吃辣却分到 {it['name']}")
            if p["kcal_max"] and it["kcal"] > p["kcal_max"]:
                errs.append(f"{pid}: {a['person']} 上限 {p['kcal_max']} 却分到 {it['kcal']}kcal 的 {it['name']}")

    return errs


SCENARIOS = [
    ("标准五人局", "王磊:nobeef;李婷:nospicy;张敏:lowcal600;陈昊:;赵宇:", 160.0, []),
    ("改禁忌后重算", "王磊:nobeef;李婷:nospicy;张敏:lowcal600;陈昊:;赵宇:", 160.0, ["陈昊:beef"]),
    ("预算压到极限", "王磊:nobeef;李婷:nospicy;张敏:lowcal600;陈昊:;赵宇:", 70.0, []),
    ("单人低卡", "我:lowcal500", 40.0, []),
    ("全员忌口重叠", "A:nobeef,nospicy;B:nobeef,nospicy,lowcal450;C:nobeef", 200.0, []),
    ("预算很宽", "A:nobeef;B:nospicy;C:;D:lowcal600", 400.0, []),
]


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    menu = load_menu()
    print(f"菜单：{len(menu['items'])} 项，主餐类 "
          f"{sum(1 for i in menu['items'] if i['category'] in ('main', 'combo'))} 项\n")

    all_errs = []
    for label, spec, budget, adds in SCENARIOS:
        people = parse_people(spec)
        for add in adds:
            name, _, meat = add.partition(":")
            for p in people:
                if p.name == name.strip():
                    p.avoid_meats.append(meat.strip())

        result = solve(menu, people, budget)
        errs = check_invariants(result, label)
        all_errs.extend(errs)

        feasible = result["feasible_count"]
        status = f"OK  {feasible}/3 套可行" if not errs else f"FAIL {len(errs)} 个问题"
        print(f"[{status}] {label}  ({len(people)} 人 / ¥{budget:.0f})")
        for p in result["plans"]:
            if p.get("valid"):
                print(f"    方案{p['id']} ¥{p['total']:.2f} "
                      f"主餐{p['unique_mains']}种 {p['total_kcal']}kcal")
        for d in result["diagnosis"]:
            print(f"    ! {d}")
        for e in errs:
            print(f"    × {e}")
        print()

    print("=" * 40)
    if all_errs:
        print(f"自检失败：{len(all_errs)} 个不变量被违反")
        return 1
    print("自检通过：所有方案均未违反预算/忌口/辣度/热量约束")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
