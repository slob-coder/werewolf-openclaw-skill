#!/bin/bash
# Werewolf Arena Agent 启动脚本
#
# 使用方法：
#   ./start_agent.sh --room-id abc123 --api-key sk-xxx
#   ./start_agent.sh -r abc123 -k sk-xxx
#
# 选项：
#   -r, --room-id      房间 ID（必填）
#   -k, --api-key      API Key（必填）
#   -s, --server-url   服务器地址（默认：localhost:8000）
#   --strategy         策略类型（默认：basic）
#   --speech-style     发言风格（默认：formal）

set -e

# 默认参数
ROOM_ID=""
API_KEY=""
SERVER_URL="localhost:8000"
STRATEGY="basic"
SPEECH_STYLE="formal"
LOG_FILE="$HOME/.openclaw/logs/werewolf-agent.log"
PID_FILE="$HOME/.openclaw/logs/werewolf-agent.pid"

# 解析参数
while [[ $# -gt 0 ]]; do
    case $1 in
        -r|--room-id)
            ROOM_ID="$2"
            shift 2
            ;;
        -k|--api-key)
            API_KEY="$2"
            shift 2
            ;;
        -s|--server-url)
            SERVER_URL="$2"
            shift 2
            ;;
        --strategy)
            STRATEGY="$2"
            shift 2
            ;;
        --speech-style)
            SPEECH_STYLE="$2"
            shift 2
            ;;
        -h|--help)
            echo "Werewolf Arena Agent 启动脚本"
            echo ""
            echo "使用方法："
            echo "  $0 --room-id abc123 --api-key sk-xxx"
            echo ""
            echo "选项："
            echo "  -r, --room-id      房间 ID（必填）"
            echo "  -k, --api-key      API Key（必填）"
            echo "  -s, --server-url   服务器地址（默认：localhost:8000）"
            echo "  --strategy         策略类型（默认：basic）"
            echo "  --speech-style     发言风格（默认：formal）"
            exit 0
            ;;
        *)
            echo "未知参数: $1"
            exit 1
            ;;
    esac
done

# 检查必填参数
if [[ -z "$ROOM_ID" ]]; then
    echo "错误：请提供房间 ID (--room-id)"
    exit 1
fi

if [[ -z "$API_KEY" ]]; then
    echo "错误：请提供 API Key (--api-key)"
    exit 1
fi

# 创建日志目录
mkdir -p "$(dirname "$LOG_FILE")"

# 检查是否已有进程运行
if [[ -f "$PID_FILE" ]]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "警告：已有 Agent 进程运行 (PID: $OLD_PID)"
        echo "如需重启，请先执行: kill $OLD_PID"
        exit 1
    else
        rm -f "$PID_FILE"
    fi
fi

# Agent 脚本路径
AGENT_SCRIPT="$HOME/.openclaw/workspace/skills/werewolf-agent/werewolf_agent.py"

# 检查脚本是否存在
if [[ ! -f "$AGENT_SCRIPT" ]]; then
    echo "错误：找不到 Agent 脚本: $AGENT_SCRIPT"
    exit 1
fi

# 启动 Agent
echo "启动 Werewolf Arena Agent..."
echo "  房间 ID: $ROOM_ID"
echo "  服务器: $SERVER_URL"
echo "  策略: $STRATEGY"
echo "  发言风格: $SPEECH_STYLE"

python "$AGENT_SCRIPT" \
    --room-id "$ROOM_ID" \
    --api-key "$API_KEY" \
    --server-url "$SERVER_URL" \
    --strategy "$STRATEGY" \
    --speech-style "$SPEECH_STYLE" \
    --log-file "$LOG_FILE" \
    > "$LOG_FILE" 2>&1 &

# 保存 PID
echo $! > "$PID_FILE"

echo ""
echo "✓ Agent 已启动 (PID: $(cat "$PID_FILE"))"
echo "✓ 日志文件: $LOG_FILE"
echo ""
echo "查看实时日志："
echo "  tail -f $LOG_FILE"
