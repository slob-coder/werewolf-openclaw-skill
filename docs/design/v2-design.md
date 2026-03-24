# Werewolf OpenClaw Skill — V2 技术设计方案

> **版本**: v2.0 | **日期**: 2026-03-24 | **设计师**: Designer Agent
> **仓库**: https://github.com/slob-coder/werewolf-openclaw-skill
> **需求文档**: werewolf-openclaw-webhook-bridge-v3.md
> **V1 设计**: [docs/design/v1-design.md](docs/design/v1-design.md)（归档）

---

## 0. 版本说明

本文档是 V2 增量设计，描述从 V1（独立 Python Agent + 日志轮询）到 V2（Webhook Bridge）的架构重构。

### V1 → V2 核心变更总览

| 维度 | V1 | V2 | 变更性质 |
|------|----|----|---------|
| **Python 进程角色** | 智能 Agent（含策略引擎 + LLM 调用 + 状态管理） | 无状态 I/O 桥接器 | **重写** |
| **LLM 推理** | Python 进程独立调 Anthropic API | OpenClaw Agent 自身推理 | **删除** |
| **通信方式** | `tail -50 \| grep "[EVENT]"` 日志轮询 | `POST /hooks/agent` Webhook 同步推送 | **替换** |
| **策略定义** | `strategy_basic.py` + `strategy_llm.py` + `prompts/*.txt` | `SKILL.md` 角色策略手册 | **迁移** |
| **状态管理** | `memory.py` GameMemory 类 + 文件归档 | OpenClaw Session JSONL 自动积累 | **删除** |
| **用户交互** | 只能通过 `tail` 日志被动查询 | 聊天界面实时推送（`deliver: true`） | **新增** |
| **API 成本** | 双重（OpenClaw + Agent 独立 Anthropic） | 单一（仅 OpenClaw） | **减半** |
| **代码量** | ~500 行（agent + strategy + memory + prompts） | ~150 行（ws_bridge.py） | **-70%** |

### V2 不变部分

- WebSocket 连接游戏服务器的方式不变
- 断线重连策略不变（5 次递增间隔）
- 行动提交到游戏 REST API 的方式不变
- 超时降级的理念不变（保证任何情况下不卡死）

---

## 1. 架构设计

### 1.1 V2 整体架构

```
Werewolf Game Server
    │  WebSocket 长连接
    ▼
┌──────────────────────────────────────┐
│  ws_bridge.py（~150 行，纯 I/O）      │
│  ├─ 维持 WebSocket 长连接             │
│  ├─ 收到游戏事件 → 格式化为自然语言     │
│  ├─ POST /hooks/agent（同步等待响应）   │
│  ├─ 解析响应中的 JSON 决策块           │
│  ├─ 提交行动到游戏服务器 REST API       │
│  └─ 内置超时降级（deadline 前 10s 无响应 → 随机合法行动）│
└──────────────────────┬───────────────┘
                       │  HTTP POST
                       ▼
┌──────────────────────────────────────┐
│  OpenClaw Gateway                    │
│  ├─ Webhook 端点接收游戏事件          │
│  ├─ 路由到 werewolf agent session     │
│  ├─ Agent Runtime 执行推理           │
│  ├─ Session 自动积累完整游戏上下文     │
│  ├─ 返回决策 JSON 给 ws_bridge        │
│  └─ deliver:true → 推送分析到用户聊天  │
└──────────────────────────────────────┘
                       │
                       ▼
              用户聊天界面（WebChat / Telegram / ...）
              ├─ 实时收到局势分析和行动报告
              └─ 可通过聊天直接与 Agent 对话
```

**与 V1 架构对比**：

V1 中 `werewolf_agent.py` 是智能核心（含策略引擎、LLM 客户端、状态管理），OpenClaw 仅做进程管理和日志查询。V2 完全反转——OpenClaw Agent 是智能核心，Python 进程退化为纯 I/O 桥接。

### 1.2 职责分工变更

| 组件 | V1 职责 | V2 职责 | 变更 |
|------|---------|---------|------|
| `SKILL.md` | 触发词、参数收集、bash 进程管理指令 | 完整角色策略手册 + 推理框架 + 响应格式约束 | **重写** |
| `ws_bridge.py`（新） | — | WebSocket↔Webhook 桥接、事件格式化、响应解析、超时降级 | **新增** |
| `werewolf_agent.py` | 事件处理、策略调用、LLM 调用、行动提交 | 保留但不再是主入口 | **弃用** |
| `strategy/` | 规则策略 + LLM 策略 | 保留但不再使用 | **弃用** |
| `memory.py` | GameMemory 进程内状态管理 | 由 OpenClaw Session 替代 | **弃用** |
| `prompts/` | LLM 调用的 prompt 模板 | 由 SKILL.md 内嵌策略替代 | **弃用** |
| OpenClaw Agent | 仅进程管理 | 推理决策核心（接收事件 → 分析 → 生成决策和发言） | **升级** |
| OpenClaw Session | 不使用 | 自动积累全局游戏上下文，替代 GameMemory | **新增** |

### 1.3 关键设计决策

| 决策点 | V1 | V2 | 理由 |
|--------|----|----|------|
| 通信方式 | 日志文件轮询 | Webhook POST /hooks/agent | 同步、可靠、无延迟 |
| 推理引擎 | Python 进程独立调 Anthropic API | OpenClaw Agent 自身 | 避免双重 LLM 调用；session 上下文自动积累 |
| 状态管理 | 进程内 GameMemory + 文件归档 | OpenClaw Session JSONL 持久化 | 零代码维护；上下文自动保留 |
| 超时降级 | LLM 超时 → 规则策略降级 | ws_bridge 内置极简规则引擎 | 不依赖 OpenClaw 可用性 |
| 用户感知 | 被动查日志 | `deliver: true` 自动推送 | 零延迟实时感知 |
| 响应格式 | LLM 返回结构化 JSON | 自然语言分析 + 尾部 JSON 决策块 | Agent 展示推理过程，bridge 机器解析决策 |

---

## 2. 文件结构变更

### 2.1 V2 目标目录结构

```
~/.openclaw/shared/projects/werewolf-openclaw-skill/repo/
├── SKILL.md                  # [重写] 角色策略手册（替代 strategy + prompts）
├── ws_bridge.py              # [新增] Webhook Bridge（~150行）
├── README.md                 # [更新] 快速开始文档
├── examples/
│   └── start_bridge.sh       # [新增] Bridge 启动示例（替代 start_agent.sh）
│
│ ── V1 文件（保留，不再是主入口）──
├── werewolf_agent.py         # [保留] V1 Agent 主进程
├── strategy/                 # [保留] V1 策略模块
│   ├── __init__.py
│   ├── base.py
│   ├── basic.py
│   └── validator.py
├── memory.py                 # [保留] V1 GameMemory
├── logger.py                 # [保留] V1 日志模块
├── prompts/                  # [保留] V1 Prompt 模板
│   ├── speech.txt
│   ├── reasoning.txt
│   └── decision.txt
├── config/
│   └── default.yaml          # [保留] V1 配置
└── docs/
    └── design/
        ├── v1-design.md      # [归档] V1 设计文档
        └── v2-design.md      # [新增] V2 设计文档（本文件）
```

### 2.2 V2 P0 交付文件清单

| 文件 | 状态 | 说明 | 预估行数 |
|------|------|------|---------|
| `SKILL.md` | 重写 | 角色策略手册 + 推理框架 + 响应格式约束 | ~300 |
| `ws_bridge.py` | 新增 | Webhook Bridge 核心 | ~150 |
| `README.md` | 更新 | V2 快速开始文档 | ~100 |
| `examples/start_bridge.sh` | 新增 | Bridge 启动脚本 | ~30 |

---

## 3. ws_bridge.py 详细设计

### 3.1 模块职责

ws_bridge.py 是一个**无状态 I/O 桥接器**，做且只做三件事：

1. **维持 WebSocket 长连接**：连接游戏服务器，接收游戏事件
2. **转发事件到 OpenClaw**：格式化为自然语言，POST /hooks/agent，同步等待响应
3. **提取决策并提交**：从 Agent 回复中解析 JSON 决策，提交行动到游戏 REST API

**不做**：不调用 LLM、不做推理、不生成发言、不管理游戏状态。

### 3.2 启动参数

```
python ws_bridge.py \
  --room-id <room_id>                          # 必填：房间 ID
  --game-api-key <key>                         # 必填：Werewolf Arena API Key
  --game-server <host:port>                    # 可选，默认 localhost:8000
  --openclaw-gateway <host:port>               # 可选，默认 127.0.0.1:18789
  --openclaw-hook-token <token>                # 必填：Gateway hook token
  --openclaw-agent-id <agent_id>               # 可选，默认不指定
  --timeout-buffer <seconds>                   # 可选，默认 10
```

### 3.3 最小状态（BridgeContext）

虽然 ws_bridge 是"无智能"的，但需要维护少量状态用于降级和事件格式化：

```python
@dataclass
class BridgeContext:
    room_id: str
    my_seat: int = 0
    my_role: str = ""
    alive_players: list[int] = field(default_factory=list)
    dead_players: list[int] = field(default_factory=list)
    teammates: list[int] = field(default_factory=list)      # 仅狼人
    checked_players: list[int] = field(default_factory=list) # 仅预言家
    last_guarded: int | None = None                          # 仅守卫
    current_round: int = 0
```

这些字段从游戏事件中被动更新，不做任何推理。

**与 V1 GameMemory 对比**：V1 GameMemory 有 ~200 行代码、15+ 个字段、主动推理（身份概率估计）、文件归档等功能。V2 BridgeContext 仅 ~10 行，纯被动记录。

### 3.4 事件格式化规范

ws_bridge 将游戏事件格式化为结构化自然语言，以 `[GAME_EVENT]` 前缀开头，包含事件类型、所有相关数据、需要什么行动及 deadline。

**事件类型及格式化**：

| 事件类型 | 需要决策 | 格式化要点 |
|---------|---------|-----------|
| `game.start` | 否 | 角色、座位、玩家列表、队友（狼人） |
| `phase.night` | 是 | 轮次、角色、存活/死亡、可执行行动、deadline |
| `phase.day.speech` | 是 | 轮次、已有发言、存活玩家、deadline |
| `phase.day.vote` | 是 | 轮次、发言回顾、历史投票、deadline |
| `werewolf.chat` | 否 | 队友消息内容 |
| `night.result` | 否 | 行动结果（查验结果等）、死亡信息 |
| `player.death` | 否 | 死亡玩家、原因 |
| `game.end` | 否 | 获胜阵营、最终身份揭示 |

每条需要决策的事件末尾附加 JSON 响应格式要求：

```
请分析当前局势，然后在回复的最后一行输出你的决策，格式：
```json
{"action": "<type>", "target": <number>}
```
```

### 3.5 Webhook 调用规范

```python
GATEWAY_URL = f"http://{args.openclaw_gateway}/hooks/agent"
SESSION_KEY = f"hook:werewolf:{args.room_id}"

async def send_to_openclaw(message: str, need_response: bool = True) -> str | None:
    payload = {
        "message": message,
        "name": "Werewolf",
        "sessionKey": SESSION_KEY,
        "deliver": True,
        "channel": "last",
    }
    if args.openclaw_agent_id:
        payload["agentId"] = args.openclaw_agent_id
    if need_response:
        payload["timeoutSeconds"] = calculate_timeout(event_deadline)
    else:
        payload["timeoutSeconds"] = 0

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {args.openclaw_hook_token}"
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            GATEWAY_URL, json=payload, headers=headers,
            timeout=event_deadline + 10
        )
        data = resp.json()

    if need_response:
        if data.get("status") == "ok":
            return data.get("reply", "")
        return None  # 触发降级
    return None
```

**关键设计点**：

- `sessionKey = hook:werewolf:{room_id}`：同一局游戏的所有事件汇聚到同一 session
- `deliver: True`：Agent 分析自动推送到用户聊天界面
- `timeoutSeconds = deadline - buffer`：留出降级操作时间
- HTTP 超时 = `deadline + 10s`：兜底防 httpx 永久阻塞

### 3.6 响应解析

Agent 回复格式为自然语言分析 + 尾部 JSON 决策块：

```python
def extract_decision(reply: str) -> dict | None:
    # 优先匹配 ```json ... ``` 代码块
    code_blocks = re.findall(r'```json\s*\n?(.*?)\n?\s*```', reply, re.DOTALL)
    if code_blocks:
        try:
            return json.loads(code_blocks[-1].strip())
        except json.JSONDecodeError:
            pass
    # 降级：匹配最后一个 {...} 块
    json_blocks = re.findall(r'\{[^{}]+\}', reply)
    if json_blocks:
        try:
            return json.loads(json_blocks[-1])
        except json.JSONDecodeError:
            pass
    return None
```

双重解析策略确保健壮性。解析失败则触发降级。

### 3.7 超时降级策略

**与 V1 对比**：V1 降级由 `strategy_basic.py` BasicStrategy 实现（~200 行），包含角色特定逻辑。V2 降级在 ws_bridge 内置，纯规则驱动、零智能（~50 行）：

```python
def fallback_action(event_type: str, role: str, context: BridgeContext) -> dict:
    alive = context.alive_players
    if event_type == "night":
        if role == "werewolf":
            candidates = [p for p in alive if p not in context.teammates]
            return {"action": "kill", "target": random.choice(candidates)}
        elif role == "seer":
            candidates = [p for p in alive
                          if p not in context.checked_players
                          and p != context.my_seat]
            return {"action": "check", "target": random.choice(candidates or alive)}
        elif role == "witch":
            return {"action": "pass"}
        elif role == "guard":
            candidates = [p for p in alive if p != context.last_guarded]
            return {"action": "guard", "target": random.choice(candidates)}
        return {"action": "pass"}
    elif event_type == "vote":
        candidates = [p for p in alive if p != context.my_seat]
        return {"action": "vote", "target": random.choice(candidates)}
    elif event_type == "speech":
        return {"action": "speech", "content": "我还在观察，暂时没有更多信息分享。"}
    return {"action": "pass"}
```

### 3.8 断线重连

与 V1 逻辑一致：最多 5 次，间隔递增（5s → 10s → 15s → 20s → 25s），失败后通知 OpenClaw 并退出。

### 3.9 进程生命周期

```
启动 → 连接游戏 WebSocket → 加入房间 → 事件循环
  │
  ├─ game.start      → 更新 context → POST webhook (fire-and-forget)
  ├─ phase.night     → POST webhook (同步) → 解析决策 → 提交行动
  ├─ phase.day.speech → POST webhook (同步) → 解析发言 → 提交发言
  ├─ phase.day.vote  → POST webhook (同步) → 解析投票 → 提交投票
  ├─ werewolf.chat   → POST webhook (fire-and-forget)
  ├─ night.result    → 更新 context → POST webhook (fire-and-forget)
  ├─ player.death    → 更新 context → POST webhook (fire-and-forget)
  ├─ game.end        → POST webhook (fire-and-forget) → 退出
  └─ 连接断开        → 重连循环（最多5次）→ 失败则退出
```

---

## 4. SKILL.md 详细设计

### 4.1 设计原则变更

| 维度 | V1 SKILL.md | V2 SKILL.md |
|------|-------------|-------------|
| 核心定位 | 进程管理指令集 | 完整角色策略手册 |
| 内容 | bash 启动/停止/查日志命令 | 推理框架、角色策略、发言指南、响应格式 |
| 替代组件 | 无（仅做进程管理） | `strategy_*.py` + `prompts/*.txt` + `memory.py` |
| 行数 | ~100 行 | ~300 行 |

### 4.2 V2 SKILL.md 结构

**Section 1: 触发与识别**
- 何时激活：消息以 `[GAME_EVENT]` 开头
- 何时引导启动：用户说"帮我加入狼人杀"

**Section 2: 响应格式约束（关键）**
- 回复 = 自然语言分析（给用户看）+ 尾部 JSON 决策块（给 ws_bridge 解析）
- JSON 格式：`{"action": "<type>", "target": <number>}` 或 `{"action": "speech", "content": "<text>"}`
- 通知型事件（game.start / werewolf.chat / game.end）不需要 JSON

**Section 3: 角色策略指南**（替代 V1 `strategy_basic.py` + `strategy_llm.py`）

| 角色 | 夜晚策略 | 白天策略 |
|------|---------|---------|
| 狼人 | 优先击杀神职；避开守卫保护目标；参考队友夜聊 | 伪装好人发言；跟随投票节奏 |
| 预言家 | 优先查验发言疑点玩家；已查验不重复 | 适时跳预言家；报验人 |
| 女巫 | 解药优先救神职；毒药仅毒高置信度狼人 | 可选明/暗女巫 |
| 猎人 | 仅高置信度开枪；中毒不能开枪 | 不暴露身份 |
| 守卫 | 不连续守同一人；守高价值目标 | 不暴露身份 |
| 村民 | 无行动 | 逻辑分析贡献信息 |
| 白痴 | 无行动 | 被投出翻牌可发言不可投票 |

**Section 4: 推理框架**（替代 V1 `prompts/reasoning.txt` + `prompts/decision.txt`）

指导 Agent 在每次决策前执行四步结构化推理：
1. **信息汇总**：回顾 session 中的关键事件
2. **身份推断**：对每个存活玩家评估身份倾向
3. **决策推导**：根据角色职责选择行动
4. **发言策略**：决定信息披露程度

**Section 5: 发言生成指南**（替代 V1 `prompts/speech.txt`）
- 角色扮演约束：不透露不可能知道的信息
- 狼人伪装：好人视角构造发言
- 长度控制：2-5 句话
- 不暴露系统信息

**Section 6: 跨轮上下文利用**（替代 V1 `memory.py` 的历史查询功能）
- 引用前轮发言支持推理
- 跟踪投票模式识别可疑行为
- 记住死亡揭示带来的信息增量

**Section 7: 启动引导**
- 收集参数 → 通过 bash 工具启动 ws_bridge

### 4.3 V1 → V2 Prompt 迁移映射

| V1 文件 | V2 SKILL.md Section | 迁移说明 |
|---------|---------------------|---------|
| `prompts/speech.txt` | Section 5: 发言生成指南 | 从独立 prompt 文件迁移为 SKILL.md 内嵌指引 |
| `prompts/reasoning.txt` | Section 4: 推理框架 | 四步推理框架替代原始 prompt |
| `prompts/decision.txt` | Section 4: 推理框架 | 合并到推理框架中 |
| `strategy_basic.py` 角色逻辑 | Section 3: 角色策略指南 | 从代码逻辑转为自然语言策略描述 |
| `strategy_llm.py` prompt 构建 | Section 2-5 | 不再需要，Agent 自身即 LLM |

---

## 5. OpenClaw 配置

### 5.1 Gateway Webhook 配置

V1 不需要 Webhook 配置。V2 需要在 `~/.openclaw/openclaw.json` 中添加：

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

### 5.2 Werewolf Agent 注册（可选）

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

未注册时由默认 agent 处理。

### 5.3 V1 配置对比

| 配置项 | V1 | V2 |
|--------|----|----|
| `ANTHROPIC_API_KEY` | 必须（Agent 独立调 API） | 不需要（OpenClaw 统一管理） |
| `config/default.yaml` | Agent 进程配置 | 不需要 |
| Gateway Webhook | 不需要 | 必须启用 |
| Agent 注册 | 不需要 | 推荐 |

---

## 6. 数据流详解

### 6.1 典型决策流程（预言家夜晚查验）

```
T+0s     Game Server     →  发送 phase.night（deadline: 60s）
T+0.1s   ws_bridge       →  收到事件，格式化为自然语言
T+0.2s   ws_bridge       →  POST /hooks/agent，timeoutSeconds=50
T+0.3s   OpenClaw GW     →  路由到 werewolf agent session
T+0.5s   OpenClaw Agent  →  开始推理（session 含前几轮完整历史）
T+8s     OpenClaw Agent  →  返回分析 + JSON 决策
T+8.1s   OpenClaw GW     →  ① 返回 reply 给 ws_bridge
                             ② deliver → 推送到用户 Telegram
T+8.2s   ws_bridge       →  extract_decision() 解析 JSON
T+8.3s   ws_bridge       →  POST 行动到 Game Server REST API
T+8.5s   用户 Telegram   →  收到："🔮 分析...决定查验3号"
```

**总耗时**: ~8s（远在 60s deadline 内）

### 6.2 超时降级流程

```
T+0s     Game Server     →  发送 phase.night（deadline: 60s）
T+0.2s   ws_bridge       →  POST /hooks/agent，timeoutSeconds=50
T+50s    OpenClaw GW     →  返回 {"status": "timeout"}
T+50.1s  ws_bridge       →  触发 fallback_action()
T+50.2s  ws_bridge       →  提交随机合法行动
T+50.3s  ws_bridge       →  POST webhook 通知超时降级
```

### 6.3 Session 上下文自动积累

**替代 V1 GameMemory**：V1 中 GameMemory 需要手动维护 15+ 个字段和归档逻辑。V2 中 OpenClaw Session 自动保留所有 webhook 交互历史：

```
[Session: hook:werewolf:room-abc123]

Turn 1: [GAME_EVENT] game.start | 角色=预言家 | 9人局
→ Agent: 收到，我是预言家。

Turn 2: [GAME_EVENT] phase.night 第1轮 | 需要查验
→ Agent: 分析... → {"action": "check", "target": 5}

Turn 3: [GAME_EVENT] night.result | 5号=好人 | 昨夜死亡: 7号
→ Agent: 记录。5号好人，7号死亡。

Turn 4: [GAME_EVENT] phase.day.speech 第1轮 | 已有发言...
→ Agent: ... → {"action": "speech", "content": "..."}

...后续轮次持续积累，Agent 天然拥有完整上下文
```

---

## 7. 启动流程变更

### 7.1 V1 启动流程

```
用户: "帮我加入房间 abc123"
→ SKILL.md 识别意图
→ 收集参数（room_id, api_key, server_url, strategy, speech_style）
→ bash: python werewolf_agent.py --room-id abc123 ... &
→ bash: echo $! > werewolf-agent.pid
→ 返回: "✓ 已启动 Agent"
```

### 7.2 V2 启动流程

```
用户: "帮我加入狼人杀"
→ SKILL.md Section 7 引导
→ 收集参数（room_id, game_api_key）
→ bash: python ws_bridge.py --room-id abc123 --game-api-key xxx \
        --openclaw-hook-token $HOOK_TOKEN &
→ 返回: "✓ Bridge 已启动，游戏事件将自动推送到这里"
```

**差异**：
- 参数更少（去掉 strategy、speech_style、model 等——这些由 SKILL.md 内嵌策略控制）
- 新增 `--openclaw-hook-token`
- 不再需要 ANTHROPIC_API_KEY 环境变量

---

## 8. 约束条件

### 8.1 时间约束（与 V1 一致）

| 约束 | 值 |
|------|-----|
| 夜晚行动总 deadline | 60s |
| 白天发言总 deadline | 90s |
| 投票总 deadline | 60s |
| Webhook timeoutSeconds | deadline − 10s |
| ws_bridge HTTP 超时 | deadline + 10s |
| OpenClaw Agent 推理耗时 | 预期 5-20s |

### 8.2 信息隔离约束（与 V1 一致）

- Agent 只能基于 webhook 传入的信息推理
- 狼人夜聊通过 `werewolf.chat` 事件注入 session
- ws_bridge 不注入 Agent 不应知道的信息

### 8.3 Session 管理约束（V2 新增）

- 单局固定 sessionKey：`hook:werewolf:{room_id}`
- 多房间并行：独立 sessionKey + 独立 ws_bridge 进程
- 游戏结束后 session 保留，用户可通过 `/new` 重置
- 标准 9 人局（6-8 轮）约 20-30 个 webhook turn，通常不超出 context window

---

## 9. 迁移策略

### 9.1 V1 → V2 迁移路径

V1 和 V2 可以**并存**。V1 文件保留在仓库中不删除，V2 文件独立新增。切换方式：

- **使用 V2**：启动 `ws_bridge.py`，使用新版 SKILL.md
- **回退 V1**：启动 `werewolf_agent.py`，恢复旧版 SKILL.md

### 9.2 SKILL.md 安装位置

- 默认 agent：`~/.openclaw/workspace/skills/werewolf-agent/SKILL.md`
- 专属 agent：`~/.openclaw/workspace-werewolf/skills/werewolf-agent/SKILL.md`

ws_bridge.py 和其他文件放在 repo 中，SKILL.md 复制/链接到上述位置。

### 9.3 V1 文件处理

| V1 文件 | 处理方式 | 原因 |
|---------|---------|------|
| `werewolf_agent.py` | 保留，标记弃用 | 回退备用 |
| `strategy/` | 保留，标记弃用 | 回退备用 |
| `memory.py` | 保留，标记弃用 | 回退备用 |
| `prompts/` | 保留，标记弃用 | 回退备用 |
| `config/default.yaml` | 保留 | V1 配置参考 |
| `logger.py` | 保留 | ws_bridge 可选复用日志格式 |
| `examples/start_agent.sh` | 保留 | V1 启动参考 |

---

## 10. 分阶段交付计划

### 10.1 P0 — 最小可行版本

**目标**: 跑通一局完整游戏，验证 Webhook Bridge 架构可行性。

**交付物**:

| 文件 | 类型 | 工作量 |
|------|------|--------|
| `ws_bridge.py` | 新增 | M（核心文件） |
| `SKILL.md` | 重写 | M（角色策略手册） |
| `README.md` | 更新 | S |
| `examples/start_bridge.sh` | 新增 | XS |

**验收标准**:

1. ws_bridge.py 成功连接游戏 WebSocket 并加入房间
2. 游戏事件通过 webhook 推送到 OpenClaw Agent
3. Agent 在 session 上下文中完成推理，返回有效 JSON 决策
4. ws_bridge 成功提取决策并提交行动
5. 用户聊天界面实时收到分析推送
6. Agent 完成角色认知、夜晚行动、白天发言、投票全流程
7. 超时降级正常工作
8. 游戏结束后 Agent 输出复盘总结
9. 断线重连在 120s 窗口内成功

**总工作量估算**: M（3-5 天）

### 10.2 P1 — 推理增强与用户协作

**目标**: 提升推理质量，开放用户干预能力。

**修改交付物**:
- `SKILL.md`：增强推理框架，加入身份概率估计指引
- `ws_bridge.py`：非紧急阶段增加"等待用户输入"窗口（可选）

**用户协作 Session 对齐方案**（P1 待定）：
- 方案 a: 用户 slash command 切入 werewolf session
- 方案 b: Agent 使用 `sessions_history` 读取用户消息（推荐，侵入性最低）
- 方案 c: 暂不实现双向协作，仅单向推送

### 10.3 P2 — 跨局学习（可选）

**目标**: 利用 OpenClaw Memory 积累元策略。

- 游戏结束后 Agent 自动提炼洞察写入 `memory/werewolf/insight-YYYY-MM-DD.md`
- 下一局读取历史洞察辅助决策
- 策略风格可配置（aggressive / conservative / silent）

---

## 11. Subtask 拆分分析

### 11.1 是否需要拆分

**建议：拆分为 2 个独立 subtask**。

理由：
1. `ws_bridge.py` 和 `SKILL.md` 是完全独立的模块——前者是 Python I/O 代码，后者是纯 Markdown 策略文档
2. 两者可以并行开发，互不阻塞
3. 各自有独立的验收标准和测试方式

### 11.2 Subtask 划分

| Subtask | 内容 | 交付物 | 依赖 |
|---------|------|--------|------|
| **subtask-1: ws_bridge** | Webhook Bridge 核心开发 | `ws_bridge.py` + `examples/start_bridge.sh` | 无 |
| **subtask-2: skill-md** | SKILL.md 角色策略手册编写 + README 更新 | `SKILL.md` + `README.md` | 无 |

两个 subtask 无依赖关系，可并行。集成测试在两者完成后进行。

---

## 12. 风险与缓解

| 风险 | V1 是否存在 | V2 缓解 |
|------|------------|---------|
| OpenClaw Gateway 不可用 | 不存在（V1 不依赖 Gateway 推理） | ws_bridge 内置降级策略 |
| Webhook 响应延迟高 | 不存在 | 使用 Sonnet 模型；SKILL.md 控制回复长度 |
| Session 上下文溢出 | 不存在（GameMemory 手动截断） | OpenClaw 内置 pruning；SKILL.md 引导阶段性总结 |
| JSON 解析失败 | 类似（LLM 输出解析） | 双重解析 + 降级 |
| WebSocket 断线 | 存在 | 5 次重连（与 V1 一致） |
| werewolf-game 后端未完成 | 存在 | 开发前跑通 examples/ |
| deliver 推送过频 | 不存在 | 通知型事件可选不 deliver |

---

## 13. Design Review 建议

**建议进行 design review**。理由：

1. 这是架构级重构（从独立 Agent 到 Webhook Bridge），不是功能迭代
2. OpenClaw Webhook API 的使用方式需要验证（sessionKey、deliver、timeoutSeconds 等参数行为）
3. SKILL.md 从进程管理指令重写为策略手册，角色完全不同
4. V1 → V2 迁移策略需要确认

**Review 重点**：
- Webhook API 参数和行为是否符合 OpenClaw 实际实现
- Session 上下文积累在长游戏中的表现
- SKILL.md 策略手册对 Agent 推理质量的影响
- 超时降级覆盖是否完整

---

## 附录 A: V2 依赖变更

| 依赖 | V1 | V2 |
|------|----|----|
| `werewolf-sdk` | 必须 | 不需要（ws_bridge 直接用 websockets） |
| `anthropic` | 必须 | 不需要 |
| `pyyaml` | 必须 | 不需要 |
| `httpx` | 不需要 | 必须（Webhook POST） |
| `websockets` | 不需要 | 必须（游戏 WebSocket） |

安装命令从 `pip install werewolf-sdk anthropic pyyaml` 变为 `pip install httpx websockets`。

## 附录 B: 完整文件映射（V1 → V2）

| V1 文件 | V2 处理 |
|---------|---------|
| `werewolf_agent.py` (~300行) | → `ws_bridge.py` (~150行)，去掉策略和 LLM |
| `strategy/basic.py` | → SKILL.md Section 3 |
| `strategy/llm.py` | → 不需要，Agent 自身即 LLM |
| `strategy/base.py` | → 不需要 |
| `strategy/validator.py` | → ws_bridge fallback_action() 内联 |
| `memory.py` | → OpenClaw Session 自动管理 |
| `prompts/speech.txt` | → SKILL.md Section 5 |
| `prompts/reasoning.txt` | → SKILL.md Section 4 |
| `prompts/decision.txt` | → SKILL.md Section 4 |
| `logger.py` | → ws_bridge 可选复用 |
| `config/default.yaml` | → 不需要（参数通过 CLI 传入） |
