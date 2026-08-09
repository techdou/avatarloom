#!/usr/bin/env python
"""AvatarLoom 一键启动三服务（Control API + Runtime Gateway + Studio）。

用法：
    uv run python scripts/dev.py         # 启动所有
    uv run python scripts/dev.py --check # 只检查端口占用

端口约定（与 .env.example / 服务自身的 Settings 别名一致）：
    AVATARLOOM_CONTROL_API_PORT      默认 8100
    AVATARLOOM_RUNTIME_GATEWAY_PORT  默认 8101
    STUDIO_PORT                      默认 3000（经 PORT 传给 next dev）

退出码：
    0   正常停止（Ctrl+C）
    1   端口冲突 / 启动失败 / 服务被信号杀死
    其他 某个服务以非零码退出时，透传该退出码
"""

from __future__ import annotations

import argparse
import contextlib
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
os.chdir(PROJECT_ROOT)

CONTROL_API_PORT = int(os.environ.get("AVATARLOOM_CONTROL_API_PORT", "8100"))
RUNTIME_GATEWAY_PORT = int(os.environ.get("AVATARLOOM_RUNTIME_GATEWAY_PORT", "8101"))
STUDIO_PORT = int(os.environ.get("STUDIO_PORT", "3000"))

# 启动宽限：进程拉起后过了这么多秒还活着，视为启动成功。
_STARTUP_GRACE_S = 3.0


def _resolve_pnpm() -> str:
    """解析 pnpm 可执行文件。

    Windows 上 pnpm 是 pnpm.cmd（PATHEXT shim），直接写 "pnpm" 时
    CreateProcess 只找 .exe 会 FileNotFoundError；shutil.which 走 PATHEXT
    能找到 .cmd 全路径，Popen 即可正常拉起。
    """
    exe = shutil.which("pnpm")
    if exe is None:
        raise FileNotFoundError("未找到 pnpm——请先安装（npm install -g pnpm 或 corepack enable）")
    return exe


def _services(pnpm: str) -> list[dict]:
    return [
        {
            "name": "control-api",
            "cmd": [sys.executable, "-m", "avatarloom_control_api"],
            "port": CONTROL_API_PORT,
            # 只传独立别名——AVATARLOOM_PORT 是两个服务共享的旧名，传了会撞车。
            "env": {**os.environ, "AVATARLOOM_CONTROL_API_PORT": str(CONTROL_API_PORT)},
            "cwd": PROJECT_ROOT,
        },
        {
            "name": "runtime-gateway",
            "cmd": [sys.executable, "-m", "avatarloom_runtime_gateway"],
            "port": RUNTIME_GATEWAY_PORT,
            "env": {**os.environ, "AVATARLOOM_RUNTIME_GATEWAY_PORT": str(RUNTIME_GATEWAY_PORT)},
            "cwd": PROJECT_ROOT,
        },
        {
            "name": "studio",
            "cmd": [pnpm, "--filter", "@avatarloom/studio", "dev"],
            "port": STUDIO_PORT,
            # next dev 读 PORT 环境变量（package.json 不再硬编码 -p 3000）。
            "env": {**os.environ, "PORT": str(STUDIO_PORT)},
            "cwd": PROJECT_ROOT,
        },
    ]


# 端口清单（--check 不需要 pnpm，单独列出）
_PORTS = [
    ("control-api", CONTROL_API_PORT),
    ("runtime-gateway", RUNTIME_GATEWAY_PORT),
    ("studio", STUDIO_PORT),
]


def is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def check_ports() -> int:
    """检查端口占用，返回冲突数。"""
    conflicts = 0
    for name, port in _PORTS:
        if is_port_in_use(port):
            print(f"  ✗ 端口 {port} 已被占用（{name}）")
            conflicts += 1
        else:
            print(f"  ✓ 端口 {port} 空闲（{name}）")
    return conflicts


def _terminate_tree(p: subprocess.Popen) -> None:
    """停掉一个服务进程（Windows 杀整棵进程树）。

    Windows 上 pnpm.cmd → node 是孙进程，terminate()（TerminateProcess）
    只杀直接子进程，会留下孤儿 node 占着 3000 端口；taskkill /T 杀整棵树。
    """
    if p.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(p.pid)],
            capture_output=True,
            check=False,
        )
        return
    try:
        p.terminate()
        p.wait(timeout=5)
    except Exception:
        p.kill()


def _shutdown_all(procs: list[subprocess.Popen]) -> None:
    for p in reversed(procs):
        with contextlib.suppress(Exception):
            _terminate_tree(p)


def _normalize_rc(rc: int | None) -> int:
    """进程退出码转成本脚本的退出码（负值=被信号杀死，归一为 1）。"""
    if rc is None:
        return 1
    if rc < 0:
        return 1
    return rc


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

    try:
        pnpm = _resolve_pnpm()
    except FileNotFoundError as e:
        print(f"  ✗ {e}", file=sys.stderr)
        return 1
    services = _services(pnpm)

    print("\n启动 AvatarLoom 三服务...")
    print(f"  Control API:     http://127.0.0.1:{CONTROL_API_PORT}")
    print(f"  Runtime Gateway: ws://127.0.0.1:{RUNTIME_GATEWAY_PORT}/ws/realtime")
    print(f"  Studio:          http://127.0.0.1:{STUDIO_PORT}")
    print("\n按 Ctrl+C 停止所有服务。\n")

    procs: list[subprocess.Popen] = []

    def shutdown(*_: object) -> None:
        print("\n停止服务...")
        _shutdown_all(procs)
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # 拉起全部服务
    for svc in services:
        try:
            p = subprocess.Popen(
                svc["cmd"],
                cwd=str(svc["cwd"]),
                env=svc["env"],
            )
            procs.append(p)
            print(f"  ✓ 启动 {svc['name']} (pid={p.pid})")
        except OSError as e:
            print(f"  ✗ 启动 {svc['name']} 失败：{e}", file=sys.stderr)
            _shutdown_all(procs)
            return 1

    # 启动宽限检查——拉起后立刻死掉的（模块缺失、bind 失败等）算启动失败
    time.sleep(_STARTUP_GRACE_S)
    for svc, p in zip(services, procs, strict=True):
        rc = p.poll()
        if rc is not None:
            print(f"  ✗ {svc['name']} 启动后立即退出 (code={rc})——启动失败", file=sys.stderr)
            _shutdown_all(procs)
            return _normalize_rc(rc) or 1

    # 监控：rc=42 是 gateway 的自重启信号（GPU 会话后清除 CUDA fork 状态），
    # dev 场景下重启该服务而非灭全栈；其他退出码 → 灭全栈。
    _RESTART_RC = 42
    while True:
        for idx, (svc, p) in enumerate(zip(services, procs, strict=True)):
            rc = p.poll()
            if rc is not None:
                if rc == _RESTART_RC:
                    print(
                        f"\n{svc['name']} 自重启 (rc={rc})，重新拉起...",
                        file=sys.stderr,
                    )
                    new_p = subprocess.Popen(
                        svc["cmd"], cwd=str(svc["cwd"]), env=svc["env"]
                    )
                    procs[idx] = new_p
                    print(f"  ✓ 重新启动 {svc['name']} (pid={new_p.pid})")
                    break  # 重启后继续监控循环，不灭全栈
                print(
                    f"\n{svc['name']} 已退出 (code={rc})，正在停止其余服务...",
                    file=sys.stderr,
                )
                _shutdown_all([q for q in procs if q is not p])
                return _normalize_rc(rc)
        time.sleep(0.5)


if __name__ == "__main__":
    sys.exit(main())
