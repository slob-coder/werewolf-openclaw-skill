# Werewolf OpenClaw Skill — V3 需求文档

> **版本**: v0.1 | **日期**: 2026-03-25
> **来源**: werewolf-game ↔ werewolf-openclaw-skill 兼容性分析
> **关联仓库**:
> - 服务端: https://github.com/slob-coder/werewolf-game
> - Skill: https://github.com/slob-coder/werewolf-openclaw-skill

---

## 1. 背景

对 `werewolf-openclaw-skill`（V2 ws_bridge 架构）与 `werewolf-game` 服务端进行兼容性分析后，发现当前实现存在 4 个致命问题和 4 个严重问题，**无法与服务端建立有效通信**。

核心问题归为两类：

**通信层问题** — 协议、认证、路径、字段名全部不匹配。服务端提供了官方 Python SDK（`werewolf_arena`），已正确封装了 Socket.IO 连接、REST 认证、Action 字段映射等所有通信细节。采用 SDK 可一次性消除全部通信层问题。

**职责边界问题** — 当前 SKILL.md 直接指导 Agent 组装 JSON 决策块（如 `{"action": "kill", "target": 5}`），由 ws_bridge 解析后转发给服务端。这导致：协议细节（字段名、枚举值、弃票语义等）泄漏到 Prompt 层；SKILL.md 与服务端 API 强耦合，服务端任何格式变更都需要同步修改 Prompt；Agent 拼 JSON 容易出格式错误触发降级。正确做法是 **SKILL.md 只负责策略推理，通过调用业务脚本来执行行动**，业务脚本基于 SDK 封装，屏蔽一切协议细节。

---

## 2. 设计原则

### 2.1 基于官方 SDK 构建通信层

废弃当前 ws_bridge.py 中自行实现的 WebSocket 连接、REST 调用和认证逻辑，改为继承 `werewolf_arena.WerewolfAgent`。SDK 已正确处理：

- Socket.IO 协议（`python-socketio` AsyncClient，`/agent` namespace）
- REST 认证（`X-Agent-Key` header）
- API 路径（`/api/v1/games/{game_id}/action`）
- Action 字段映射（`target` → `target_seat`）
- game_id 生命周期管理（从 `game.sync` 自动获取）
- 断线重连（内置 reconnection 策略）

### 2.2 SKILL.md 不组装协议数据，通过业务脚本交互

**当前（错误）**:
```
SKILL.md 指导 Agent → 输出 JSON: {"action":"kill","target":5}
         → ws_bridge 正则提取 JSON → 字段转换 → 提交 REST API
```

**目标**:
```
SKILL.md 指导 Agent → 调用业务脚本: werewolf_action kill --target 5
         → 业务脚本内部使用 SDK 处理字段映射、提交
         → 返回执行结果给 Agent
```

**分层职责**:

| 层 | 职责 | 不做 |
|----|------|------|
| **SKILL.md** | 角色策略推理、发言生成、信息分析 | 不拼 JSON、不关心字段名、不知道 API 格式 |
| **业务脚本** | 暴露高层语义命令（kill/check/vote/speech 等），内部使用 SDK 封装所有协议细节 | 不做策略决策、不调 LLM |
| **SDK** | Socket.IO 连接、REST 调用、字段映射、重连 | 不关心游戏策略 |

---

## 3. 功能需求

### F-01: 基于 SDK 重构 Bridge 通信层

**优先级**: P0
**类型**: 重构

**描述**:
废弃 ws_bridge.py 中基于 `websockets` + `httpx` 的自建通信层，改为继承 `werewolf_arena.WerewolfAgent`，在其事件回调中接入 OpenClaw Webhook。

**验收标准**:
1. Bridge 能通过 SDK 成功连接游戏服务端 Socket.IO
2. 能正确接收 `game.start`、`phase.night`、`phase.day.speech`、`phase.day.vote`、`game.end` 等事件
3. 能通过 SDK 的 `submit_action()` 成功提交行动，服务端返回 `success: true`
4. 断线后自动重连，重连后能接收缓冲事件

**修复的问题**:
- 🔴 WebSocket 协议不匹配（websockets → Socket.IO）
- 🔴 REST API 路径错误（/api/rooms/ → /api/v1/games/）
- 🔴 认证方式不匹配（Authorization: Bearer → X-Agent-Key）
- 🔴 Action 字段名不匹配（action/target → action_type/target_seat）
- 🟠 room_id / game_id 混淆
- 🟠 事件消息结构解析错误

**实现要点**:
- 继承 `WerewolfAgent`，覆写 `on_game_start`、`on_night_action`、`on_speech_turn`、`on_vote`、`on_game_end` 等回调
- 在回调中调用 OpenClaw Webhook 获取 Agent 决策
- 使用 SDK 的 `Action` 模型提交行动（SDK 内部处理字段映射）
- 保留超时降级逻辑（在 Webhook 超时时使用 fallback）

**依赖变更**:
```
- websockets          # 移除
+ werewolf-arena      # 新增（含 python-socketio 依赖）
  httpx               # 保留（Webhook 调用仍需要）
```

---

### F-02: 业务脚本层（werewolf_cli.py）

**优先级**: P0
**类型**: 新增

**描述**:
新增业务脚本 `werewolf_cli.py`，封装所有游戏行动为高层语义命令。SKILL.md 指导 Agent 通过 bash 调用此脚本执行行动，脚本内部使用 SDK 处理协议细节。

**命令设计**:

```bash
# 夜晚行动
python werewolf_cli.py kill --target 5          # 狼人击杀
python werewolf_cli.py check --target 3         # 预言家查验
python werewolf_cli.py guard --target 2         # 守卫守护
python werewolf_cli.py save                     # 女巫救人
python werewolf_cli.py poison --target 7        # 女巫毒杀
python werewolf_cli.py skip                     # 女巫跳过 / 猎人不开枪
python werewolf_cli.py shoot --target 4         # 猎人开枪

# 白天行动
python werewolf_cli.py speech --content "我觉得3号很可疑"
python werewolf_cli.py vote --target 3          # 投票
python werewolf_cli.py vote --abstain           # 弃票

# 查询（辅助 Agent 获取当前状态）
python werewolf_cli.py status                   # 当前游戏状态
python werewolf_cli.py alive                    # 存活玩家列表
```

**验收标准**:
1. 每个命令在脚本内部映射到正确的 SDK `ActionType`（如 `kill` → `werewolf_kill`）
2. 命令执行后输出人类可读的结果（如 "✅ 已击杀 5 号" 或 "❌ 行动失败: 目标已死亡"）
3. 非法参数（如 guard 连续守同一人）在脚本层提前校验并给出提示
4. Agent 可在 SKILL.md 指导下正确调用这些命令

**内部映射表**:

| CLI 命令 | SDK ActionType | 服务端枚举值 |
|----------|---------------|-------------|
| `kill` | `werewolf_kill` | `werewolf_kill` |
| `check` | `seer_check` | `seer_check` |
| `guard` | `guard_protect` | `guard_protect` |
| `save` | `witch_save` | `witch_save` |
| `poison` | `witch_poison` | `witch_poison` |
| `skip`（女巫上下文） | `witch_skip` | `witch_skip` |
| `shoot` | `hunter_shoot` | `hunter_shoot` |
| `skip`（猎人上下文） | `hunter_skip` | `hunter_skip` |
| `speech` | `speech` | `speech` |
| `vote` | `vote` | `vote` |
| `vote --abstain` | `vote_abstain` | `vote_abstain` |

**实现要点**:
- 脚本通过共享文件或环境变量获取运行时上下文（game_id、api_key、当前角色等），由 Bridge 启动时写入
- 内部使用 SDK 的 `ArenaRESTClient` 提交行动
- 输出格式简洁，适合 Agent 解析（成功/失败 + 原因）
- 女巫的 `skip` 和猎人的 `skip` 通过上下文（当前角色 + 当前阶段）自动区分

---

### F-03: SKILL.md 重构 — 策略与协议解耦

**优先级**: P0
**类型**: 重构

**描述**:
重写 SKILL.md，移除所有 JSON 格式组装指令，改为通过调用业务脚本（F-02）执行行动。SKILL.md 只关注策略推理和发言生成。

**变更对比**:

**当前 SKILL.md（移除）**:
```markdown
## 响应格式约束
每次回复由两部分组成：
1. 自然语言分析
2. JSON 决策块（尾部），格式：
   ```json
   {"action": "kill", "target": 5}
   ```
```

**目标 SKILL.md（替换为）**:
```markdown
## 行动执行
分析完局势后，调用业务脚本执行行动：

夜晚行动示例：
  - 狼人击杀: `python werewolf_cli.py kill --target 5`
  - 预言家查验: `python werewolf_cli.py check --target 3`
  - 女巫救人: `python werewolf_cli.py save`
  - 女巫跳过: `python werewolf_cli.py skip`
  - 守卫守护: `python werewolf_cli.py guard --target 2`

白天行动示例：
  - 发言: `python werewolf_cli.py speech --content "你的发言内容"`
  - 投票: `python werewolf_cli.py vote --target 3`
  - 弃票: `python werewolf_cli.py vote --abstain`
```

**验收标准**:
1. SKILL.md 中不包含任何 JSON 格式模板或字段名（action_type、target_seat 等）
2. 所有行动执行通过 `python werewolf_cli.py <command>` 形式
3. SKILL.md 保留完整的策略推理框架（角色策略、推理步骤、发言指南等）
4. Agent 能根据 SKILL.md 指导，在收到游戏事件后给出策略分析并调用正确的脚本命令

**保留的内容**:
- Section 1: 触发与识别（调整激活条件）
- Section 3: 角色策略指南（不变）
- Section 4: 推理框架（不变）
- Section 5: 发言生成指南（不变）
- Section 6: 跨轮上下文利用（不变）
- Section 7: 启动引导（更新启动命令）

**移除的内容**:
- Section 2 全部: 响应格式约束（JSON 模板、事件分类表、代码块格式规范）
- 所有 ````json {...} ```` 示例

**新增的内容**:
- 行动执行部分: 业务脚本命令参考
- 命令输出解读: 如何理解脚本返回的成功/失败信息

---

### F-04: Bridge 事件转发重构

**优先级**: P0
**类型**: 重构

**描述**:
基于 SDK 的事件回调机制，重构事件转发逻辑。当前 ws_bridge.py 的 `format_event()` 自行拼装事件文本，需要改为基于 SDK 回调中已解析好的事件数据进行格式化。

**验收标准**:
1. 所有 SDK 回调事件（game.start、phase.night、phase.day.speech、phase.day.vote、game.end、player.death、werewolf.chat、vote.result、game.sync）都能正确格式化并转发到 OpenClaw Webhook
2. 事件格式化后的自然语言描述包含 Agent 决策所需的全部上下文信息
3. 通知型事件（无需 Agent 回复的）正确标记为 `need_response=False`

**实现要点**:
- `on_game_start`: 格式化角色信息、玩家列表（角色和座位从 SDK `_role`/`_seat` 获取）
- `on_night_action`: 格式化当前角色、存活玩家、历史信息，Webhook 获取 Agent 决策后调用脚本
- `on_speech_turn`: 格式化已有发言、存活玩家，Webhook 获取 Agent 发言后调用脚本
- `on_vote`: 格式化发言回顾、投票历史，Webhook 获取 Agent 投票后调用脚本
- `on_player_death` / `on_werewolf_chat` / `on_vote_result`: 通知型，转发到 Webhook 但不等待决策

---

## 4. Bug 修复

以下问题无法通过 SDK 集成和业务脚本层完全解决，需要单独修复。

### BUG-01: 女巫专有阶段事件缺失

**优先级**: P1
**类型**: Bug

**现象**:
服务端在 `NIGHT_WITCH` 阶段会向女巫推送专有事件，包含被害者信息（谁被狼人刀了），供女巫决定是否使用解药。SDK 的 `on_night_action` 是通用夜晚回调，不区分狼人/预言家/女巫/守卫的各自阶段，也没有 `on_witch_action` 专用回调。

**影响**:
女巫无法获知被害者信息，无法做出"是否救人"的决策。

**修复方案**:
在 Bridge 中注册额外的 Socket.IO 事件监听器，捕获女巫专有阶段事件：

```python
@self._sio.on("phase.night.witch", namespace="/agent")
async def on_witch_phase(data):
    # data 中应包含 victim 信息
    # 格式化并转发到 Webhook
    pass
```

如果服务端不发独立的 `phase.night.witch` 事件，而是复用 `phase.night` 并在 data 中区分角色，则需要在 `on_night_action` 回调中根据 `self.role == "witch"` 做分支处理，将被害者信息传递给 Agent。

**依赖**:
需要确认服务端 `game_engine.py` 在女巫阶段推送的具体事件名称和数据结构。

---

### BUG-02: 猎人死亡开枪阶段缺失

**优先级**: P1
**类型**: Bug

**现象**:
服务端在猎人死亡时进入 `HUNTER_SHOOT` 阶段，推送事件要求猎人决定是否开枪（`hunter_shoot` 或 `hunter_skip`）。SDK 没有 `on_hunter_shoot` 回调，猎人死亡开枪的决策流程不完整。

**影响**:
猎人死亡后无法做出开枪决策，导致超时或默认行为。

**修复方案**:
在 Bridge 中注册猎人开枪阶段事件监听器：

```python
@self._sio.on("hunter.shoot", namespace="/agent")
async def on_hunter_shoot(data):
    # 转发到 Webhook，让 Agent 决定是否开枪以及带谁
    # Agent 调用: werewolf_cli.py shoot --target X
    # 或: werewolf_cli.py skip
    pass
```

同样需要确认服务端推送的具体事件名称。

**依赖**:
需要确认服务端 `game_engine.py` 在 `HUNTER_SHOOT` 阶段推送的事件名和数据格式。

---

### BUG-03: role.assigned 事件未处理

**优先级**: P1
**类型**: Bug

**现象**:
服务端在游戏开始时通过独立的 `role.assigned` 事件（visibility=private）通知每个玩家各自的角色、座位和阵营。SDK 在 `game.sync` 中能获取角色和座位，但 `role.assigned` 事件中可能包含额外的角色描述信息（display_name、faction）。此外狼人队友信息通过独立的 `werewolf.teammates` 事件推送，SDK 也未显式处理。

**影响**:
- 可能丢失角色详细描述（display_name）
- 狼人可能无法及时获知队友座位号

**修复方案**:
在 Bridge 中注册这两个事件：

```python
@self._sio.on("role.assigned", namespace="/agent")
async def on_role_assigned(data):
    # 补充角色详细信息到 context
    pass

@self._sio.on("werewolf.teammates", namespace="/agent")
async def on_werewolf_teammates(data):
    # 记录狼人队友信息，转发给 Agent
    pass
```

**依赖**:
确认 `game.sync` 是否已包含足够的角色信息。如果 `game.sync` 已包含 `your_role`、`your_seat` 及狼人互相可见，则此 Bug 降级为 P2（仅缺少 display_name）。

---

### BUG-04: night.result 事件未处理

**优先级**: P1
**类型**: Bug

**现象**:
ws_bridge 中定义了 `night.result` 的格式化逻辑（查验结果、守护结果、死亡信息等），但 SDK 没有对应的 `on_night_result` 回调。该事件携带预言家查验结果、女巫行动结果、昨夜死亡等关键信息。

**影响**:
Agent 无法获知夜晚行动的结果，预言家不知道查验结果，所有玩家不知道昨夜谁死了。

**修复方案**:
在 Bridge 中注册 night.result 事件（如果服务端有此事件），或者在 `on_player_death` 等已有回调中聚合信息：

```python
@self._sio.on("night.result", namespace="/agent")
async def on_night_result(data):
    # 格式化查验结果、死亡信息等
    # 转发到 Webhook（通知型，need_response=False）
    pass
```

**依赖**:
需确认服务端是否发出 `night.result` 这个聚合事件，还是通过多个独立事件（`player.death`、`seer.result` 等）分别通知。

---

### BUG-05: 超时降级策略不完整

**优先级**: P2
**类型**: Bug

**现象**:
当前 `fallback_action()` 缺少以下角色/场景的降级逻辑：
1. 猎人死亡开枪（应降级为 `hunter_skip`，不盲目带人）
2. 女巫的 save/poison 选择（当前统一返回 `{"action": "pass"}`，应根据上下文决定）
3. 遗言（`last_words`）— 服务端支持但 Bridge 未处理

**影响**:
超时时行动可能非法（服务端拒绝），或错失关键操作机会。

**修复方案**:
在业务脚本或 Bridge 中补充完整的降级映射：

```python
def fallback_action(phase: str, role: str, context: dict) -> str:
    """返回降级时应调用的 CLI 命令。"""
    if phase == "hunter_shoot":
        return "skip"  # 不确定时不开枪
    if phase == "night" and role == "witch":
        return "skip"  # 不确定时不用药
    if phase == "last_words":
        return 'speech --content "我没什么想说的。"'
    # ... 其他已有逻辑
```

---

## 5. 非功能需求

### NFR-01: 依赖管理

**当前依赖**:
```
httpx, websockets
```

**目标依赖**:
```
werewolf-arena (SDK, 含 python-socketio, httpx)
```

SDK 已包含 httpx，`websockets` 应移除。确认 `werewolf-arena` 是否已发布到 PyPI，若未发布需支持从 git 安装：

```bash
pip install git+https://github.com/slob-coder/werewolf-game.git#subdirectory=sdk/python
```

### NFR-02: 运行时上下文传递

业务脚本（werewolf_cli.py）需要获取运行时信息（game_id、api_key、server_url、当前角色等）。推荐通过环境变量或共享状态文件传递：

```bash
# 方案 A: 环境变量（Bridge 启动时设置）
export WEREWOLF_GAME_ID=xxx
export WEREWOLF_API_KEY=sk-xxx
export WEREWOLF_SERVER=http://localhost:8000
export WEREWOLF_MY_ROLE=seer
export WEREWOLF_MY_SEAT=3

# 方案 B: 状态文件（Bridge 写入，脚本读取）
# /tmp/werewolf_context_{room_id}.json
```

### NFR-03: 服务端事件名确认

多个 Bug 修复依赖于确认服务端推送的具体事件名称。在开发前需要通过以下方式确认：

1. 阅读 `game_engine.py` 中 `_emit_event` 的所有调用点，整理完整的事件清单
2. 或连接一个测试游戏，记录 Socket.IO 收到的所有事件名和数据结构
3. 将结果补充到本文档附录

---

