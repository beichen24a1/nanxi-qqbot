# astrbot_plugin_netease_pick · 网易云点歌

把网易云的**歌曲链接**发（或引用）给机器人，它就把那首歌下载下来，
以 **mp3 文件 + 语音**两种形式发到群里。

走的是**官方外链直链**（`music.163.com/song/media/outer/url`）——
**零依赖、免 key、免登录**，不会因为第三方 API 服务挂掉而失效。
代价见下面的「已知限制」。

## 效果

| 你发什么 | 群里收到什么 |
| --- | --- |
| `@机器人 https://music.163.com/song?id=3413072220` | `直到大地变成一颗酸橙.mp3` + 同名语音 |
| **引用**一条含链接的消息 + `@机器人`（纯文本分享也行） | 同上 |
| **引用**一条 QQ 音乐卡片（`[分享]歌曲名`）+ `@机器人` | `歌名 - 歌手.mp3` + 语音 |
| **引用** `https://163cn.tv/xxxx`（App 分享短链）+ `@机器人` | 同上（短链会先跟随 302 拿到真实 id） |

文件名里的歌名有两个来源：**卡片里有就挖卡片的**（`歌名 - 歌手`），
没有卡片就去读**歌曲页的 `<meta property="og:title">`**（歌名），
两条都拿不到才退回歌曲 id。

## 安装

### 插件市场

AstrBot 面板 → 插件市场 → 搜「**网易云点歌**」→ 安装 → 重载插件。

### 手动

```bash
cd AstrBot/data/plugins
git clone https://github.com/beichen24a1/astrbot_plugin_netease_pick
```

然后在面板里重载插件（或重启 AstrBot）。

### ⚠️ 语音依赖宿主机 ffmpeg

发**语音**（`record`）时 AstrBot 会先调 `ffmpeg` 转码。宿主机没有的话会报
`Exception: ffmpeg not found`，此时可以：

- 装上 ffmpeg（Windows：`winget install Gyan.FFmpeg`；Debian/Ubuntu：`apt install ffmpeg`），**或**
- 把配置里的 `send_as` 改成 `file`，只发 mp3 文件。

⚠️ 装完记得让 **AstrBot 进程**能看见它 —— 有些包管理器（比如 winget）写的是**注册表 PATH**，
而已经在跑的进程继承的是**旧环境变量**，必须重启 AstrBot 才生效。

## 配置

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `enable` | `true` | 总开关 |
| `send_as` | `record,file` | 发哪些形式，逗号分隔。`record`=语音、`file`=mp3 文件。只想要一个就填单个值 |
| `container` | *(空)* | QQ 协议端的 Docker 容器名，**仅发 `file` 时用到**，见下 |

### `send_as` 与发送顺序

⚠️ 无论怎么填，群里看到的顺序**固定是「文件在上、语音在下」**。
这不是随便定的：语音必须走处理器的**最后一次 `yield`**，而 AstrBot 在
`stop_event()` 之后就不再往下迭代生成器了 —— 所以文件只能在它**之前**用
`await` 发完。（这个坑真踩过：写成"先 yield 语音、再发文件"的话，
文件那一段**一行都不会跑，而且不报错**。）

### `container`：要不要 `docker cp`

发 mp3 文件走的是 OneBot 的 `upload_group_file`，它读的是**协议端所在机器**的路径。
所以要看 AstrBot 和协议端的文件系统关系：

- **AstrBot 在宿主机、协议端在 Docker 容器里** ⇒ 两边隔离，**必须**先把文件
  `docker cp` 进容器再发容器内路径。这时 `container` 填协议端的**容器名**
  （NapCat / Lagrange / SnowLuma 等）。
- **AstrBot 自己也在容器里**（官方 Docker Compose 部署就是这样，容器内**没有
  `docker` CLI**），或两边共享了挂载卷 ⇒ **把 `container` 留空**，直接把路径交给协议端。

一句话：**配了就 `docker cp`，留空就直传。**

## 原理

```
QQ 消息 → AstrBot → 本插件
                      ├─ 从被引用的消息 / 本条消息里抠出网易云链接
                      ├─ 短链先跟随 302 拿歌曲 id
                      ├─ GET http://music.163.com/song/media/outer/url?id=<id>.mp3
                      │    （带浏览器 UA，会 302 到 music.126.net CDN）
                      ├─ 验证：Content-Type 是 audio/* + 落到 music.126.net + 体积 > 200 KB
                      ├─ （可选）docker cp 进协议端容器
                      ├─ upload_group_file 发 mp3      ← await
                      └─ yield Record(语音)            ← 必须是最后一次 yield
```

## 已知限制

- **拿不到 VIP / 版权受限的歌。** 官方外链接口只给能免费听的歌，
  受限的歌会返回一个 404 页面（而不是报错）——插件会识别出来并回复
  「这首下不了喵 —— …（多半是 VIP / 版权受限）」，而不是一声不吭。
- **没有歌名搜索。** 必须给链接或卡片，不支持"点一首 XX"（那需要第三方搜索 API）。
- 每群有 **20 秒冷却**，防刷屏。
- 测试环境：AstrBot `4.27.4`、Python `3.10+`、OneBot v11 协议端。

## 开发 / 自测

仓库里的 `tools/test_card_parse.py` 是**离线单测**：不需要 AstrBot、不需要 QQ，
mock 掉 `astrbot` 模块树就能验链接提取、卡片解析、歌名提取、以及各种 URL 形态。

```bash
python tools/test_card_parse.py
```

`main.py` 顶部的 **docstring 记着 7 个实测踩出来的坑**（UA、HTTP 200 不可信、
短链、`Reply.text`、`yield` 截断、`File` 组件不可用、`Record` 的 ffmpeg 依赖）——
改这个插件之前先读它，能省几小时。

## 许可

[MIT](LICENSE)
