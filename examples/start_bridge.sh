#!/bin/bash
# ─────────────────────────────────────────────────────────────
# Werewolf Arena — Webhook Bridge 启动脚本 (V2)
#
# 使用方法:
#   ./start_bridge.sh --room-id abc123
#
# 前置条件:
#   1. 安装 Python 依赖:  pip install httpx websockets
#   2. OpenClaw Gateway 已运行且 hooks 已启用
#   3. Werewolf Arena 游戏服务器已运行
# ─────────────────────────────────────────────────────────────
set -e

# ── 环境变量（必填，请在运行前设置或在此处填写） ──
GAME_API_KEY="${GAME_API_KEY:-}"              # Werewolf Arena API Key
OPENCLAW_HOOK_TOKEN="${OPENCLAW_HOOK_TOKEN:-}" # OpenClaw Gateway Hook Token

# ── 可选环境变量 ──
GAME_SERVER="${GAME_SERVER:-localhost:8000}"
OPENCLAW_GATEWAY="${OPENCLAW_GATEWAY:-127.0.0.1:18789}"
OPENCLAW_AGENT_ID="${OPENCLAW_AGENT_ID:-}"     # 留空则使用默认 agent
TIMEOUT_BUFFER="${TIMEOUT_BUFFER:-10}"

# ── 参数解析 ──
ROOM_ID=""
while [[ $# -gt 0 ]]; do
    case $1 in
        --room-id|-r)  ROOM_ID="$2"; shift 2 ;;
        --game-api-key) GAME_API_KEY="$2"; shift 2 ;;
        --hook-token)   OPENCLAW_HOOK_TOKEN="$2"; shift 2 ;;
        --game-server)  GAME_SERVER="$2"; shift 2 ;;
        --gateway)      OPENCLAW_GATEWAY="$2"; shift 2 ;;
        --agent-id)     OPENCLAW_AGENT_ID="$2"; shift 2 ;;
        -h|--help)
            echo "Werewolf Webhook Bridge 启动脚本"
            echo ""
            echo "用法:  $0 --room-id <room_id>"
            echo ""
            echo "参数:"
            echo "  -r, --room-id      房间 ID（必填）"
            echo "  --game-api-key     Game API Key（或设 GAME_API_KEY 环境变量）"
            echo "  --hook-token       Hook Token（或设 OPENCLAW_HOOK_TOKEN 环境变量）"
            echo "  --game-server      游戏服务器 (默认: localhost:8000)"
            echo "  --gateway          OpenClaw Gateway (默认: 127.0.0.1:18789)"
            echo "  --agent-id         OpenClaw Agent ID (可选)"
            echo ""
            echo "环境变量:"
            echo "  GAME_API_KEY          Werewolf Arena API Key"
            echo "  OPENCLAW_HOOK_TOKEN   OpenClaw Gateway Hook Token"
            echo "  GAME_SERVER           游戏服务器地址"
            echo "  OPENCLAW_GATEWAY      Gateway 地址"
            echo "  OPENCLAW_AGENT_ID     Agent ID"
            echo "  TIMEOUT_BUFFER        降级缓冲秒数 (默认: 10)"
            exit 0
            ;;
        *) echo "未知参数: $1"; exit 1 ;;
    esac
done

# ── 必填检查 ──
if [[ -z "$ROOM_ID" ]]; then
    echo "错误: 请提供 --room-id"; exit 1
fi
if [[ -z "$GAME_API_KEY" ]]; then
    echo "错误: 请设置 GAME_API_KEY 或传入 --game-api-key"; exit 1
fi
if [[ -z "$OPENCLAW_HOOK_TOKEN" ]]; then
    echo "错误: 请设置 OPENCLAW_HOOK_TOKEN 或传入 --hook-token"; exit 1
fi

# ── 检查依赖 ──
python3 -c "import httpx, websockets" 2>/dev/null || {
    echo "缺少依赖，正在安装..."
    pip install httpx websockets
}

# ── 定位 ws_bridge.py ──
SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BRIDGE="$SCRIPT_DIR/ws_bridge.py"
if [[ ! -f "$BRIDGE" ]]; then
    echo "错误: 找不到 $BRIDGE"; exit 1
fi

# ── 构建启动命令 ──
CMD=(python3 "$BRIDGE"
    --room-id "$ROOM_ID"
    --game-api-key "$GAME_API_KEY"
    --game-server "$GAME_SERVER"
    --openclaw-gateway "$OPENCLAW_GATEWAY"
    --openclaw-hook-token "$OPENCLAW_HOOK_TOKEN"
    --timeout-buffer "$TIMEOUT_BUFFER"
)
[[ -n "$OPENCLAW_AGENT_ID" ]] && CMD+=(--openclaw-agent-id "$OPENCLAW_AGENT_ID")

# ── 启动 ──
LOG_DIR="$HOME/.openclaw/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/ws_bridge_${ROOM_ID}.log"

echo "启动 Webhook Bridge..."
echo "  房间:    $ROOM_ID"
echo "  游戏:    $GAME_SERVER"
echo "  网关:    $OPENCLAW_GATEWAY"
echo "  日志:    $LOG_FILE"

"${CMD[@]}" > "$LOG_FILE" 2>&1 &
PID=$!
echo ""
echo "✓ Bridge 已启动 (PID: $PID)"
echo "✓ 查看日志: tail -f $LOG_FILE"
echo "✓ 停止: kill $PID"
