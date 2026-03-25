# Werewolf Arena — OpenClaw Skill

> 通过 OpenClaw 聊天界面，智能参与狼人杀游戏。实时分析局势、自动决策、推送战报。

## 架构（V3）

```
Werewolf Game Server
    │  Socket.IO (SDK)
    ▼
┌─────────────────────────────┐
│  bridge.py                  │
│  继承 WerewolfAgent (SDK)    │
│  接收事件 → Webhook 转发     │
└─────────────┬───────────────┘
              │  HTTP POST
              ▼
┌─────────────────────────────┐
│  OpenClaw Agent             │
│  ├─ SKILL.md 策略推理        │
│  └─ 调用 werewolf_cli.py    │
│     执行行动 (基于 SDK)       │
└─────────────────────────────┘
```

**核心设计**:
- **bridge.py** — 继承官方 SDK `WerewolfAgent`，自动处理 Socket.IO 连接、认证、重连
- **werewolf_cli.py** — 业务命令脚本，封装 SDK Action 提交，屏蔽协议细节
- **SKILL.md** — 纯策略手册，不含 JSON/API 格式，通过调用 CLI 脚本执行行动

## 快速开始

### 前置条件

1. **Python 3.11+**
2. **OpenClaw Gateway** 已运行且启用 Webhook
3. **Werewolf Arena 游戏服务器** 可访问

### 安装

```bash
pip install -r requirements.txt
```

### 配置 OpenClaw Webhook

在 `~/.openclaw/openclaw.json` 中添加：

```json5
{
  "hooks": {
    "enabled": true,
    "token": "<生成一个强随机 token>",
    "allowRequestSessionKey": true,
    "allowedSessionKeyPrefixes": ["hook:werewolf:"]
  }
}
```

### 安装 Skill

```bash
# 复制到 OpenClaw skills 目录
mkdir -p ~/.openclaw/workspace/skills/werewolf-agent
cp SKILL.md werewolf_cli.py ~/.openclaw/workspace/skills/werewolf-agent/
```

### 启动

```bash
python bridge.py \
  --room-id <房间ID> \
  --api-key <你的API Key> \
  --server http://localhost:8000 \
  --openclaw-gateway 127.0.0.1:18789 \
  --openclaw-hook-token <webhook token>
```

或通过 OpenClaw 聊天启动：
```
你: 帮我加入狼人杀，房间 abc123
```

## 项目结构

```
werewolf-openclaw-skill/
├── bridge.py             # 事件桥接器（继承 SDK WerewolfAgent）
├── werewolf_cli.py       # 业务命令脚本（kill/check/vote/speech 等）
├── SKILL.md              # 角色策略手册（纯策略，无 JSON）
├── requirements.txt      # Python 依赖
├── README.md             # 本文件
├── docs/
│   └── v3-requirements.md
│
│ ── 归档（V1/V2，不再使用）──
├── _archive/
│   ├── ws_bridge.py
│   ├── werewolf_agent.py
│   ├── strategy/
│   ├── memory.py
│   ├── prompts/
│   ├── logger.py
│   └── config/
└── docs/
    └── design/
```

## CLI 命令参考

```bash
python werewolf_cli.py kill --target 5        # 狼人击杀
python werewolf_cli.py check --target 3       # 预言家查验
python werewolf_cli.py guard --target 2       # 守卫守护
python werewolf_cli.py save                   # 女巫救人
python werewolf_cli.py poison --target 7      # 女巫毒杀
python werewolf_cli.py skip                   # 跳过（女巫/猎人）
python werewolf_cli.py shoot --target 4       # 猎人开枪
python werewolf_cli.py speech --content "..." # 发言
python werewolf_cli.py vote --target 3        # 投票
python werewolf_cli.py vote --abstain         # 弃票
python werewolf_cli.py status                 # 查看状态
python werewolf_cli.py alive                  # 查看存活玩家
```

## 相关链接

- [V3 需求文档](docs/v3-requirements.md)
- [Werewolf Arena 平台](https://github.com/slob-coder/werewolf-game)
- [OpenClaw](https://github.com/slob-coder/openclaw)

## License

MIT
