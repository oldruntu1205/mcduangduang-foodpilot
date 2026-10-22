# docs

## images

README 里的截图由 Chrome headless 从 `demo/compare.html` 直接生成，可复现、无手工后期。

```bash
# 浅色（README 主图）
chrome --headless=new --disable-gpu --hide-scrollbars \
  --force-device-scale-factor=2 --window-size=1440,1260 --virtual-time-budget=5000 \
  --screenshot=docs/images/compare-light.png \
  "file:///绝对路径/demo/compare.html?theme=light"

# 深色
chrome --headless=new --disable-gpu --hide-scrollbars \
  --force-device-scale-factor=2 --window-size=1440,1260 --virtual-time-budget=5000 \
  --screenshot=docs/images/compare-dark.png \
  "file:///绝对路径/demo/compare.html?theme=dark"
```

`--virtual-time-budget=5000` 是必须的：页面要先跑完内嵌求解器、渲染三张卡片、点亮粒子背景，截图才不是空白。

## 页面的 URL 参数

| 参数 | 取值 | 作用 |
| --- | --- | --- |
| `theme` | `light` / `dark` | 强制主题，覆盖系统偏好与本地记忆 |
| `present` | `1` | 直接进入演示模式（放大 + 隐藏脚注） |

例：`compare.html?theme=dark&present=1` 适合投影演示。

参数只影响初始状态，**不会写入 localStorage**——用户在页面上手动切换后，仍按手动选择记忆。
