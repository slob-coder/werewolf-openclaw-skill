#!/usr/bin/env python3
# ⚠️ DEPRECATED (V1) — 此文件已被 V2 ws_bridge.py 替代。
# V2 使用 Webhook Bridge 架构，所有推理由 OpenClaw Agent 完成。
# 保留此文件仅供回退参考，不再作为主入口。
"""
Werewolf Arena Agent - OpenClaw Skill 后台进程

职责：
1. 维持 WebSocket 长连接（通过 werewolf_sdk）
2. 接收并处理游戏事件
3. 调用策略引擎进行决策
4. 提交行动到游戏平台
5. 记录关键事件到日志

使用方法：
    python werewolf_agent.py --room-id abc123 --api-key xxx

P0 MVP 说明：
    - 当前使用 Mock 客户端模拟通信
    - 策略使用规则驱动（随机 + 约束）
    - 不调用 LLM API
"""

import argparse
import asyncio
import json
import signal
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

# 项目内模块
sys.path.insert(0, str(Path(__file__).parent))
from memory import GameMemory
from strategy import BasicStrategy
from logger import AgentLogger


class MockWerewolfClient:
    """
    Mock 客户端 - 模拟 werewolf_sdk.WerewolfClient

    P0 阶段使用，用于测试 Agent 逻辑
    """

    def __init__(self, server_url: str, api_key: str):
        """初始化 Mock 客户端

        Args:
            server_url: 服务器地址
            api_key: API Key
        """
        self.server_url = server_url
        self.api_key = api_key
        self.connected = False
        self.room_id: Optional[str] = None
        self.game_state: Dict[str, Any] = {}

    async def connect(self) -> None:
        """建立 WebSocket 连接"""
        await asyncio.sleep(0.1)  # 模拟网络延迟
        self.connected = True

    async def join_room(self, room_id: str) -> Dict[str, Any]:
        """加入游戏房间

        Args:
            room_id: 房间 ID

        Returns:
            房间信息
        """
        self.room_id = room_id
        await asyncio.sleep(0.1)

        return {
            "room_id": room_id,
            "status": "waiting",
            "players": [],
        }

    async def receive_event(self) -> Dict[str, Any]:
        """接收游戏事件（阻塞）

        Returns:
            事件字典
        """
        # Mock: 模拟事件循环
        await asyncio.sleep(1.0)

        # 返回心跳事件
        return {
            "event_type": "heartbeat",
            "data": {},
        }

    async def submit_action(self, action: Dict[str, Any]) -> bool:
        """提交行动

        Args:
            action: 行动字典

        Returns:
            是否成功
        """
        await asyncio.sleep(0.1)
        return True

    async def get_game_state(self) -> Dict[str, Any]:
        """获取当前游戏状态

        Returns:
            游戏状态字典
        """
        return self.game_state

    async def close(self) -> None:
        """关闭连接"""
        self.connected = False


class WerewolfAgent:
    """
    狼人杀 Agent 主类

    管理：
    - WebSocket 连接生命周期
    - 事件路由和处理
    - 策略引擎调用
    - 状态持久化
    """

    def __init__(self, args: argparse.Namespace):
        """初始化 Agent

        Args:
            args: 命令行参数
        """
        self.args = args
        self.memory: Optional[GameMemory] = None
        self.strategy = BasicStrategy(speech_style=args.speech_style)
        self.logger = AgentLogger(args.log_file)
        self.client: Optional[MockWerewolfClient] = None
        self.running = False

    async def run(self) -> None:
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

    async def _connect(self) -> None:
        """建立 WebSocket 连接"""
        self.logger.info("正在连接服务器...")

        # 创建客户端（P0 使用 Mock）
        self.client = MockWerewolfClient(
            server_url=self.args.server_url,
            api_key=self.args.api_key,
        )
        await self.client.connect()

        self.logger.info("连接成功")

    async def _join_room(self) -> None:
        """加入游戏房间"""
        self.logger.info(f"正在加入房间 {self.args.room_id}...")

        if self.client:
            await self.client.join_room(self.args.room_id)

        self.logger.event(f"已加入房间 {self.args.room_id}，等待游戏开始")

    async def _event_loop(self) -> None:
        """事件处理循环"""
        self.logger.info("开始监听游戏事件...")

        while self.running:
            try:
                # 等待并处理事件
                if self.client:
                    event = await self.client.receive_event()
                    await self._dispatch_event(event)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"事件处理异常: {e}")
                await asyncio.sleep(1.0)

    async def _dispatch_event(self, event: Dict[str, Any]) -> None:
        """事件分发路由

        Args:
            event: 事件字典
        """
        event_type = event.get("event_type")

        # 忽略心跳事件
        if event_type == "heartbeat":
            return

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
        else:
            self.logger.debug(f"未知事件类型: {event_type}")

    # === 事件处理器 ===

    async def _on_game_start(self, event: Dict[str, Any]) -> None:
        """游戏开始"""
        data = event.get("data", {})

        # 初始化游戏状态
        self.memory = GameMemory(
            game_id=event.get("game_id", "unknown"),
            room_id=self.args.room_id,
            my_role=data.get("your_role", "villager"),
            my_faction=data.get("your_faction", "villager"),
            my_seat=data.get("your_seat", 1),
        )

        # 初始化玩家列表
        players = data.get("players", [])
        self.memory.init_players(players)

        # 狼人记录队友
        if data.get("teammates"):
            self.memory.werewolf_teammates = data["teammates"]

        self.logger.event(f"游戏开始，角色={self.memory.my_role}，座位={self.memory.my_seat}")

    async def _on_night_phase(self, event: Dict[str, Any]) -> None:
        """夜晚行动"""
        if not self.memory:
            return

        data = event.get("data", {})
        self.memory.current_phase = "night"
        self.memory.current_round = data.get("round", self.memory.current_round)

        my_role = self.memory.my_role

        self.logger.info(f"第 {self.memory.current_round} 轮夜晚开始")

        # 根据角色选择行动
        action = await self.strategy.night_action(
            role=my_role,
            memory=self.memory,
            event_data=data,
            timeout=60,
        )

        # 提交行动
        await self._submit_action(action)
        self.logger.action(f"夜晚行动: {action.get('action_type', 'skip')}")

    async def _on_speech_phase(self, event: Dict[str, Any]) -> None:
        """白天发言"""
        if not self.memory:
            return

        data = event.get("data", {})
        self.memory.current_phase = "day_speech"

        # 检查是否轮到自己发言
        if not data.get("is_your_turn", False):
            return

        self.logger.info(f"第 {self.memory.current_round} 轮发言轮次")

        # 生成发言
        speech = await self.strategy.generate_speech(
            memory=self.memory,
            event_data=data,
            timeout=90,
        )

        # 提交发言
        action = {"action_type": "speech", "content": speech}
        await self._submit_action(action)
        self.logger.action(f"已提交发言: {speech[:50]}...")

    async def _on_vote_phase(self, event: Dict[str, Any]) -> None:
        """投票"""
        if not self.memory:
            return

        data = event.get("data", {})
        self.memory.current_phase = "day_vote"

        self.logger.info(f"第 {self.memory.current_round} 轮投票开始")

        # 选择投票目标
        target = await self.strategy.vote_target(
            memory=self.memory,
            event_data=data,
            timeout=60,
        )

        # 提交投票
        action = {"action_type": "vote", "target": target}
        await self._submit_action(action)

        if target == -1:
            self.logger.action("已弃票")
        else:
            self.logger.action(f"投票给 {target} 号玩家")

    async def _on_werewolf_chat(self, event: Dict[str, Any]) -> None:
        """狼人夜聊（仅狼人可见）"""
        if not self.memory:
            return

        data = event.get("data", {})

        # 记录狼人夜聊
        self.memory.add_werewolf_chat(
            speaker=data.get("speaker", 0),
            content=data.get("content", ""),
        )

        # 不写日志，保持私密性

    async def _on_game_end(self, event: Dict[str, Any]) -> None:
        """游戏结束"""
        if not self.memory:
            return

        data = event.get("data", {})
        winner = data.get("winner", "unknown")
        rounds = data.get("rounds_played", 0)

        # 归档对局
        archive_path = self.memory.archive(winner=winner, rounds=rounds)

        self.logger.event(f"游戏结束，{winner}获胜，共 {rounds} 轮")
        self.logger.info(f"对局已归档到: {archive_path}")

        # 停止运行
        self.running = False

    # === 辅助方法 ===

    async def _submit_action(self, action: Dict[str, Any]) -> bool:
        """提交行动到平台

        Args:
            action: 行动字典

        Returns:
            是否成功
        """
        if not self.client:
            return False

        # 规则校验
        if self.memory and not self.strategy.validate_action(action, self.memory):
            self.logger.warn(f"行动校验失败，执行降级: {action}")
            action = self.strategy.fallback_action(action, self.memory or {})

        # 调用 SDK 提交
        try:
            return await self.client.submit_action(action)
        except Exception as e:
            self.logger.error(f"提交行动失败: {e}")
            return False

    async def _cleanup(self) -> None:
        """清理资源"""
        if self.client:
            await self.client.close()

        self.logger.info("Agent 进程退出")

    def _handle_shutdown(self, signum: int, frame: Any) -> None:
        """处理关闭信号

        Args:
            signum: 信号编号
            frame: 栈帧
        """
        self.logger.info(f"收到关闭信号 ({signum})")
        self.running = False


def main() -> None:
    """主入口"""
    parser = argparse.ArgumentParser(description="Werewolf Arena Agent")

    parser.add_argument("--room-id", required=True, help="房间 ID")
    parser.add_argument("--api-key", required=True, help="API Key")
    parser.add_argument(
        "--server-url",
        default="localhost:8000",
        help="服务器地址",
    )
    parser.add_argument(
        "--strategy",
        default="basic",
        choices=["basic", "llm"],
        help="策略类型",
    )
    parser.add_argument(
        "--model",
        default="claude-sonnet-4-6",
        help="LLM 模型（P1 使用）",
    )
    parser.add_argument(
        "--speech-style",
        default="formal",
        choices=["formal", "casual"],
        help="发言风格",
    )
    parser.add_argument(
        "--log-file",
        default="~/.openclaw/logs/werewolf-agent.log",
        help="日志文件路径",
    )

    args = parser.parse_args()

    # 创建并运行 Agent
    agent = WerewolfAgent(args)

    try:
        asyncio.run(agent.run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
