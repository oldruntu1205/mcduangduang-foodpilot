#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_page.py —— 对比页出厂检查

浏览器里的静默失败最难查：JS 语法错、数据没注进去、关键容器缺失，
在页面上往往只表现为"卡片没了"。所以把能机检的项目都机检掉。

用法：python check_page.py ../demo/compare.html
"""

import os
import re
import sys


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    path = sys.argv[1] if len(sys.argv) > 1 else \
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "demo", "compare.html")

    with open(path, encoding="utf-8") as f:
        s = f.read()

    checks = [
        ("页面脚本存在", "<script>" in s and "</script>" in s),
        ("求解器已内嵌", "function solveAll" in s),
        ("菜单数据已注入", "const MENU=" in s and '"items"' in s),
        ("初始人员已注入", "const PEOPLE_INIT=" in s),
        ("baseline 已注入", "const BASELINE=" in s),
        ("预算档位已生成", "const BUDGET_OPTS=" in s),
        ("调节台容器", 'id="ctrls"' in s),
        ("指标容器", 'id="metrics"' in s),
        ("方案容器", 'id="plans"' in s),
        ("结论容器", 'id="concl"' in s),
        ("演示模式按钮", 'id="presentbtn"' in s),
        ("演示模式样式", 'html[data-present="on"]' in s),
        ("日夜主题样式", 'html[data-theme="dark"]' in s),
        ("粒子画布", 'id="bg"' in s),
        ("粒子数量 400", "N=400" in s),
        ("堆叠条样式", ".seg.dessert" in s),
        ("备选展开容器", ".alts summary" in s),
        ("无外部资源", "http://" not in s.replace("http://www.w3.org", "") and "https://" not in s),
    ]

    bad = 0
    for name, ok in checks:
        print(("  OK   " if ok else "  FAIL ") + name)
        if not ok:
            bad += 1

    m = re.search(r"<script>(.*)</script>", s, re.S)
    if m:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "_check.js"),
                  "w", encoding="utf-8") as f:
            f.write(m.group(1))
        print(f"  --    页面脚本已导出到 _check.js（{len(m.group(1))} 字符），可执行 node --check 验证")

    print(f"\n{len(checks) - bad}/{len(checks)} 项通过，页面 {round(len(s.encode())/1024,1)}KB")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
