#!/usr/bin/env python3
"""
策略基类模块

定义策略引擎的抽象接口
"""

from abc import ABC, abstractmethod
from typing import Dict, Any

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from memory import GameMemory


class StrategyBase(ABC):
    """
    策略引擎基类

    定义 Agent 决策的核心接口：
    - 夜晚行动决策
    - 发言生成
    - 投票目标选择
    """

    @abstractmethod
    async def night_action(
        self,
        role: str,
        memory: GameMemory,
        event_data: Dict[str, Any],
        timeout: int = 60,
    ) -> Dict[str, Any]:
        """夜晚行动决策

        Args:
            role: 当前角色
            memory: 游戏状态
            event_data: 事件数据
            timeout: 超时时间（秒）

        Returns:
            行动字典，包含 action_type 和相关参数
        """
        pass

    @abstractmethod
    async def generate_speech(
        self,
        memory: GameMemory,
        event_data: Dict[str, Any],
        timeout: int = 90,
    ) -> str:
        """生成发言内容

        Args:
            memory: 游戏状态
            event_data: 事件数据
            timeout: 超时时间（秒）

        Returns:
            发言文本
        """
        pass

    @abstractmethod
    async def vote_target(
        self,
        memory: GameMemory,
        event_data: Dict[str, Any],
        timeout: int = 60,
    ) -> int:
        """投票目标选择

        Args:
            memory: 游戏状态
            event_data: 事件数据
            timeout: 超时时间（秒）

        Returns:
            目标座位号（-1 表示弃票）
        """
        pass

    def validate_action(
        self, action: Dict[str, Any], memory: GameMemory
    ) -> bool:
        """校验行动是否合法

        Args:
            action: 行动字典
            memory: 游戏状态

        Returns:
            是否合法
        """
        from .validator import ActionValidator
        return ActionValidator.validate(action, memory)

    @abstractmethod
    def fallback_action(
        self, action: Dict[str, Any], memory: GameMemory
    ) -> Dict[str, Any]:
        """降级行动

        当行动校验失败或超时时，返回安全的默认行动

        Args:
            action: 原始行动
            memory: 游戏状态

        Returns:
            降级后的行动字典
        """
        pass
