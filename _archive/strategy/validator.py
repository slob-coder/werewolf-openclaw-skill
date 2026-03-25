#!/usr/bin/env python3
"""
行动校验器模块

拦截明显错误的行动，保证游戏合规
"""

from typing import Dict, Any

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from memory import GameMemory


class ActionValidator:
    """
    行动校验器

    校验规则：
    - 狼人不能击杀队友或已死亡玩家
    - 预言家不能重复查验或查验已死亡玩家
    - 女巫不能重复使用解药/毒药
    - 守卫不能连续守护同一人
    - 投票不能投给已死亡玩家
    - 猎人中毒死亡不能开枪
    """

    @staticmethod
    def validate(action: Dict[str, Any], memory: GameMemory) -> bool:
        """校验行动是否合法

        Args:
            action: 行动字典，包含 action_type 和相关参数
            memory: 游戏状态

        Returns:
            是否合法
        """
        action_type = action.get("action_type")

        validators = {
            "werewolf_kill": ActionValidator._validate_werewolf_kill,
            "seer_check": ActionValidator._validate_seer_check,
            "witch_save": ActionValidator._validate_witch_save,
            "witch_poison": ActionValidator._validate_witch_poison,
            "guard_protect": ActionValidator._validate_guard_protect,
            "vote": ActionValidator._validate_vote,
            "hunter_shoot": ActionValidator._validate_hunter_shoot,
        }

        validator = validators.get(action_type)
        if validator:
            return validator(action, memory)

        # 未知行动类型放行（如 skip）
        return True

    @staticmethod
    def _validate_werewolf_kill(action: Dict[str, Any], memory: GameMemory) -> bool:
        """狼人击杀校验"""
        target = action.get("target")

        # 不能击杀队友
        if target in memory.werewolf_teammates:
            return False

        # 不能击杀已死亡玩家
        dead_seats = memory.get_dead_seats()
        if target in dead_seats:
            return False

        return True

    @staticmethod
    def _validate_seer_check(action: Dict[str, Any], memory: GameMemory) -> bool:
        """预言家查验校验"""
        target = action.get("target")

        # 不能重复查验
        if target in memory.seer_check_results:
            return False

        # 不能查验已死亡玩家
        dead_seats = memory.get_dead_seats()
        if target in dead_seats:
            return False

        return True

    @staticmethod
    def _validate_witch_save(action: Dict[str, Any], memory: GameMemory) -> bool:
        """女巫救人校验"""
        # 解药已用
        if memory.witch_antidote_used:
            return False

        # 检查是否有被杀目标
        if not memory.night_kill_target:
            return False

        return True

    @staticmethod
    def _validate_witch_poison(action: Dict[str, Any], memory: GameMemory) -> bool:
        """女巫毒人校验"""
        target = action.get("target")

        # 毒药已用
        if memory.witch_poison_used:
            return False

        # 不能毒已死亡玩家
        dead_seats = memory.get_dead_seats()
        if target in dead_seats:
            return False

        return True

    @staticmethod
    def _validate_guard_protect(action: Dict[str, Any], memory: GameMemory) -> bool:
        """守卫守护校验"""
        target = action.get("target")

        # 不能连续守同一人
        if target == memory.last_guarded:
            return False

        # 不能守已死亡玩家
        dead_seats = memory.get_dead_seats()
        if target in dead_seats:
            return False

        return True

    @staticmethod
    def _validate_vote(action: Dict[str, Any], memory: GameMemory) -> bool:
        """投票校验"""
        target = action.get("target")

        # 弃票合法
        if target == -1:
            return True

        # 不能投票给已死亡玩家
        dead_seats = memory.get_dead_seats()
        if target in dead_seats:
            return False

        return True

    @staticmethod
    def _validate_hunter_shoot(action: Dict[str, Any], memory: GameMemory) -> bool:
        """猎人开枪校验"""
        target = action.get("target")

        # 中毒死亡不能开枪
        if memory.death_cause == "poison":
            return False

        # 不能射击已死亡玩家
        dead_seats = memory.get_dead_seats()
        if target in dead_seats:
            return False

        return True
