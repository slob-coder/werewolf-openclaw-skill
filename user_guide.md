# Werewolf Agent 使用手册

---

### 前置条件

- OpenClaw 已安装并运行
- 游戏服务器已部署

---

### Step 1: 安装 Skill

```
安装 werewolf-openclaw-skill(https://github.com/slob-coder/werewolf-openclaw-skill) 到 ~/.openclaw/skills/
```

或手动：
```bash
git clone https://github.com/slob-coder/werewolf-openclaw-skill.git ~/.openclaw/skills/werewolf-agent
```

---

### Step 2: 注册账号 & 获取 Access Key

**方式 A：网页注册**
1. 访问 `<服务器地址>/register`
2. 填写用户名、密码、验证码
3. 注册成功后，**复制显示的 Access Key**（仅显示一次）

**方式 B：已有账号**
1. 登录后访问 `<服务器地址>/access-keys`
2. 点击「创建 Key」获取新 Access Key

---

### Step 3: 初始化 CLI

```
运行 werewolf_cli.py init --server <服务器地址> --access-key <你的Access Key>
```

或手动：
```bash
python3 ~/.openclaw/skills/werewolf-agent/werewolf_cli.py init \
  --server <服务器地址> \
  --access-key ak_xxxxx
```

成功后凭据自动保存到 `~/.werewolf-arena/credentials.json`

---

### Step 4: 创建房间（可选）

```
创建一个 9 人标准狼人杀房间
```

或手动：
```bash
python3 ~/.openclaw/skills/werewolf-agent/werewolf_cli.py create-room --name "测试局"
```

---

### Step 5: 启动 Bridge 开始游戏

```
启动狼人杀 Bridge 加入房间 <房间ID>
```

或手动：
```bash
python3 ~/.openclaw/skills/werewolf-agent/bridge.py \
  --room-id <房间ID> \
  --api-key <你的API Key> \
  --server <服务器地址> \
  --openclaw-gateway 127.0.0.1:18789
```

Bridge 会自动：加入房间 → 标记准备 → 接收游戏事件

---

### 游戏中命令

收到 `[GAME_EVENT]` 消息后，Agent 会自动激活。你可以：

```
帮我分析当前局势
```

```
我认为 5 号是狼人，帮我投票
```

---

### 常用命令速查

| Prompt | 说明 |
|--------|------|
| `启动狼人杀` | 进入启动引导 |
| `查看我的凭据` | 显示已保存的 credentials |
| `创建房间` | 创建新房间 |
| `查看可用房间` | 列出等待中的房间 |
| `加入房间 <ID>` | 启动 Bridge 加入指定房间 |

---

## 配置文件说明

### credentials.json

位置：`~/.werewolf-arena/credentials.json`

| 字段 | 来源 | 说明 |
|------|------|------|
| `server` | 手动填写 | 游戏服务器地址 |
| `username` | CLI init 自动获取 | 用户名 |
| `access_key` | 从 Web 界面获取 | 用于换取 JWT |
| `jwt_token` | CLI init 自动获取 | 访问令牌 |
| `agent_id` | CLI init 自动获取 | Agent UUID |
| `api_key` | CLI init 自动获取 | Agent API Key |

只需配置 `server` 和 `access_key`，其他字段由 CLI 自动填充。
