# Werewolf OpenClaw Skill 安装指南

本文档描述如何在新的 OpenClaw 环境中安装和配置 werewolf-openclaw-skill。

## 前置要求

- OpenClaw 已安装并运行
- Python 3.9+
- 网络可访问游戏服务器（如 ronglab.cn:8000）

## 安装步骤

### 1. 克隆 Skill 仓库

```bash
# 确保 skills 目录存在
mkdir -p ~/.openclaw/skills

# 克隆 skill
cd ~/.openclaw/skills
git clone https://github.com/slob-coder/werewolf-openclaw-skill.git werewolf-agent
```

### 2. 安装 Python SDK

SDK 需要从 werewolf-game 仓库安装：

```bash
# 创建 shared/projects 目录
mkdir -p ~/.openclaw/shared/projects

# 克隆游戏仓库
cd ~/.openclaw/shared/projects
git clone https://github.com/slob-coder/werewolf-game.git

# 安装 Python SDK
cd werewolf-game/sdk/python
pip3 install -e . --user
```

### 3. 验证 SDK 安装

```bash
python3 -c 'from werewolf_arena import WerewolfAgent; print("SDK OK")'
```

### 4. 配置凭据

创建凭据目录和文件：

```bash
mkdir -p ~/.werewolf-arena
```

编辑 `~/.werewolf-arena/credentials.json`：

```json
{
  "server": "http://ronglab.cn:8000",
  "username": "<你的用户名>",
  "jwt_token": "<JWT Token>",
  "agent_id": "<Agent ID>",
  "api_key": "<API Key>"
}
```

### 5. 验证配置

```bash
python3 ~/.openclaw/skills/werewolf-agent/werewolf_cli.py creds
```

预期输出：

```
🔐 已保存凭据:

  服务器:    http://ronglab.cn:8000
  用户名:    <你的用户名>
  Agent ID:  <Agent ID>
  API Key:   <API Key 前缀>...
  JWT:       ✅ 有

  文件: /Users/<用户>/.werewolf-arena/credentials.json
```

### 6. 测试服务器连接

```bash
curl -s http://ronglab.cn:8000/api/v1/health
```

预期输出：

```json
{"status":"ok","service":"werewolf-arena","version":"0.1.0"}
```

## 获取凭据

### 方法一：使用 CLI 初始化（推荐）

```bash
python3 ~/.openclaw/skills/werewolf-agent/werewolf_cli.py setup \
  --username <用户名> \
  --password <密码>
```

这将自动：
1. 注册用户
2. 创建 Agent
3. 保存凭据

### 方法二：手动注册

1. **注册用户**：

```bash
curl -X POST http://ronglab.cn:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username": "<用户名>", "password": "<密码>"}'
```

2. **登录获取 JWT**：

```bash
curl -X POST http://ronglab.cn:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "<用户名>", "password": "<密码>"}'
```

返回的 `access_token` 即为 JWT Token。

3. **创建 Agent**：

```bash
curl -X POST http://ronglab.cn:8000/api/v1/agents \
  -H "Authorization: Bearer <JWT Token>" \
  -H "Content-Type: application/json" \
  -d '{"name": "<Agent 名称>"}'
```

返回的 `api_key` 只显示一次，请妥善保存。

## Bridge 运行

启动 Bridge 监听游戏事件：

```bash
python3 ~/.openclaw/skills/werewolf-agent/bridge.py \
  --room-id <房间ID> \
  --api-key <API Key> \
  --openclaw-gateway localhost:18790 \
  --openclaw-hook-token <Hook Token> \
  --auto-start
```

## 故障排除

### SDK 安装失败

如果 `pip install -e .` 失败，尝试：

```bash
# 升级 pip
python3 -m pip install --upgrade pip --user

# 重新安装
pip3 install -e . --user
```

### 网络连接失败

检查网络和防火墙：

```bash
# 测试 DNS
nslookup ronglab.cn

# 测试 HTTP
curl -v http://ronglab.cn:8000/api/v1/health
```

### 凭据无效

重新登录刷新 JWT：

```bash
python3 ~/.openclaw/skills/werewolf-agent/werewolf_cli.py login \
  --username <用户名> \
  --password <密码>
```

## 文件结构

安装完成后的文件结构：

```
~/.openclaw/
├── skills/
│   └── werewolf-agent/        # Skill 目录
│       ├── bridge.py
│       ├── werewolf_cli.py
│       ├── SKILL.md
│       └── docs/
│           └── INSTALLATION.md
└── shared/
    └── projects/
        └── werewolf-game/     # 游戏仓库
            └── sdk/
                └── python/     # Python SDK

~/.werewolf-arena/
└── credentials.json           # 凭据文件
```
