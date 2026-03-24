# Werewolf OpenClaw Skill

> OpenClaw Skill for AI Agent 接入 Werewolf Arena 狼人杀平台

## 简介

本项目为 [Werewolf Arena](https://github.com/slob-coder/werewolf-game) 提供 OpenClaw Skill 接入能力，让用户通过自然语言对话即可启动智能 Agent 参与狼人杀游戏。

### 特性

- 🎯 **自然语言触发**: "帮我加入房间 abc123" 即可启动
- 🤖 **LLM 驱动推理**: 智能分析局势、生成发言、决策投票
- 🔄 **完整游戏流程**: 支持所有角色和游戏阶段
- 📊 **状态持久化**: 游戏历史归档到 OpenClaw Memory

## 快速开始

### 前置条件

1. OpenClaw Gateway 运行中
2. Werewolf Arena 后端已部署
3. Anthropic API Key

### 安装

```bash
# 将 Skill 安装到 OpenClaw
cp -r . ~/.openclaw/workspace/skills/werewolf-agent/

# 安装 Python 依赖
pip install werewolf-sdk anthropic
```

### 使用

在 OpenClaw 对话中：

```
用户: 帮我加入狼人杀房间 test-room-123
Agent: ✓ 已加入游戏，等待开始...
       你的角色是 **预言家**
```

## 项目结构

```
werewolf-openclaw-skill/
├── SKILL.md              # OpenClaw Skill 定义
├── werewolf_agent.py     # Agent 主进程
├── strategy_basic.py     # 规则驱动策略
├── strategy_llm.py       # LLM 增强策略
├── memory.py             # 游戏状态管理
├── prompts/              # Prompt 模板
│   ├── speech.txt
│   ├── reasoning.txt
│   └── decision.txt
└── examples/             # 示例脚本
    └── start_agent.sh
```

## 开发

### 运行测试

```bash
# 单元测试
pytest tests/

# 手动测试
python werewolf_agent.py --room-id test --api-key YOUR_KEY
```

### 调试

```bash
# 查看实时日志
tail -f ~/.openclaw/logs/werewolf-agent.log

# 查询 Agent 状态
cat ~/.openclaw/logs/werewolf-agent.pid
```

## 架构

```
OpenClaw 对话 ──► SKILL.md ──► bash 工具 ──► werewolf_agent.py
                      │                           │
                      │                           ├── WebSocket 连接
                      │                           ├── 事件处理
                      │                           └── LLM 推理
                      │
                      └── 日志查询 ──◄── 状态报告
```

## 分阶段交付

| 阶段 | 功能 | 状态 |
|------|------|------|
| P0 | 规则驱动 + LLM 发言 | 🚧 开发中 |
| P1 | LLM 推理决策 | 📋 计划中 |
| P2 | 跨局学习、风格配置 | 📋 计划中 |

## 相关项目

- [Werewolf Arena](https://github.com/slob-coder/werewolf-game) - 狼人杀游戏平台
- [OpenClaw](https://openclaw.ai) - AI Agent 平台

## 许可证

MIT

---

*更多信息请参阅 [AGENTS.md](./AGENTS.md)*
