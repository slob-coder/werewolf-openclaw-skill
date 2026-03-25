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

from werewolf_arena import Action, ArenaRESTClient, ArenaAPIError, ArenaConnectionError

# ---------------------------------------------------------------------------
# Runtime context
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
# CLI parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="werewolf_cli.py",
        description="Werewolf Arena 业务命令脚本",
    )
    sub = p.add_subparsers(dest="command", help="可用命令")

    # Night actions
    for cmd in ("kill", "check", "guard", "poison", "shoot"):
        sp = sub.add_parser(cmd, help=COMMAND_DESC[cmd])
        sp.add_argument("--target", type=int, required=True, help="目标座位号")

    sub.add_parser("save", help=COMMAND_DESC["save"])
    sub.add_parser("skip", help=COMMAND_DESC["skip"])

    # Speech
    sp = sub.add_parser("speech", help=COMMAND_DESC["speech"])
    sp.add_argument("--content", type=str, required=True, help="发言内容")

    # Vote
    sp = sub.add_parser("vote", help=COMMAND_DESC["vote"])
    vote_group = sp.add_mutually_exclusive_group(required=True)
    vote_group.add_argument("--target", type=int, help="投票目标座位号")
    vote_group.add_argument("--abstain", action="store_true", help="弃票")

    # Query commands
    sub.add_parser("status", help="查看当前游戏状态")
    sub.add_parser("alive", help="查看存活玩家")

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

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
