#!/bin/bash
# AvatarLoom AutoDL 服务启动
#
# 用法：
#   bash scripts/autodl_start.sh           # 启动所有服务（前台）
#   bash scripts/autodl_start.sh stop      # 停止
#   bash scripts/autodl_start.sh status    # 查看状态
#
# 服务端口：
#   Control API:     8100
#   Runtime Gateway: 8101
#   Studio:          3000
#
# AutoDL 访问方式：
#   - AutoDL 控制台做端口映射（推荐 3000 端口）
#   - 或本地 SSH 隧道：ssh -L 3000:127.0.0.1:3000 -L 8101:127.0.0.1:8101 root@<ip> -p <port>

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

# 加载环境
export PATH="$HOME/.local/bin:$PATH"
export HF_ENDPOINT=${HF_ENDPOINT:-https://hf-mirror.com}
export HF_HUB_DISABLE_XET=1

# 读 .env
if [ -f .env ]; then
    set -a
    . ./.env
    set +a
fi

PID_DIR="./data"
mkdir -p "$PID_DIR"

ACTION="${1:-start}"

stop_service() {
    local name=$1
    local pidfile="$PID_DIR/${name}.pid"
    if [ -f "$pidfile" ]; then
        local pid=$(cat "$pidfile")
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid"
            echo "停止 $name (pid=$pid)"
            sleep 1
        fi
        rm -f "$pidfile"
    fi
}

start_service() {
    local name=$1
    shift
    local pidfile="$PID_DIR/${name}.pid"
    echo "启动 $name..."
    "$@" &
    local pid=$!
    echo "$pid" > "$pidfile"
    echo "  $name pid=$pid"
    sleep 1
}

case "$ACTION" in
    start)
        echo "========================================"
        echo "AvatarLoom 服务启动"
        echo "========================================"

        # Control API
        start_service control-api \
            uv run python -m avatarloom_control_api

        # Runtime Gateway
        start_service runtime-gateway \
            uv run python -m avatarloom_runtime_gateway

        # Studio（生产模式，省内存）
        cd apps/studio
        if [ ! -d .next ]; then
            echo "首次启动，构建 Studio..."
            pnpm build 2>&1 | tail -3
        fi
        cd "$PROJECT_ROOT"
        start_service studio \
            pnpm --filter @avatarloom/studio start

        echo ""
        echo "========================================"
        echo "服务已启动"
        echo "========================================"
        echo "  Control API:     http://127.0.0.1:8100"
        echo "  Runtime Gateway: ws://127.0.0.1:8101"
        echo "  Studio:          http://127.0.0.1:3000"
        echo ""
        echo "AutoDL 外部访问："
        echo "  1. 控制台 -> 容器 -> 自定义服务（暴露 3000）"
        echo "  2. 或本地 SSH 隧道："
        echo "     ssh -L 3000:127.0.0.1:3000 root@<ip> -p <port>"
        echo ""
        echo "停止：bash scripts/autodl_start.sh stop"
        echo "状态：bash scripts/autodl_start.sh status"
        ;;

    stop)
        stop_service studio
        stop_service runtime-gateway
        stop_service control-api
        echo "所有服务已停止"
        ;;

    status)
        for svc in control-api runtime-gateway studio; do
            pidfile="$PID_DIR/${svc}.pid"
            if [ -f "$pidfile" ]; then
                pid=$(cat "$pidfile")
                if kill -0 "$pid" 2>/dev/null; then
                    echo "  ✓ $svc (pid=$pid) 运行中"
                else
                    echo "  ✗ $svc 进程不存在（pid=$pid 已死）"
                fi
            else
                echo "  - $svc 未启动"
            fi
        done
        ;;

    *)
        echo "用法: $0 {start|stop|status}"
        exit 1
        ;;
esac
