#!/usr/bin/env python
"""AvatarLoom 环境自检。

检查：
- Python / Node 版本
- 核心依赖 + 可选 GPU 依赖
- Profile 文件完整性
- 端口可用性
- API Key 状态（不打印值，只看是否设置）
- Workspace 目录
"""

from __future__ import annotations

import contextlib
import importlib
import os
import socket
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _check(label: str, ok: bool, detail: str = "") -> tuple[str, bool, str]:
    status = "✓" if ok else "✗"
    return (f"  {status} {label}{(': ' + detail) if detail else ''}", ok, detail)


def check_python() -> list[tuple[str, bool, str]]:
    results = []
    v = sys.version_info
    ok = v >= (3, 11)
    results.append(
        _check(
            f"Python {v.major}.{v.minor}.{v.micro}",
            ok,
            "需要 3.11+" if not ok else "",
        )
    )
    return results


def check_core_deps() -> list[tuple[str, bool, str]]:
    results = []
    for mod in [
        "fastapi",
        "uvicorn",
        "pydantic",
        "sqlalchemy",
        "httpx",
        "websockets",
        "numpy",
        "yaml",
    ]:
        try:
            importlib.import_module(mod)
            results.append(_check(f"依赖 {mod}", True))
        except ImportError:
            results.append(_check(f"依赖 {mod}", False, "未安装，运行 uv sync"))
    return results


def check_gpu_deps() -> list[tuple[str, bool, str]]:
    results = []
    for mod, extra in [
        ("torch", "silero/sensevoice/qwen3-tts/voxcpm2/musetalk"),
        ("funasr", "sensevoice"),
        ("transformers", "qwen3-tts/voxcpm2"),
        ("cv2", "musetalk"),
        ("voxcpm", "voxcpm2"),
    ]:
        try:
            importlib.import_module(mod)
            results.append(_check(f"GPU 依赖 {mod}", True))
        except ImportError:
            results.append(_check(f"GPU 依赖 {mod}（可选）", False, f"uv sync --extra {extra}"))
    return results


def check_profiles() -> list[tuple[str, bool, str]]:
    results = []
    profiles_dir = PROJECT_ROOT / "profiles"
    expected = ["mock.yaml", "lite-12gb.yaml", "distributed.yaml", "full-24gb.yaml"]
    for name in expected:
        p = profiles_dir / name
        results.append(_check(f"Profile {name}", p.exists(), "缺失" if not p.exists() else ""))
    # 验证 mock profile 可加载
    try:
        from runtime.orchestrator.profile_loader import load_profile

        load_profile(profiles_dir / "mock.yaml")
        results.append(_check("mock profile 可加载", True))
    except Exception as e:
        results.append(_check("mock profile 可加载", False, str(e)))
    return results


def check_ports() -> list[tuple[str, bool, str]]:
    results = []
    # 端口与 .env.example / dev.py 同一来源：独立别名优先，默认 8100/8101/3000
    ports = [
        ("Control API", int(os.environ.get("AVATARLOOM_CONTROL_API_PORT", "8100"))),
        ("Runtime Gateway", int(os.environ.get("AVATARLOOM_RUNTIME_GATEWAY_PORT", "8101"))),
        ("Studio", int(os.environ.get("STUDIO_PORT", "3000"))),
    ]
    for name, port in ports:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            in_use = s.connect_ex(("127.0.0.1", port)) == 0
        # 端口被占用不一定是错（可能服务已起），这里只报状态
        results.append(
            _check(
                f"端口 {port} ({name})",
                True,  # 总是 ok
                "已占用（服务运行中）" if in_use else "空闲",
            )
        )
    return results


def check_api_keys() -> list[tuple[str, bool, str]]:
    """检查 API Key 状态——只看是否设置，不打印值。"""
    results = []
    for key in ["LLM_API_KEY", "STT_API_KEY", "TTS_API_KEY", "VISION_API_KEY", "OLLAMA_BASE_URL"]:
        is_set = bool(os.environ.get(key))
        # 这些都是可选的——Mock profile 不需要
        results.append(
            _check(
                f"环境变量 {key}",
                True,
                "已设置" if is_set else "未设置（Mock profile 不需要）",
            )
        )
    return results


def check_workspace() -> list[tuple[str, bool, str]]:
    results = []
    for d in ["data", "data/runs", "data/artifacts"]:
        p = PROJECT_ROOT / d
        exists = p.exists()
        results.append(_check(f"目录 {d}", True, "存在" if exists else "将自动创建"))
    return results


def main() -> int:
    # Windows/GBK 控制台下 print("✓") 会抛 UnicodeEncodeError，强制 UTF-8
    with contextlib.suppress(Exception):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    print("=" * 60)
    print("AvatarLoom Doctor — 环境自检")
    print("=" * 60)

    sections = [
        ("Python", check_python),
        ("核心依赖", check_core_deps),
        ("GPU 依赖（可选）", check_gpu_deps),
        ("Profiles", check_profiles),
        ("端口", check_ports),
        ("API Keys", check_api_keys),
        ("Workspace", check_workspace),
    ]

    critical_failures = 0
    for title, checker in sections:
        print(f"\n[{title}]")
        for msg, ok, _ in checker():
            print(msg)
            if not ok and title in ("Python", "核心依赖", "Profiles"):
                critical_failures += 1

    print("\n" + "=" * 60)
    if critical_failures == 0:
        print("✓ 核心环境正常。Mock Profile 可直接运行（make smoke）")
        print("  GPU 依赖缺失不影响 Mock 链路。")
        return 0
    else:
        print(f"✗ {critical_failures} 个关键问题。请修复后再运行。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
