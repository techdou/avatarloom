#!/bin/bash
# AvatarLoom AutoDL 服务启动
#
# 用法：
#   bash scripts/autodl_start.sh           # 启动所有服务（幂等——已运行的跳过）
#   bash scripts/autodl_start.sh stop      # 停止
#   bash scripts/autodl_start.sh status    # 查看状态（有服务没起来时退出码 1）
#
# 服务端口（可用 .env 的独立别名覆盖）：
#   Control API:     ${AVATARLOOM_CONTROL_API_PORT:-27810}
#   Runtime Gateway: ${AVATARLOOM_RUNTIME_GATEWAY_PORT:-27811}
#   Studio:          ${STUDIO_PORT:-27300}
#
# 本地固定访问标准：
#   Studio 27300 → 27300；Control API 27810 → 27810；Gateway 27811 → 27811。
#   SSH 隧道示例：
#   ssh -L 27300:127.0.0.1:27300 -L 27810:127.0.0.1:27810 \
#       -L 27811:127.0.0.1:27811 root@<ip> -p <port>

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

# 加载环境
export PATH="$HOME/.local/bin:$PATH"
# pnpm 常见安装位置（npm -g 或 corepack），start.sh 是非交互 shell 不读 .bashrc
for _p in /usr/local/lib/node22/bin /usr/local/bin "$HOME/.local/share/pnpm" "$HOME/.npm-global/bin"; do
    if [ -x "$_p/pnpm" ] || [ -x "$_p/pnpm.cmd" ]; then
        export PATH="$_p:$PATH"
        break
    fi
done
export HF_ENDPOINT=${HF_ENDPOINT:-https://hf-mirror.com}
export HF_HUB_DISABLE_XET=1

# 读 .env
if [ -f .env ]; then
    set -a
    . ./.env
    set +a
fi

# 端口解析（与 .env.example / 服务 Settings 别名一致）
CONTROL_API_PORT=${AVATARLOOM_CONTROL_API_PORT:-27810}
RUNTIME_GATEWAY_PORT=${AVATARLOOM_RUNTIME_GATEWAY_PORT:-27811}
STUDIO_PORT=${STUDIO_PORT:-27300}

PID_DIR="./data"
mkdir -p "$PID_DIR"

ACTION="${1:-start}"

# 等待端口就绪：进程活着且端口能 accept 才算起来。
# 返回 0=就绪，1=超时（含进程中途死亡）。
wait_for_port() {
    local port=$1 pid=$2 timeout=${3:-60}
    local elapsed=0
    while [ "$elapsed" -lt "$timeout" ]; do
        if ! kill -0 "$pid" 2>/dev/null; then
            return 1   # 进程已死
        fi
        if (echo > "/dev/tcp/127.0.0.1/$port") 2>/dev/null; then
            return 0
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done
    return 1
}

is_running() {
    local pidfile="$PID_DIR/$1.pid"
    [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile")" 2>/dev/null
}

stop_service() {
    local name=$1
    local pidfile="$PID_DIR/${name}.pid"
    if [ ! -f "$pidfile" ]; then
        echo "  - $name 未启动"
        return 0
    fi
    local pid
    pid=$(cat "$pidfile")
    if ! kill -0 "$pid" 2>/dev/null; then
        echo "  ~ $name 进程已不在（pid=$pid），清理 stale pidfile"
        rm -f "$pidfile"
        return 0
    fi
    kill "$pid"
    # 等最多 10s 优雅退出，不行再 SIGKILL
    for _ in $(seq 1 10); do
        kill -0 "$pid" 2>/dev/null || break
        sleep 1
    done
    if kill -0 "$pid" 2>/dev/null; then
        kill -9 "$pid" 2>/dev/null || true
        echo "  ✓ $name 已强制停止 (pid=$pid)"
    else
        echo "  ✓ 停止 $name (pid=$pid)"
    fi
    rm -f "$pidfile"
}

# start_service <name> <port> <cmd...>
# 幂等：已在运行则跳过；启动失败（进程死亡/端口超时）→ 杀掉并整体退出 1。
# 成功拉起的服务记入 STARTED（全局数组），供失败时回滚——只停本次拉起的，
# 不动脚本运行前就在跑的。
start_service() {
    local name=$1 port=$2
    shift 2
    local pidfile="$PID_DIR/${name}.pid"

    if is_running "$name"; then
        echo "  ~ $name 已在运行 (pid=$(cat "$pidfile"))，跳过"
        return 0
    fi
    rm -f "$pidfile"   # stale pidfile

    echo "启动 $name..."
    # 日志落盘（data/<name>.log）——后台进程的 stdout 不重定向会在
    # SSH 会话结束后写进死管道，排障时日志直接丢失。
    "$@" >> "$PID_DIR/$name.log" 2>&1 &
    local pid=$!
    echo "$pid" > "$pidfile"
    echo "  $name pid=$pid，等待端口 $port 就绪..."

    if ! wait_for_port "$port" "$pid" 60; then
        echo "  ✗ $name 启动失败（端口 $port 60s 未就绪或进程已退出）" >&2
        kill "$pid" 2>/dev/null || true
        rm -f "$pidfile"
        return 1
    fi
    STARTED+=("$name")
    echo "  ✓ $name 就绪（127.0.0.1:$port）"
}

case "$ACTION" in
    start)
        echo "========================================"
        echo "AvatarLoom 服务启动"
        echo "========================================"

        # 浏览器 WS 鉴权 token 是 NEXT_PUBLIC_（编译期内联进客户端 bundle），
        # 必须在 build 环境导出才生效；漏配会让 gateway fail-closed 拒绝所有 WS，
        # 页面报"鉴权失败"。AVATARLOOM_API_TOKEN 已配而它未配时自动同步。
        if [ -n "${AVATARLOOM_API_TOKEN:-}" ] && [ -z "${NEXT_PUBLIC_WS_TOKEN:-}" ]; then
            export NEXT_PUBLIC_WS_TOKEN="$AVATARLOOM_API_TOKEN"
        fi

        # 需要构建：无 .next（首次），或 token 已轮换（产物里 grep 不到当前值）
        need_build=0
        if [ ! -d apps/studio/.next ]; then
            echo "首次启动，构建 Studio..."
            need_build=1
        elif [ -n "${NEXT_PUBLIC_WS_TOKEN:-}" ] \
            && ! grep -rq -- "$NEXT_PUBLIC_WS_TOKEN" apps/studio/.next/static apps/studio/.next/server 2>/dev/null; then
            echo "检测到 WS token 与构建产物不一致（.env 轮换过 token？），重建 Studio..."
            need_build=1
        fi
        if [ "$need_build" = 1 ]; then
            mkdir -p data/logs
            # 构建输出落日志——Next.js 类型错误通常在中部，tail -3 只留空白排障不可见
            (cd apps/studio && pnpm build > ../data/logs/studio_build.log 2>&1) || {
                echo "Studio 构建失败，尾部输出如下（全文 data/logs/studio_build.log）：" >&2
                tail -30 data/logs/studio_build.log >&2
                exit 1
            }
        fi

        # 回滚：任一服务启动失败时，把本次拉起的服务停掉，不留半拉子栈
        STARTED=()
        rollback() {
            echo "启动失败，回滚本次拉起的服务..." >&2
            local i
            for ((i=${#STARTED[@]}-1; i>=0; i--)); do
                stop_service "${STARTED[$i]}"
            done
        }

        # Control API
        # 注意：必须 --no-sync——uv run 默认会按 lockfile 重新 sync 并 prune 掉
        # setup.sh 用 --extra gpu-full 装的 torch/funasr/transformers 等（不在默认 extras），
        # 不带 --no-sync 首次启动会把 GPU 依赖全部卸载，SenseVoice 装配直接失败。
        start_service control-api "$CONTROL_API_PORT" \
            uv run --no-sync python -m avatarloom_control_api || { rollback; exit 1; }

        # Runtime Gateway——守护循环：gateway 每次真实会话后以 42 自重启
        # （CUDA context 污染后 fork 子进程必崩，见 ws_handler.cleanup），
        # 循环在此拉起新进程；stop 时 bash 收 TERM 转发给子进程后退出。
        start_service runtime-gateway "$RUNTIME_GATEWAY_PORT" \
            bash -c '
                while true; do
                    uv run --no-sync python -m avatarloom_runtime_gateway
                    rc=$?
                    echo "[autodl_start] runtime-gateway exited rc=$rc"
                    if [ "$rc" -eq 42 ]; then
                        echo "[autodl_start] 会话后自动重启 gateway"
                        continue
                    fi
                    break
                done
            ' || { rollback; exit 1; }

        # Studio（生产模式，省内存；next start 读 PORT）
        start_service studio "$STUDIO_PORT" \
            env "PORT=$STUDIO_PORT" pnpm --filter @avatarloom/studio start || { rollback; exit 1; }

        echo ""
        echo "========================================"
        echo "服务已启动"
        echo "========================================"
        echo "  Control API:     http://127.0.0.1:$CONTROL_API_PORT"
        echo "  Runtime Gateway: ws://127.0.0.1:$RUNTIME_GATEWAY_PORT"
        echo "  Studio:          http://127.0.0.1:$STUDIO_PORT"
        echo ""
        echo "本地固定访问（SSH 隧道）："
        echo "  ssh -L 27300:127.0.0.1:$STUDIO_PORT \"
        echo "      -L 27810:127.0.0.1:$CONTROL_API_PORT \"
        echo "      -L 27811:127.0.0.1:$RUNTIME_GATEWAY_PORT root@<ip> -p <port>"
        echo "  Studio:      http://localhost:27300"
        echo "  Control API: http://localhost:27810/api"
        echo "  Gateway WS:  ws://localhost:27811/ws/realtime"
        echo ""
        echo "停止：bash scripts/autodl_start.sh stop"
        echo "状态：bash scripts/autodl_start.sh status"
        ;;

    stop)
        stop_service studio
        stop_service runtime-gateway
        stop_service control-api
        # 守护循环兜底：bash 收 TERM 退出后 uv run/python 子进程可能残留，
        # 按服务名精确清理（与 restart 脚本同款姿势）
        for pat in 'avatarloom_runtime_gateway' 'avatarloom_control_api' 'next-server'; do
            # grep 无匹配退出 1，pipefail + set -e 会在此杀掉整个脚本，
            # 导致后面的模式（next-server）永远执行不到——历代 next-server
            # 残留占端口的根因。命令替换兜 || true 使赋值恒成功。
            pids=$(ps -eo pid,cmd | grep -E "$pat" | grep -v grep | awk '{print $1}' || true)
            if [ -n "$pids" ]; then
                kill $pids 2>/dev/null || true
                # next-server 等进程可能忽略/拖延 SIGTERM（keep-alive 优雅关闭），
                # 等 3s 仍存活则升级 SIGKILL，避免残留进程占住端口坑下一次启动
                for _ in $(seq 1 3); do
                    alive=""
                    for p in $pids; do
                        kill -0 "$p" 2>/dev/null && alive="$alive $p"
                    done
                    [ -z "$alive" ] && break
                    sleep 1
                done
                if [ -n "$alive" ]; then
                    kill -9 $alive 2>/dev/null || true
                    echo "  ✓ 清理残留 $pat ($pids，SIGTERM 无效已强杀:$alive)"
                else
                    echo "  ✓ 清理残留 $pat ($pids)"
                fi
            fi
        done
        echo "所有服务已停止"
        ;;

    status)
        rc=0
        for svc in control-api runtime-gateway studio; do
            pidfile="$PID_DIR/${svc}.pid"
            if [ -f "$pidfile" ]; then
                pid=$(cat "$pidfile")
                if kill -0 "$pid" 2>/dev/null; then
                    echo "  ✓ $svc (pid=$pid) 运行中"
                else
                    echo "  ✗ $svc 进程不存在（pid=$pid 已死，stale pidfile）"
                    rc=1
                fi
            else
                echo "  - $svc 未启动"
                rc=1
            fi
        done
        exit "$rc"
        ;;

    *)
        echo "用法: $0 {start|stop|status}"
        exit 1
        ;;
esac
