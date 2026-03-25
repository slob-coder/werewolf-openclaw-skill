#!/usr/bin/env python3
"""
Werewolf Arena — Webhook Bridge (V2)

无状态 I/O 桥接器：WebSocket ↔ OpenClaw Webhook。
不调用 LLM、不做推理、不生成发言。所有智能由 OpenClaw Agent 提供。

依赖: pip install httpx websockets
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import random
import re
import sys
from dataclasses import dataclass, field

import httpx
import websockets

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("ws_bridge")

# ---------------------------------------------------------------------------
# BridgeContext — 最小游戏状态（仅用于降级和事件格式化）
# ---------------------------------------------------------------------------

@dataclass
class BridgeContext:
    room_id: str
    my_seat: int = 0
    my_role: str = ""
    alive_players: list[int] = field(default_factory=list)
    dead_players: list[int] = field(default_factory=list)
    teammates: list[int] = field(default_factory=list)
    checked_players: list[int] = field(default_factory=list)
    last_guarded: int | None = None
    current_round: int = 0


# ---------------------------------------------------------------------------
# Event formatting — 将游戏事件转为 [GAME_EVENT] 结构化自然语言
# ---------------------------------------------------------------------------

def _decision_prompt(action_type: str) -> str:
    return (
        "\n请分析当前局势，然后在回复的最后输出你的决策，格式：\n"
        "```json\n"
        f'{{"action": "{action_type}", "target": <player_number>}}\n'
        "```"
    )

SPEECH_PROMPT = (
    "\n请生成你的发言内容。注意：\n"
    "1. 发言必须符合你的角色视角，不能透露不可能知道的信息\n"
    "2. 在回复的最后输出发言，格式：\n"
    "```json\n"
    '{"action": "speech", "content": "你的发言内容"}\n'
    "```"
)

VOTE_PROMPT = (
    "\n请分析谁最可疑，然后输出投票决策：\n"
    "```json\n"
    '{"action": "vote", "target": <player_number>}\n'
    "```\n"
    "可以投 0 表示弃权。"
)

ACTION_MAP = {
    "werewolf": "kill",
    "seer": "check",
    "guard": "guard",
    "witch": "use_potion",
}


def format_event(event_type: str, data: dict, ctx: BridgeContext) -> tuple[str, bool]:
    """Return (formatted_message, need_response)."""

    if event_type == "game.start":
        teammates_info = f"\n已知队友（狼人同伴）: {ctx.teammates}" if ctx.teammates else ""
        return (
            f"[GAME_EVENT] game.start\n"
            f"游戏开始！\n"
            f"你的座位号: {ctx.my_seat}\n"
            f"你的角色: {ctx.my_role}\n"
            f"所有玩家: {ctx.alive_players}"
            f"{teammates_info}\n\n"
            f"请确认收到并做好准备。无需回复 JSON。"
        ), False

    if event_type == "phase.night":
        action_type = ACTION_MAP.get(ctx.my_role, "pass")
        role_action = {
            "werewolf": "选择一名玩家击杀",
            "seer": "选择一名玩家查验身份",
            "witch": "决定是否使用解药/毒药（pass 表示不使用）",
            "guard": "选择一名玩家守护（不能连续守同一人）",
        }.get(ctx.my_role, "等待天亮（无需行动）")

        dead_info = f"\n已死亡: {ctx.dead_players}" if ctx.dead_players else ""
        prompt = _decision_prompt(action_type) if ctx.my_role in ACTION_MAP else ""
        need_resp = ctx.my_role in ACTION_MAP
        return (
            f"[GAME_EVENT] phase.night (第 {ctx.current_round} 轮)\n"
            f"当前阶段: 夜晚行动\n"
            f"你的角色: {ctx.my_role}\n"
            f"存活玩家: {ctx.alive_players}"
            f"{dead_info}\n"
            f"需要你执行: {role_action}\n"
            f"响应截止: {data.get('deadline', 60)} 秒"
            f"{prompt}"
        ), need_resp

    if event_type == "phase.day.speech":
        speeches = data.get("speeches", [])
        speech_lines = "\n".join(
            f"  - {s['player']}号: \"{s['content']}\"" for s in speeches
        ) if speeches else "  （暂无发言）"
        return (
            f"[GAME_EVENT] phase.day.speech (第 {ctx.current_round} 轮)\n"
            f"当前阶段: 白天发言\n"
            f"轮到你发言。\n"
            f"本轮已有发言:\n{speech_lines}\n"
            f"存活玩家: {ctx.alive_players}\n"
            f"响应截止: {data.get('deadline', 90)} 秒"
            f"{SPEECH_PROMPT}"
        ), True

    if event_type == "phase.day.vote":
        speeches = data.get("speeches", [])
        speech_lines = "\n".join(
            f"  - {s['player']}号: \"{s['content']}\"" for s in speeches
        ) if speeches else "  （无发言记录）"
        vote_history = data.get("vote_history", [])
        vote_lines = "\n".join(
            f"  - 第{v['round']}轮: {v['summary']}" for v in vote_history
        ) if vote_history else "  （无历史投票）"
        return (
            f"[GAME_EVENT] phase.day.vote (第 {ctx.current_round} 轮)\n"
            f"当前阶段: 投票阶段\n"
            f"存活玩家: {ctx.alive_players}\n"
            f"本轮发言回顾:\n{speech_lines}\n"
            f"历史投票记录:\n{vote_lines}\n"
            f"响应截止: {data.get('deadline', 60)} 秒"
            f"{VOTE_PROMPT}"
        ), True

    if event_type == "werewolf.chat":
        return (
            f"[GAME_EVENT] werewolf.chat\n"
            f"狼人队友 {data.get('player', '?')} 号说: \"{data.get('message', '')}\"\n\n"
            f"请记住这条信息用于后续决策。无需回复 JSON。"
        ), False

    if event_type == "night.result":
        parts = [f"[GAME_EVENT] night.result (第 {ctx.current_round} 轮)"]
        # 查验结果（仅预言家）
        check = data.get("check_result")
        if check:
            parts.append(f"查验结果: {check['target']}号是【{check['identity']}】")
        # 守护结果（仅守卫）
        guard = data.get("guard_result")
        if guard:
            parts.append(f"你守护了 {guard['target']} 号")
        # 女巫行动结果
        witch = data.get("witch_result")
        if witch:
            parts.append(f"女巫行动: {witch.get('summary', '无')}")
        # 昨夜死亡
        deaths = data.get("deaths", [])
        if deaths:
            death_info = ", ".join(f"{d['player']}号" for d in deaths)
            parts.append(f"昨夜死亡: {death_info}")
        else:
            parts.append("昨夜平安夜，无人死亡。")
        parts.append("\n请记录以上信息。无需回复 JSON。")
        return "\n".join(parts), False

    if event_type == "player.death":
        player = data.get("player", "?")
        reason = data.get("reason", "未知原因")
        role_reveal = data.get("role", "")
        parts = [
            f"[GAME_EVENT] player.death",
            f"玩家 {player} 号死亡。原因: {reason}。",
        ]
        if role_reveal:
            parts.append(f"身份揭示: {player}号是【{role_reveal}】")
        # 猎人开枪
        hunter_shot = data.get("hunter_shot")
        if hunter_shot:
            parts.append(f"猎人 {player} 号发动技能，带走了 {hunter_shot} 号！")
        parts.append("\n请记录这个信息。无需回复 JSON。")
        return "\n".join(parts), False

    if event_type == "game.end":
        players_info = data.get("players", [])
        player_lines = "\n".join(
            f"  - {p['seat']}号: {p['role']} ({p['faction']})" for p in players_info
        ) if players_info else "  （无玩家信息）"
        alive_status = "存活" if ctx.my_seat in ctx.alive_players else "已死亡"
        return (
            f"[GAME_EVENT] game.end\n"
            f"游戏结束！\n"
            f"获胜阵营: {data.get('winner', '未知')}\n"
            f"你的角色: {ctx.my_role}\n"
            f"你的存活状态: {alive_status}\n"
            f"最终玩家身份:\n{player_lines}\n\n"
            f"请对本局做一个简短复盘总结。无需回复 JSON。"
        ), False

    # 未知事件类型 — 原样转发
    return (
        f"[GAME_EVENT] {event_type}\n"
        f"数据: {json.dumps(data, ensure_ascii=False)}\n\n"
        f"无需回复 JSON。"
    ), False


# ---------------------------------------------------------------------------
# Context update — 从游戏事件被动更新 BridgeContext
# ---------------------------------------------------------------------------

def update_context(ctx: BridgeContext, event_type: str, data: dict) -> None:
    if event_type == "game.start":
        ctx.my_seat = data.get("seat", 0)
        ctx.my_role = data.get("role", "")
        ctx.alive_players = data.get("players", [])
        ctx.teammates = data.get("teammates", [])

    elif event_type == "phase.night":
        ctx.current_round = data.get("round", ctx.current_round + 1)

    elif event_type == "night.result":
        check = data.get("check_result")
        if check and check["target"] not in ctx.checked_players:
            ctx.checked_players.append(check["target"])

    elif event_type == "player.death":
        player = data.get("player")
        if player and player in ctx.alive_players:
            ctx.alive_players.remove(player)
        if player and player not in ctx.dead_players:
            ctx.dead_players.append(player)
        # 猎人带走的人
        hunter_shot = data.get("hunter_shot")
        if hunter_shot:
            if hunter_shot in ctx.alive_players:
                ctx.alive_players.remove(hunter_shot)
            if hunter_shot not in ctx.dead_players:
                ctx.dead_players.append(hunter_shot)


# ---------------------------------------------------------------------------
# Response parsing — 双重 JSON 解析
# ---------------------------------------------------------------------------

def extract_decision(reply: str) -> dict | None:
    """从 Agent 回复中提取最后一个 JSON 决策块。"""
    # 优先：```json ... ``` 代码块
    code_blocks = re.findall(r"```json\s*\n?(.*?)\n?\s*```", reply, re.DOTALL)
    if code_blocks:
        try:
            return json.loads(code_blocks[-1].strip())
        except json.JSONDecodeError:
            pass
    # 降级：最后一个 {...}
    json_blocks = re.findall(r"\{[^{}]+\}", reply)
    if json_blocks:
        try:
            return json.loads(json_blocks[-1])
        except json.JSONDecodeError:
            pass
    return None


# ---------------------------------------------------------------------------
# Fallback — 纯规则驱动超时降级
# ---------------------------------------------------------------------------

def fallback_action(event_type: str, ctx: BridgeContext) -> dict:
    """零智能降级策略，仅保证行动合法。"""
    alive = ctx.alive_players or [1]

    if event_type == "night":
        role = ctx.my_role
        if role == "werewolf":
            candidates = [p for p in alive if p not in ctx.teammates] or alive
            return {"action": "kill", "target": random.choice(candidates)}
        if role == "seer":
            candidates = [
                p for p in alive
                if p not in ctx.checked_players and p != ctx.my_seat
            ] or [p for p in alive if p != ctx.my_seat] or alive
            return {"action": "check", "target": random.choice(candidates)}
        if role == "witch":
            return {"action": "pass"}
        if role == "guard":
            candidates = [p for p in alive if p != ctx.last_guarded] or alive
            return {"action": "guard", "target": random.choice(candidates)}
        return {"action": "pass"}

    if event_type == "vote":
        candidates = [p for p in alive if p != ctx.my_seat] or alive
        return {"action": "vote", "target": random.choice(candidates)}

    if event_type == "speech":
        return {"action": "speech", "content": "我还在观察，暂时没有更多信息分享。"}

    return {"action": "pass"}


# ---------------------------------------------------------------------------
# Webhook POST — 串行发送到 OpenClaw Gateway
# ---------------------------------------------------------------------------

class WebhookClient:
    """Manages a reusable httpx.AsyncClient for webhook calls."""

    def __init__(self, gateway: str, token: str, agent_id: str | None, timeout_buffer: int):
        self.url = f"http://{gateway}/hooks/agent"
        self.token = token
        self.agent_id = agent_id
        self.timeout_buffer = timeout_buffer
        self._client: httpx.AsyncClient | None = None
        self._lock = asyncio.Lock()  # 串行事件处理

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient()
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def send(
        self,
        message: str,
        session_key: str,
        need_response: bool = True,
        deadline: int = 60,
    ) -> str | None:
        """串行发送事件到 OpenClaw，返回 Agent 回复文本或 None。"""
        async with self._lock:
            return await self._send_inner(message, session_key, need_response, deadline)

    async def _send_inner(
        self, message: str, session_key: str, need_response: bool, deadline: int
    ) -> str | None:
        payload: dict = {
            "message": message,
            "name": "Werewolf",
            "sessionKey": session_key,
            "deliver": True,
            "channel": "last",
        }
        if self.agent_id:
            payload["agentId"] = self.agent_id
        if need_response:
            payload["timeoutSeconds"] = max(deadline - self.timeout_buffer, 10)
        else:
            payload["timeoutSeconds"] = 0

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.token}",
        }
        http_timeout = deadline + 10 if need_response else 30

        try:
            client = await self._get_client()
            resp = await client.post(
                self.url, json=payload, headers=headers, timeout=http_timeout
            )
            data = resp.json()
        except Exception as exc:
            log.error("Webhook POST failed: %s", exc)
            return None

        if need_response:
            if data.get("status") == "ok":
                return data.get("reply", "")
            log.warning("Webhook non-ok status: %s", data.get("status"))
            return None
        return None


# ---------------------------------------------------------------------------
# Game action submit — 提交行动到游戏 REST API
# ---------------------------------------------------------------------------

async def submit_action(
    client: httpx.AsyncClient, server: str, room_id: str, api_key: str, action: dict
) -> bool:
    url = f"http://{server}/api/rooms/{room_id}/action"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        resp = await client.post(url, json=action, headers=headers, timeout=10)
        if resp.status_code < 300:
            log.info("Action submitted: %s", action)
            return True
        log.warning("Action submit failed (%d): %s", resp.status_code, resp.text[:200])
    except Exception as exc:
        log.error("Action submit error: %s", exc)
    return False


# ---------------------------------------------------------------------------
# Main game loop
# ---------------------------------------------------------------------------

async def run_game(args: argparse.Namespace, webhook: WebhookClient) -> None:
    """Connect to game server WebSocket and process events until game.end."""
    ws_url = f"ws://{args.game_server}/ws/agent?room_id={args.room_id}"
    session_key = f"hook:werewolf:{args.room_id}"
    ctx = BridgeContext(room_id=args.room_id)

    log.info("Connecting to %s", ws_url)
    async with websockets.connect(
        ws_url, extra_headers={"Authorization": f"Bearer {args.game_api_key}"}
    ) as ws:
        log.info("Connected. Waiting for game events...")

        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                log.warning("Non-JSON message: %s", raw[:100])
                continue

            event_type = msg.get("type", "unknown")
            data = msg.get("data", {})
            log.info("Event: %s", event_type)

            # Update context from event
            update_context(ctx, event_type, data)

            # Format event
            formatted, need_response = format_event(event_type, data, ctx)
            deadline = data.get("deadline", 60)

            # Send to OpenClaw
            reply = await webhook.send(
                formatted, session_key, need_response=need_response, deadline=deadline
            )

            # If decision needed, extract and submit
            if need_response:
                decision = extract_decision(reply) if reply else None
                if decision is None:
                    # Determine fallback event type
                    fb_type = "night" if "night" in event_type else (
                        "vote" if "vote" in event_type else (
                            "speech" if "speech" in event_type else "pass"
                        )
                    )
                    decision = fallback_action(fb_type, ctx)
                    log.warning("Fallback triggered: %s", decision)
                    # P1: fire-and-forget notify OpenClaw about fallback
                    await webhook.send(
                        f"[GAME_EVENT] fallback_triggered\n"
                        f"Agent 响应超时或解析失败，已执行降级行动: "
                        f"{json.dumps(decision, ensure_ascii=False)}",
                        session_key,
                        need_response=False,
                        deadline=10,
                    )

                # Track guard target for no-consecutive-guard rule
                if ctx.my_role == "guard" and decision.get("action") == "guard":
                    ctx.last_guarded = decision.get("target")

                # Submit action to game server
                client = await webhook._get_client()
                await submit_action(
                    client, args.game_server, args.room_id, args.game_api_key, decision
                )

            # Exit on game end
            if event_type == "game.end":
                log.info("Game ended. Exiting.")
                return


# ---------------------------------------------------------------------------
# Reconnect wrapper
# ---------------------------------------------------------------------------

async def run_with_reconnect(args: argparse.Namespace, webhook: WebhookClient) -> None:
    session_key = f"hook:werewolf:{args.room_id}"
    for attempt in range(5):
        try:
            await run_game(args, webhook)
            return  # Normal exit on game.end
        except (websockets.ConnectionClosed, ConnectionError, OSError) as exc:
            wait = 5 * (attempt + 1)
            log.warning("Connection lost (attempt %d/5), reconnecting in %ds: %s", attempt + 1, wait, exc)
            await asyncio.sleep(wait)

    log.error("All reconnect attempts failed. Exiting.")
    await webhook.send(
        "[GAME_EVENT] connection.lost\n连接丢失，无法重连。游戏可能仍在进行中。",
        session_key,
        need_response=False,
        deadline=10,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Werewolf Arena Webhook Bridge (V2)")
    p.add_argument("--room-id", required=True, help="Game room ID")
    p.add_argument("--game-api-key", required=True, help="Werewolf Arena API key")
    p.add_argument("--game-server", default="localhost:8000", help="Game server host:port")
    p.add_argument("--openclaw-gateway", default="127.0.0.1:18789", help="OpenClaw Gateway host:port")
    p.add_argument("--openclaw-hook-token", required=True, help="OpenClaw webhook token")
    p.add_argument("--openclaw-agent-id", default=None, help="OpenClaw agent ID (optional)")
    p.add_argument("--timeout-buffer", type=int, default=10, help="Seconds before deadline to trigger fallback")
    return p.parse_args()


async def main() -> None:
    args = parse_args()
    webhook = WebhookClient(
        gateway=args.openclaw_gateway,
        token=args.openclaw_hook_token,
        agent_id=args.openclaw_agent_id,
        timeout_buffer=args.timeout_buffer,
    )
    try:
        await run_with_reconnect(args, webhook)
    finally:
        await webhook.close()


if __name__ == "__main__":
    asyncio.run(main())
