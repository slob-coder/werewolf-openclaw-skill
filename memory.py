#!/usr/bin/env python3
"""
游戏状态管理模块

职责：
1. 维护一局游戏内的所有状态
2. 支持状态更新和查询
3. 游戏结束后归档到本地文件
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict


@dataclass
class DeathRecord:
    """死亡记录"""
    seat: int
    round: int
    cause: str  # kill, poison, vote, shoot
    role_revealed: Optional[str] = None


@dataclass
class SpeechRecord:
    """发言记录"""
    round: int
    seat: int
    content: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class VoteRecord:
    """投票记录"""
    round: int
    voter: int
    target: int  # -1 表示弃票


@dataclass
class GameMemory:
    """
    游戏状态管理

    维护单局游戏的完整状态，包括：
    - 玩家身份和存活状态
    - 角色特定信息（狼人队友、预言家查验结果等）
    - 游戏进程（轮次、阶段）
    - 历史记录（发言、投票、狼人夜聊）
    """

    # 基本信息
    game_id: str
    room_id: str
    my_role: str
    my_faction: str  # werewolf, god, villager
    my_seat: int

    # 玩家状态
    players: List[Dict[str, Any]] = field(default_factory=list)
    alive_players: List[int] = field(default_factory=list)
    dead_players: List[DeathRecord] = field(default_factory=list)

    # 角色特定信息
    werewolf_teammates: List[int] = field(default_factory=list)
    seer_check_results: Dict[int, str] = field(default_factory=dict)  # seat -> good/wolf
    witch_antidote_used: bool = False
    witch_poison_used: bool = False

    # 游戏进程
    current_round: int = 1
    current_phase: str = "waiting"  # night / day_speech / day_vote

    # 历史记录
    speeches: List[SpeechRecord] = field(default_factory=list)
    vote_history: List[VoteRecord] = field(default_factory=list)
    werewolf_chat: List[Dict[str, Any]] = field(default_factory=list)

    # 推理状态
    identity_estimates: Dict[int, float] = field(default_factory=dict)  # seat -> 狼人概率

    # 守卫状态
    last_guarded: Optional[int] = None

    # 夜晚状态
    night_kill_target: Optional[int] = None
    death_cause: Optional[str] = None

    def init_players(self, players: List[Dict[str, Any]]) -> None:
        """初始化玩家列表

        Args:
            players: 玩家信息列表，每个元素包含 seat, name, status 等字段
        """
        self.players = players
        self.alive_players = [
            p["seat"] for p in players if p.get("status", "alive") == "alive"
        ]

        # 初始化身份概率估计（50% 基线）
        for seat in self.alive_players:
            if seat != self.my_seat:
                self.identity_estimates[seat] = 0.5

    def update_alive_players(self) -> None:
        """根据死亡记录更新存活玩家列表"""
        dead_seats = {d.seat for d in self.dead_players}
        self.alive_players = [
            p["seat"] for p in self.players
            if p["seat"] not in dead_seats
        ]

    def add_death(
        self,
        seat: int,
        round: int,
        cause: str,
        role: Optional[str] = None,
    ) -> None:
        """记录死亡事件

        Args:
            seat: 死亡玩家座位号
            round: 死亡轮次
            cause: 死因 (kill, poison, vote, shoot)
            role: 公开的角色（可选）
        """
        self.dead_players.append(
            DeathRecord(seat=seat, round=round, cause=cause, role_revealed=role)
        )
        self.update_alive_players()

        # 清理身份估计
        if seat in self.identity_estimates:
            del self.identity_estimates[seat]

    def add_speech(self, round: int, seat: int, content: str) -> None:
        """记录发言

        Args:
            round: 发言轮次
            seat: 发言玩家座位号
            content: 发言内容
        """
        self.speeches.append(
            SpeechRecord(round=round, seat=seat, content=content)
        )

    def add_vote(self, round: int, voter: int, target: int) -> None:
        """记录投票

        Args:
            round: 投票轮次
            voter: 投票人座位号
            target: 目标座位号（-1 表示弃票）
        """
        self.vote_history.append(
            VoteRecord(round=round, voter=voter, target=target)
        )

    def add_werewolf_chat(self, speaker: int, content: str) -> None:
        """记录狼人夜聊

        Args:
            speaker: 发言狼人座位号
            content: 发言内容
        """
        self.werewolf_chat.append({
            "round": self.current_round,
            "speaker": speaker,
            "content": content,
            "timestamp": datetime.now().isoformat(),
        })

    def update_seer_result(self, seat: int, result: str) -> None:
        """更新预言家查验结果

        Args:
            seat: 被查验玩家座位号
            result: 查验结果 ("good" 或 "wolf")
        """
        self.seer_check_results[seat] = result

        # 更新身份估计
        if result == "wolf":
            self.identity_estimates[seat] = 1.0
        else:
            self.identity_estimates[seat] = 0.0

    def get_recent_speeches(self, n_rounds: int = 5) -> List[SpeechRecord]:
        """获取最近 N 轮的发言

        Args:
            n_rounds: 回溯的轮数

        Returns:
            最近 n_rounds 轮内的所有发言记录
        """
        min_round = max(1, self.current_round - n_rounds + 1)
        return [s for s in self.speeches if s.round >= min_round]

    def get_dead_seats(self) -> List[int]:
        """获取所有已死亡玩家的座位号列表"""
        return [d.seat for d in self.dead_players]

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（用于序列化）"""
        return asdict(self)

    def archive(self, winner: str, rounds: int) -> Path:
        """归档对局到本地文件

        Args:
            winner: 获胜阵营
            rounds: 总轮数

        Returns:
            归档文件路径
        """
        archive_dir = Path.home() / ".openclaw" / "logs" / "werewolf-history"
        archive_dir.mkdir(parents=True, exist_ok=True)

        archive_data = {
            "game_id": self.game_id,
            "room_id": self.room_id,
            "my_role": self.my_role,
            "my_faction": self.my_faction,
            "my_seat": self.my_seat,
            "winner": winner,
            "rounds_played": rounds,
            "players": self.players,
            "dead_players": [asdict(d) for d in self.dead_players],
            "speeches": [asdict(s) for s in self.speeches],
            "vote_history": [asdict(v) for v in self.vote_history],
            "seer_check_results": self.seer_check_results,
            "archived_at": datetime.now().isoformat(),
        }

        archive_file = archive_dir / f"{self.game_id}.json"
        with open(archive_file, "w", encoding="utf-8") as f:
            json.dump(archive_data, f, ensure_ascii=False, indent=2)

        return archive_file

    @classmethod
    def from_server_state(cls, state: Dict[str, Any]) -> "GameMemory":
        """从服务器状态创建 GameMemory 实例（断线重连用）

        Args:
            state: 服务器返回的游戏状态字典

        Returns:
            恢复后的 GameMemory 实例
        """
        memory = cls(
            game_id=state["game_id"],
            room_id=state["room_id"],
            my_role=state["your_role"],
            my_faction=state["your_faction"],
            my_seat=state["your_seat"],
        )
        memory.init_players(state.get("players", []))
        memory.current_round = state.get("current_round", 1)
        memory.current_phase = state.get("current_phase", "waiting")
        return memory
