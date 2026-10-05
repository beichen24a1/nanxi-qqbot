# 摸头杀插件（astrbot_plugin_petpet）

给南汐加个「摸头」技能：**@南汐 摸摸** 就能生成一张摸头杀动图。

## 用法

在群里 **@一下南汐**，再带上触发词就行 —— `/` 可加可不加，**@ 的位置也不限**：

| 你这么发 | 摸的是谁 |
|---|---|
| `@南汐 摸摸` | 你自己（发送者）的头像 |
| `@用户 @南汐 摸摸` | **被 @ 的那个人的头像** |
| `@用户 摸摸 @南汐` | 同上 |
| `@南汐 @用户 摸摸` | 同上 |
| 引用一张图 + `@南汐 摸摸` | **被引用的那张图**（推荐用法） |
| 直接发一张图 + `@南汐 摸摸` | 你发的那张图 |
| `@南汐 /摸摸` | 同 `@南汐 摸摸` |

**触发词**：`摸摸`、`摸头`、`摸摸头`、`拍头`、`petpet`、`rua`（大小写不敏感）。

**回复内容**：只有一张 112×112 的透明背景 GIF，**不带任何文字**。

优先级：**引用图 > 本条消息的图 > @ 的人 > 发送者自己**。

细节：
- 群聊里**必须 @ 南汐 或使用 `/` 前缀**（AstrBot 的唤醒判定），否则只含"摸摸"的闲聊不会被理会；
- 插件自己（`<BOT_QQ>`）会被忽略 —— `@南汐 摸摸` 不会变成摸南汐自己的头；
- `@全体成员` 同样被忽略（`qq == "all"`）；
- 一条消息里 @ 了多个人时，**取最后一个**非南汐的 @；
- 头像走腾讯的 `q1.qlogo.cn`，取不到时返回默认头像，不会报错；
- 触发词前后要求词边界，所以 `gradual`（含 `rua`）、"别**摸摸**我" 这类不会误触发。

> 实现要点：这里用的是 `@filter.regex()` 而不是 `@filter.command()`。
> 因为命令过滤器是「整行以命令开头」匹配，而 `@用户 @南汐 摸摸` 的 message_str 会变成
> `@用户(123) 摸摸`（@南汐 被剥离、@用户 被保留），整行匹配会失败。
> 正则过滤器用 `search`，任意位置都能命中；是否"该理会"则交给 `event.is_at_or_wake_command` 判定。

生成结果：112×112、5 帧的透明背景 GIF（和 toolwa.com/petpet 网页版一模一样的效果）。

## 组成

| 文件 | 作用 |
|---|---|
| `main.py` | AstrBot 插件主体：挑图 → 渲染 → 回复 |
| `petpet_render.py` | 渲染器（Pillow 实现，可单独命令行使用） |
| `assets/hand.png` | 手部精灵图：560×112，横向 5 帧，每帧 112×112 |

## 渲染算法来源

算法逐项复刻自网页版生成器 [B1gM8c/Petpet](https://github.com/B1gM8c/Petpet)（toolwa.com/petpet 用的就是这套）。
网页版 `main.js` 的关键常量，在 `petpet_render.py` 中一一对应：

```
MAX_FRAME = 4                 # 共 5 帧（0..4）
OUT_SIZE  = 112               # 输出画布 112x112
squish = 1.25, scale = 0.875  # 挤压程度 / 尺寸
delay  = 60                   # 帧间隔（毫秒）
spriteX = 14, spriteY = 20, spriteWidth = 112
frameOffsets = [(0,0,0,0), (-4,12,4,-12), (-12,18,12,-18), (-8,12,4,-12), (-4,0,0,0)]
```

`assets/hand.png` 即网页版 `img/sprite.png`（原样复制）。

> 网页版是在浏览器里用 canvas 画每一帧再交给 gif.js 编码，所以「很卡」；
> 这里改成服务端用 Pillow 直接合成，一次生成只要几十毫秒。

**与网页版唯一的差异**：网页版固定按宽度缩放到 112，横图（例如 400×200 的截图）会被压成一条；
本插件的 `auto_fit`（默认开启）让横图改为按高度撑满画布并水平居中，方图和竖图行为与网页版完全一致。
需要回到网页版原逻辑时：命令行加 `--no-auto-fit`，或调用 `render_frames(..., auto_fit=False)`。

## 单独调试（不开 AstrBot）

```powershell
cd <PROJECT_ROOT>
C:\Python310\python.exe astrbot_plugin_petpet\petpet_render.py astrbot_plugin_petpet\assets\sample.png _test\out.gif --preview _test\out_f0.png
```

可选参数：`--squish`（挤压）、`--scale`（大小）、`--delay`（速度）、`--sprite-x/--sprite-y/--sprite-w`（位置与宽度）、`--flip`（水平翻转）。

## 部署

插件本体在 `<PROJECT_ROOT>\astrbot_plugin_petpet\`，实际生效的副本要放到 AstrBot 的插件目录：

```powershell
Copy-Item <PROJECT_ROOT>\astrbot_plugin_petpet <PROJECT_ROOT>\astrbot\data\plugins\ -Recurse -Force
```

改完插件必须重启 AstrBot 才生效（`启动\stop_astrbot.bat` + `启动\一键启动.bat`）。
