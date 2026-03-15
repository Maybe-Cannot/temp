# OpenClaw — 个人 AI 助手

<p align="center">
  <a href="https://github.com/openclaw/openclaw/actions/workflows/ci.yml?branch=main"><img src="https://img.shields.io/github/actions/workflow/status/openclaw/openclaw/ci.yml?branch=main&style=for-the-badge" alt="CI 状态"></a>
  <a href="https://github.com/openclaw/openclaw/releases"><img src="https://img.shields.io/github/v/release/openclaw/openclaw?include_prereleases&style=for-the-badge" alt="GitHub 发布版本"></a>
  <a href="https://discord.gg/clawd"><img src="https://img.shields.io/discord/1456350064065904867?label=Discord&logo=discord&logoColor=white&color=5865F2&style=for-the-badge" alt="Discord"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg?style=for-the-badge" alt="MIT 许可证"></a>
</p>
**OpenClaw** 是一个运行在你自有设备上的个人 AI 助手。
它可以在你已经在用的渠道中回复你（WhatsApp、Telegram、Slack、Discord、Google Chat、Signal、iMessage、BlueBubbles、IRC、Microsoft Teams、Matrix、飞书、LINE、Mattermost、Nextcloud Talk、Nostr、Synology Chat、Tlon、Twitch、Zalo、Zalo Personal、WebChat）。它还能在 macOS/iOS/Android 上进行语音收发，并可渲染可交互的实时 Canvas。Gateway 只是控制平面，真正的产品是这个助手本身。

如果你希望拥有一个面向个人、单用户、具备本地感、响应快、常驻在线的助手，这就是它。

[官网](https://openclaw.ai) · [文档](https://docs.openclaw.ai) · [愿景](VISION.md) · [DeepWiki](https://deepwiki.com/openclaw/openclaw) · [快速开始](https://docs.openclaw.ai/start/getting-started) · [升级指南](https://docs.openclaw.ai/install/updating) · [展示](https://docs.openclaw.ai/start/showcase) · [FAQ](https://docs.openclaw.ai/help/faq) · [向导](https://docs.openclaw.ai/start/wizard) · [Nix](https://github.com/openclaw/nix-openclaw) · [Docker](https://docs.openclaw.ai/install/docker) · [Discord](https://discord.gg/clawd)

推荐方式：在终端中运行引导向导（openclaw onboard）。
向导会一步步带你完成 Gateway、工作区、渠道和技能的配置。CLI 向导是推荐路径，支持 macOS、Linux 和 Windows（通过 WSL2，强烈推荐）。
支持 npm、pnpm 或 bun。
新安装用户请从这里开始：[快速开始](https://docs.openclaw.ai/start/getting-started)

**订阅（OAuth）：**

- **[OpenAI](https://openai.com/)**（ChatGPT/Codex）

模型说明：尽管支持很多提供商和模型，但为了获得最佳体验并降低提示注入风险，建议使用你可用的最新一代强模型。参见：[Onboarding](https://docs.openclaw.ai/start/onboarding)。

## 模型（选择 + 鉴权）

- 模型配置与 CLI： [Models](https://docs.openclaw.ai/concepts/models)
- 鉴权档案轮换（OAuth 与 API Key）及回退： [Model failover](https://docs.openclaw.ai/concepts/model-failover)

## 安装（推荐）

运行时要求：**Node >= 22**。

```bash
npm install -g openclaw@latest
# 或：pnpm add -g openclaw@latest

openclaw onboard --install-daemon
```

向导会安装 Gateway 守护服务（launchd/systemd user service），使其常驻运行。

## 快速开始（TL;DR）

运行时要求：**Node >= 22**。

完整新手指南（鉴权、配对、渠道）：[Getting started](https://docs.openclaw.ai/start/getting-started)

```bash
openclaw onboard --install-daemon

openclaw gateway --port 18789 --verbose

# 发送消息
openclaw message send --to +1234567890 --message "Hello from OpenClaw"

# 与助手对话（可选将结果回传到任一已连接渠道：WhatsApp/Telegram/Slack/Discord/Google Chat/Signal/iMessage/BlueBubbles/IRC/Microsoft Teams/Matrix/Feishu/LINE/Mattermost/Nextcloud Talk/Nostr/Synology Chat/Tlon/Twitch/Zalo/Zalo Personal/WebChat）
openclaw agent --message "Ship checklist" --thinking high
```

升级请看：[Updating guide](https://docs.openclaw.ai/install/updating)（并执行 openclaw doctor）。

## 开发通道

- **stable**：带标签发布（vYYYY.M.D 或 vYYYY.M.D-<patch>），npm dist-tag 为 latest。
- **beta**：预发布标签（vYYYY.M.D-beta.N），npm dist-tag 为 beta（可能不含 macOS app）。
- **dev**：main 分支的滚动版本，npm dist-tag 为 dev（发布时可用）。

切换通道（git + npm）：openclaw update --channel stable|beta|dev。
详情： [Development channels](https://docs.openclaw.ai/install/development-channels)。

## 从源码安装（开发）

从源码构建时推荐使用 pnpm。若仅需直接运行 TypeScript，bun 可选。

```bash
git clone https://github.com/openclaw/openclaw.git
cd openclaw

pnpm install
pnpm ui:build # 首次运行会自动安装 UI 依赖
pnpm build

pnpm openclaw onboard --install-daemon

# 开发循环（TS 变更自动重载）
pnpm gateway:watch
```

说明：pnpm openclaw ... 会通过 tsx 直接运行 TypeScript。pnpm build 会产出 dist/，用于通过 Node 或打包后的 openclaw 二进制运行。

## 默认安全策略（DM 访问）

OpenClaw 会接入真实消息渠道。请将入站私信视为**不可信输入**。

完整安全指南： [Security](https://docs.openclaw.ai/gateway/security)

Telegram/WhatsApp/Signal/iMessage/Microsoft Teams/Discord/Google Chat/Slack 的默认行为：

- **DM 配对**（dmPolicy="pairing" / channels.discord.dmPolicy="pairing" / channels.slack.dmPolicy="pairing"；旧字段：channels.discord.dm.policy、channels.slack.dm.policy）：未知发送者会收到简短配对码，机器人不会处理其消息。
- 批准命令：openclaw pairing approve <channel> <code>（批准后发送者会被加入本地 allowlist 存储）。
- 若要公开接收私信，需显式开启：设置 dmPolicy="open"，并在渠道 allowlist（allowFrom / channels.discord.allowFrom / channels.slack.allowFrom；旧字段：channels.discord.dm.allowFrom、channels.slack.dm.allowFrom）里包含 "*"。

执行 openclaw doctor 可发现高风险/错误 DM 配置。

## 亮点

- **[Local-first Gateway](https://docs.openclaw.ai/gateway)**：统一控制平面，管理会话、渠道、工具和事件。
- **[多渠道收件箱](https://docs.openclaw.ai/channels)**：覆盖 WhatsApp、Telegram、Slack、Discord、Google Chat、Signal、BlueBubbles（iMessage）、iMessage（legacy）、IRC、Microsoft Teams、Matrix、飞书、LINE、Mattermost、Nextcloud Talk、Nostr、Synology Chat、Tlon、Twitch、Zalo、Zalo Personal、WebChat、macOS、iOS/Android。
- **[多 Agent 路由](https://docs.openclaw.ai/gateway/configuration)**：按渠道/账号/对端将消息路由到隔离 Agent（独立 workspace + session）。
- **[Voice Wake](https://docs.openclaw.ai/nodes/voicewake) + [Talk Mode](https://docs.openclaw.ai/nodes/talk)**：macOS/iOS 唤醒词 + Android 持续语音（ElevenLabs，系统 TTS 回退）。
- **[Live Canvas](https://docs.openclaw.ai/platforms/mac/canvas)**：Agent 驱动的可视工作区，支持 [A2UI](https://docs.openclaw.ai/platforms/mac/canvas#canvas-a2ui)。
- **[一等工具体系](https://docs.openclaw.ai/tools)**：browser、canvas、nodes、cron、sessions、Discord/Slack actions。
- **[配套应用](https://docs.openclaw.ai/platforms/macos)**：macOS 菜单栏应用 + iOS/Android [nodes](https://docs.openclaw.ai/nodes)。
- **[Onboarding](https://docs.openclaw.ai/start/wizard) + [skills](https://docs.openclaw.ai/tools/skills)**：向导式配置，支持内置/托管/工作区技能。

## Star 历史

[![Star History Chart](https://api.star-history.com/svg?repos=openclaw/openclaw&type=date&legend=top-left)](https://www.star-history.com/#openclaw/openclaw&type=date&legend=top-left)

## 我们已经构建的内容

### 核心平台

- [Gateway WS 控制平面](https://docs.openclaw.ai/gateway)：会话、在线状态、配置、cron、webhook、[Control UI](https://docs.openclaw.ai/web)、[Canvas host](https://docs.openclaw.ai/platforms/mac/canvas#canvas-a2ui)。
- [CLI 接口](https://docs.openclaw.ai/tools/agent-send)：gateway、agent、send、[wizard](https://docs.openclaw.ai/start/wizard)、[doctor](https://docs.openclaw.ai/gateway/doctor)。
- [Pi Agent 运行时](https://docs.openclaw.ai/concepts/agent)：RPC 模式，支持工具流与块流。
- [会话模型](https://docs.openclaw.ai/concepts/session)：主会话 main、群组隔离、激活模式、队列模式、回复回传。群组规则： [Groups](https://docs.openclaw.ai/channels/groups)。
- [媒体管道](https://docs.openclaw.ai/nodes/images)：图片/音频/视频、转录钩子、尺寸限制、临时文件生命周期。音频细节： [Audio](https://docs.openclaw.ai/nodes/audio)。

### 渠道

- [Channels](https://docs.openclaw.ai/channels)：[WhatsApp](https://docs.openclaw.ai/channels/whatsapp)（Baileys）、[Telegram](https://docs.openclaw.ai/channels/telegram)（grammY）、[Slack](https://docs.openclaw.ai/channels/slack)（Bolt）、[Discord](https://docs.openclaw.ai/channels/discord)（discord.js）、[Google Chat](https://docs.openclaw.ai/channels/googlechat)（Chat API）、[Signal](https://docs.openclaw.ai/channels/signal)（signal-cli）、[BlueBubbles](https://docs.openclaw.ai/channels/bluebubbles)（iMessage，推荐）、[iMessage](https://docs.openclaw.ai/channels/imessage)（legacy imsg）、[IRC](https://docs.openclaw.ai/channels/irc)、[Microsoft Teams](https://docs.openclaw.ai/channels/msteams)、[Matrix](https://docs.openclaw.ai/channels/matrix)、[飞书](https://docs.openclaw.ai/channels/feishu)、[LINE](https://docs.openclaw.ai/channels/line)、[Mattermost](https://docs.openclaw.ai/channels/mattermost)、[Nextcloud Talk](https://docs.openclaw.ai/channels/nextcloud-talk)、[Nostr](https://docs.openclaw.ai/channels/nostr)、[Synology Chat](https://docs.openclaw.ai/channels/synology-chat)、[Tlon](https://docs.openclaw.ai/channels/tlon)、[Twitch](https://docs.openclaw.ai/channels/twitch)、[Zalo](https://docs.openclaw.ai/channels/zalo)、[Zalo Personal](https://docs.openclaw.ai/channels/zalouser)、[WebChat](https://docs.openclaw.ai/web/webchat)。
- [群组路由](https://docs.openclaw.ai/channels/group-messages)：提及门控、回复标签、按渠道分片与路由。渠道规则： [Channels](https://docs.openclaw.ai/channels)。

### App + 节点

- [macOS app](https://docs.openclaw.ai/platforms/macos)：菜单栏控制平面、[Voice Wake](https://docs.openclaw.ai/nodes/voicewake)/PTT、[Talk Mode](https://docs.openclaw.ai/nodes/talk) 浮层、[WebChat](https://docs.openclaw.ai/web/webchat)、调试工具、[远程网关](https://docs.openclaw.ai/gateway/remote) 控制。
- [iOS 节点](https://docs.openclaw.ai/platforms/ios)：[Canvas](https://docs.openclaw.ai/platforms/mac/canvas)、[Voice Wake](https://docs.openclaw.ai/nodes/voicewake)、[Talk Mode](https://docs.openclaw.ai/nodes/talk)、相机、录屏、Bonjour + 设备配对。
- [Android 节点](https://docs.openclaw.ai/platforms/android)：Connect（setup code/manual）、聊天会话、语音标签页、[Canvas](https://docs.openclaw.ai/platforms/mac/canvas)、相机/录屏，以及 Android 设备命令（通知/定位/SMS/照片/联系人/日历/运动/app 更新）。
- [macOS 节点模式](https://docs.openclaw.ai/nodes)：system.run/system.notify + canvas/camera 能力暴露。

### 工具与自动化

- [浏览器控制](https://docs.openclaw.ai/tools/browser)：OpenClaw 管理的 Chrome/Chromium，支持快照、操作、上传、Profile。
- [Canvas](https://docs.openclaw.ai/platforms/mac/canvas)：支持 [A2UI](https://docs.openclaw.ai/platforms/mac/canvas#canvas-a2ui) push/reset、eval、snapshot。
- [Nodes](https://docs.openclaw.ai/nodes)：camera snap/clip、screen record、[location.get](https://docs.openclaw.ai/nodes/location-command)、notifications。
- [Cron + 唤醒任务](https://docs.openclaw.ai/automation/cron-jobs)；[webhook](https://docs.openclaw.ai/automation/webhook)；[Gmail Pub/Sub](https://docs.openclaw.ai/automation/gmail-pubsub)。
- [技能平台](https://docs.openclaw.ai/tools/skills)：内置、托管与工作区技能，支持安装门控和 UI。

### 运行时与安全

- [渠道路由](https://docs.openclaw.ai/channels/channel-routing)、[重试策略](https://docs.openclaw.ai/concepts/retry)、[流式/分片](https://docs.openclaw.ai/concepts/streaming)。
- [在线状态](https://docs.openclaw.ai/concepts/presence)、[输入中提示](https://docs.openclaw.ai/concepts/typing-indicators)、[用量追踪](https://docs.openclaw.ai/concepts/usage-tracking)。
- [模型](https://docs.openclaw.ai/concepts/models)、[模型回退](https://docs.openclaw.ai/concepts/model-failover)、[会话裁剪](https://docs.openclaw.ai/concepts/session-pruning)。
- [安全](https://docs.openclaw.ai/gateway/security) 与 [故障排查](https://docs.openclaw.ai/channels/troubleshooting)。

### 运维与打包

- [Control UI](https://docs.openclaw.ai/web) + [WebChat](https://docs.openclaw.ai/web/webchat) 由 Gateway 直接提供。
- [Tailscale Serve/Funnel](https://docs.openclaw.ai/gateway/tailscale) 或 [SSH 隧道](https://docs.openclaw.ai/gateway/remote)，支持 token/password 鉴权。
- [Nix 模式](https://docs.openclaw.ai/install/nix)（声明式配置）；[Docker](https://docs.openclaw.ai/install/docker) 安装。
- [Doctor](https://docs.openclaw.ai/gateway/doctor) 迁移与 [日志](https://docs.openclaw.ai/logging)。

## 工作原理（简版）

```
WhatsApp / Telegram / Slack / Discord / Google Chat / Signal / iMessage / BlueBubbles / IRC / Microsoft Teams / Matrix / Feishu / LINE / Mattermost / Nextcloud Talk / Nostr / Synology Chat / Tlon / Twitch / Zalo / Zalo Personal / WebChat
               │
               ▼
┌───────────────────────────────┐
│            Gateway            │
│       (control plane)         │
│     ws://127.0.0.1:18789      │
└──────────────┬────────────────┘
               │
               ├─ Pi agent (RPC)
               ├─ CLI (openclaw …)
               ├─ WebChat UI
               ├─ macOS app
               └─ iOS / Android nodes
```

## 关键子系统

- **[Gateway WebSocket 网络](https://docs.openclaw.ai/concepts/architecture)**：面向客户端、工具、事件的统一 WS 控制平面（运维参见 [Gateway runbook](https://docs.openclaw.ai/gateway)）。
- **[Tailscale 暴露](https://docs.openclaw.ai/gateway/tailscale)**：为 Gateway dashboard + WS 提供 Serve/Funnel（远程访问参见 [Remote](https://docs.openclaw.ai/gateway/remote)）。
- **[浏览器控制](https://docs.openclaw.ai/tools/browser)**：OpenClaw 管理的 Chrome/Chromium + CDP 控制。
- **[Canvas + A2UI](https://docs.openclaw.ai/platforms/mac/canvas)**：Agent 驱动可视工作区（A2UI host 见 [Canvas/A2UI](https://docs.openclaw.ai/platforms/mac/canvas#canvas-a2ui)）。
- **[Voice Wake](https://docs.openclaw.ai/nodes/voicewake) + [Talk Mode](https://docs.openclaw.ai/nodes/talk)**：macOS/iOS 唤醒词，Android 持续语音。
- **[Nodes](https://docs.openclaw.ai/nodes)**：Canvas、相机拍照/录像、录屏、location.get、通知，以及仅 macOS 可用的 system.run/system.notify。

## Tailscale 访问（Gateway Dashboard）

OpenClaw 可自动配置 Tailscale **Serve**（仅 tailnet）或 **Funnel**（公网），同时 Gateway 保持绑定到 loopback。通过 gateway.tailscale.mode 配置：

- off：关闭 Tailscale 自动化（默认）。
- serve：通过 tailscale serve 提供 tailnet 内 HTTPS（默认使用 Tailscale 身份头）。
- funnel：通过 tailscale funnel 提供公网 HTTPS（需共享密码鉴权）。

注意：

- 开启 Serve/Funnel 时，gateway.bind 必须保持 loopback（OpenClaw 会强制执行）。
- 可通过 gateway.auth.mode: "password" 或 gateway.auth.allowTailscale: false 强制 Serve 需要密码。
- Funnel 仅在 gateway.auth.mode: "password" 时可启动。
- 可选：gateway.tailscale.resetOnExit，在退出时撤销 Serve/Funnel。

详情： [Tailscale guide](https://docs.openclaw.ai/gateway/tailscale) · [Web surfaces](https://docs.openclaw.ai/web)

## 远程 Gateway（Linux 很适合）

将 Gateway 运行在一台小型 Linux 实例上完全可行。客户端（macOS app、CLI、WebChat）可以通过 **Tailscale Serve/Funnel** 或 **SSH 隧道** 连接；你也可以继续配对设备节点（macOS/iOS/Android）执行设备本地动作。

- **Gateway 主机**默认运行 exec 工具与渠道连接。
- **设备节点**通过 node.invoke 执行设备本地动作（system.run、相机、录屏、通知）。
  简单说：exec 在 Gateway 所在主机执行，设备动作在设备本机执行。

详情： [Remote access](https://docs.openclaw.ai/gateway/remote) · [Nodes](https://docs.openclaw.ai/nodes) · [Security](https://docs.openclaw.ai/gateway/security)

## 通过 Gateway 协议处理 macOS 权限

macOS app 可运行在 **node mode**，并通过 Gateway WebSocket 广播其能力与权限映射（node.list / node.describe）。客户端随后可通过 node.invoke 执行本地动作：

- system.run：运行本地命令并返回 stdout/stderr/exit code；设置 needsScreenRecording: true 时要求屏幕录制权限（否则返回 PERMISSION_MISSING）。
- system.notify：发送系统通知；若通知权限被拒绝则失败。
- canvas.*、camera.*、screen.record、location.get 同样通过 node.invoke 路由，并受 TCC 权限状态约束。

宿主机提权 bash（host permissions）与 macOS TCC 权限是两套体系：

- 用 /elevated on|off 切换会话级提权（需启用并在 allowlist）。
- Gateway 会通过 sessions.patch（WS 方法）持久化该开关，同时持久化 thinkingLevel、verboseLevel、model、sendPolicy、groupActivation。

详情： [Nodes](https://docs.openclaw.ai/nodes) · [macOS app](https://docs.openclaw.ai/platforms/macos) · [Gateway protocol](https://docs.openclaw.ai/concepts/architecture)

## Agent to Agent（sessions_* 工具）

- 用于跨会话协作，无需在多个聊天渠道间跳转。
- sessions_list：发现活跃会话（agent）及元数据。
- sessions_history：获取指定会话的历史对话。
- sessions_send：向其他会话发消息；可选 reply-back 乒乓与 announce 步骤（REPLY_SKIP、ANNOUNCE_SKIP）。

详情： [Session tools](https://docs.openclaw.ai/concepts/session-tool)

## 技能注册表（ClawHub）

ClawHub 是一个轻量技能注册表。启用后，Agent 可以自动检索技能并按需拉取。

[ClawHub](https://clawhub.com)

## 聊天命令

可在 WhatsApp/Telegram/Slack/Google Chat/Microsoft Teams/WebChat 发送以下命令（群组命令仅 owner 可用）：

- /status：紧凑会话状态（模型 + token，用量成本可用时显示）
- /new 或 /reset：重置会话
- /compact：压缩会话上下文（摘要）
- /think <level>：off|minimal|low|medium|high|xhigh（仅 GPT-5.2 + Codex 模型）
- /verbose on|off
- /usage off|tokens|full：每条回复底部用量信息
- /restart：重启网关（群组中仅 owner）
- /activation mention|always：群组激活模式切换（仅群组）

## 应用（可选）

仅 Gateway 本身就能提供很好的体验。所有 app 都是可选项，用于增加额外能力。

如果你计划构建/运行配套 app，请按以下平台 runbook 操作。

### macOS（OpenClaw.app）（可选）

- 菜单栏控制 Gateway 与健康状态
- Voice Wake + 按住说话浮层
- WebChat + 调试工具
- 通过 SSH 远程控制 Gateway

说明：要让 macOS 权限在多次重建后保持生效，需要签名构建（参见 docs/mac/permissions.md）。

### iOS 节点（可选）

- 通过 Gateway WebSocket（设备配对）接入为节点
- 语音触发转发 + Canvas 视图
- 通过 openclaw nodes ... 控制

Runbook： [iOS connect](https://docs.openclaw.ai/platforms/ios)

### Android 节点（可选）

- 通过设备配对接入 WS 节点（openclaw devices ...）
- 提供 Connect/Chat/Voice 标签页，以及 Canvas、Camera、Screen capture、Android 设备命令族
- Runbook： [Android connect](https://docs.openclaw.ai/platforms/android)

## Agent 工作区与技能

- 工作区根目录：~/.openclaw/workspace（可通过 agents.defaults.workspace 配置）
- 注入提示词文件：AGENTS.md、SOUL.md、TOOLS.md
- 技能目录：~/.openclaw/workspace/skills/<skill>/SKILL.md

## 配置

最小化 ~/.openclaw/openclaw.json（模型 + 默认项）：

```json5
{
  agent: {
    model: "anthropic/claude-opus-4-6",
  },
}
```

[完整配置参考（全部键 + 示例）](https://docs.openclaw.ai/gateway/configuration)

## 安全模型（重要）

- **默认：** 工具运行在主机上的 main 会话中；因此在个人场景下助手拥有完整访问能力。
- **群组/渠道安全：** 将 agents.defaults.sandbox.mode 设为 "non-main"，让**非 main 会话**（群组/渠道）在每会话独立 Docker 沙箱内运行；此时 bash 在 Docker 内执行。
- **沙箱默认策略：** allowlist：bash、process、read、write、edit、sessions_list、sessions_history、sessions_send、sessions_spawn；denylist：browser、canvas、nodes、cron、discord、gateway。

详情： [Security guide](https://docs.openclaw.ai/gateway/security) · [Docker + sandboxing](https://docs.openclaw.ai/install/docker) · [Sandbox config](https://docs.openclaw.ai/gateway/configuration)

### [WhatsApp](https://docs.openclaw.ai/channels/whatsapp)

- 设备登录：pnpm openclaw channels login（凭据存于 ~/.openclaw/credentials）
- 使用 channels.whatsapp.allowFrom 配置可与助手对话的 allowlist
- 若设置 channels.whatsapp.groups，则它会成为群组 allowlist；包含 "*" 可放开所有

### [Telegram](https://docs.openclaw.ai/channels/telegram)

- 设置 TELEGRAM_BOT_TOKEN 或 channels.telegram.botToken（环境变量优先）
- 可选：设置 channels.telegram.groups（配合 channels.telegram.groups."*".requireMention）；设置后其即为群组 allowlist（包含 "*" 表示全放开）。也可按需设置 channels.telegram.allowFrom 或 channels.telegram.webhookUrl + channels.telegram.webhookSecret。

```json5
{
  channels: {
    telegram: {
      botToken: "123456:ABCDEF",
    },
  },
}
```

### [Slack](https://docs.openclaw.ai/channels/slack)

- 设置 SLACK_BOT_TOKEN + SLACK_APP_TOKEN（或 channels.slack.botToken + channels.slack.appToken）

### [Discord](https://docs.openclaw.ai/channels/discord)

- 设置 DISCORD_BOT_TOKEN 或 channels.discord.token（环境变量优先）
- 可选：按需设置 commands.native、commands.text、commands.useAccessGroups，以及 channels.discord.allowFrom、channels.discord.guilds、channels.discord.mediaMaxMb

```json5
{
  channels: {
    discord: {
      token: "1234abcd",
    },
  },
}
```

### [Signal](https://docs.openclaw.ai/channels/signal)

- 依赖 signal-cli，并需要 channels.signal 配置段

### [BlueBubbles（iMessage）](https://docs.openclaw.ai/channels/bluebubbles)

- **推荐** 的 iMessage 集成方式
- 配置 channels.bluebubbles.serverUrl + channels.bluebubbles.password，并配置 webhook（channels.bluebubbles.webhookPath）
- BlueBubbles 服务运行在 macOS；Gateway 可运行在 macOS 或其他机器

### [iMessage（legacy）](https://docs.openclaw.ai/channels/imessage)

- 旧版 macOS 专属集成，基于 imsg（Messages 需已登录）
- 若设置 channels.imessage.groups，则其即为群组 allowlist；包含 "*" 可放开所有

### [Microsoft Teams](https://docs.openclaw.ai/channels/msteams)

- 配置 Teams 应用 + Bot Framework，然后加入 msteams 配置段
- 通过 msteams.allowFrom 配置可对话对象；群组访问可通过 msteams.groupAllowFrom 或 msteams.groupPolicy: "open"

### [WebChat](https://docs.openclaw.ai/web/webchat)

- 走 Gateway WebSocket，不需要额外 WebChat 端口/配置

浏览器控制（可选）：

```json5
{
  browser: {
    enabled: true,
    color: "#FF4500",
  },
}
```

## 文档

当你已经完成引导流程并希望查看更深层参考资料时，建议从这些入口开始：

- [文档索引（导航与总览）](https://docs.openclaw.ai)
- [架构总览（gateway + 协议模型）](https://docs.openclaw.ai/concepts/architecture)
- [完整配置参考（全量键与示例）](https://docs.openclaw.ai/gateway/configuration)
- [Gateway 运行手册（运维）](https://docs.openclaw.ai/gateway)
- [Control UI/Web 暴露与安全](https://docs.openclaw.ai/web)
- [通过 SSH 隧道或 tailnet 的远程访问](https://docs.openclaw.ai/gateway/remote)
- [向导流程（引导式配置）](https://docs.openclaw.ai/start/wizard)
- [Webhook 外部触发](https://docs.openclaw.ai/automation/webhook)
- [Gmail Pub/Sub 触发](https://docs.openclaw.ai/automation/gmail-pubsub)
- [macOS 菜单栏应用细节](https://docs.openclaw.ai/platforms/mac/menu-bar)
- [平台指南：Windows (WSL2)](https://docs.openclaw.ai/platforms/windows)、[Linux](https://docs.openclaw.ai/platforms/linux)、[macOS](https://docs.openclaw.ai/platforms/macos)、[iOS](https://docs.openclaw.ai/platforms/ios)、[Android](https://docs.openclaw.ai/platforms/android)
- [常见故障排查](https://docs.openclaw.ai/channels/troubleshooting)
- [对外暴露前的安全指南](https://docs.openclaw.ai/gateway/security)

## 高级文档（发现与控制）

- [Discovery + transports](https://docs.openclaw.ai/gateway/discovery)
- [Bonjour/mDNS](https://docs.openclaw.ai/gateway/bonjour)
- [Gateway pairing](https://docs.openclaw.ai/gateway/pairing)
- [Remote gateway README](https://docs.openclaw.ai/gateway/remote-gateway-readme)
- [Control UI](https://docs.openclaw.ai/web/control-ui)
- [Dashboard](https://docs.openclaw.ai/web/dashboard)

## 运维与排障

- [Health checks](https://docs.openclaw.ai/gateway/health)
- [Gateway lock](https://docs.openclaw.ai/gateway/gateway-lock)
- [Background process](https://docs.openclaw.ai/gateway/background-process)
- [Browser troubleshooting (Linux)](https://docs.openclaw.ai/tools/browser-linux-troubleshooting)
- [Logging](https://docs.openclaw.ai/logging)

## 深入主题

- [Agent loop](https://docs.openclaw.ai/concepts/agent-loop)
- [Presence](https://docs.openclaw.ai/concepts/presence)
- [TypeBox schemas](https://docs.openclaw.ai/concepts/typebox)
- [RPC adapters](https://docs.openclaw.ai/reference/rpc)
- [Queue](https://docs.openclaw.ai/concepts/queue)

## 工作区与技能

- [Skills config](https://docs.openclaw.ai/tools/skills-config)
- [Default AGENTS](https://docs.openclaw.ai/reference/AGENTS.default)
- [Templates: AGENTS](https://docs.openclaw.ai/reference/templates/AGENTS)
- [Templates: BOOTSTRAP](https://docs.openclaw.ai/reference/templates/BOOTSTRAP)
- [Templates: IDENTITY](https://docs.openclaw.ai/reference/templates/IDENTITY)
- [Templates: SOUL](https://docs.openclaw.ai/reference/templates/SOUL)
- [Templates: TOOLS](https://docs.openclaw.ai/reference/templates/TOOLS)
- [Templates: USER](https://docs.openclaw.ai/reference/templates/USER)

## 平台内部文档

- [macOS dev setup](https://docs.openclaw.ai/platforms/mac/dev-setup)
- [macOS menu bar](https://docs.openclaw.ai/platforms/mac/menu-bar)
- [macOS voice wake](https://docs.openclaw.ai/platforms/mac/voicewake)
- [iOS node](https://docs.openclaw.ai/platforms/ios)
- [Android node](https://docs.openclaw.ai/platforms/android)
- [Windows (WSL2)](https://docs.openclaw.ai/platforms/windows)
- [Linux app](https://docs.openclaw.ai/platforms/linux)

## 邮件钩子（Gmail）

- [docs.openclaw.ai/gmail-pubsub](https://docs.openclaw.ai/automation/gmail-pubsub)

## Molty

OpenClaw 是为 **Molty**（一只太空龙虾 AI 助手）打造的。🦞
由 Peter Steinberger 与社区共同构建。

- [openclaw.ai](https://openclaw.ai)
- [soul.md](https://soul.md)
- [steipete.me](https://steipete.me)
- [@openclaw](https://x.com/openclaw)

## 社区

贡献规范、维护者信息、PR 提交流程见 [CONTRIBUTING.md](CONTRIBUTING.md)。
欢迎 AI/vibe-coded PR！

特别感谢 [Mario Zechner](https://mariozechner.at/) 的支持，以及 [pi-mono](https://github.com/badlogic/pi-mono)。
特别感谢 Adam Doppelt 对 lobster.bot 的贡献。