#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
group_prompt.py —— 群聊征集：发得出去，也读得回来。

两件事：
  make   生成可直接转发到微信群的征集消息（短、有编号、有示例、有截止时间）
  parse  把群里乱七八糟的回复解析成 meal_solver 能吃的 people spec

为什么模板要带编号和固定忌口词：
不是为了让用户"按规矩填"——现实中没人按规矩填。是为了让 AI 在用户乱回的时候
还有锚点可抓。模板是给人省事的，解析器是给混乱兜底的，两者都得有。

真实群回复长这样，全都要能吃下去：
    1 王磊 不吃牛
    李婷：不要辣
    3、张敏 减肥中
    陈昊 同上
    我不吃鱼
    都行吧

用法：
    python group_prompt.py make --count 5 --budget 160 --store "望京SOHO店"
    python group_prompt.py parse replies.txt --expect 5
    python group_prompt.py parse replies.txt --names "王磊,李婷,张敏,陈昊,赵宇"
"""

import argparse
import json
import re
import sys

# ---------- 口语关键词表：比菜单识别宽得多，因为人说的是人话 ----------

HARD_MEAT = {
    "beef": ["不吃牛", "牛肉不行", "牛不行", "忌牛", "牛过敏", "牛肉过敏", "不能吃牛", "别给牛"],
    "chicken": ["不吃鸡", "鸡肉不行", "鸡不行", "鸡过敏", "不能吃鸡", "不吃鸡肉",
                "不吃禽", "鸡过敏"],
    "fish": ["不吃鱼", "鱼不行", "鱼过敏", "不能吃鱼", "不吃鱼虾", "海鲜过敏", "不吃海鲜"],
    "pork": ["不吃猪", "猪肉不行", "猪不行", "猪过敏", "不能吃猪", "不吃猪肉"],
    "veg": ["吃素", "素食", "全素", "纯素", "不吃肉"],
}

HARD_SPICY = ["不吃辣", "不能吃辣", "辣的不要", "不要辣", "怕辣", "忌辣", "辣过敏",
              "一点辣都不行", "辣不行", "别放辣", "不要辣椒", "不能辣"]

SOFT_SPICY = ["尽量别辣", "少辣", "微辣", "不要太辣", "别太辣", "能不放辣最好"]

LOWCAL = {
    500: ["减脂", "严格控卡", "严格控制", "在减肥很狠"],
    600: ["低卡", "低热量", "热量低", "减肥", "控卡", "在减", "减重", "少吃点", "热量控制"],
}

ANYTHING = ["都行", "随便", "无所谓", "不挑", "听你们", "你们定", "都可以", "没啥要求",
            "没有忌口", "无", "没忌口", "随意"]

SAME_AS_ABOVE = ["同上", "一样", "跟他", "跟她", "同前", "复制上面", "+1", "加一"]

NOISE = ["收到", "好的", "好", "嗯", "ok", "OK", "可以", "没问题", "哈哈", "行", "赞", "1"]

MEAT_CN = {"beef": "牛肉", "chicken": "鸡肉", "fish": "鱼肉", "pork": "猪肉", "veg": "肉"}

# 词表永远补不全——「牛的不行」「牛肉我拒绝」都能躲过去。
# 所以再加一层结构匹配：肉类字 + 3 字内的否定词，两个方向都扫。
MEAT_CHAR = {"beef": "牛", "chicken": "鸡", "fish": "鱼", "pork": "猪"}
NEG_WORDS = ["不行", "不吃", "不要", "不能", "别", "过敏", "忌", "拒绝", "受不了"]


def match_meat(text: str) -> list[str]:
    hits = []
    for meat, ch in MEAT_CHAR.items():
        for w in NEG_WORDS:
            if re.search(ch + r".{0,3}" + w, text) or re.search(w + r".{0,3}" + ch, text):
                hits.append(meat)
                break
    return hits


def make_prompt(count: int, budget: float, store: str, deadline: str,
                mode: str, names: list[str]) -> str:
    mode_cn = {"delivery": "外送", "pickup": "到店自取", "dinein": "堂食"}.get(mode, "到店自取")
    head = f"【麦当劳拼单】{count} 人 · 预算 ¥{budget:.0f}"
    if store:
        head += f" · {store}"
    head += f"{mode_cn}"

    L = [head]
    if deadline:
        L.append(f"{deadline} 截止，我统一下单。")
    else:
        L.append("截止时间我一会儿定，先报忌口。")
    L.append("")
    L.append("每人回一行：编号 + 忌口。没忌口就写「都行」")
    for i in range(1, count + 1):
        nm = names[i - 1] if i - 1 < len(names) else ""
        L.append(f"{i} {nm}".rstrip())
    L.append("")
    L.append("忌口直接写白话：不吃牛肉 / 不吃辣 / 低卡 / 不吃鸡 / 吃素")
    L.append("例：2 李婷 不吃辣")
    L.append("")
    L.append("有过敏的一定标「过敏」两个字，我按零容忍配。")
    return "\n".join(L)


def _hit(text: str, words: list[str]) -> bool:
    return any(w in text for w in words)


def extract_name_and_body(line: str) -> tuple[int | None, str | None, str]:
    """
    从一行里剥出「原始编号 / 名字 / 正文」。
    编号必须尽量保留原样——中间有人那行解析失败时，如果重新编号，
    用户会以为漏的是最后一个人，实际漏的是第 4 个。
    """
    m_idx = re.match(r"^\s*(\d+)\s*[.、)．:：]?\s*", line)
    idx = int(m_idx.group(1)) if m_idx else None

    s = re.sub(r"^\s*\d+\s*[.、)．:：]?\s*", "", line).strip()

    # 有冒号：冒号前就是名字
    m = re.match(r"^([^\s：:,，]{1,12})\s*[：:,，]\s*(.*)$", s)
    if m:
        return idx, m.group(1), m.group(2)

    # 没冒号：按空白切，第一个不像约束词的片段当名字
    segs = re.split(r"[\s,，、]+", s)
    for i, seg in enumerate(segs):
        if not seg:
            continue
        if _looks_like_constraint(seg):
            # 这一格就是约束，说明前面没有独立名字
            return idx, None, s
        # 名字长度收紧到 2~6 字：太长的多半是「今天想吃点好的」这类整句，
        # 当成人名会把一句废话变成一个人
        if i == 0 and 2 <= len(seg) <= 6:
            return idx, seg, " ".join(segs[1:])
    return idx, None, s


def _looks_like_constraint(seg: str) -> bool:
    if _hit(seg, ANYTHING) or _hit(seg, SAME_AS_ABOVE):
        return True
    if match_meat(seg):
        return True
    for ws in HARD_MEAT.values():
        if _hit(seg, ws):
            return True
    return _hit(seg, HARD_SPICY) or _hit(seg, SOFT_SPICY) or \
        any(_hit(seg, ws) for ws in LOWCAL.values())


def parse_constraints(body: str) -> tuple[dict, list[str]]:
    """返回 (约束字典, 标记)。标记里记录 'hard'/'soft_spicy'/'allergy' 这类需要人确认的事。"""
    c = {"avoid_meats": [], "no_spicy": False, "kcal_max": None}
    flags = []
    text = body.strip()
    if not text:
        return c, flags

    if _hit(text, ANYTHING):
        flags.append("any")
        return c, flags

    for meat in match_meat(text):
        if meat not in c["avoid_meats"]:
            c["avoid_meats"].append(meat)
    # 词表命中的也算（覆盖「吃素」「不吃海鲜」这类结构匹配抓不到的）
    for meat, words in HARD_MEAT.items():
        if _hit(text, words):
            if meat == "veg":
                c["avoid_meats"] = ["beef", "chicken", "fish", "pork"]
            elif meat not in c["avoid_meats"]:
                c["avoid_meats"].append(meat)

    if _hit(text, HARD_SPICY):
        c["no_spicy"] = True
        flags.append("hard")
    elif _hit(text, SOFT_SPICY):
        # 软约束按硬处理（安全优先），但必须标出来让人确认
        c["no_spicy"] = True
        flags.append("soft_spicy")

    # 先看强信号（减脂/严格控卡→500），再看一般信号（减肥/低卡→600）
    for k in (500, 600):
        if _hit(text, LOWCAL[k]):
            c["kcal_max"] = k
            break

    if "过敏" in text:
        flags.append("allergy")

    if c["avoid_meats"] or c["no_spicy"] or c["kcal_max"]:
        if "hard" not in flags:
            flags.append("hard")
    return c, flags


def to_spec_flags(c: dict) -> str:
    bits = []
    for m in c["avoid_meats"]:
        bits.append("veg" if len(c["avoid_meats"]) == 4 else f"no{m}" if m != "veg" else "veg")
    if c["no_spicy"]:
        bits.append("nospicy")
    if c["kcal_max"]:
        bits.append(f"lowcal{c['kcal_max']}")
    return ",".join(bits)


def parse_replies(text: str, expect: int | None, names: list[str]) -> dict:
    entries, unknown = [], []
    prev = None

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line in NOISE or len(line) <= 1:
            continue
        # 纯表情/符号行
        if not re.search(r"[\u4e00-\u9fa5A-Za-z0-9]", line):
            continue

        raw_idx, name, body = extract_name_and_body(line)
        seq = raw_idx or (len(entries) + 1)

        # 「同上」复制上一人的约束
        if _hit(line, SAME_AS_ABOVE) and prev is not None:
            entries.append({
                "idx": seq, "name": name or prev["name"],
                "constraints": json.loads(json.dumps(prev["constraints"])),
                "flags": prev["flags"] + ["same_as_above"], "raw": line,
                "note": f"「同上」→ 已复制 {prev['name']} 的约束",
            })
            prev = entries[-1]
            continue

        c, flags = parse_constraints(body or line)
        # 一行里啥约束都没识别出来，且不含"都行"类表达 → 记为未识别，别硬猜
        if not flags:
            if body and body.strip() and not _hit(body, ANYTHING):
                unknown.append(line)
                continue
            flags = ["any"]

        entries.append({"idx": seq, "name": name or f"第{seq}位",
                        "constraints": c, "flags": flags, "raw": line, "note": ""})
        prev = entries[-1]

    # 用预期名单校正名字：回复里缺名字的按顺序补
    notes = []
    if names:
        for i, e in enumerate(entries):
            if e["name"].startswith("第") and i < len(names):
                e["name"] = names[i]
                notes.append(f"第 {i+1} 条没有名字，按名单补为「{names[i]}」，如不对请改")

    replied = {e["name"] for e in entries}
    missing = [n for n in names if n not in replied] if names else []
    if expect and len(entries) < expect:
        notes.append(f"预期 {expect} 人，只解析到 {len(entries)} 条回复，可能有人还没回")
    if expect and len(entries) > expect:
        notes.append(f"预期 {expect} 人，却解析到 {len(entries)} 条，检查是否有重复回复")

    for e in entries:
        if "allergy" in e["flags"]:
            notes.append(f"{e['name']} 提到过敏，已按零容忍处理，下单前建议再确认一次")
        if "soft_spicy" in e["flags"]:
            notes.append(f"{e['name']} 说的是「尽量别辣」这类软要求，已按不吃辣保守处理；"
                         f"若他能接受微辣，可放宽以增加选项")
        if "any" in e["flags"] and not e["constraints"]["avoid_meats"] \
                and not e["constraints"]["no_spicy"] and not e["constraints"]["kcal_max"]:
            pass

    for n in missing:
        notes.append(f"{n} 还没回复，暂按无约束处理，下单前最好催一句")
    for u in unknown:
        notes.append(f"这行没看懂，已跳过：{u}")

    spec = ";".join(f"{e['name']}:{to_spec_flags(e['constraints'])}" for e in entries)
    return {"entries": entries, "spec": spec, "missing": missing,
            "unknown": unknown, "notes": notes}


def _desc(e: dict) -> str:
    c = e["constraints"]
    bits = []
    if c["avoid_meats"]:
        if len(c["avoid_meats"]) == 4:
            bits.append("素食")
        else:
            bits.append("不吃" + "/".join(MEAT_CN.get(m, m) for m in c["avoid_meats"]))
    if c["no_spicy"]:
        bits.append("不吃辣" + ("（软）" if "soft_spicy" in e["flags"] else ""))
    if c["kcal_max"]:
        bits.append(f"主餐≤{c['kcal_max']}kcal")
    return "、".join(bits) if bits else "无特殊要求"


def render(result: dict) -> str:
    L = ["【群聊回复解析】"]
    for e in result["entries"]:
        tag = ""
        if "same_as_above" in e["flags"]:
            tag = "  [同上]"
        elif "allergy" in e["flags"]:
            tag = "  [过敏·零容忍]"
        L.append(f"  {e['idx']}  {e['name']:<6} {_desc(e)}{tag}")
        if e["note"]:
            L.append(f"       ↳ {e['note']}")
    if not result["entries"]:
        L.append("  （没解析出任何有效回复）")

    L.append("")
    L.append("people spec（可直接喂给 meal_solver）：")
    L.append(f'  "{result["spec"]}"')

    if result["notes"]:
        L.append("")
        L.append("需确认：")
        for n in result["notes"]:
            L.append(f"  ! {n}")
    return "\n".join(L)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="多人点餐群聊征集：生成模板 / 解析回复")
    sub = ap.add_subparsers(dest="cmd", required=True)

    mk = sub.add_parser("make", help="生成可直接转发的征集消息")
    mk.add_argument("--count", type=int, required=True)
    mk.add_argument("--budget", type=float, required=True)
    mk.add_argument("--store", default="")
    mk.add_argument("--deadline", default="")
    mk.add_argument("--mode", choices=["delivery", "pickup", "dinein"], default="pickup")
    mk.add_argument("--names", default="", help="逗号分隔，预填编号后的人名")

    ps = sub.add_parser("parse", help="解析群回复，输出 people spec")
    ps.add_argument("file", help="回复文本文件；用 - 表示从 stdin 读")
    ps.add_argument("--expect", type=int)
    ps.add_argument("--names", default="", help="预期名单，用于核对谁没回")
    ps.add_argument("--format", choices=["text", "json"], default="text")

    args = ap.parse_args()
    names = [n.strip() for n in args.names.split(",") if n.strip()]

    if args.cmd == "make":
        print(make_prompt(args.count, args.budget, args.store, args.deadline,
                          args.mode, names))
        return 0

    text = sys.stdin.read() if args.file == "-" else open(args.file, encoding="utf-8").read()
    result = parse_replies(text, args.expect, names)
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.format == "json"
          else render(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
