# QQ 猫娘机器人「南汐」调研报告与方案

> ⚠️ **本文是选型阶段的调研，结论已部分过时**：报告里的"硬约束"（Docker 不可用 / HTTPS 出网不通 /
> 需一台远程服务器）均已被实际部署推翻 —— 现状是 SnowLuma Docker 容器正在运行、AstrBot 与 DSH
> 都已本地部署、代理 7897 可用。**当前口径以 `AGENTS.md` 为准**，本文仅作选型过程留档。

> 机器人 QQ 号：<BOT_QQ>　｜　人设：南汐（傲娇猫娘）

## 一、项目定位

### SnowLuma（QQ 协议端）
- **定位**：Next Remote Protocol Framework（下一代远程协议框架），社区新出现的 QQ 协议接入方案。
- **状态**：活跃开发，已迭代至 v1.14.11；官方文档站 <https://snowluma.github.io/>；提供 Docker 框架（`SnowLuma/SnowLuma.Docker.Framework`）。
- **能力**：作为 QQ 协议端，把 QQ 消息转换成远程协议，供机器人框架（如 AstrBot）对接。支持 **Windows 手动部署** 与 Docker 部署。
- **背景**：搜索结果显示社区正从 LLOneBot（"LLBOT 跑路"）迁移，SnowLuma 是较新的替代。
- 参考：[SnowLuma/SnowLuma](https://github.com/SnowLuma/SnowLuma)、[Windows 手动部署](https://snowluma.github.io/guide/deploy/windows.html)、[SnowLuma.Docker.Framework](https://github.com/SnowLuma/SnowLuma.Docker.Framework)

### AstrBot（机器人框架）
- **定位**：多平台 AI 机器人框架（QQ / 微信 / Telegram / Discord 等）。
- **能力**：
  - 通过协议端（NapCat / LLOneBot / SnowLuma）接入 QQ
  - 接入各类 LLM（DeepSeek / OpenAI / Claude 等，支持 OpenAI 兼容接口），即 Provider 系统
  - **Persona 系统**（人设/提示词注入，适合做猫娘 Bot）
  - 插件系统（人设增强、长期记忆、世界书等）
  - 可视化管理控制台 WebDash
  - 完善的中文文档 <https://docs.astrbot.app>
- 参考：[AstrBotDevs/AstrBot](https://github.com/AstrBotDevs/AstrBot)、[接入模型服务](https://docs.astrbot.app/providers/start.html)、[Persona System](https://deepwiki.com/AstrBotDevs/AstrBot/10.3-persona-system)

### DeepSeek（LLM）
- DeepSeek 官方提供 AstrBot 接入文档与社区最佳实践，中文效果好、成本低。
- 参考：[DeepSeek API - 接入 AstrBot](https://api-docs.deepseek.com/zh-cn/quick_start/agent_integrations/astrbot/)、[awesome-deepseek-agent / astrbot.md](https://github.com/deepseek-ai/awesome-deepseek-agent/blob/main/docs/astrbot.md)

## 二、推荐架构

```
QQ(395920388)
   │  QQ 登录
SnowLuma  ←── QQ 协议端（转发消息 → 远程协议）
   │  远程协议
AstrBot  ←── 机器人框架（人设 / 插件 / LLM 调用 / WebDash）
   │  OpenAI 兼容 API
DeepSeek ←── LLM（「南汐」的大脑）
```

## 三、猫娘人设「南汐」的实现

- 通过 **AstrBot Persona 系统**（即 system_prompt）注入用户提供的提示词，实现傲娇猫娘人设。
- 关键约束已在提示词中给出：**禁止描述动作/表情/神态**，仅输出对话，用颜文字表达情绪。这是重要的安全/一致性设定，应原样写入 persona。
- 可选的增强插件：
  - `astrbot_plugin_worldbook`：正则触发注入 system_prompt（构建与管理"世界书"规则）
  - `astrbot_plugin_self_evolution`：人设进化 / 长期记忆 / 元编程
  - `galgame-astrbot-personas`：社区人设参考（基于视觉小说台词风格）
  - `astrbot_plugin_memory_beyond`：增强记忆

## 四、可借鉴的优秀项目 / 教程

1. **Fast_Deploy_Astrbot_Napcat**（10XuQ）—— 面向国内网络的 AstrBot + 协议端一键部署脚本，免 Docker。
   <https://github.com/10XuQ/Fast_Deploy_Astrbot_napcat>
2. **awesome-deepseek-agent**（DeepSeek 官方）—— AstrBot 接入 DeepSeek 的最佳实践文档。
   <https://github.com/deepseek-ai/awesome-deepseek-agent/blob/main/docs/astrbot.md>
3. **galgame-astrbot-personas**（LanternFlower）—— 社区人设合集，可作「南汐」人设参考。
   <https://github.com/LanternFlower/galgame-astrbot-personas>
4. **世界书 / 长期记忆插件**：
   - <https://github.com/Zhalslar/astrbot_plugin_worldbook>
   - <https://github.com/Renyus/astrbot_plugin_self_evolution>
   - <https://github.com/AlanBacker/astrbot_plugin_memory_beyond>
5. 教程：CSDN《QQ 接入 DeepSeek：Docker 部署 AstrBot + NapCat》、B 站《使用 AstrBot 构建可爱的 Deepseek 猫娘 Bot》、阿里云开发者《使用宝塔面板部署 AstrBot 与 NapCat》。

## 五、本机环境硬约束（重要）

实测本机**无法直接部署**：

- **HTTPS 出网基本不通**：TLS 握手被中断。`pip` / `git` / `curl` / `npm` 拉取依赖全部失败；连国内镜像（清华 pypi、npmmirror）与 GitHub 加速镜像也无法访问；仅 `web_search` 工具能联网。
- **Docker 不可用**。
- **SSH 尚未配置任何主机**。

> 结论：需要一台能联网的远程服务器（推荐 Linux + Docker / Python），或先解决本机代理/网络问题，才能完成 AstrBot + SnowLuma 的依赖下载与部署。
