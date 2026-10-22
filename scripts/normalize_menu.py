#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
normalize_menu.py —— 把麦当劳 MCP 的原始菜单返回，归一化成求解器能吃的标准结构。

为什么需要这一层：
query-meals / query-meal-detail / list-nutrition-foods 三个工具的返回字段并不统一，
版本迭代也改过字段名。求解器不能依赖任何一种线上字段名，否则接口一改就全线崩。
所以所有原始返回先过这一层，统一成 NormalizedItem。

用法：
    python normalize_menu.py raw_menu.json -o menu.json
    python normalize_menu.py raw_menu.json -o menu.json --kcal-file nutrition.json

输出结构（items[]）：
    code        str   餐品编码（作为唯一键，不可为空）
    name        str   餐品名
    price       float 单价（元，已从分换算）
    kcal        int   热量（kcal），无数据时为经验估算值
    kcal_source str   "api" | "estimate"
    category    str   "combo" | "main" | "side" | "drink" | "dessert" | "veg" | "unknown"
    meat        str   "beef" | "chicken" | "fish" | "pork" | "veg" | "unknown"
    spicy       bool
    is_combo    bool

重要：meat / spicy 是**关键词启发式**，一定会误判（例如「吉士」其实是牛肉）。
它只用于初筛，下单前必须用 query-meal-detail 的餐品描述复核。
误判一个忌口就是这个作品最致命的事故，所以本文件在输出时会带 warnings。
"""

import argparse
import json
import statistics
import sys
from typing import Any

# ---------- 关键词表（全部为大写无关子串匹配） ----------

BEEF_WORDS = ["牛", "犇", "巨无霸", "吉士", "安格斯", "培根", "双层牛", "牛堡"]
CHICKEN_WORDS = ["鸡", "板烧", "麦乐", "脆皮", "鸡排", "鸡腿", "鸡翅"]
FISH_WORDS = ["鱼", "鳕"]
PORK_WORDS = ["猪", "麦芬猪", "火腿"]
SPICY_WORDS = ["辣", "香辛", "麻辣"]
VEG_WORDS = ["沙拉", "蔬", "玉米", "生菜", "水果", "番茄"]
DRINK_WORDS = ["可乐", "雪碧", "芬达", "茶", "咖啡", "美式", "拿铁", "果汁", "牛奶",
               "雪冰", "气泡", "矿泉水", "饮品", "豆浆"]
DESSERT_WORDS = ["麦旋风", "圣代", "圆筒", "冰淇淋", "甜筒", "派", "蛋糕", "可颂"]
SIDE_WORDS = ["薯条", "薯", "麦乐鸡", "鸡块", "鸡翅", "鸡柳", "小食", "拼盘"]
COMBO_WORDS = ["套餐", "四件套", "三件套", "两件套", "组合", "餐盒", "全餐"]

# 无数据时的经验热量（仅供估算，不可当作营养依据）
KCAL_ESTIMATE = {
    "combo": 900, "main": 480, "side": 260, "drink": 150,
    "dessert": 280, "veg": 100, "unknown": 400,
}

CODE_KEYS = ["code", "mealCode", "productCode", "skuCode", "itemCode", "goodsCode", "id"]
NAME_KEYS = ["name", "mealName", "productName", "goodsName", "title", "shortName"]
PRICE_KEYS = ["price", "salePrice", "currentPrice", "amount", "priceInCent", "amountInCent"]
CATEGORY_KEYS = ["category", "categoryName", "type", "typeName", "groupName"]
KCAL_KEYS = ["kcal", "energy", "calories", "energyKcal", "calorie"]
CENT_HINT = ("cent", "fen", "分")


def _pick(d: dict, keys: list[str]) -> Any:
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    # 大小写不敏感兜底
    lower = {str(k).lower(): v for k, v in d.items()}
    for k in keys:
        if k.lower() in lower and lower[k.lower()] not in (None, ""):
            return lower[k.lower()]
    return None


def to_yuan(value: Any, key_hint: str = "") -> float | None:
    """金额统一换算成元。字段名含 cent 一律按分处理；数值 > 200 也按分处理（单品价不可能超 200 元）。"""
    if value is None:
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    hit_cent = any(h in key_hint.lower() for h in CENT_HINT)
    if not hit_cent and num > 200:
        hit_cent = True
    return round(num / 100, 2) if hit_cent else round(num, 2)


def classify(name: str) -> dict:
    """按名称做启发式分类。宁可标 unknown 也不要猜错——猜错的代价是忌口事故。"""
    n = str(name or "")
    is_combo = any(w in n for w in COMBO_WORDS)

    meat = "unknown"
    # 先判鱼 > 鸡 > 猪 > 牛，因为「麦香鱼」不含牛羊词但「培根蔬萃双层牛堡」同时命中培根和牛
    if any(w in n for w in FISH_WORDS):
        meat = "fish"
    elif any(w in n for w in BEEF_WORDS):
        meat = "beef"
    elif any(w in n for w in PORK_WORDS):
        meat = "pork"
    elif any(w in n for w in CHICKEN_WORDS):
        meat = "chicken"

    category = "unknown"
    if is_combo:
        category = "combo"
    elif any(w in n for w in DESSERT_WORDS):
        category = "dessert"
    elif any(w in n for w in DRINK_WORDS):
        category = "drink"
    elif any(w in n for w in VEG_WORDS):
        category = "veg"
    elif any(w in n for w in SIDE_WORDS):
        category = "side"
    elif meat in ("beef", "chicken", "fish", "pork"):
        category = "main"

    # 套餐本身就是主餐；含肉则不算 veg
    if category == "veg" and meat not in ("veg", "unknown"):
        category = "side"

    return {
        "category": category,
        "meat": meat,
        "spicy": any(w in n for w in SPICY_WORDS),
        "is_combo": is_combo,
    }


def normalize(raw_items: list[dict], nutrition: dict | None = None) -> dict:
    """raw_items 可以是 MCP 任意层级的返回展开后的餐品字典列表。"""
    nutrition = nutrition or {}
    items, warnings = [], []

    for raw in raw_items:
        if not isinstance(raw, dict):
            continue

        code = _pick(raw, CODE_KEYS)
        name = _pick(raw, NAME_KEYS)
        if code is None or name is None:
            continue
        code = str(code).strip()

        price_key = next((k for k in PRICE_KEYS if k in raw), "")
        price = to_yuan(_pick(raw, PRICE_KEYS), price_key)
        if price is None or price <= 0:
            warnings.append(f"[{code}] {name} 无有效价格，已跳过——价格缺失的餐品不能进配餐方案")
            continue

        info = classify(name)

        # 热量：优先营养接口 > 内嵌字段 > 经验估算
        kcal_raw = None
        for k in KCAL_KEYS:
            if k in raw and raw[k] not in (None, ""):
                kcal_raw = raw[k]
                break
        if kcal_raw is None:
            kcal_raw = nutrition.get(code)
        kcal_source = "api"
        if kcal_raw is None:
            kcal_raw = KCAL_ESTIMATE.get(info["category"], 400)
            kcal_source = "estimate"
        try:
            kcal = int(float(kcal_raw))
        except (TypeError, ValueError):
            kcal = KCAL_ESTIMATE.get(info["category"], 400)
            kcal_source = "estimate"

        if info["meat"] == "unknown" and info["category"] in ("main", "combo"):
            warnings.append(f"[{code}] {name} 无法判定肉类成分，遇到忌口用户必须人工复核")

        items.append({
            "code": code,
            "name": str(name).strip(),
            "price": price,
            "kcal": kcal,
            "kcal_source": kcal_source,
            **info,
        })

    # 去重（同 code 保留首个）
    seen, deduped = set(), []
    for it in items:
        if it["code"] in seen:
            continue
        seen.add(it["code"])
        deduped.append(it)

    # 价格量级自检：如果中位数异常高，多半是没识别出「分」
    if deduped:
        med = statistics.median([i["price"] for i in deduped])
        if med > 200:
            warnings.append(f"菜单价格中位数 {med} 元明显异常，疑似仍为分单位，请人工核对")

    return {"items": deduped, "warnings": warnings,
            "stats": {"count": len(deduped),
                      "main_like": sum(1 for i in deduped if i["category"] in ("main", "combo"))}}


def main() -> int:
    ap = argparse.ArgumentParser(description="麦当劳 MCP 菜单归一化")
    ap.add_argument("input", help="原始菜单 JSON（列表，或含 list/items/data 键的对象）")
    ap.add_argument("-o", "--output", default="menu.json")
    ap.add_argument("--kcal-file", help='可选：{"code": kcal} 形式的营养数据')
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    with open(args.input, encoding="utf-8") as f:
        raw = json.load(f)
    if isinstance(raw, dict):
        for key in ("items", "list", "data", "meals", "result"):
            if isinstance(raw.get(key), list):
                raw = raw[key]
                break
    if not isinstance(raw, list):
        print("输入必须是餐品数组，或包含 items/list/data 键的对象", file=sys.stderr)
        return 2

    nutrition = {}
    if args.kcal_file:
        with open(args.kcal_file, encoding="utf-8") as f:
            nutrition = json.load(f)

    out = normalize(raw, nutrition)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"归一化完成：{out['stats']['count']} 项，其中主餐类 {out['stats']['main_like']} 项 → {args.output}")
    for w in out["warnings"]:
        print(f"  ! {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
