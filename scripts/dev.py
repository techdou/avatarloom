#!/usr/bin/env python
"""AvatarLoom 一键启动三服务（Control API + Runtime Gateway + Studio）。

用法：
    uv run python scripts/dev.py         # 启动所有
    uv run python scripts/dev.py --check # 只检查端口占用
"""

from __future__ import annotations

import argparse
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
os.chdir(PROJECT_ROOT)

# 把项目根加到 sys.path 让 gateway 能 import runtime/blocks
sys.path.insert(0, str(PROJECT_ROOT))

SERVICES = [
    {
        "name": "control-api",
        "cmd": [sys.executable, "-m", "avatarloom_control_api"],
        "port": int(os.environ.get("CONTROL_API_PORT", "8100")),
        "env": {**os.environ, "AVATARLOOM_PORT": "8100"},
        "cwd": PROJECT_ROOT,
    },
    {
        "name": "runtime-gateway",
        "cmd": [sys.executable, "-m", "avatarloom_runtime_gateway"],
        "port": int(os.environ.get("RUNTIME_GATEWAY_PORT", "8101")),
        "env": {**os.environ, "AVATARLOOM_PORT": "8101"},
        "cwd": PROJECT_ROOT,
    },
    {
        "name": "studio",
        "cmd": ["pnpm", "--filter", "@avatarloom/studio", "dev"],
        "port": int(os.environ.get("STUDIO_PORT", "3000")),
        "env": {**os.environ},
        "cwd": PROJECT_ROOT,
    },
]


def is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def check_ports() -> int:
    """检查端口占用，返回冲突数。"""
    conflicts = 0
    for svc in SERVICES:
        if is_port_in_use(svc["port"]):
            print(f"  ✗ 端口 {svc['port']} 已被占用（{svc['name']}）")
            conflicts += 1
        else:
            print(f"  ✓ 端口 {svc['port']} 空闲（{svc['name']}）")
    return conflicts


def main() -> int:
    parser = argparse.ArgumentParser(description="AvatarLoom dev launcher")
    parser.add_argument("--check", action="store_true", help="只检查端口")
    args = parser.parse_args()

    if args.check:
        print("端口检查：")
        return 0 if check_ports() == 0 else 1

    # 预检
    conflicts = check_ports()
    if conflicts > 0:
        print(f"\n{conflicts} 个端口被占用，请先释放或修改端口。", file=sys.stderr)
        return 1

    print("\n启动 AvatarLoom 三服务...")
    print("  Control API:     http://127.0.0.1:8100")
    print("  Runtime Gateway: ws://127.0.0.1:8101/ws/realtime")
    print("  Studio:          http://127.0.0.1:3000")
    print("\n按 Ctrl+C 停止所有服务。\n")

    procs: list[subprocess.Popen] = []

    def shutdown(*_: object) -> None:
        print("\n停止服务...")
        for p in reversed(procs):
            try:
                p.terminate()
                p.wait(timeout=5)
            except Exception:
                p.kill()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    for svc in SERVICES:
        try:
            p = subprocess.Popen(
                svc["cmd"],
                cwd=str(svc["cwd"]),
                env=svc["env"],
            )
            procs.append(p)
            print(f"  ✓ 启动 {svc['name']} (pid={p.pid})")
            time.sleep(0.5)
        except FileNotFoundError as e:
            print(f"  ✗ 启动 {svc['name']} 失败：{e}", file=sys.stderr)
            shutdown()

    # 等待所有进程
    try:
        for p in procs:
            p.wait()
    except KeyboardInterrupt:
        shutdown()

    return 0


if __name__ == "__main__":
    sys.exit(main())
