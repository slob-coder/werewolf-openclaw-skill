#!/usr/bin/env python3
"""
Werewolf Arena — 业务命令脚本

供 OpenClaw Agent 在 SKILL.md 指导下调用。
将高层语义命令（kill/check/vote 等）映射为 SDK Action 并提交。

用法:
    python werewolf_cli.py kill --target 5
    python werewolf_cli.py check --target 3
    python werewolf_cli.py speech --content "我觉得3号可疑"
    python werewolf_cli.py vote --target 7
    python werewolf_cli.py vote --abstain
    python werewolf_cli.py status
    python werewolf_cli.py alive

依赖: pip install werewolf-arena
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import httpx
from werewolf_arena import Action, ArenaRESTClient, ArenaAPIError, ArenaConnectionError

# ---------------------------------------------------------------------------
# Credential store — persistent across sessions
# ---------------------------------------------------------------------------
CRED_DIR = Path.home() / ".werewolf-arena"
CRED_FILE = CRED_DIR / "credentials.json"


def load_creds() -> dict:
    if CRED_FILE.exists():
        return json.loads(CRED_FILE.read_text())
    return {}


def save_creds(creds: dict) -> None:
    CRED_DIR.mkdir(parents=True, exist_ok=True)
    CRED_FILE.write_text(json.dumps(creds, indent=2))
    CRED_FILE.chmod(0o600)


# ---------------------------------------------------------------------------
# Runtime context — written by bridge.py during game
# ---------------------------------------------------------------------------
CONTEXT_DIR = Path("/tmp/werewolf_arena")


def find_context() -> dict:
    """Load the most recent runtime context written by bridge.py."""
    if not CONTEXT_DIR.exists():
        print("❌ 错误: 未找到运行时上下文。请确认 bridge.py 已启动。", file=sys.stderr)
        sys.exit(1)

    files = sorted(CONTEXT_DIR.glob("context_*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
    if not files:
        print("❌ 错误: 无可用上下文文件。请确认 bridge.py 已启动。", file=sys.stderr)
        sys.exit(1)

    ctx = json.loads(files[0].read_text())
    if not ctx.get("game_id"):
        print("❌ 错误: 游戏尚未开始 (game_id 为空)。", file=sys.stderr)
        sys.exit(1)

    return ctx


# ---------------------------------------------------------------------------
# Command → SDK Action mapping
# ---------------------------------------------------------------------------
COMMAND_MAP = {
    "kill":    "werewolf_kill",
    "check":   "seer_check",
    "guard":   "guard_protect",
    "save":    "witch_save",
    "poison":  "witch_poison",
    "skip":    "witch_skip",     # Also used for hunter_skip, resolved by context
    "shoot":   "hunter_shoot",
    "speech":  "speech",
    "vote":    "vote",
}

# Commands that require --target
TARGET_REQUIRED = {"kill", "check", "guard", "poison", "shoot", "vote"}

# Commands with no target
NO_TARGET = {"save", "skip"}

# Human-readable descriptions
COMMAND_DESC = {
    "kill":    "狼人击杀",
    "check":   "预言家查验",
    "guard":   "守卫守护",
    "save":    "女巫使用解药",
    "poison":  "女巫使用毒药",
    "skip":    "跳过行动",
    "shoot":   "猎人开枪",
    "speech":  "发言",
    "vote":    "投票",
}


async def submit(ctx: dict, action: Action) -> None:
    """Submit an action via SDK REST client."""
    client = ArenaRESTClient(ctx["server_url"], ctx["api_key"])
    try:
        result = await client.submit_action(ctx["game_id"], action)
        if result.get("success"):
            print(f"✅ 行动成功: {COMMAND_DESC.get(action.action_type, action.action_type)}", end="")
            if action.target is not None:
                print(f" → 目标 {action.target} 号", end="")
            if action.content:
                preview = action.content[:40] + ("..." if len(action.content) > 40 else "")
                print(f" → \"{preview}\"", end="")
            print()
        else:
            msg = result.get("message", "未知错误")
            print(f"❌ 行动失败: {msg}")
    except ArenaAPIError as e:
        print(f"❌ API 错误 ({e.status_code}): {e.detail}")
    except ArenaConnectionError as e:
        print(f"❌ 连接错误: {e}")
    except Exception as e:
        print(f"❌ 未知错误: {e}")
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# Pre-submission validation
# ---------------------------------------------------------------------------

def validate(cmd: str, target: int | None, ctx: dict) -> str | None:
    """Return error message if invalid, else None."""
    alive = ctx.get("alive_players", [])
    my_seat = ctx.get("my_seat")
    my_role = ctx.get("my_role", "")

    if cmd in TARGET_REQUIRED and target is None:
        return f"命令 {cmd} 需要 --target 参数"

    if target is not None and target not in alive and cmd != "vote":
        return f"目标 {target} 号不在存活玩家列表中: {alive}"

    if cmd == "kill" and target == my_seat:
        return "狼人不能击杀自己"

    if cmd == "poison" and target == my_seat:
        return "女巫不能毒杀自己"

    if cmd == "check" and my_role != "seer":
        return f"你的角色是 {my_role}，不是预言家，不能查验"

    if cmd == "kill" and my_role != "werewolf":
        return f"你的角色是 {my_role}，不是狼人，不能击杀"

    if cmd in ("save", "poison", "skip") and my_role not in ("witch", "hunter"):
        if my_role != "witch" and cmd in ("save", "poison"):
            return f"你的角色是 {my_role}，不是女巫"

    if cmd == "guard" and my_role != "guard":
        return f"你的角色是 {my_role}，不是守卫，不能守护"

    if cmd == "shoot" and my_role != "hunter":
        return f"你的角色是 {my_role}，不是猎人，不能开枪"

    return None


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def handle_status(ctx: dict) -> None:
    """Print current game status."""
    print(f"🎮 游戏状态")
    print(f"  Game ID:  {ctx.get('game_id', '?')}")
    print(f"  你的座位: {ctx.get('my_seat', '?')} 号")
    print(f"  你的角色: {ctx.get('my_role', '?')}")
    print(f"  当前轮次: 第 {ctx.get('current_round', '?')} 轮")
    print(f"  存活玩家: {ctx.get('alive_players', [])}")
    print(f"  死亡玩家: {ctx.get('dead_players', [])}")
    teammates = ctx.get("teammates", [])
    if teammates:
        print(f"  狼人队友: {teammates}")
    seer = ctx.get("seer_results", {})
    if seer:
        print(f"  查验记录: {seer}")


def handle_alive(ctx: dict) -> None:
    """Print alive players."""
    alive = ctx.get("alive_players", [])
    my_seat = ctx.get("my_seat")
    print(f"存活玩家 ({len(alive)}人): ", end="")
    parts = []
    for s in alive:
        marker = " ← 你" if s == my_seat else ""
        parts.append(f"{s}号{marker}")
    print(", ".join(parts))


async def handle_action(cmd: str, args: argparse.Namespace, ctx: dict) -> None:
    """Handle action commands."""
    target = getattr(args, "target", None)
    content = getattr(args, "content", None)
    abstain = getattr(args, "abstain", False)

    # Vote abstain
    if cmd == "vote" and abstain:
        action = Action(action_type="vote_abstain")
        await submit(ctx, action)
        return

    # Validate
    error = validate(cmd, target, ctx)
    if error:
        print(f"⚠️ 验证失败: {error}")
        return

    # Resolve skip → witch_skip or hunter_skip based on role
    action_type = COMMAND_MAP[cmd]
    if cmd == "skip" and ctx.get("my_role") == "hunter":
        action_type = "hunter_skip"

    # Build action
    action = Action(action_type=action_type)
    if target is not None:
        action.target = target
    if content is not None:
        action.content = content

    await submit(ctx, action)


# ---------------------------------------------------------------------------
# Setup & Room management (no bridge needed, uses REST directly)
# ---------------------------------------------------------------------------

def _get_server(args) -> str:
    server = getattr(args, "server", None)
    if not server:
        creds = load_creds()
        server = creds.get("server", "http://localhost:8000")
    return server.rstrip("/")


async def handle_setup(args: argparse.Namespace) -> None:
    """One-time setup: register user → login → create agent → save all."""
    server = _get_server(args)
    base = f"{server}/api/v1"

    async with httpx.AsyncClient() as http:
        # Step 1: Register user
        username = args.username
        password = args.password
        print(f"📝 注册用户 {username}...")
        try:
            resp = await http.post(f"{base}/auth/register", json={
                "username": username, "password": password,
            })
            if resp.status_code == 201:
                user = resp.json()
                print(f"✅ 用户注册成功: {user.get('id', '?')}")
            elif resp.status_code == 400 and "already" in resp.text.lower():
                print(f"ℹ️  用户 {username} 已存在，跳过注册")
            else:
                print(f"❌ 注册失败: {resp.text}")
                return
        except Exception as e:
            print(f"❌ 连接失败: {e}")
            return

        # Step 2: Login
        print(f"🔑 登录...")
        resp = await http.post(f"{base}/auth/login", json={
            "username": username, "password": password,
        })
        if resp.status_code != 200:
            print(f"❌ 登录失败: {resp.text}")
            return
        jwt_token = resp.json().get("access_token")
        print(f"✅ 登录成功")

        # Step 3: Create agent
        agent_name = args.agent_name or f"{username}-agent"
        print(f"🤖 创建 Agent: {agent_name}...")
        resp = await http.post(f"{base}/agents", json={
            "name": agent_name,
            "description": f"OpenClaw Werewolf Agent ({username})",
        }, headers={"Authorization": f"Bearer {jwt_token}"})

        if resp.status_code != 201:
            print(f"❌ 创建 Agent 失败: {resp.text}")
            return
        agent_data = resp.json()
        api_key = agent_data.get("api_key")
        agent_id = agent_data.get("id")
        print(f"✅ Agent 创建成功")
        print(f"   Agent ID:  {agent_id}")
        print(f"   API Key:   {api_key}")
        print(f"   ⚠️  API Key 仅显示一次，请妥善保存！")

        # Save credentials
        creds = {
            "server": server,
            "username": username,
            "jwt_token": jwt_token,
            "agent_id": agent_id,
            "api_key": api_key,
        }
        save_creds(creds)
        print(f"\n✅ 凭据已保存到 {CRED_FILE}")
        print(f"   后续命令将自动使用这些凭据。")


async def handle_login(args: argparse.Namespace) -> None:
    """Login to refresh JWT token."""
    server = _get_server(args)
    base = f"{server}/api/v1"

    async with httpx.AsyncClient() as http:
        resp = await http.post(f"{base}/auth/login", json={
            "username": args.username, "password": args.password,
        })
        if resp.status_code != 200:
            print(f"❌ 登录失败: {resp.text}")
            return
        jwt_token = resp.json().get("access_token")
        creds = load_creds()
        creds["jwt_token"] = jwt_token
        creds["server"] = server
        creds["username"] = args.username
        save_creds(creds)
        print(f"✅ 登录成功，token 已更新")


async def refresh_jwt_by_access_key(server: str, access_key: str) -> str | None:
    """Exchange access_key for JWT token."""
    base = f"{server}/api/v1"
    async with httpx.AsyncClient() as http:
        try:
            resp = await http.post(f"{base}/auth/token-by-access-key", json={
                "access_key": access_key,
            })
            if resp.status_code == 200:
                return resp.json().get("access_token")
            else:
                print(f"❌ Access Key 认证失败: {resp.text}")
                return None
        except Exception as e:
            print(f"❌ 连接失败: {e}")
            return None


async def handle_init(args: argparse.Namespace) -> None:
    """Initialize with access_key: get JWT → create/get agent → save credentials."""
    server = args.server.rstrip("/")
    access_key = args.access_key
    base = f"{server}/api/v1"

    async with httpx.AsyncClient() as http:
        # Step 1: Exchange access_key for JWT
        print(f"🔑 使用 Access Key 认证...")
        jwt_token = await refresh_jwt_by_access_key(server, access_key)
        if not jwt_token:
            return
        print(f"✅ 认证成功")

        # Step 2: Get user info
        print(f"📋 获取用户信息...")
        resp = await http.get(f"{base}/auth/me", headers={"Authorization": f"Bearer {jwt_token}"})
        if resp.status_code != 200:
            print(f"❌ 获取用户信息失败: {resp.text}")
            return
        user = resp.json()
        username = user.get("username", "unknown")
        print(f"✅ 用户: {username}")

        # Step 3: Check if agent already configured
        creds = load_creds()
        existing_agent_id = creds.get("agent_id")

        if existing_agent_id:
            # Verify the agent exists and belongs to this user
            resp = await http.get(f"{base}/agents/{existing_agent_id}",
                                   headers={"Authorization": f"Bearer {jwt_token}"})
            if resp.status_code == 200:
                agent_data = resp.json()
                api_key = agent_data.get("api_key") or creds.get("api_key")
                print(f"✅ 使用已有 Agent: {existing_agent_id}")
            else:
                # Agent not found, create new one
                existing_agent_id = None

        if not existing_agent_id:
            # Step 4: List existing agents or create new one
            print(f"🤖 查找/创建 Agent...")
            resp = await http.get(f"{base}/agents", headers={"Authorization": f"Bearer {jwt_token}"})
            agents = resp.json() if resp.status_code == 200 else []

            if agents:
                # Use first existing agent
                agent_data = agents[0]
                agent_id = agent_data.get("id")
                api_key = agent_data.get("api_key")
                print(f"✅ 使用已有 Agent: {agent_id}")
            else:
                # Create new agent
                agent_name = args.agent_name or f"{username}-agent"
                resp = await http.post(f"{base}/agents", json={
                    "name": agent_name,
                    "description": f"OpenClaw Werewolf Agent ({username})",
                }, headers={"Authorization": f"Bearer {jwt_token}"})

                if resp.status_code != 201:
                    print(f"❌ 创建 Agent 失败: {resp.text}")
                    return
                agent_data = resp.json()
                agent_id = agent_data.get("id")
                api_key = agent_data.get("api_key")
                print(f"✅ Agent 创建成功")
                print(f"   Agent ID:  {agent_id}")
                print(f"   API Key:   {api_key}")
                print(f"   ⚠️  API Key 仅显示一次，请妥善保存！")

            existing_agent_id = agent_id

        # Step 5: Save credentials
        creds = {
            "server": server,
            "username": username,
            "access_key": access_key,
            "jwt_token": jwt_token,
            "agent_id": existing_agent_id,
            "api_key": api_key,
        }
        save_creds(creds)
        print(f"\n✅ 凭据已保存到 {CRED_FILE}")
        print(f"   后续命令将自动使用这些凭据。")


async def handle_create_room(args: argparse.Namespace) -> None:
    """Create a game room (requires JWT)."""
    creds = load_creds()
    jwt_token = creds.get("jwt_token")
    access_key = creds.get("access_key")
    if not jwt_token:
        print("❌ 未登录。请先执行: werewolf_cli.py init --access-key <your_access_key>")
        return

    server = _get_server(args)
    base = f"{server}/api/v1"
    name = args.name or "OpenClaw 狼人杀"
    preset = args.preset or "standard_9"
    player_count = args.players or 9

    async with httpx.AsyncClient() as http:
        resp = await http.post(f"{base}/rooms", json={
            "name": name,
            "player_count": player_count,
            "role_preset": preset,
            "auto_start": True,
        }, headers={"Authorization": f"Bearer {jwt_token}"})

        # Auto-refresh JWT if expired
        if resp.status_code == 401 and access_key:
            print("🔄 JWT 已过期，使用 Access Key 刷新...")
            jwt_token = await refresh_jwt_by_access_key(server, access_key)
            if jwt_token:
                creds["jwt_token"] = jwt_token
                save_creds(creds)
                resp = await http.post(f"{base}/rooms", json={
                    "name": name,
                    "player_count": player_count,
                    "role_preset": preset,
                    "auto_start": True,
                }, headers={"Authorization": f"Bearer {jwt_token}"})

        if resp.status_code == 201:
            room = resp.json()
            room_id = room.get("id")
            print(f"✅ 房间创建成功")
            print(f"   房间 ID:   {room_id}")
            print(f"   房间名:    {room.get('name')}")
            print(f"   人数:      {room.get('player_count')}")
            print(f"\n   下一步 — 启动 Bridge 加入游戏:")
            api_key = creds.get("api_key", "<你的API Key>")
            print(f"   python3 bridge.py --room-id {room_id} --api-key {api_key} ...")
        elif resp.status_code == 401:
            print("❌ 认证失败。请执行: werewolf_cli.py init --access-key <your_access_key>")
        else:
            print(f"❌ 创建失败 ({resp.status_code}): {resp.text}")


async def handle_list_rooms(args: argparse.Namespace) -> None:
    """List available rooms."""
    server = _get_server(args)
    base = f"{server}/api/v1"

    async with httpx.AsyncClient() as http:
        params = {}
        if args.status:
            params["status"] = args.status
        resp = await http.get(f"{base}/rooms", params=params)
        if resp.status_code != 200:
            print(f"❌ 查询失败: {resp.text}")
            return
        rooms = resp.json()

    if not rooms:
        print("📭 没有可用房间。使用 create-room 创建一个。")
        return

    print(f"🏠 房间列表 ({len(rooms)} 个):\n")
    for r in rooms:
        status_emoji = {
            "open": "🟢", "full": "🟡", "in_progress": "🔴", "finished": "⚫"
        }.get(r.get("status", ""), "⚪")
        print(f"  {status_emoji} {r.get('id', '?')[:8]}...  "
              f"{r.get('name', '?'):20s}  "
              f"{r.get('current_players', 0)}/{r.get('player_count', '?')}人  "
              f"({r.get('status', '?')})")


async def handle_show_creds(_args: argparse.Namespace) -> None:
    """Show saved credentials."""
    creds = load_creds()
    if not creds:
        print("📭 未找到凭据。请先执行: werewolf_cli.py init --access-key <your_access_key>")
        return
    print("🔐 已保存凭据:\n")
    print(f"  服务器:    {creds.get('server', '?')}")
    print(f"  用户名:    {creds.get('username', '?')}")
    access_key = creds.get("access_key", "")
    if access_key:
        masked = access_key[:8] + "..." + access_key[-4:] if len(access_key) > 12 else access_key
        print(f"  Access Key: {masked}")
    print(f"  Agent ID:  {creds.get('agent_id', '?')}")
    api_key = creds.get("api_key", "")
    masked = api_key[:8] + "..." + api_key[-4:] if len(api_key) > 12 else api_key
    print(f"  API Key:   {masked}")
    print(f"  JWT:       {'✅ 有' if creds.get('jwt_token') else '❌ 无'}")
    print(f"\n  文件: {CRED_FILE}")


# ---------------------------------------------------------------------------
# CLI parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="werewolf_cli.py",
        description="Werewolf Arena 业务命令脚本",
    )
    p.add_argument("--server", default=None, help="游戏服务器地址 (默认从凭据读取)")
    sub = p.add_subparsers(dest="command", help="可用命令")

    # ── Setup commands (no bridge needed) ──

    sp = sub.add_parser("init", help="使用 Access Key 初始化: 获取 JWT → 创建/获取 Agent → 保存凭据")
    sp.add_argument("--server", required=True, help="游戏服务器地址")
    sp.add_argument("--access-key", required=True, help="用户 Access Key (从 Web 界面获取)")
    sp.add_argument("--agent-name", default=None, help="Agent 名称 (默认: 用户名-agent)")

    sp = sub.add_parser("setup", help="[已废弃] 旧版初始化命令，请使用 init")
    sp.add_argument("--username", required=True, help="用户名")
    sp.add_argument("--password", required=True, help="密码")
    sp.add_argument("--agent-name", default=None, help="Agent 名称 (默认: 用户名-agent)")

    sp = sub.add_parser("login", help="[已废弃] 旧版登录命令，请使用 init")
    sp.add_argument("--username", required=True, help="用户名")
    sp.add_argument("--password", required=True, help="密码")

    sp = sub.add_parser("create-room", help="创建游戏房间")
    sp.add_argument("--name", default=None, help="房间名称")
    sp.add_argument("--preset", default="standard_9",
                    help="角色预设 (standard_9/standard_12/guard_9)")
    sp.add_argument("--players", type=int, default=None, help="玩家人数")

    sp = sub.add_parser("list-rooms", help="查看可用房间")
    sp.add_argument("--status", default=None, help="按状态过滤 (open/full/in_progress)")

    sub.add_parser("creds", help="查看已保存的凭据")

    # ── Game action commands (bridge must be running) ──

    for cmd in ("kill", "check", "guard", "poison", "shoot"):
        sp = sub.add_parser(cmd, help=COMMAND_DESC[cmd])
        sp.add_argument("--target", type=int, required=True, help="目标座位号")

    sub.add_parser("save", help=COMMAND_DESC["save"])
    sub.add_parser("skip", help=COMMAND_DESC["skip"])

    sp = sub.add_parser("speech", help=COMMAND_DESC["speech"])
    sp.add_argument("--content", type=str, required=True, help="发言内容")

    sp = sub.add_parser("vote", help=COMMAND_DESC["vote"])
    vote_group = sp.add_mutually_exclusive_group(required=True)
    vote_group.add_argument("--target", type=int, help="投票目标座位号")
    vote_group.add_argument("--abstain", action="store_true", help="弃票")

    # ── Query commands ──
    sub.add_parser("status", help="查看当前游戏状态")
    sub.add_parser("alive", help="查看存活玩家")

    return p


# Commands that don't need bridge/game context
SETUP_COMMANDS = {"init", "setup", "login", "create-room", "list-rooms", "creds"}
QUERY_COMMANDS = {"status", "alive"}
ACTION_COMMANDS = set(COMMAND_MAP.keys()) | {"save", "skip"}


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Setup commands — no bridge needed
    if args.command == "init":
        asyncio.run(handle_init(args))
        return
    if args.command == "setup":
        print("⚠️  setup 命令已废弃，请使用: werewolf_cli.py init --server <url> --access-key <key>")
        asyncio.run(handle_setup(args))
        return
    if args.command == "login":
        print("⚠️  login 命令已废弃，请使用: werewolf_cli.py init --server <url> --access-key <key>")
        asyncio.run(handle_login(args))
        return
    if args.command == "create-room":
        asyncio.run(handle_create_room(args))
        return
    if args.command == "list-rooms":
        asyncio.run(handle_list_rooms(args))
        return
    if args.command == "creds":
        asyncio.run(handle_show_creds(args))
        return

    # Game commands — need bridge context
    ctx = find_context()

    if args.command == "status":
        handle_status(ctx)
        return
    if args.command == "alive":
        handle_alive(ctx)
        return

    asyncio.run(handle_action(args.command, args, ctx))


if __name__ == "__main__":
    main()
