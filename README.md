# Werewolf Arena — OpenClaw Skill

> 通过 OpenClaw 聊天界面，智能参与狼人杀游戏。实时分析局势、自动决策、推送战报。

## 架构版本

本项目有两套架构，可按需切换：

| | V1（独立 Agent） | V2（Webhook Bridge）✨ |
|---|---|---|
| **推理引擎** | Python 进程独立调 Anthropic API | OpenClaw Agent 自身推理 |
| **通信方式** | 日志文件轮询 | Webhook POST 同步推送 |
| **策略定义** | `strategy_basic.py` + `prompts/*.txt` | `SKILL.md` 角色策略手册 |
| **状态管理** | `memory.py` GameMemory 类 | OpenClaw Session 自动积累 |
| **用户感知** | 被动查日志 | 聊天界面实时推送 |
| **API 成本** | 双重（OpenClaw + Anthropic） | 单一（仅 OpenClaw） |
| **代码量** | ~500 行 | ~150 行 |
| **依赖** | werewolf-sdk, anthropic, pyyaml | httpx, websockets |

---

## V2 快速开始

### 前置条件

1. **OpenClaw Gateway** 已运行且启用 Webhook
2. **Python 3.11+**
3. **Werewolf Arena 游戏服务器** 可访问

### Step 1: 安装依赖

```bash
pip install httpx websockets
```

### Step 2: 配置 OpenClaw Webhook

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

重启 Gateway 使配置生效：

```bash
openclaw gateway restart
```

### Step 3: 安装 Skill

将 `SKILL.md` 放置到 OpenClaw 技能目录：

```bash
# 默认 agent
mkdir -p ~/.openclaw/workspace/skills/werewolf-agent
cp SKILL.md ~/.openclaw/workspace/skills/werewolf-agent/
cp ws_bridge.py ~/.openclaw/workspace/skills/werewolf-agent/

# 或使用专属 agent（推荐）
mkdir -p ~/.openclaw/workspace-werewolf/skills/werewolf-agent
cp SKILL.md ~/.openclaw/workspace-werewolf/skills/werewolf-agent/
cp ws_bridge.py ~/.openclaw/workspace-werewolf/skills/werewolf-agent/
```

### Step 4: 通过对话启动

在 OpenClaw 聊天中：

```
你：帮我加入狼人杀，房间 abc123
Agent：好的，请提供你的 Werewolf Arena API Key...
你：sk-xxx
Agent：✅ Bridge 已启动，连接房间 abc123。游戏事件将自动推送到这里。
```

### 手动启动（可选）

```bash
python ws_bridge.py \
  --room-id abc123 \
  --game-api-key sk-xxx \
  --game-server localhost:8000 \
  --openclaw-gateway 127.0.0.1:18789 \
  --openclaw-hook-token <your-hook-token>
```

---

## V2 项目结构

```
werewolf-openclaw-skill/
├── SKILL.md              # 角色策略手册（推理框架 + 角色策略 + 响应格式）
├── ws_bridge.py          # Webhook Bridge（~150行，纯 I/O）
├── README.md             # 本文件
├── examples/
│   ├── start_bridge.sh   # V2 Bridge 启动脚本
│   └── start_agent.sh    # V1 Agent 启动脚本
│
│ ── V1 文件（保留，不再是主入口）──
├── werewolf_agent.py     # V1 Agent 主进程
├── strategy/             # V1 策略模块
├── memory.py             # V1 GameMemory
├── prompts/              # V1 Prompt 模板
├── logger.py             # V1 日志模块
├── config/               # V1 配置
└── docs/                 # 设计文档
```

---

## V2 架构说明

```
Werewolf Game Server
    │  WebSocket 长连接
    ▼
┌────────────────────────────────────┐
│  ws_bridge.py（~150 行，纯 I/O）    │
│  ├─ 维持 WebSocket 长连接           │
│  ├─ 格式化游戏事件为自然语言         │
│  ├─ POST /hooks/agent 推送到 Agent  │
│  ├─ 解析 Agent 回复中的 JSON 决策   │
│  ├─ 提交行动到游戏 REST API         │
│  └─ 超时降级（随机合法行动）         │
└────────────────┬───────────────────┘
                 │  HTTP POST
                 ▼
┌────────────────────────────────────┐
│  OpenClaw Gateway                  │
│  ├─ Webhook 接收事件               │
│  ├─ Agent 推理（读取 SKILL.md）     │
│  ├─ Session 自动积累上下文          │
│  ├─ 返回决策 JSON 给 ws_bridge     │
│  └─ 推送分析到用户聊天界面          │
└────────────────────────────────────┘
```

---

## V1 / V2 切换

### 使用 V2（推荐）

1. 确保 OpenClaw Webhook 已配置
2. 使用新版 `SKILL.md`（角色策略手册）
3. 启动 `ws_bridge.py`

### 回退到 V1

1. 恢复旧版 `SKILL.md`（进程管理指令版本，见 git 历史 `v0.1.0` tag）
2. 安装 V1 依赖：`pip install werewolf-sdk anthropic pyyaml`
3. 设置 `ANTHROPIC_API_KEY` 环境变量
4. 启动 `werewolf_agent.py`

```bash
# V1 启动
export ANTHROPIC_API_KEY=sk-xxx
python werewolf_agent.py --room-id abc123 --api-key sk-xxx
```

---

## 依赖变更

| 依赖 | V1 | V2 |
|------|:--:|:--:|
| `httpx` | — | ✅ |
| `websockets` | — | ✅ |
| `werewolf-sdk` | ✅ | — |
| `anthropic` | ✅ | — |
| `pyyaml` | ✅ | — |

```bash
# V2 安装
pip install httpx websockets

# V1 安装（如需回退）
pip install werewolf-sdk anthropic pyyaml
```

---

## 可选：注册专属 Agent

在 `~/.openclaw/openclaw.json` 中注册专属 werewolf agent：

```json5
{
  "agents": {
    "list": [
      {
        "id": "werewolf",
        "name": "Werewolf Strategist",
        "model": "anthropic/claude-sonnet-4-6",
        "workspace": "~/.openclaw/workspace-werewolf"
      }
    ]
  }
}
```

未注册时由默认 agent 处理，也能正常工作。

---

## 相关链接

- [V2 设计文档](docs/design/v2-design.md)
- [V1 设计文档](docs/design/v1-design.md)
- [Werewolf Arena 平台](https://github.com/slob-coder/werewolf-game)
- [OpenClaw](https://github.com/slob-coder/openclaw)

## License

MIT
