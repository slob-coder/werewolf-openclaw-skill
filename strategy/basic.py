#!/usr/bin/env python3
"""
规则驱动策略模块

P0 MVP：随机行动 + 规则约束
"""

import random
from typing import Dict, Any, List, Optional

from .base import StrategyBase

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from memory import GameMemory


class BasicStrategy(StrategyBase):
    """
    规则驱动策略

    实现：
    - 基于规则的随机行动选择
    - 发言模板生成
    - 投票目标随机选择
    """

    def __init__(self, speech_style: str = "formal"):
        """初始化策略

        Args:
            speech_style: 发言风格 (formal, casual)
        """
        self.speech_style = speech_style

    async def night_action(
        self,
        role: str,
        memory: GameMemory,
        event_data: Dict[str, Any],
        timeout: int = 60,
    ) -> Dict[str, Any]:
        """夜晚行动 - 基于规则的随机选择

        Args:
            role: 当前角色
            memory: 游戏状态
            event_data: 事件数据
            timeout: 超时时间（秒）

        Returns:
            行动字典
        """
        # 获取可选行动
        available_actions = event_data.get("available_actions", [])
        if not available_actions:
            return {"action_type": "skip"}

        # 根据角色选择行动类型
        action_type = self._get_action_type_for_role(role)

        if action_type == "werewolf_kill":
            target = self._select_werewolf_target(memory, event_data)
            return {"action_type": "werewolf_kill", "target": target}

        elif action_type == "seer_check":
            target = self._select_seer_target(memory, event_data)
            return {"action_type": "seer_check", "target": target}

        elif action_type == "guard_protect":
            target = self._select_guard_target(memory, event_data)
            return {"action_type": "guard_protect", "target": target}

        elif role == "witch":
            return self._witch_action(memory, event_data)

        return {"action_type": "skip"}

    async def generate_speech(
        self,
        memory: GameMemory,
        event_data: Dict[str, Any],
        timeout: int = 90,
    ) -> str:
        """生成发言 - 使用模板

        Args:
            memory: 游戏状态
            event_data: 事件数据
            timeout: 超时时间（秒）

        Returns:
            发言文本
        """
        role = memory.my_role
        templates = self._get_speech_templates(role)

        # 随机选择一个模板
        speech = random.choice(templates)

        # 替换占位符
        speech = speech.replace("{round}", str(memory.current_round))
        speech = speech.replace("{my_seat}", str(memory.my_seat))

        return speech

    async def vote_target(
        self,
        memory: GameMemory,
        event_data: Dict[str, Any],
        timeout: int = 60,
    ) -> int:
        """投票目标 - 随机选择（排除自己）

        Args:
            memory: 游戏状态
            event_data: 事件数据
            timeout: 超时时间（秒）

        Returns:
            目标座位号（-1 表示弃票）
        """
        candidates = event_data.get("candidates", [])
        my_seat = memory.my_seat

        # 如果没有候选人，使用存活玩家列表
        if not candidates:
            candidates = [s for s in memory.alive_players if s != my_seat]

        # 排除自己和已死亡玩家
        dead_seats = memory.get_dead_seats()
        valid_candidates = [
            c for c in candidates
            if c != my_seat and c not in dead_seats
        ]

        if not valid_candidates:
            # 弃票
            return -1

        return random.choice(valid_candidates)

    # === 角色特定选择逻辑 ===

    def _select_werewolf_target(
        self, memory: GameMemory, event_data: Dict[str, Any]
    ) -> int:
        """狼人击杀目标选择"""
        # 从事件数据获取可选目标
        targets = event_data.get("targets", [])
        if not targets:
            targets = event_data.get("available_actions", [{}])[0].get("targets", [])

        # 排除队友和已死亡玩家
        dead_seats = memory.get_dead_seats()
        valid_targets = [
            t for t in targets
            if t not in memory.werewolf_teammates
            and t not in dead_seats
        ]

        return random.choice(valid_targets) if valid_targets else targets[0] if targets else 0

    def _select_seer_target(
        self, memory: GameMemory, event_data: Dict[str, Any]
    ) -> int:
        """预言家查验目标选择"""
        targets = event_data.get("targets", [])
        if not targets:
            targets = event_data.get("available_actions", [{}])[0].get("targets", [])

        # 优先查验未查验过的
        unchecked = [
            t for t in targets
            if t not in memory.seer_check_results
        ]

        return random.choice(unchecked) if unchecked else targets[0] if targets else 0

    def _select_guard_target(
        self, memory: GameMemory, event_data: Dict[str, Any]
    ) -> int:
        """守卫守护目标选择"""
        targets = event_data.get("targets", [])
        if not targets:
            targets = event_data.get("available_actions", [{}])[0].get("targets", [])

        # 不能连续守同一人
        valid_targets = [
            t for t in targets
            if t != memory.last_guarded
        ]

        return random.choice(valid_targets) if valid_targets else targets[0] if targets else 0

    def _witch_action(
        self, memory: GameMemory, event_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """女巫行动"""
        # 检查是否有被杀目标
        kill_target = memory.night_kill_target

        # 简化策略：如果解药未用且有被杀目标，50% 概率救人
        if kill_target and not memory.witch_antidote_used:
            if random.random() < 0.5:
                return {"action_type": "witch_save", "target": kill_target}

        return {"action_type": "skip"}

    def _get_speech_templates(self, role: str) -> List[str]:
        """获取发言模板

        Args:
            role: 角色名

        Returns:
            模板列表
        """
        templates = {
            "villager": [
                "我是村民，没有特殊信息，请大家多发言。",
                "我是好人，目前没有太多线索，听听大家的意见。",
                "我是平民，希望大家能多分享一些有用的信息。",
                "我是普通村民，第 {round} 轮我会继续观察大家的发言。",
                "大家好，我是村民，希望大家能找出狼人。",
            ],
            "seer": [
                "我是预言家，昨晚查验了某位玩家，有重要信息。",
                "预言家在此，我会在合适的时机公布查验结果。",
                "我是预言家，请大家相信我的验人信息。",
                "预言家发言，我有查杀/金水要报。",
            ],
            "werewolf": [
                "我是好人，大家不要怀疑我。",
                "我觉得某位玩家比较可疑，建议关注。",
                "我发言比较少，因为我需要思考。",
                "我是普通村民，请大家相信我。",
                "我站边好人阵营，希望能找到狼人。",
            ],
            "witch": [
                "我是女巫，昨晚有人被刀。",
                "女巫在此，我会在关键时刻使用我的药水。",
                "我是女巫，请大家注意发言中的逻辑漏洞。",
            ],
            "hunter": [
                "我是猎人，如果我被投出去会开枪带人。",
                "我发言比较直接，请大家理解。",
                "猎人发言，希望大家能给出合理的投票理由。",
            ],
            "guard": [
                "我是守卫，昨晚守护了某位玩家。",
                "守卫在此，我会尽力保护好人。",
                "我发言比较谨慎，请大家多提供信息。",
            ],
        }

        return templates.get(role, templates["villager"])

    def _get_action_type_for_role(self, role: str) -> str:
        """获取角色对应的行动类型

        Args:
            role: 角色名

        Returns:
            行动类型
        """
        mapping = {
            "werewolf": "werewolf_kill",
            "seer": "seer_check",
            "guard": "guard_protect",
            "witch": "witch_action",
        }
        return mapping.get(role, "skip")

    def fallback_action(
        self, action: Dict[str, Any], memory: GameMemory
    ) -> Dict[str, Any]:
        """降级行动

        Args:
            action: 原始行动
            memory: 游戏状态

        Returns:
            降级后的行动字典
        """
        # 返回一个安全的默认行动
        return {"action_type": "skip"}
