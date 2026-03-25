#!/usr/bin/env python3
"""
Werewolf Arena — OpenClaw Bridge (V3)

基于官方 SDK (WerewolfAgent) 的事件桥接器。
接收游戏事件 → 转发到 OpenClaw Webhook → Agent 调用 werewolf_cli.py 执行行动。

依赖: pip install werewolf-arena httpx
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import random
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
from werewolf_arena import Action, GameEvent, WerewolfAgent

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("bridge")

# ---------------------------------------------------------------------------
# Runtime context — shared with werewolf_cli.py
# ---------------------------------------------------------------------------
CONTEXT_DIR = Path("/tmp/werewolf_arena")
SKILL_DIR = Path("~/.openclaw/workspace/skills/werewolf-agent").expanduser()
WCLI = f"python3 {SKILL_DIR}/werewolf_cli.py"


def _context_path(room_id: str) -> Path:
    return CONTEXT_DIR / f"context_{room_id}.json"


def write_context(room_id: str, data: dict) -> None:
    """Write runtime context for werewolf_cli.py to read."""
    CONTEXT_DIR.mkdir(parents=True, exist_ok=True)
    path = _context_path(room_id)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    log.debug("Context written to %s", path)


# ---------------------------------------------------------------------------
# OpenClaw Webhook client
# ---------------------------------------------------------------------------

class WebhookClient:
    """POST events to OpenClaw Gateway /hooks/agent endpoint."""

    def __init__(self, gateway: str, token: str, agent_id: str | None, timeout_buffer: int):
        self.url = f"http://{gateway}/hooks/agent"
        self.token = token
        self.agent_id = agent_id
        self.timeout_buffer = timeout_buffer
        self._client: httpx.AsyncClient | None = None
        self._lock = asyncio.Lock()

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient()
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def send(
        self, message: str, session_key: str,
        need_response: bool = True, deadline: int = 60,
    ) -> str | None:
        """Send event to OpenClaw. Returns Agent reply text or None."""
        async with self._lock:
            return await self._send_inner(message, session_key, need_response, deadline)

    async def _send_inner(
        self, message: str, session_key: str,
        need_response: bool, deadline: int,
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
        payload["timeoutSeconds"] = max(deadline - self.timeout_buffer, 10) if need_response else 0

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.token}",
        }
        http_timeout = deadline + 10 if need_response else 30

        try:
            client = await self._get_client()
            resp = await client.post(self.url, json=payload, headers=headers, timeout=http_timeout)
            data = resp.json()
        except Exception as exc:
            log.error("Webhook POST failed: %s", exc)
            return None

        if need_response and data.get("status") == "ok":
            return data.get("reply", "")
        return None


# ---------------------------------------------------------------------------
# Bridge Agent — extends WerewolfAgent with Webhook forwarding
# ---------------------------------------------------------------------------

class BridgeAgent(WerewolfAgent):
    """Inherits SDK WerewolfAgent, forwards events to OpenClaw Webhook.

    OpenClaw Agent handles strategy reasoning and calls werewolf_cli.py
    to submit actions. This bridge only does event formatting + forwarding.
    """

    def __init__(
        self,
        webhook: WebhookClient,
        room_id: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.webhook = webhook
        self._room_id = room_id
        self._session_key = f"hook:werewolf:{room_id}"
        self._teammates: list[int] = []
        self._alive_players: list[int] = []
        self._dead_players: list[int] = []
        self._current_round: int = 0
        self._seer_results: dict[int, str] = {}  # seat → "werewolf"/"good"

    # ── SDK callback overrides ────────────────────────────────

    async def on_game_sync(self, data: Dict[str, Any]) -> None:
        self._update_context()
        log.info("Game sync: seat=%s role=%s", self.seat, self.role)

    async def on_game_start(self, event: GameEvent) -> None:
        self._update_context()
        msg = (
            f"[GAME_EVENT] game.start\n"
            f"游戏开始！\n"
            f"你的座位号: {self.seat}\n"
            f"你的角色: {self.role}\n"
            f"玩家数: {event.data.get('player_count', '?')}\n"
            f"请确认角色并做好准备。"
        )
        await self._forward(msg, need_response=False)

    async def on_night_action(self, event: GameEvent) -> Optional[Action]:
        # SDK fires this for generic "phase.night". The actual role-specific
        # events (phase.night.werewolf etc.) are handled by custom handlers.
        # Return None so SDK doesn't submit anything.
        self._current_round = event.data.get("round", self._current_round + 1)
        self._update_context()
        return None

    async def on_speech_turn(self, event: GameEvent) -> Optional[Action]:
        speeches = event.data.get("speeches", [])
        speech_lines = "\n".join(
            f"  - {s.get('seat', '?')}号: \"{s.get('content', '')}\"" for s in speeches
        ) if speeches else "  （暂无发言）"

        msg = (
            f"[GAME_EVENT] phase.day.speech (第 {self._current_round} 轮)\n"
            f"轮到你发言。\n"
            f"存活玩家: {self._alive_players}\n"
            f"本轮已有发言:\n{speech_lines}\n\n"
            f"请分析局势并执行发言命令:\n"
            f"  {WCLI} speech --content \"你的发言内容\""
        )
        await self._forward(msg, need_response=True, deadline=90)
        return None  # CLI already submitted

    async def on_vote(self, event: GameEvent) -> Optional[Action]:
        msg = (
            f"[GAME_EVENT] phase.day.vote (第 {self._current_round} 轮)\n"
            f"投票阶段。\n"
            f"存活玩家: {self._alive_players}\n\n"
            f"请分析后执行投票命令:\n"
            f"  {WCLI} vote --target <座位号>\n"
            f"  {WCLI} vote --abstain  # 弃票"
        )
        await self._forward(msg, need_response=True, deadline=60)
        return None

    async def on_game_end(self, event: GameEvent) -> None:
        winner = event.data.get("winner", "未知")
        msg = (
            f"[GAME_EVENT] game.end\n"
            f"游戏结束！获胜阵营: {winner}\n"
            f"请对本局做一个简短复盘总结。"
        )
        await self._forward(msg, need_response=False)

    async def on_player_speech(self, data: Dict[str, Any]) -> None:
        seat = data.get("seat", "?")
        content = data.get("content", "")
        msg = (
            f"[GAME_EVENT] player.speech\n"
            f"{seat}号发言: \"{content}\"\n"
            f"请记住此发言用于后续分析。"
        )
        await self._forward(msg, need_response=False)

    async def on_player_death(self, data: Dict[str, Any]) -> None:
        seat = data.get("seat")
        cause = data.get("cause", "未知")
        if seat and seat in self._alive_players:
            self._alive_players.remove(seat)
        if seat and seat not in self._dead_players:
            self._dead_players.append(seat)
        self._update_context()

        msg = (
            f"[GAME_EVENT] player.death\n"
            f"玩家 {seat} 号死亡，原因: {cause}\n"
            f"请记录此信息。"
        )
        await self._forward(msg, need_response=False)

    async def on_vote_result(self, data: Dict[str, Any]) -> None:
        result = data.get("result", "")
        message = data.get("message", "")
        msg = (
            f"[GAME_EVENT] vote.result\n"
            f"投票结果: {message}\n"
            f"请记录此信息。"
        )
        await self._forward(msg, need_response=False)

    async def on_werewolf_chat(self, data: Dict[str, Any]) -> None:
        seat = data.get("seat", "?")
        content = data.get("content", "")
        msg = (
            f"[GAME_EVENT] werewolf.chat\n"
            f"狼人队友 {seat} 号说: \"{content}\"\n"
            f"请记住此信息用于夜晚协作。"
        )
        await self._forward(msg, need_response=False)

    async def on_action_rejected(self, data: Dict[str, Any]) -> None:
        reason = data.get("reason", "unknown")
        log.warning("Action rejected: %s", reason)
        msg = (
            f"[GAME_EVENT] action.rejected\n"
            f"行动被服务端拒绝: {reason}\n"
            f"请检查命令参数后重试。"
        )
        await self._forward(msg, need_response=False)

    # ── Custom event handlers (not in SDK) ────────────────────

    def _register_custom_handlers(self) -> None:
        """Register handlers for events the SDK doesn't cover."""
        ns = "/agent"

        @self._sio.on("role.assigned", namespace=ns)
        async def _on_role_assigned(data: dict) -> None:
            log.info("Role assigned: seat=%s role=%s", data.get("seat"), data.get("role"))
            self._update_context()

        @self._sio.on("werewolf.teammates", namespace=ns)
        async def _on_werewolf_teammates(data: dict) -> None:
            self._teammates = data.get("teammates", [])
            self._update_context()
            msg = (
                f"[GAME_EVENT] werewolf.teammates\n"
                f"你的狼人队友座位号: {self._teammates}\n"
                f"请记住此信息。"
            )
            await self._forward(msg, need_response=False)

        @self._sio.on("phase.night.werewolf", namespace=ns)
        async def _on_night_werewolf(data: dict) -> None:
            msg = (
                f"[GAME_EVENT] phase.night.werewolf (第 {self._current_round} 轮)\n"
                f"狼人行动阶段。\n"
                f"你的队友: {self._teammates}\n"
                f"存活玩家: {self._alive_players}\n\n"
                f"请选择击杀目标并执行命令:\n"
                f"  {WCLI} kill --target <座位号>"
            )
            await self._forward(msg, need_response=True, deadline=60)

        @self._sio.on("phase.night.seer", namespace=ns)
        async def _on_night_seer(data: dict) -> None:
            checked = list(self._seer_results.keys())
            checked_info = f"\n已查验: {self._seer_results}" if checked else ""
            msg = (
                f"[GAME_EVENT] phase.night.seer (第 {self._current_round} 轮)\n"
                f"预言家查验阶段。\n"
                f"存活玩家: {self._alive_players}"
                f"{checked_info}\n\n"
                f"请选择查验目标并执行命令:\n"
                f"  {WCLI} check --target <座位号>"
            )
            await self._forward(msg, need_response=True, deadline=60)

        @self._sio.on("phase.night.witch", namespace=ns)
        async def _on_night_witch(data: dict) -> None:
            killed_seat = data.get("killed_seat")
            victim_info = f"今晚被狼人杀害的是: {killed_seat} 号" if killed_seat else "今晚无人被杀"
            msg = (
                f"[GAME_EVENT] phase.night.witch (第 {self._current_round} 轮)\n"
                f"女巫行动阶段。\n"
                f"{victim_info}\n"
                f"存活玩家: {self._alive_players}\n\n"
                f"可执行命令:\n"
                f"  {WCLI} save              # 使用解药救人\n"
                f"  {WCLI} poison --target <座位号>  # 使用毒药\n"
                f"  {WCLI} skip              # 不使用药水"
            )
            await self._forward(msg, need_response=True, deadline=60)

        @self._sio.on("phase.night.hunter", namespace=ns)
        async def _on_night_hunter(data: dict) -> None:
            msg = (
                f"[GAME_EVENT] phase.night.hunter (第 {self._current_round} 轮)\n"
                f"猎人被毒杀，是否开枪？\n"
                f"注意: 被女巫毒杀的猎人通常不能开枪（取决于规则设置）。\n\n"
                f"可执行命令:\n"
                f"  {WCLI} shoot --target <座位号>  # 开枪带人\n"
                f"  {WCLI} skip                    # 不开枪"
            )
            await self._forward(msg, need_response=True, deadline=30)

        @self._sio.on("seer.result", namespace=ns)
        async def _on_seer_result(data: dict) -> None:
            target = data.get("target_seat")
            result = data.get("result", "unknown")
            if target is not None:
                self._seer_results[target] = result
            identity = "狼人" if result == "werewolf" else "好人"
            self._update_context()
            msg = (
                f"[GAME_EVENT] seer.result\n"
                f"查验结果: {target} 号是【{identity}】\n"
                f"历史查验: {self._seer_results}\n"
                f"请记录此关键信息。"
            )
            await self._forward(msg, need_response=False)

        @self._sio.on("day.announcement", namespace=ns)
        async def _on_day_announcement(data: dict) -> None:
            message = data.get("message", "")
            deaths = data.get("deaths", [])
            msg = (
                f"[GAME_EVENT] day.announcement (第 {self._current_round} 轮)\n"
                f"{message}\n"
                f"当前存活: {self._alive_players}\n"
                f"请记录此信息。"
            )
            await self._forward(msg, need_response=False)

        @self._sio.on("phase.hunter_shoot", namespace=ns)
        async def _on_hunter_shoot(data: dict) -> None:
            msg = (
                f"[GAME_EVENT] phase.hunter_shoot (第 {self._current_round} 轮)\n"
                f"猎人发动技能，请选择开枪目标。\n"
                f"存活玩家: {self._alive_players}\n\n"
                f"可执行命令:\n"
                f"  {WCLI} shoot --target <座位号>\n"
                f"  {WCLI} skip  # 不开枪"
            )
            await self._forward(msg, need_response=True, deadline=30)

        @self._sio.on("phase.last_words", namespace=ns)
        async def _on_last_words(data: dict) -> None:
            msg = (
                f"[GAME_EVENT] phase.last_words\n"
                f"请发表遗言。\n\n"
                f"  {WCLI} speech --content \"你的遗言\""
            )
            await self._forward(msg, need_response=True, deadline=30)

    # ── Internal helpers ──────────────────────────────────────

    async def _forward(self, message: str, need_response: bool = True, deadline: int = 60) -> None:
        """Forward formatted event to OpenClaw Webhook."""
        log.info("→ Webhook [resp=%s]: %s...", need_response, message[:80])
        reply = await self.webhook.send(
            message, self._session_key,
            need_response=need_response, deadline=deadline,
        )
        if need_response and reply:
            log.info("← Webhook reply: %s...", reply[:80])

    def _update_context(self) -> None:
        """Write current game state to context file for werewolf_cli.py."""
        # Rebuild alive list from game_state if available
        if self.game_state and self.game_state.players:
            self._alive_players = [
                p.seat for p in self.game_state.players if p.is_alive
            ]

        ctx = {
            "game_id": self.game_id or "",
            "api_key": self.api_key,
            "server_url": self.server_url,
            "my_seat": self.seat,
            "my_role": self.role,
            "alive_players": self._alive_players,
            "dead_players": self._dead_players,
            "teammates": self._teammates,
            "seer_results": self._seer_results,
            "current_round": self._current_round,
        }
        write_context(self._room_id, ctx)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Werewolf Arena OpenClaw Bridge (V3)")
    p.add_argument("--room-id", required=True, help="Game room ID")
    p.add_argument("--game-id", default=None,
                   help="Game ID (if omitted, bridge will auto-start when all players ready)")
    p.add_argument("--api-key", required=True, help="Werewolf Arena Agent API key")
    p.add_argument("--server", default="http://localhost:8000", help="Game server URL")
    p.add_argument("--openclaw-gateway", default="127.0.0.1:18789", help="OpenClaw Gateway host:port")
    p.add_argument("--openclaw-hook-token", required=True, help="OpenClaw webhook token")
    p.add_argument("--openclaw-agent-id", default=None, help="OpenClaw agent ID")
    p.add_argument("--timeout-buffer", type=int, default=10, help="Seconds before deadline for fallback")
    p.add_argument("--auto-start", action="store_true", default=True,
                   help="Auto-start game when all players ready (default: true)")
    p.add_argument("--no-auto-start", dest="auto_start", action="store_false",
                   help="Don't auto-start; wait for --game-id or external start")
    return p.parse_args()


# ---------------------------------------------------------------------------
# game_id resolution — the core lifecycle problem
# ---------------------------------------------------------------------------
#
# Lifecycle:
#   ① join_room (REST)     → seat assigned, no game_id yet
#   ② toggle_ready (REST)  → marked ready
#   ③ game starts           → game_id created (only returned by POST /rooms/{id}/start)
#   ④ set_game_id           → SDK requires this before connect()
#   ⑤ connect (Socket.IO)  → auth = {api_key, game_id}
#   ⑥ run_async             → receive events
#
# Gap: between ② and ⑤, the agent needs game_id, but:
#   - RoomResponse doesn't include game_id
#   - game_id is only in the RoomStartResponse from POST /rooms/{id}/start
#
# Strategy:
#   A. --game-id provided     → use it directly (skip to ⑤)
#   B. --auto-start enabled   → poll room, call start when full+ready, get game_id
#   C. neither                → poll room status until "in_progress", then query for game_id

async def wait_for_game_id(
    rest_client: httpx.AsyncClient,
    server_url: str,
    room_id: str,
    api_key: str,
    auto_start: bool,
) -> str:
    """Poll room status and resolve game_id. Returns game_id string."""
    base = f"{server_url.rstrip('/')}/api/v1"
    headers = {"X-Agent-Key": api_key}

    for attempt in range(120):  # ~4 minutes max
        await asyncio.sleep(2)

        # Check room status
        try:
            resp = await rest_client.get(f"{base}/rooms/{room_id}", headers=headers)
            room = resp.json()
        except Exception as exc:
            log.warning("Room poll failed: %s", exc)
            continue

        status = room.get("status", "")

        if status == "in_progress":
            # Game already started by someone else — find game_id
            log.info("Room is in_progress, searching for game_id...")
            game_id = await _find_game_id_for_room(rest_client, base, room_id, headers)
            if game_id:
                return game_id
            # Fallback: can't find it via API, ask user
            log.error("Game started but cannot discover game_id via API.")
            log.error("Please restart with --game-id <id>")
            raise SystemExit(1)

        if auto_start and status == "full":
            # All slots occupied — check if all ready, try to start
            slots = room.get("slots", [])
            all_ready = all(s.get("status") == "ready" for s in slots if s.get("status") != "empty")
            if all_ready:
                log.info("All players ready. Starting game...")
                try:
                    start_resp = await rest_client.post(
                        f"{base}/rooms/{room_id}/start", headers=headers
                    )
                    start_data = start_resp.json()
                    game_id = start_data.get("game_id")
                    if game_id:
                        log.info("Game started! game_id=%s", game_id)
                        return game_id
                    log.warning("Start response missing game_id: %s", start_data)
                except Exception as exc:
                    log.warning("Start attempt failed: %s (may already be started)", exc)

        # Still waiting
        player_count = room.get("current_players", "?")
        total = room.get("player_count", "?")
        if attempt % 5 == 0:
            log.info("Waiting for game... room=%s status=%s players=%s/%s",
                     room_id, status, player_count, total)

    log.error("Timeout waiting for game to start. Please provide --game-id manually.")
    raise SystemExit(1)


async def _find_game_id_for_room(
    client: httpx.AsyncClient, base: str, room_id: str, headers: dict
) -> str | None:
    """Try to discover game_id for an in-progress room.
    Queries recent games or uses room's game relationship."""
    # Attempt: query games endpoint if it exists
    # The server doesn't have a /games?room_id=X endpoint, so we try
    # getting the room and looking for game info in the response.
    # If not found, return None.
    try:
        # Some servers may include game info — try parsing
        resp = await client.get(f"{base}/rooms/{room_id}", headers=headers)
        room = resp.json()
        # Check if game_id is nested in config or elsewhere
        game_id = room.get("game_id") or room.get("config", {}).get("game_id")
        if game_id:
            return game_id
    except Exception:
        pass
    return None


async def main() -> None:
    args = parse_args()

    webhook = WebhookClient(
        gateway=args.openclaw_gateway,
        token=args.openclaw_hook_token,
        agent_id=args.openclaw_agent_id,
        timeout_buffer=args.timeout_buffer,
    )

    agent = BridgeAgent(
        webhook=webhook,
        room_id=args.room_id,
        api_key=args.api_key,
        server_url=args.server,
        agent_name="OpenClaw-Bridge",
    )

    try:
        # ── Phase 1: Join room (REST) ──
        result = await agent.join_room(args.room_id)
        log.info("Joined room %s at seat %s", args.room_id, result.get("seat"))

        # ── Phase 2: Mark ready (REST) ──
        await agent.rest.toggle_ready(args.room_id)
        log.info("Marked ready.")

        # ── Phase 3: Resolve game_id ──
        if args.game_id:
            # Provided by user — use directly
            agent.set_game_id(args.game_id)
            log.info("Using provided game_id: %s", args.game_id)
        else:
            # Wait for game to start, auto-start if enabled
            log.info("Waiting for game_id (auto_start=%s)...", args.auto_start)
            async with httpx.AsyncClient() as http:
                game_id = await wait_for_game_id(
                    http, args.server, args.room_id, args.api_key, args.auto_start
                )
            agent.set_game_id(game_id)
            log.info("Resolved game_id: %s", game_id)

        # ── Phase 4: Connect Socket.IO (requires game_id) ──
        # Custom handlers must be registered before connect
        agent._register_custom_handlers()
        await agent.connect()
        log.info("Socket.IO connected.")

        # ── Phase 5: Run until game ends ──
        await agent.run_async()

    except KeyboardInterrupt:
        log.info("Interrupted.")
    except SystemExit:
        raise
    except Exception as exc:
        log.error("Fatal error: %s", exc, exc_info=True)
    finally:
        await webhook.close()
        await agent.rest.close()


if __name__ == "__main__":
    asyncio.run(main())
