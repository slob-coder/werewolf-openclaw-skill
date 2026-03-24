# Werewolf Arena Agent

> OpenClaw Skill - 通过自然语言对话，一键启动智能 Agent 参与狼人杀游戏

## 快速开始

### 1. 通过 OpenClaw 启动

```
用户：帮我加入房间 abc123
OpenClaw：好的，请提供你的 API Key...
用户：sk-xxx
OpenClaw：✓ Agent 已启动，已加入房间 abc123
```

### 2. 通过命令行启动

```bash
# 安装依赖
pip install pyyaml

# 启动 Agent
./examples/start_agent.sh --room-id abc123 --api-key sk-xxx

# 或直接运行 Python 脚本
python werewolf_agent.py --room-id abc123 --api-key sk-xxx
```

## 项目结构

```
werewolf-agent/
├── SKILL.md              # OpenClaw Skill 核心文件
├── werewolf_agent.py     # Agent 主进程
├── memory.py             # 游戏状态管理
├── logger.py             # 日志模块
├── strategy/
│   ├── __init__.py
│   ├── base.py           # 策略基类
│   ├── basic.py          # 规则驱动策略 (P0)
│   └── validator.py      # 行动校验器
├── prompts/
│   ├── speech.txt        # 发言生成模板
│   ├── reasoning.txt     # 推理分析模板 (P1)
│   └── decision.txt      # 决策模板 (P1)
├── config/
│   └── default.yaml      # 默认配置
├── examples/
│   └── start_agent.sh    # 启动脚本
└── README.md
```

## 功能特性

### P0 - MVP（当前版本）

- ✅ 规则驱动策略（随机 + 约束）
- ✅ 完整的游戏流程支持
- ✅ 行动校验层（防止非法操作）
- ✅ 状态持久化和归档
- ✅ 结构化日志

### P1 - 推理增强（计划中）

- 🔲 LLM 增强策略
- 🔲 身份概率估计
- 🔲 智能发言生成

## 架构说明

```
┌─────────────────────────────────────────────────────────────┐
│                    用户对话层 (OpenClaw)                      │
│                  "帮我加入房间 abc123"                        │
└─────────────────────────────┬───────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                     SKILL.md (OpenClaw)                      │
│              理解意图 → 收集参数 → 调用 bash 工具              │
└─────────────────────────────┬───────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   werewolf_agent.py                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │ Mock SDK     │  │ EventHandler │  │  BasicStrategy   │   │
│  │ (P0)         │──▶│   Router     │──▶│  (规则驱动)      │   │
│  └──────────────┘  └──────────────┘  └────────┬─────────┘   │
│                                               │              │
│                              ┌────────────────▼───────────┐  │
│                              │        GameMemory          │  │
│                              │   (状态管理 + 持久化)       │  │
│                              └────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

## 命令行参数

| 参数 | 说明 | 必填 | 默认值 |
|------|------|:----:|--------|
| `--room-id` | 房间 ID | ✅ | - |
| `--api-key` | API Key | ✅ | - |
| `--server-url` | 服务器地址 | ❌ | localhost:8000 |
| `--strategy` | 策略类型 | ❌ | basic |
| `--speech-style` | 发言风格 | ❌ | formal |
| `--log-file` | 日志文件 | ❌ | ~/.openclaw/logs/werewolf-agent.log |

## 日志格式

```
[2024-03-24 16:00:00] [INFO] [EVENT] 游戏开始，角色=预言家
[2024-03-24 16:00:10] [INFO] [ACTION] 查验 5 号玩家
[2024-03-24 16:01:00] [INFO] [ACTION] 已提交发言: 我是预言家...
[2024-03-24 16:02:00] [INFO] [ACTION] 投票给 7 号玩家
[2024-03-24 16:03:00] [INFO] [EVENT] 游戏结束，好人获胜
```

## 配置文件

配置文件位置：`~/.openclaw/config/werewolf-agent.yaml`

```yaml
api_key: "your-api-key"
server_url: "localhost:8000"
strategy: "basic"
speech_style: "formal"
```

## 开发说明

### 运行测试

```bash
# 验证模块导入
python -c "from memory import GameMemory; print('OK')"
python -c "from strategy import BasicStrategy; print('OK')"
python -c "from logger import AgentLogger; print('OK')"

# 运行 Agent（使用 Mock 客户端）
python werewolf_agent.py --room-id test --api-key test
```

### 添加新策略

1. 继承 `StrategyBase` 类
2. 实现 `night_action`, `generate_speech`, `vote_target` 方法
3. 在 `werewolf_agent.py` 中注册

## 相关链接

- [设计文档](docs/design.md)
- [Werewolf Arena 平台](https://github.com/slob-coder/werewolf-game)
- [OpenClaw](https://github.com/slob-coder/openclaw)

## License

MIT
