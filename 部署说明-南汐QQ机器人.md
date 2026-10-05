# 南汐 QQ 猫娘机器人 · 部署说明

> 机器人 QQ：**<BOT_QQ>** ｜ 白名单群（4 项）：**<TEST_GROUP_ID>**、**<GROUP_D>**、**<GROUP_B>**、**<GROUP_C>** ｜ 人设：**南汐**（傲娇猫娘）｜ LLM：**DeepSeek** ｜ 主人：**<OWNER_QQ>**

---

## 一、整体架构

```
QQ群 <TEST_GROUP_ID> 里 @南汐
        │  (QQ消息)
        ▼
┌─────────────────────────────────────────────┐
│  SnowLuma   ←【Docker 容器】：QQ 登录端       │
│   · QQ <BOT_QQ> 在线                       │
│   · 把 QQ 消息 → OneBot v11 协议             │
│   · 端口: 6081(noVNC) 5099(WebUI)            │
│          3000(HTTP) 3001(WS服务端)           │
└──────────────────┬──────────────────────────┘
                   │ OneBot 反向 WebSocket (客户端)
                   │  → 连到 AstrBot 的 3002
                   ▼
┌─────────────────────────────────────────────┐
│  AstrBot   ←【Python 进程】：机器人大脑        │
│   · OneBot WS 服务端 :3002                   │
│   · WebUI/API :6185                         │
│   · 白名单（只回 4 个群，见 §四）             │
│   · 注入「南汐」猫娘人设 system_prompt        │
└──────────────────┬──────────────────────────┘
                   │ OpenAI 兼容 API
                   ▼
        DeepSeek (deepseek-chat)  ← 外部大模型
```

逻辑：**QQ → SnowLuma(协议) → OneBot → AstrBot(大脑+白名单+人设) → DeepSeek(生成) → 回 QQ**

---

## 二、三个组件

| 组件 | 是什么 | 位置 | 主要端口 | 访问入口 |
|---|---|---|---|---|
| **SnowLuma** | QQ 协议端（Docker 容器，名 `snowluma`） | Docker 容器 | 6081 / 5099 / 3000 / 3001 | WebUI <http://localhost:5099> |
| **AstrBot** | 机器人大脑（Python 进程） | `<PROJECT_ROOT>\astrbot` | 6185(WebUI) / 3002(OneBot) | WebUI <http://localhost:6185> |
| **DeepSeek** | LLM 大模型（外部 API） | 云端 | - | API Key 已配置 |

### 端口明细
| 端口 | 归属 | 用途 |
|---|---|---|
| 6081 | SnowLuma | noVNC 远程桌面（QQ 扫码窗口） |
| 5099 | SnowLuma | SnowLuma WebUI |
| 3000 | SnowLuma | OneBot HTTP |
| 3001 | SnowLuma | OneBot WebSocket（服务端，供参考） |
| 3002 | AstrBot | OneBot 反向 WS **服务端**（SnowLuma 连入） |
| 6185 | AstrBot | AstrBot WebUI / API |

---

## 三、目录结构

```
<PROJECT_ROOT>\
├── 启动\                   ← 启动/停止脚本都在这（2026-09-05 整理过，别再往根目录找）
│   ├── 一键启动.bat        ← 双击启动机器人
│   ├── start_all.ps1       ← 启动逻辑（被 bat 调用）
│   └── stop_astrbot.bat    ← 只停 AstrBot（按端口 6185/3002，不误杀其它 python）
├── run_astrbot.py          ← AstrBot 启动器（设置 pywin32）
├── onebot_<BOT_QQ>.json  ← SnowLuma OneBot 配置（工作区副本）
├── astrbot\                ← AstrBot 源码 + 数据
│   ├── data\
│   │   ├── cmd_config.json       ← 核心配置（DeepSeek/南汐/白名单/OneBot平台）
│   │   ├── data_v4.db            ← 数据库（人设、会话）
│   │   └── site-packages\        ← Python 依赖
│   ├── main.py                   ← AstrBot 入口
│   └── ...
└── snowluma\               ← SnowLuma 发行包（本机手动版，未使用；实际跑容器）
```

---

## 四、关键配置（都在 `astrbot\data\cmd_config.json`）

- **模型 Provider**：DeepSeek（`deepseek-chat`，api_base `https://api.deepseek.com/v1`），设为默认（`default_provider_id`）
- **人设**：`provider_settings.default_personality = "南汐"`（在 **provider_settings** 段下，不在顶层），且群会话 `persona_id = "南汐"`（强制猫娘人设）
- **主人识别**：人设里绑定主人 = User ID `<OWNER_QQ>`；并开启 `provider_settings.identifier = true`（让 AI 看到消息发送者 User ID / 昵称）。效果：只有 `<OWNER_QQ>` 发消息才称"主人"，其他人一律当普通群友、不叫主人。
- **白名单**：`platform_settings.enable_id_white_list = true`，`platform_settings.id_whitelist` 共 **4** 项
  （<TEST_GROUP_ID> / <GROUP_D> / <GROUP_B> / <GROUP_C>）→ 只在这 4 个群回复。后两个群是主人手动加的。
  注意：白名单在 **`platform_settings`** 段下，不在顶层。
- **OneBot 平台**：aiocqhttp，监听 `0.0.0.0:3002`，作为反向 WS **服务端**等 SnowLuma 连入
- 群 <TEST_GROUP_ID> 的会话人设已固定为南汐（在数据库里）

SnowLuma 容器内 `/app/data/config/onebot_<BOT_QQ>.json` 配置了 `wsClients`（反向连 `ws://host.docker.internal:3002`）。

---

## 五、管理入口与凭据

> ⚠️ **此处不写明文密码** —— 本文件已被 git 跟踪，写进来等于入库。值请从本地读，
> 位置见 `AGENTS.md` §4「关键凭据与"别泄露"」。

| 入口 | 用户名 | 密码 |
|---|---|---|
| AstrBot WebUI :6185 | `astrbot` | 见 `AGENTS.md` §4（失效时按该节重置，从启动日志读 Initial password） |
| SnowLuma WebUI :5099 | `admin` | （容器日志可查） |
| noVNC 扫码 :6081 | - | 见 `AGENTS.md` §4 |

---

## 六、如何启动 / 停止

### 一键启动（推荐）
双击 **`<PROJECT_ROOT>\启动\一键启动.bat`** 即可（脚本都在 `启动\` 子目录，根目录没有）。
- 自动启动 SnowLuma（Docker 容器）+ AstrBot（Python 进程）
- 幂等：已在运行的组件跳过，重复双击安全
- 运行完服务在后台，可关掉黑窗口

### 手动启动
```powershell
# SnowLuma（若容器停了）—— 注意：沙箱内 docker CLI 被禁，需在宿主机终端执行
docker start snowluma

# AstrBot
cd <PROJECT_ROOT>\astrbot
set PYTHONIOENCODING=utf-8
C:\Python310\python.exe <PROJECT_ROOT>\run_astrbot.py
```

### 停止
- **一键关闭（推荐）**：双击 **`启动\一键关闭.bat`** —— 按端口停 AstrBot + `docker stop snowluma`。
  只想看会停什么、不动手：`powershell -NoProfile -File 启动\stop_all.ps1 -DryRun`
- **只停 AstrBot**：双击 `启动\stop_astrbot.bat`（按端口 6185/3002 停）。
  ⚠️ **不要**用"任务管理器结束 `python.exe`" —— 机器上还有别的 python 进程，会误杀。
- **SnowLuma**：`docker stop snowluma`。
  ⚠️ 本机沙箱内 **docker CLI 被禁**（连 npipe 无权限），查状态请用
  `netstat -ano | Select-String ":5099"` + `Get-Process`。

---

## 七、排障速查

- **QQ 掉线 / 需重新登录**：访问 <http://localhost:6081>（密码见 `AGENTS.md` §4），在 noVNC 里重新扫码登录 <BOT_QQ>
- **南汐不回复**：确认 AstrBot 在跑（<http://localhost:6185> 能打开）+ SnowLuma 容器在跑
  （沙箱内查法：`netstat -ano | Select-String ":5099"`，**docker CLI 被禁**）+ 是否在群 <TEST_GROUP_ID> 里发
- **连接断了**：检查 AstrBot 日志 / SnowLuma 日志；必要时重启容器（沙箱内 docker CLI 不可用，见上）
- **改人设/模型**：登录 AstrBot WebUI (6185)

---

*生成时间：2026-08-29 ｜ 由 DSH 部署助手整理*
