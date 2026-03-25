#!/usr/bin/env python3
"""
Agent 日志模块

日志格式：[TIMESTAMP] [LEVEL] [TAG] message
日志级别：INFO, WARN, ERROR, DEBUG
日志标签：EVENT, ACTION, REASON, WARN, ERROR
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional


class AgentLogger:
    """
    Agent 日志记录器

    提供结构化日志输出，支持：
    - 游戏事件记录 (EVENT)
    - 行动提交记录 (ACTION)
    - 推理结果记录 (REASON)
    - 警告和错误日志
    """

    def __init__(self, log_file: str):
        """初始化日志记录器

        Args:
            log_file: 日志文件路径
        """
        self.log_file = Path(log_file).expanduser()
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

        self.logger = logging.getLogger("werewolf-agent")
        self.logger.setLevel(logging.DEBUG)

        # 清除已有的 handlers（避免重复添加）
        self.logger.handlers.clear()

        # 文件处理器
        fh = logging.FileHandler(self.log_file, encoding="utf-8")
        fh.setLevel(logging.DEBUG)

        # 控制台处理器
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)

        # 格式化器
        formatter = logging.Formatter(
            "[%(asctime)s] [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        fh.setFormatter(formatter)
        ch.setFormatter(formatter)

        self.logger.addHandler(fh)
        self.logger.addHandler(ch)

    def _format_tag(self, tag: str) -> str:
        """格式化标签"""
        return f"[{tag}]"

    def info(self, message: str) -> None:
        """记录普通信息

        Args:
            message: 日志消息
        """
        self.logger.info(message)

    def warn(self, message: str) -> None:
        """记录警告信息

        Args:
            message: 警告消息
        """
        self.logger.warning(self._format_tag("WARN") + " " + message)

    def error(self, message: str) -> None:
        """记录错误信息

        Args:
            message: 错误消息
        """
        self.logger.error(self._format_tag("ERROR") + " " + message)

    def debug(self, message: str) -> None:
        """记录调试信息

        Args:
            message: 调试消息
        """
        self.logger.debug(message)

    def event(self, message: str) -> None:
        """记录游戏事件

        Args:
            message: 事件描述
        """
        self.logger.info(self._format_tag("EVENT") + " " + message)

    def action(self, message: str) -> None:
        """记录行动提交

        Args:
            message: 行动描述
        """
        self.logger.info(self._format_tag("ACTION") + " " + message)

    def reason(self, message: str) -> None:
        """记录推理结果

        Args:
            message: 推理结论
        """
        self.logger.info(self._format_tag("REASON") + " " + message)


# 全局日志实例（单例模式）
_logger_instance: Optional[AgentLogger] = None


def get_logger(log_file: Optional[str] = None) -> AgentLogger:
    """获取全局日志实例

    Args:
        log_file: 日志文件路径（首次调用时需要）

    Returns:
        AgentLogger 实例
    """
    global _logger_instance

    if _logger_instance is None:
        if log_file is None:
            log_file = "~/.openclaw/logs/werewolf-agent.log"
        _logger_instance = AgentLogger(log_file)

    return _logger_instance
