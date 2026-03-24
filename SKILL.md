# Werewolf Arena Agent Skill

> 通过自然语言对话，一键启动智能 Agent 参与狼人杀游戏

## 触发条件

当用户说出以下意图时激活本 Skill：

- "加入狼人杀房间 {room_id}"
- "启动狼人杀 Agent"
- "帮我玩狼人杀"
- "加入 Werewolf Arena"
- 提及房间 ID 格式（如 abc123, room-xxx）
- "开始狼人杀游戏"

## 参数收集

首次使用时，通过对话收集以下参数（后续存入 `~/.openclaw/config/werewolf-agent.yaml`）：

| 参数 | 说明 | 必填 | 默认值 |
|------|------|:----:|--------|
| `room_id` | 房间 ID | ✅ | - |
| `api_key` | Werewolf Arena API Key | ✅ | - |
| `server_url` | 后端地址 | ❌ | localhost:8000 |
| `strategy` | 策略风格 | ❌ | basic |
| `speech_style` | 发言风格 | ❌ | formal |

### 收集流程

1. 检查配置文件 `~/.openclaw/config/werewolf-agent.yaml` 是否存在
2. 若不存在，依次询问必填参数：
   - "请提供房间 ID："
   - "请提供 API Key："
3. 询问可选参数（若用户需要自定义）：
   - "使用默认配置还是自定义？（默认：basic 策略，formal 发言风格）"
4. 保存配置后执行启动命令

## 进程管理

### 启动 Agent

```bash
# 安装依赖（首次运行）
pip install werewolf-sdk anthropic pyyaml 2>/dev/null || true

# 启动 Agent 进程
mkdir -p ~/.openclaw/logs

python ~/.openclaw/workspace/skills/werewolf-agent/werewolf_agent.py \
  --room-id {room_id} \
  --api-key {api_key} \
  --server-url {server_url} \
  --strategy {strategy} \
  --speech-style {speech_style} \
  --log-file ~/.openclaw/logs/werewolf-agent.log \
  > ~/.openclaw/logs/werewolf-agent.log 2>&1 &

# 保存 PID
echo $! > ~/.openclaw/logs/werewolf-agent.pid

echo "✓ Agent 已启动 (PID: $(cat ~/.openclaw/logs/werewolf-agent.pid))"
```

### 查询状态

```bash
# 查询进程是否存活
if [ -f ~/.openclaw/logs/werewolf-agent.pid ]; then
  pid=$(cat ~/.openclaw/logs/werewolf-agent.pid)
  if kill -0 $pid 2>/dev/null; then
    echo "Agent 运行中 (PID: $pid)"
  else
    echo "Agent 已停止"
  fi
else
  echo "未找到 Agent 进程"
fi

# 查询最新事件
tail -20 ~/.openclaw/logs/werewolf-agent.log 2>/dev/null | grep "\[EVENT\]" || echo "暂无事件"

# 查询最近行动
tail -20 ~/.openclaw/logs/werewolf-agent.log 2>/dev/null | grep "\[ACTION\]" || echo "暂无行动"
```

### 停止 Agent

```bash
if [ -f ~/.openclaw/logs/werewolf-agent.pid ]; then
  pid=$(cat ~/.openclaw/logs/werewolf-agent.pid)
  kill $pid 2>/dev/null && echo "✓ Agent 已停止" || echo "Agent 已停止"
  rm ~/.openclaw/logs/werewolf-agent.pid
else
  echo "未找到 Agent 进程"
fi
```

## 状态反馈

向用户展示的信息格式：

| 场景 | 反馈内容 |
|------|---------|
| 启动成功 | ✓ 已加入游戏，等待开始... |
| 游戏开始 | 游戏开始，你的角色是 **{角色名}**（{座位号}号） |
| 夜晚行动 | 🌙 第 {n} 轮夜晚，正在执行 {行动}... |
| 白天发言 | ☀️ 第 {n} 轮发言，已提交发言 |
| 投票完成 | 🗳️ 第 {n} 轮投票，已投票给 {m} 号玩家 |
| 游戏结束 | 🎉 游戏结束，**{阵营}** 获胜！ |
| 进程停止 | ⚠️ Agent 进程已停止运行 |

### 定期检查

当用户询问游戏状态时，执行日志查询并格式化输出：

```bash
# 获取最新状态
tail -50 ~/.openclaw/logs/werewolf-agent.log 2>/dev/null
```

## 配置文件

配置文件位置：`~/.openclaw/config/werewolf-agent.yaml`

```yaml
# Werewolf Arena Agent 配置
api_key: "your-api-key"
server_url: "localhost:8000"
strategy: "basic"
speech_style: "formal"
```

## 使用示例

### 用户：帮我加入房间 abc123

```
Agent 回复：
好的，我来帮你启动狼人杀 Agent。

检查配置... 未找到配置文件。

请提供你的 API Key：
```

### 用户：sk-xxx

```
Agent 回复：
✓ 配置已保存

正在启动 Agent...
✓ Agent 已启动 (PID: 12345)
✓ 已加入房间 abc123，等待游戏开始...

你随时可以问我游戏状态。
```

### 用户：游戏怎么样了？

```
Agent 回复：
让我查一下...

当前状态：
- 第 3 轮
- 你的角色：预言家
- 最近行动：查验了 5 号玩家（好人）

游戏还在进行中，我会继续自动操作。
```

## 注意事项

1. **P0 MVP 阶段**：策略使用规则驱动（随机 + 约束），不调用 LLM
2. **进程管理**：Agent 作为后台进程运行，OpenClaw 通过日志监控状态
3. **断线重连**：若进程崩溃，需要用户手动重新启动
4. **信息隔离**：Agent 只访问自己可见的游戏数据

## 相关文件

- `werewolf_agent.py` - Agent 主进程
- `strategy/basic.py` - 规则驱动策略
- `memory.py` - 游戏状态管理
- `logger.py` - 日志模块
- `config/default.yaml` - 默认配置
