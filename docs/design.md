# Werewolf OpenClaw Skill — 技术设计方案

> **版本**: v1.0 | **日期**: 2026-03-24 | **设计师**: Designer Agent
> **仓库**: https://github.com/slob-coder/werewolf-openclaw-skill
> **需求文档**: werewolf-openclaw-agent-v2.md

---

## 1. 项目概述

### 1.1 目标

为 Werewolf Arena 狼人杀平台开发 OpenClaw Skill，使用户能够通过自然语言对话，一键启动智能 Agent 参与完整的狼人杀游戏流程。

### 1.2 核心架构原则

**OpenClaw Skill ≠ 独立服务**。Skill 是注入到 Agent system prompt 的指令集，由 `SKILL.md` 描述。它引导 Agent 通过 `bash` 工具管理一个**外部 Python 进程**，该进程才是真正维持 WebSocket 长连接和处理游戏事件的实体。

```
┌─────────────────────────────────────────────────────────────────────┐
│                        用户对话层 (OpenClaw)                          │
│                    "帮我加入房间 abc123"                               │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      SKILL.md (OpenClaw 侧)                          │
│              理解意图 → 收集参数 → 调用 bash 工具                       │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        bash 工具执行                                  │
│  ├─ pip install werewolf-sdk anthropic (首次)                        │
│  ├─ python werewolf_agent.py --room abc123 --api-key xxx &           │
│  └─ 启动后台进程，写 PID 到日志                                        │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│              werewolf_agent.py (独立 Python 进程)                     │
│  ├─ 维持 WebSocket 长连接 (werewolf_sdk)                              │
│  ├─ 接收游戏事件 (game.start / phase.* / game.end)                   │
│  ├─ 调用 LLM API 进行推理决策                                         │
│  ├─ 提交行动 (REST API)                                              │
│  └─ 将关键事件写入日志文件                                            │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│              OpenClaw 定期查询日志 / 监听进程状态                       │
│       向用户报告："已投票给 3 号玩家" / "游戏结束，好人获胜"              │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.3 职责分工

| 组件 | 职责 | 技术实现 |
|------|------|---------|
| `SKILL.md` | 触发词识别、参数收集、进程管理指令 | OpenClaw Skill |
| `werewolf_agent.py` | WebSocket 长连接、事件处理、行动提交 | Python + werewolf_sdk |
| `strategy_*.py` | 推理决策（目标选择、发言生成） | LLM API 调用 |
| `memory.py` | 游戏状态维护、历史记录归档 | 本地 JSON + 文件 |

---

## 2. 架构设计

### 2.1 目录结构

```
~/.openclaw/workspace/skills/werewolf-agent/
├── SKILL.md                  # OpenClaw Skill 核心文件
├── werewolf_agent.py         # Agent 主进程
├── strategy_basic.py         # 规则驱动策略 (P0)
├── strategy_llm.py           # LLM 推理策略 (P1)
├── memory.py                 # 游戏状态管理
├── prompts/
│   ├── speech.txt            # 发言生成 Prompt (P0)
│   ├── reasoning.txt         # 推理分析 Prompt (P1)
│   └── decision.txt          # 决策 Prompt (P1)
├── config/
│   └── default.yaml          # 默认配置
├── examples/
│   └── start_agent.sh        # 手动启动示例脚本
└── README.md                 # 快速开始文档
```

### 2.2 数据流

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   OpenClaw   │────▶│   SKILL.md   │────▶│  bash/exec   │
│   (用户对话)  │     │  (意图识别)   │     │  (进程管理)   │
└──────────────┘     └──────────────┘     └──────┬───────┘
                                                  │
                                                  ▼
┌──────────────────────────────────────────────────────────────┐
│                    werewolf_agent.py                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐   │
│  │ WebSocket   │  │  EventHandler│  │    Strategy Engine  │   │
│  │ Client      │──▶│   Router     │──▶│   (basic/llm)       │   │
│  │ (SDK)       │  │              │  │                     │   │
│  └─────────────┘  └─────────────┘  └──────────┬──────────┘   │
│         │                                     │              │
│         │              ┌──────────────────────▼───────────┐  │
│         │              │         GameMemory              │  │
│         │              │  (状态管理 + 持久化)              │  │
│         │              └──────────────────────────────────┘  │
│         │                                                   │
│         ▼                                                   │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              Log File (事件日志)                      │    │
│  │   ~/.openclaw/logs/werewolf-agent.log               │    │
│  └─────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────┘
         │
         ▼
┌──────────────────┐
│  Werewolf Arena  │
│   (游戏平台)      │
│   REST + WS      │
└──────────────────┘
```

### 2.3 运行时序

```
User: "帮我加入房间 abc123"
   │
   ├─▶ SKILL.md 识别意图
   │      │
   │      ├─▶ 检查配置文件是否存在
   │      │      └─▶ 不存在 → 对话收集参数
   │      │
   │      ├─▶ 执行: python werewolf_agent.py --room abc123 ... &
   │      │
   │      └─▶ 返回: "✓ 已启动 Agent，正在加入房间..."
   │
   ├─▶ Agent 进程启动
   │      │
   │      ├─▶ 建立 WebSocket 连接
   │      │
   │      ├─▶ 收到 game.start 事件
   │      │      └─▶ 写日志: [EVENT] 游戏开始，角色=预言家
   │      │
   │      ├─▶ 收到 phase.night 事件
   │      │      ├─▶ 调用策略选择查验目标
   │      │      ├─▶ 提交 seer_check 行动
   │      │      └─▶ 写日志: [ACTION] 查验 5 号玩家
   │      │
   │      ├─▶ 收到 phase.day.speech 事件
   │      │      ├─▶ 调用 LLM 生成发言
   │      │      ├─▶ 提交 speech 行动
   │      │      └─▶ 写日志: [ACTION] 已发言
   │      │
   │      └─▶ 收到 game.end 事件
   │             └─▶ 写日志: [EVENT] 游戏结束，好人获胜
   │
   └─▶ OpenClaw 查询日志
          └─▶ 向用户报告关键事件
```

---

## 3. SKILL.md 设计

### 3.1 文件位置

```
~/.openclaw/workspace/skills/werewolf-agent/SKILL.md
```

### 3.2 触发条件

当用户说出以下意图时激活本 Skill：

```markdown
## 触发条件

当用户提到以下关键词或意图时激活：
- "加入狼人杀房间 {room_id}"
- "启动狼人杀 Agent"
- "帮我玩狼人杀"
- "加入 Werewolf Arena"
- 提及房间 ID 格式（如 abc123, room-xxx）
```

### 3.3 参数收集流程

```markdown
## 参数收集

首次使用时，通过对话收集以下参数（后续存入 `~/.openclaw/config/werewolf-agent.yaml`）：

| 参数 | 说明 | 必填 | 默认值 |
|------|------|:----:|--------|
| `room_id` | 房间 ID | ✅ | - |
| `api_key` | Werewolf Arena API Key | ✅ | - |
| `server_url` | 后端地址 | ❌ | localhost:8000 |
| `strategy` | 策略风格 | ❌ | conservative |
| `speech_style` | 发言风格 | ❌ | formal |
| `cot_visibility` | 思维链可见性 | ❌ | private |

### 收集流程

1. 检查配置文件是否存在
2. 若不存在，依次询问必填参数
3. 保存配置后执行启动命令
```

### 3.4 进程管理指令

```markdown
## 进程管理

### 启动 Agent

```bash
# 安装依赖（首次）
pip install werewolf-sdk anthropic pyyaml

# 启动 Agent 进程
python ~/.openclaw/workspace/skills/werewolf-agent/werewolf_agent.py \
  --room-id {room_id} \
  --api-key {api_key} \
  --server-url {server_url} \
  --strategy {strategy} \
  --speech-style {speech_style} \
  --log-file ~/.openclaw/logs/werewolf-agent.log \
  > ~/.openclaw/logs/werewolf-agent.log 2>&1 &

echo $! > ~/.openclaw/logs/werewolf-agent.pid
```

### 查询状态

```bash
# 查询进程是否存活
kill -0 $(cat ~/.openclaw/logs/werewolf-agent.pid) 2>/dev/null && echo "running" || echo "stopped"

# 查询最新状态
tail -50 ~/.openclaw/logs/werewolf-agent.log | grep "\[EVENT\]"

# 查询最近行动
tail -20 ~/.openclaw/logs/werewolf-agent.log | grep "\[ACTION\]"
```

### 停止 Agent

```bash
kill $(cat ~/.openclaw/logs/werewolf-agent.pid) 2>/dev/null
rm ~/.openclaw/logs/werewolf-agent.pid
```
```

### 3.5 状态反馈

```markdown
## 状态反馈

向用户展示的信息格式：

| 场景 | 反馈内容 |
|------|---------|
| 启动成功 | ✓ 已加入游戏，等待开始... |
| 游戏开始 | 游戏开始，你的角色是 **{角色名}** |
| 夜晚行动 | [夜晚] 正在选择{行动}目标... |
| 白天发言 | [发言] 已生成发言内容 |
| 投票完成 | [投票] 已投票给 {n} 号玩家 |
| 游戏结束 | 游戏结束，**{阵营}**获胜 🎉｜你存活到第 {n} 轮 |
| 进程停止 | ⚠️ Agent 进程已停止运行 |

### 定期检查

当用户询问游戏状态时，执行日志查询并格式化输出。
```

---

## 4. werewolf_agent.py 设计

### 4.1 主进程架构

```python
#!/usr/bin/env python3
"""
Werewolf Arena Agent - OpenClaw Skill 后台进程

职责：
1. 维持 WebSocket 长连接
2. 接收并处理游戏事件
3. 调用策略引擎进行决策
4. 提交行动到游戏平台
5. 记录关键事件到日志
"""

import asyncio
import argparse
import signal
import sys
from pathlib import Path
from typing import Optional

# 项目内模块
from memory import GameMemory
from strategy_basic import BasicStrategy
from strategy_llm import LLMStrategy
from logger import AgentLogger


class WerewolfAgent:
    """狼人杀 Agent 主类"""
    
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.memory: Optional[GameMemory] = None
        self.strategy = self._create_strategy()
        self.logger = AgentLogger(args.log_file)
        self.client = None  # werewolf_sdk.WerewolfClient
        self.running = False
        
    def _create_strategy(self):
        """根据配置创建策略引擎"""
        if self.args.strategy == 'llm':
            return LLMStrategy(
                model=self.args.model,
                speech_style=self.args.speech_style
            )
        return BasicStrategy(speech_style=self.args.speech_style)
    
    async def run(self):
        """主运行循环"""
        self.running = True
        
        # 注册信号处理
        signal.signal(signal.SIGTERM, self._handle_shutdown)
        signal.signal(signal.SIGINT, self._handle_shutdown)
        
        try:
            # 初始化 WebSocket 客户端
            await self._connect()
            
            # 加入房间
            await self._join_room()
            
            # 阻塞运行，处理事件
            await self._event_loop()
            
        except Exception as e:
            self.logger.error(f"Agent 运行异常: {e}")
            raise
        finally:
            await self._cleanup()
    
    async def _connect(self):
        """建立 WebSocket 连接"""
        self.logger.info("正在连接服务器...")
        # 实际实现使用 werewolf_sdk
        # self.client = WerewolfClient(...)
        # await self.client.connect()
        self.logger.info("连接成功")
    
    async def _join_room(self):
        """加入游戏房间"""
        self.logger.info(f"正在加入房间 {self.args.room_id}...")
        # await self.client.join_room(self.args.room_id)
        self.logger.event("已加入房间，等待游戏开始")
    
    async def _event_loop(self):
        """事件处理循环"""
        while self.running:
            # 等待并处理事件
            # event = await self.client.receive_event()
            # await self._dispatch_event(event)
            await asyncio.sleep(0.1)
    
    async def _dispatch_event(self, event: dict):
        """事件分发路由"""
        event_type = event.get("event_type")
        handlers = {
            "game.start": self._on_game_start,
            "phase.night": self._on_night_phase,
            "phase.day.speech": self._on_speech_phase,
            "phase.day.vote": self._on_vote_phase,
            "werewolf.chat": self._on_werewolf_chat,
            "game.end": self._on_game_end,
        }
        
        handler = handlers.get(event_type)
        if handler:
            await handler(event)
    
    # === 事件处理器 ===
    
    async def _on_game_start(self, event: dict):
        """游戏开始"""
        data = event["data"]
        self.memory = GameMemory(
            game_id=event["game_id"],
            room_id=self.args.room_id,
            my_role=data["your_role"],
            my_faction=data["your_faction"],
            my_seat=data["your_seat"],
        )
        self.memory.init_players(data["players"])
        
        # 狼人记录队友
        if data.get("teammates"):
            self.memory.werewolf_teammates = data["teammates"]
        
        self.logger.event(f"游戏开始，角色={data['your_role']}")
    
    async def _on_night_phase(self, event: dict):
        """夜晚行动"""
        data = event["data"]
        my_role = self.memory.my_role
        
        # 根据角色选择行动
        action = await self.strategy.night_action(
            role=my_role,
            memory=self.memory,
            event_data=data,
            timeout=60
        )
        
        # 提交行动
        await self._submit_action(action)
        self.logger.action(f"夜晚行动: {action['action_type']}")
    
    async def _on_speech_phase(self, event: dict):
        """白天发言"""
        data = event["data"]
        
        if not data.get("is_your_turn"):
            return
        
        # 生成发言
        speech = await self.strategy.generate_speech(
            memory=self.memory,
            event_data=data,
            timeout=90
        )
        
        # 提交发言
        action = {"action_type": "speech", "content": speech}
        await self._submit_action(action)
        self.logger.action("已提交发言")
    
    async def _on_vote_phase(self, event: dict):
        """投票"""
        data = event["data"]
        
        # 选择投票目标
        target = await self.strategy.vote_target(
            memory=self.memory,
            event_data=data,
            timeout=60
        )
        
        # 提交投票
        action = {"action_type": "vote", "target": target}
        await self._submit_action(action)
        self.logger.action(f"投票给 {target} 号玩家")
    
    async def _on_werewolf_chat(self, event: dict):
        """狼人夜聊（仅狼人可见）"""
        data = event["data"]
        self.memory.add_werewolf_chat(
            speaker=data["speaker"],
            content=data["content"]
        )
        # 不写日志，保持私密性
    
    async def _on_game_end(self, event: dict):
        """游戏结束"""
        data = event["data"]
        winner = data["winner"]
        
        # 归档对局
        self.memory.archive(
            winner=winner,
            rounds=data["rounds_played"]
        )
        
        self.logger.event(f"游戏结束，{winner}获胜")
        self.running = False
    
    # === 辅助方法 ===
    
    async def _submit_action(self, action: dict):
        """提交行动到平台"""
        # 规则校验
        if not self._validate_action(action):
            action = self._fallback_action(action)
        
        # 调用 SDK 提交
        # await self.client.submit_action(action)
        pass
    
    def _validate_action(self, action: dict) -> bool:
        """规则校验"""
        # 详见 strategy_basic.py
        return self.strategy.validate_action(action, self.memory)
    
    def _fallback_action(self, action: dict) -> dict:
        """降级行动"""
        return self.strategy.fallback_action(action, self.memory)
    
    async def _cleanup(self):
        """清理资源"""
        self.logger.info("Agent 进程退出")
    
    def _handle_shutdown(self, signum, frame):
        """处理关闭信号"""
        self.logger.info("收到关闭信号")
        self.running = False


def main():
    parser = argparse.ArgumentParser(description="Werewolf Arena Agent")
    parser.add_argument("--room-id", required=True, help="房间 ID")
    parser.add_argument("--api-key", required=True, help="API Key")
    parser.add_argument("--server-url", default="localhost:8000")
    parser.add_argument("--strategy", default="basic", choices=["basic", "llm"])
    parser.add_argument("--model", default="claude-sonnet-4-6")
    parser.add_argument("--speech-style", default="formal")
    parser.add_argument("--log-file", default="~/.openclaw/logs/werewolf-agent.log")
    
    args = parser.parse_args()
    
    agent = WerewolfAgent(args)
    asyncio.run(agent.run())


if __name__ == "__main__":
    main()
```

### 4.2 断线重连机制

```python
async def _connect_with_reconnect(self):
    """带重连的连接管理"""
    max_attempts = 5
    
    for attempt in range(max_attempts):
        try:
            await self._connect()
            return
        except Exception as e:
            if attempt == max_attempts - 1:
                raise
            
            wait_time = 5 * (attempt + 1)
            self.logger.warn(f"连接失败，{wait_time}秒后重试...")
            await asyncio.sleep(wait_time)


async def _on_disconnect(self):
    """断线重连处理"""
    self.logger.warn("连接断开，尝试重连...")
    
    for attempt in range(5):
        await asyncio.sleep(5 * (attempt + 1))
        
        try:
            await self._connect()
            
            # 同步最新状态
            state = await self.client.get_game_state()
            self.memory.sync_from_server(state)
            
            self.logger.info("重连成功，状态已同步")
            return
            
        except Exception as e:
            self.logger.warn(f"重连失败（第{attempt+1}次）: {e}")
    
    self.logger.error("重连失败，进程退出")
    self.running = False
```

### 4.3 超时处理

```python
async def _execute_with_timeout(self, coro, timeout: int, fallback):
    """带超时保护的执行"""
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        self.logger.warn(f"操作超时，执行降级策略")
        return fallback()
```

---

## 5. Strategy 模块设计

### 5.1 模块架构

```
strategy/
├── __init__.py
├── base.py           # 策略基类
├── basic.py          # 规则驱动策略 (P0)
├── llm.py            # LLM 增强策略 (P1)
└── validator.py      # 规则校验层
```

### 5.2 策略基类

```python
# strategy/base.py
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from memory import GameMemory


class StrategyBase(ABC):
    """策略引擎基类"""
    
    @abstractmethod
    async def night_action(
        self, 
        role: str, 
        memory: GameMemory, 
        event_data: dict,
        timeout: int = 60
    ) -> dict:
        """夜晚行动决策"""
        pass
    
    @abstractmethod
    async def generate_speech(
        self,
        memory: GameMemory,
        event_data: dict,
        timeout: int = 90
    ) -> str:
        """生成发言内容"""
        pass
    
    @abstractmethod
    async def vote_target(
        self,
        memory: GameMemory,
        event_data: dict,
        timeout: int = 60
    ) -> int:
        """投票目标选择"""
        pass
    
    def validate_action(self, action: dict, memory: GameMemory) -> bool:
        """规则校验（通用）"""
        from .validator import ActionValidator
        return ActionValidator.validate(action, memory)
    
    def fallback_action(self, action: dict, memory: GameMemory) -> dict:
        """降级行动"""
        # 返回随机合法行动
        pass
```

### 5.3 规则校验层 (P0 核心)

```python
# strategy/validator.py
from typing import Dict, Any
from memory import GameMemory


class ActionValidator:
    """行动校验器 - 拦截明显错误的行动"""
    
    @staticmethod
    def validate(action: dict, memory: GameMemory) -> bool:
        """校验行动是否合法"""
        action_type = action.get("action_type")
        
        validators = {
            "werewolf_kill": ActionValidator._validate_werewolf_kill,
            "seer_check": ActionValidator._validate_seer_check,
            "witch_save": ActionValidator._validate_witch_save,
            "witch_poison": ActionValidator._validate_witch_poison,
            "guard_protect": ActionValidator._validate_guard_protect,
            "vote": ActionValidator._validate_vote,
            "hunter_shoot": ActionValidator._validate_hunter_shoot,
        }
        
        validator = validators.get(action_type)
        if validator:
            return validator(action, memory)
        
        return True  # 未知行动类型放行
    
    @staticmethod
    def _validate_werewolf_kill(action: dict, memory: GameMemory) -> bool:
        """狼人击杀校验"""
        target = action.get("target")
        
        # 不能击杀队友
        if target in memory.werewolf_teammates:
            return False
        
        # 不能击杀已死亡玩家
        if target in memory.dead_players:
            return False
        
        return True
    
    @staticmethod
    def _validate_seer_check(action: dict, memory: GameMemory) -> bool:
        """预言家查验校验"""
        target = action.get("target")
        
        # 不能重复查验
        if target in memory.seer_check_results:
            return False
        
        # 不能查验已死亡玩家
        if target in memory.dead_players:
            return False
        
        return True
    
    @staticmethod
    def _validate_witch_save(action: dict, memory: GameMemory) -> bool:
        """女巫救人校验"""
        # 解药已用
        if memory.witch_antidote_used:
            return False
        
        # 检查是否有被杀目标
        if not memory.night_kill_target:
            return False
        
        return True
    
    @staticmethod
    def _validate_witch_poison(action: dict, memory: GameMemory) -> bool:
        """女巫毒人校验"""
        target = action.get("target")
        
        # 毒药已用
        if memory.witch_poison_used:
            return False
        
        # 不能毒已死亡玩家
        if target in memory.dead_players:
            return False
        
        return True
    
    @staticmethod
    def _validate_guard_protect(action: dict, memory: GameMemory) -> bool:
        """守卫守护校验"""
        target = action.get("target")
        
        # 不能连续守同一人
        if target == memory.last_guarded:
            return False
        
        # 不能守已死亡玩家
        if target in memory.dead_players:
            return False
        
        return True
    
    @staticmethod
    def _validate_vote(action: dict, memory: GameMemory) -> bool:
        """投票校验"""
        target = action.get("target")
        
        # 不能投票给已死亡玩家
        if target in memory.dead_players:
            return False
        
        # target 必须在候选人中
        # candidates = ...  # 从 memory 获取
        # return target in candidates
        
        return True
    
    @staticmethod
    def _validate_hunter_shoot(action: dict, memory: GameMemory) -> bool:
        """猎人开枪校验"""
        target = action.get("target")
        
        # 中毒死亡不能开枪
        if memory.death_cause == "poison":
            return False
        
        # 不能射击已死亡玩家
        if target in memory.dead_players:
            return False
        
        return True
```

### 5.4 规则驱动策略 (P0)

```python
# strategy/basic.py
import random
from typing import Dict, Any, Optional
from .base import StrategyBase
from memory import GameMemory


class BasicStrategy(StrategyBase):
    """规则驱动策略 - 随机行动 + 规则约束"""
    
    def __init__(self, speech_style: str = "formal"):
        self.speech_style = speech_style
    
    async def night_action(
        self, 
        role: str, 
        memory: GameMemory, 
        event_data: dict,
        timeout: int = 60
    ) -> dict:
        """夜晚行动 - 基于规则的随机选择"""
        
        available_actions = event_data.get("available_actions", [])
        if not available_actions:
            return {"action_type": "skip"}
        
        # 根据角色选择行动
        action_type = self._get_action_type_for_role(role)
        
        if action_type == "werewolf_kill":
            target = self._select_werewolf_target(memory, event_data)
            return {"action_type": "werewolf_kill", "target": target}
        
        elif action_type == "seer_check":
            target = self._select_seer_target(memory, event_data)
            return {"action_type": "seer_check", "target": target}
        
        elif action_type == "guard_protect":
            target = self._select_guard_target(memory, event_data)
            return {"action_type": "guard_protect", "target": target}
        
        # 女巫需要特殊处理
        elif role == "witch":
            return self._witch_action(memory, event_data)
        
        return {"action_type": "skip"}
    
    async def generate_speech(
        self,
        memory: GameMemory,
        event_data: dict,
        timeout: int = 90
    ) -> str:
        """生成发言 - P0 阶段使用模板"""
        
        role = memory.my_role
        templates = self._get_speech_templates(role)
        
        # 随机选择一个模板
        return random.choice(templates)
    
    async def vote_target(
        self,
        memory: GameMemory,
        event_data: dict,
        timeout: int = 60
    ) -> int:
        """投票目标 - 随机选择（排除自己）"""
        
        candidates = event_data.get("candidates", [])
        my_seat = memory.my_seat
        
        # 排除自己
        valid_candidates = [c for c in candidates if c != my_seat]
        
        if not valid_candidates:
            # 弃票
            return -1
        
        return random.choice(valid_candidates)
    
    # === 角色特定选择逻辑 ===
    
    def _select_werewolf_target(self, memory: GameMemory, event_data: dict) -> int:
        """狼人击杀目标选择"""
        # 可选目标
        targets = event_data.get("available_actions", [{}])[0].get("targets", [])
        
        # 排除队友
        valid_targets = [
            t for t in targets 
            if t not in memory.werewolf_teammates
        ]
        
        return random.choice(valid_targets) if valid_targets else targets[0]
    
    def _select_seer_target(self, memory: GameMemory, event_data: dict) -> int:
        """预言家查验目标选择"""
        targets = event_data.get("available_actions", [{}])[0].get("targets", [])
        
        # 优先查验未查验过的
        unchecked = [
            t for t in targets 
            if t not in memory.seer_check_results
        ]
        
        return random.choice(unchecked) if unchecked else targets[0]
    
    def _select_guard_target(self, memory: GameMemory, event_data: dict) -> int:
        """守卫守护目标选择"""
        targets = event_data.get("available_actions", [{}])[0].get("targets", [])
        
        # 不能连续守同一人
        valid_targets = [
            t for t in targets 
            if t != memory.last_guarded
        ]
        
        return random.choice(valid_targets) if valid_targets else targets[0]
    
    def _witch_action(self, memory: GameMemory, event_data: dict) -> dict:
        """女巫行动"""
        # 简化逻辑：随机决定是否救人/毒人
        # 实际实现需要更多状态判断
        return {"action_type": "witch_skip"}
    
    def _get_speech_templates(self, role: str) -> list:
        """获取发言模板"""
        templates = {
            "villager": [
                "我是村民，没有特殊信息，请大家多发言。",
                "我是好人，目前没有太多线索，听听大家的意见。",
                "我是平民，希望大家能多分享一些有用的信息。",
            ],
            "seer": [
                "我是预言家，昨晚查验了 X 号玩家，是好人/狼人。",
                "预言家在此，我有重要信息要分享。",
            ],
            "werewolf": [
                "我是好人，大家不要怀疑我。",
                "我觉得 X 号玩家比较可疑，建议关注。",
            ],
            "witch": [
                "我是女巫，昨晚有人被刀，我选择救/不救。",
            ],
            "hunter": [
                "我是猎人，如果我被投出去会开枪带人。",
            ],
            "guard": [
                "我是守卫，昨晚守护了 X 号。",
            ],
        }
        
        return templates.get(role, templates["villager"])
    
    def _get_action_type_for_role(self, role: str) -> str:
        """获取角色对应的行动类型"""
        mapping = {
            "werewolf": "werewolf_kill",
            "seer": "seer_check",
            "guard": "guard_protect",
            "witch": "witch_action",
        }
        return mapping.get(role, "skip")
    
    def fallback_action(self, action: dict, memory: GameMemory) -> dict:
        """降级行动"""
        # 返回一个安全的默认行动
        return {"action_type": "skip"}
```

### 5.5 LLM 增强策略 (P1)

```python
# strategy/llm.py
import os
import asyncio
from typing import Dict, Any, Optional
from .base import StrategyBase
from .basic import BasicStrategy
from memory import GameMemory


class LLMStrategy(StrategyBase):
    """LLM 增强策略 - 使用 Claude 进行推理决策"""
    
    def __init__(
        self, 
        model: str = "claude-sonnet-4-6",
        speech_style: str = "formal"
    ):
        self.model = model
        self.speech_style = speech_style
        self.basic_strategy = BasicStrategy(speech_style)
        self.api_key = os.getenv("ANTHROPIC_API_KEY")
        
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY 环境变量未设置")
    
    async def _call_llm(
        self, 
        prompt: str, 
        timeout: int = 30
    ) -> str:
        """调用 Claude API"""
        # 使用 anthropic SDK
        # import anthropic
        # client = anthropic.Anthropic(api_key=self.api_key)
        # message = client.messages.create(...)
        # return message.content
        
        # 实际实现
        pass
    
    async def night_action(
        self, 
        role: str, 
        memory: GameMemory, 
        event_data: dict,
        timeout: int = 60
    ) -> dict:
        """夜晚行动 - LLM 决策"""
        
        try:
            # 构建 prompt
            prompt = self._build_night_prompt(role, memory, event_data)
            
            # 调用 LLM（限时 30 秒）
            response = await asyncio.wait_for(
                self._call_llm(prompt),
                timeout=min(30, timeout - 5)
            )
            
            # 解析响应
            action = self._parse_action_response(response, role)
            
            # 校验
            if self.validate_action(action, memory):
                return action
            
        except asyncio.TimeoutError:
            pass
        except Exception as e:
            pass
        
        # 降级到规则策略
        return await self.basic_strategy.night_action(role, memory, event_data, timeout)
    
    async def generate_speech(
        self,
        memory: GameMemory,
        event_data: dict,
        timeout: int = 90
    ) -> str:
        """生成发言 - LLM 生成"""
        
        try:
            prompt = self._build_speech_prompt(memory, event_data)
            response = await asyncio.wait_for(
                self._call_llm(prompt),
                timeout=min(30, timeout - 5)
            )
            
            # 内容安全检查
            if self._is_safe_speech(response):
                return response
            
        except asyncio.TimeoutError:
            pass
        except Exception as e:
            pass
        
        return await self.basic_strategy.generate_speech(memory, event_data, timeout)
    
    async def vote_target(
        self,
        memory: GameMemory,
        event_data: dict,
        timeout: int = 60
    ) -> int:
        """投票目标 - LLM 决策"""
        
        try:
            prompt = self._build_vote_prompt(memory, event_data)
            response = await asyncio.wait_for(
                self._call_llm(prompt),
                timeout=min(30, timeout - 5)
            )
            
            target = self._parse_vote_response(response)
            
            if self.validate_action({"action_type": "vote", "target": target}, memory):
                return target
            
        except asyncio.TimeoutError:
            pass
        except Exception as e:
            pass
        
        return await self.basic_strategy.vote_target(memory, event_data, timeout)
    
    # === Prompt 构建 ===
    
    def _build_night_prompt(self, role: str, memory: GameMemory, event_data: dict) -> str:
        """构建夜晚行动 Prompt"""
        # 详见 prompts/ 目录下的模板
        pass
    
    def _build_speech_prompt(self, memory: GameMemory, event_data: dict) -> str:
        """构建发言生成 Prompt"""
        pass
    
    def _build_vote_prompt(self, memory: GameMemory, event_data: dict) -> str:
        """构建投票决策 Prompt"""
        pass
    
    # === 响应解析 ===
    
    def _parse_action_response(self, response: str, role: str) -> dict:
        """解析 LLM 行动响应"""
        pass
    
    def _parse_vote_response(self, response: str) -> int:
        """解析投票响应"""
        pass
    
    def _is_safe_speech(self, content: str) -> bool:
        """内容安全检查"""
        # 检查是否包含系统内部信息
        forbidden_patterns = [
            "event_type",
            "action_type",
            "api_key",
            "player_id",
            # 更多模式...
        ]
        
        for pattern in forbidden_patterns:
            if pattern in content.lower():
                return False
        
        return True
    
    def fallback_action(self, action: dict, memory: GameMemory) -> dict:
        return self.basic_strategy.fallback_action(action, memory)
```

### 5.6 LLM 调用规范

```python
# strategy/llm_client.py
"""
LLM 调用规范：
1. 模型：默认 claude-sonnet-4-6
2. 超时：单次调用 30 秒
3. API Key：从环境变量 ANTHROPIC_API_KEY 读取
4. Token 控制：历史发言最多保留最近 5 轮
"""

import os
from typing import Optional
import anthropic


class LLMClient:
    """LLM 客户端封装"""
    
    def __init__(self, model: str = "claude-sonnet-4-6"):
        self.model = model
        self.api_key = os.getenv("ANTHROPIC_API_KEY")
        
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY 未设置")
        
        self.client = anthropic.Anthropic(api_key=self.api_key)
    
    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 1024,
        temperature: float = 0.7
    ) -> str:
        """生成响应"""
        message = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt,
            messages=[
                {"role": "user", "content": user_prompt}
            ]
        )
        
        return message.content[0].text
```

---

## 6. Memory 模块设计

### 6.1 GameMemory 类

```python
# memory.py
"""
游戏状态管理模块

职责：
1. 维护一局游戏内的所有状态
2. 支持状态更新和查询
3. 游戏结束后归档到本地文件
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict


@dataclass
class DeathRecord:
    """死亡记录"""
    seat: int
    round: int
    cause: str  # kill, poison, vote, shoot
    role_revealed: Optional[str] = None


@dataclass
class SpeechRecord:
    """发言记录"""
    round: int
    seat: int
    content: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class VoteRecord:
    """投票记录"""
    round: int
    voter: int
    target: int  # -1 表示弃票


@dataclass
class GameMemory:
    """游戏状态管理"""
    
    # 基本信息
    game_id: str
    room_id: str
    my_role: str
    my_faction: str  # werewolf, god, villager
    my_seat: int
    
    # 玩家状态
    players: List[Dict[str, Any]] = field(default_factory=list)  # [{seat, name, status}]
    alive_players: List[int] = field(default_factory=list)
    dead_players: List[DeathRecord] = field(default_factory=list)
    
    # 角色特定信息
    werewolf_teammates: List[int] = field(default_factory=list)  # 仅狼人
    seer_check_results: Dict[int, str] = field(default_factory=dict)  # seat -> good/wolf
    witch_antidote_used: bool = False
    witch_poison_used: bool = False
    
    # 游戏进程
    current_round: int = 1
    current_phase: str = "waiting"  # night / day_speech / day_vote
    
    # 历史记录
    speeches: List[SpeechRecord] = field(default_factory=list)
    vote_history: List[VoteRecord] = field(default_factory=list)
    werewolf_chat: List[Dict[str, Any]] = field(default_factory=list)  # 狼人夜聊记录
    
    # 推理状态 (P1)
    identity_estimates: Dict[int, float] = field(default_factory=dict)  # seat -> 狼人概率
    
    # 守卫状态
    last_guarded: Optional[int] = None
    
    # 夜晚状态
    night_kill_target: Optional[int] = None
    death_cause: Optional[str] = None
    
    def init_players(self, players: List[Dict]):
        """初始化玩家列表"""
        self.players = players
        self.alive_players = [p["seat"] for p in players if p.get("status") == "alive"]
        
        # 初始化身份概率估计
        for seat in self.alive_players:
            if seat != self.my_seat:
                self.identity_estimates[seat] = 0.5  # 初始 50%
    
    def update_alive_players(self):
        """更新存活玩家列表"""
        dead_seats = {d.seat for d in self.dead_players}
        self.alive_players = [
            p["seat"] for p in self.players 
            if p["seat"] not in dead_seats
        ]
    
    def add_death(self, seat: int, round: int, cause: str, role: Optional[str] = None):
        """记录死亡"""
        self.dead_players.append(DeathRecord(
            seat=seat,
            round=round,
            cause=cause,
            role_revealed=role
        ))
        self.update_alive_players()
        
        # 更新身份估计
        if seat in self.identity_estimates:
            del self.identity_estimates[seat]
    
    def add_speech(self, round: int, seat: int, content: str):
        """记录发言"""
        self.speeches.append(SpeechRecord(
            round=round,
            seat=seat,
            content=content
        ))
    
    def add_vote(self, round: int, voter: int, target: int):
        """记录投票"""
        self.vote_history.append(VoteRecord(
            round=round,
            voter=voter,
            target=target
        ))
    
    def add_werewolf_chat(self, speaker: int, content: str):
        """记录狼人夜聊"""
        self.werewolf_chat.append({
            "round": self.current_round,
            "speaker": speaker,
            "content": content,
            "timestamp": datetime.now().isoformat()
        })
    
    def update_seer_result(self, seat: int, result: str):
        """更新预言家查验结果"""
        self.seer_check_results[seat] = result
        
        # 更新身份估计
        if result == "wolf":
            self.identity_estimates[seat] = 1.0
        else:
            self.identity_estimates[seat] = 0.0
    
    def get_recent_speeches(self, n_rounds: int = 5) -> List[SpeechRecord]:
        """获取最近 N 轮的发言"""
        recent_rounds = range(max(1, self.current_round - n_rounds), self.current_round + 1)
        return [s for s in self.speeches if s.round in recent_rounds]
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return asdict(self)
    
    def archive(self, winner: str, rounds: int):
        """归档对局到本地文件"""
        archive_dir = Path.home() / ".openclaw" / "logs" / "werewolf-history"
        archive_dir.mkdir(parents=True, exist_ok=True)
        
        archive_data = {
            "game_id": self.game_id,
            "room_id": self.room_id,
            "my_role": self.my_role,
            "my_faction": self.my_faction,
            "my_seat": self.my_seat,
            "winner": winner,
            "rounds_played": rounds,
            "players": self.players,
            "dead_players": [asdict(d) for d in self.dead_players],
            "speeches": [asdict(s) for s in self.speeches],
            "vote_history": [asdict(v) for v in self.vote_history],
            "seer_check_results": self.seer_check_results,
            "archived_at": datetime.now().isoformat()
        }
        
        archive_file = archive_dir / f"{self.game_id}.json"
        with open(archive_file, "w", encoding="utf-8") as f:
            json.dump(archive_data, f, ensure_ascii=False, indent=2)
    
    @classmethod
    def sync_from_server(cls, state: dict) -> "GameMemory":
        """从服务器状态同步"""
        # 实现状态恢复逻辑
        pass
```

### 6.2 归档机制

```
归档目录结构：

~/.openclaw/logs/werewolf-history/
├── {game_id_1}.json
├── {game_id_2}.json
└── ...

归档内容：
- 基本信息：game_id, room_id, 角色, 阵营
- 游戏结果：获胜方, 总轮数
- 玩家信息：座位, 名称, 最终状态
- 死亡记录：死亡顺序, 原因, 公开角色
- 发言历史：所有公开发言
- 投票历史：所有投票记录
- 角色特定：查验结果（预言家）
```

---

## 7. Prompt 模板设计

### 7.1 发言生成 (P0)

```
# prompts/speech.txt

## 系统角色

你正在玩狼人杀游戏，需要生成一段发言。

## 你的身份

- 角色：{role}
- 阵营：{faction}
- 座位号：{my_seat}

## 当前局势

- 当前轮次：第 {round} 轮
- 存活玩家：{alive_players}
- 已死亡玩家：{dead_players}
- 你的已知信息：{known_info}

## 最近发言

{recent_speeches}

## 任务

生成一段发言（50-150字），要求：
1. 符合你角色的视角和信息范围
2. 不透露超出角色可见范围的信息
3. 语气自然，符合游戏氛围
4. 可以表达观点、质疑或辩解

## 输出格式

直接输出发言内容，不要包含任何其他文字。
```

### 7.2 推理分析 (P1)

```
# prompts/reasoning.txt

## 系统角色

你正在玩狼人杀游戏，需要对场上局势进行推理分析。

## 你的身份

- 角色：{role}
- 阵营：{faction}
- 座位号：{my_seat}

## 已知信息

{known_info}

## 当前局势

- 当前轮次：第 {round} 轮
- 存活玩家：{alive_players}
- 死亡记录：{death_log}
- 最近发言：{recent_speeches}
- 投票记录：{vote_history}

## 任务

分析每个存活玩家是狼人的概率（0-100%），并给出理由。

## 输出格式

请按以下格式输出：

玩家 {seat} 号：概率 {probability}%
理由：{reason}

（为每个存活玩家重复以上格式）
```

### 7.3 决策 (P1)

```
# prompts/decision.txt

## 系统角色

你正在玩狼人杀游戏，需要做出一个决策。

## 你的身份

- 角色：{role}
- 阵营：{faction}

## 决策场景

{decision_context}

## 可选项

{available_options}

## 推理结果

{reasoning_result}

## 任务

基于以上信息，选择最佳行动方案。

## 输出格式

选择：{option}
理由：{reason}
```

---

## 8. 日志规范

### 8.1 日志格式

```
[TIMESTAMP] [LEVEL] [TAG] message
```

### 8.2 日志级别

| 级别 | 说明 |
|------|------|
| INFO | 正常运行信息 |
| WARN | 警告（超时、重连） |
| ERROR | 错误 |
| DEBUG | 调试信息 |

### 8.3 日志标签

| TAG | 含义 | 示例 |
|-----|------|------|
| `[EVENT]` | 游戏关键事件 | `[EVENT] 游戏开始，角色=预言家` |
| `[ACTION]` | 行动提交记录 | `[ACTION] 查验 5 号玩家` |
| `[REASON]` | LLM 推理结果 | `[REASON] 5号狼人概率 80%` |
| `[WARN]` | 警告 | `[WARN] 操作超时，降级执行` |
| `[ERROR]` | 错误 | `[ERROR] 连接失败` |

### 8.4 Logger 实现

```python
# logger.py
import logging
from datetime import datetime
from pathlib import Path


class AgentLogger:
    """Agent 日志记录器"""
    
    def __init__(self, log_file: str):
        self.log_file = Path(log_file).expanduser()
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        
        self.logger = logging.getLogger("werewolf-agent")
        self.logger.setLevel(logging.DEBUG)
        
        # 文件处理器
        fh = logging.FileHandler(self.log_file, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        
        # 格式化器
        formatter = logging.Formatter(
            "[%(asctime)s] [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        fh.setFormatter(formatter)
        
        self.logger.addHandler(fh)
    
    def _format_tag(self, tag: str) -> str:
        return f"[{tag}]"
    
    def info(self, message: str):
        self.logger.info(message)
    
    def warn(self, message: str):
        self.logger.warning(self._format_tag("WARN") + " " + message)
    
    def error(self, message: str):
        self.logger.error(self._format_tag("ERROR") + " " + message)
    
    def debug(self, message: str):
        self.logger.debug(message)
    
    def event(self, message: str):
        """记录游戏事件"""
        self.logger.info(self._format_tag("EVENT") + " " + message)
    
    def action(self, message: str):
        """记录行动"""
        self.logger.info(self._format_tag("ACTION") + " " + message)
    
    def reason(self, message: str):
        """记录推理结果"""
        self.logger.info(self._format_tag("REASON") + " " + message)
```

---

## 9. 分阶段交付计划

### 9.1 P0 - MVP（最小可行版本）

**目标**：能跑完一局完整游戏，策略为规则驱动随机。

**交付物**：

| 模块 | 文件 | 说明 |
|------|------|------|
| OpenClaw Skill | `SKILL.md` | 触发词、参数收集、进程管理 |
| Agent 主进程 | `werewolf_agent.py` | 事件处理、行动提交 |
| 规则策略 | `strategy_basic.py` | 随机行动 + 规则约束 |
| 状态管理 | `memory.py` | GameMemory 类 |
| Prompt 模板 | `prompts/speech.txt` | 发言生成模板 |
| 配置 | `config/default.yaml` | 默认配置 |
| 示例 | `examples/start_agent.sh` | 启动脚本 |
| 文档 | `README.md` | 快速开始 |

**验收标准**：

- [ ] 用户说"帮我加入房间 {room_id}"，OpenClaw 能成功启动 Agent 进程
- [ ] Agent 能完成角色认知、夜晚行动、白天发言、投票全流程
- [ ] 所有行动在超时前提交（有默认降级策略）
- [ ] 游戏结束后 OpenClaw 向用户报告结果

**工作量估算**：M (3-5 天)

### 9.2 P1 - 推理增强

**目标**：引入 LLM 推理层，Agent 能基于历史信息做出有策略意义的决策。

**新增交付物**：

| 模块 | 文件 | 说明 |
|------|------|------|
| LLM 策略 | `strategy_llm.py` | LLM 驱动决策 |
| Prompt 模板 | `prompts/reasoning.txt` | 推理分析 |
| Prompt 模板 | `prompts/decision.txt` | 决策 Prompt |

**验收标准**：

- [ ] Agent 能维护每个玩家的身份概率估计并动态更新
- [ ] 发言内容包含推理逻辑（而非随机表态）
- [ ] 规则校验层能拦截明显错误行动

**工作量估算**：M (3-5 天)

### 9.3 P2 - 扩展能力（可选）

**目标**：跨局学习、配置化策略风格、历史回顾。

**新增交付物**：

- 历史对局归档到 OpenClaw Memory
- 策略风格配置（aggressive / conservative / silent）
- 发言风格配置（formal / casual）

**工作量估算**：S (1-3 天)

---

## 10. 前置条件验收

在开始任何代码开发之前，需要验证以下条件均已满足：

### 10.1 werewolf-game 后端可运行

```bash
# 启动后端
cd ~/.openclaw/shared/projects/werewolf-game/repo
docker-compose up -d

# 验证
curl http://localhost:8000/health
# 期望：{"status": "healthy"}

# 访问 API 文档
open http://localhost:8000/docs
```

### 10.2 Python SDK 可用

```bash
# 安装 SDK
pip install werewolf-sdk

# 或从本地安装
pip install ~/.openclaw/shared/projects/werewolf-game/repo/sdk/python/

# 运行示例 Agent
python ~/.openclaw/shared/projects/werewolf-game/repo/examples/random_agent.py
```

### 10.3 Anthropic API Key 可用

```bash
# 设置环境变量
export ANTHROPIC_API_KEY="sk-ant-..."

# 验证
python -c "import anthropic; client = anthropic.Anthropic(); print('OK')"
```

### 10.4 OpenClaw 环境

```bash
# 检查 OpenClaw Gateway 版本
openclaw gateway version

# 确认 workspace/skills 目录可写
touch ~/.openclaw/workspace/skills/.test && rm ~/.openclaw/workspace/skills/.test
```

---

## 11. 约束条件

### 11.1 时间约束

| 操作 | 超时 | 降级策略 |
|------|------|---------|
| 夜晚行动 | ≤ 60s | 随机合法行动 |
| 白天发言 | ≤ 90s | 预设简短发言 |
| 投票 | ≤ 60s | 弃票或随机投票 |
| 单次 LLM 调用 | ≤ 30s | 降级到规则策略 |

### 11.2 API 限流

- Werewolf Arena API：100 req/min per Agent

### 11.3 WebSocket 重连

- 平台支持 120s 重连窗口
- Agent 需在窗口内完成重连

### 11.4 信息隔离

- Agent 进程只访问平台 API 中自己可见的数据字段
- 狼人协作信息只通过 `werewolf.chat` 平台事件通信
- 不得利用侧信道推断他人行动

---

## 12. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| werewolf-game 后端未完成 | Agent 无法运行 | 开发前先跑通示例 Agent |
| LLM 响应超时 | 错过行动时间 | 30s 超时 + 规则策略降级 |
| LLM 生成错误行动 | 不合理决策 | 规则校验层拦截 |
| Token 消耗过高 | 成本过高 | 历史记录截断到 5 轮 |
| WebSocket 断线 | 丢失状态 | 120s 内重连 + 状态同步 |
| 进程崩溃无感知 | 用户不知道 Agent 已停止 | 定期 PID 检查 + 通知 |

---

## 13. 后续优化方向

1. **多模型支持**：支持 OpenAI、本地模型等
2. **策略热更新**：无需重启更新策略参数
3. **对局分析**：自动生成对局分析报告
4. **观战集成**：将 Agent 推理过程暴露给观战系统
5. **团队协作**：多 Agent 协作（狼人团队）

---

## 附录：关键设计决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| Skill 与 Agent 进程的关系 | Skill 通过 bash 启动独立进程 | Skill 无法维持长连接 |
| 狼人夜聊通信 | 使用平台 `werewolf.chat` 事件 | 必须走平台协议 |
| LLM API 调用 | Agent 进程直接调用 Anthropic API | 简单可控 |
| 策略引擎 | 规则驱动（P0）+ LLM 增强（P1） | 渐进式交付 |
| 状态管理 | 进程内 GameMemory + 文件归档 | 单局内存，跨局持久化 |
| 超时降级 | LLM 超时 → 规则策略 → 随机 | 保证不超时 |
