"""RuntimeProfile 加载器。

从 YAML 文件加载 RuntimeProfile 到 OrchestratorConfig。

支持配置：
- ${ENV_VAR} 环境变量插值
- profile 引用解析
- Block manifest 校验（可选）
"""

from __future__ import annotations

import difflib
import os
import re
from pathlib import Path
from typing import Any

import yaml

from runtime.orchestrator.config import BlockRef, OrchestratorConfig, SyncConfig
from runtime.orchestrator.orchestrator import BLOCK_REGISTRY

_ENV_PATTERN = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")


class ProfileError(Exception):
    """Profile 加载错误。"""


def load_profile(profile_path: str | Path) -> OrchestratorConfig:
    """从 YAML 加载 RuntimeProfile。

    Args:
        profile_path: profile yaml 文件路径

    Returns:
        OrchestratorConfig 实例

    Raises:
        ProfileError: 文件缺失/格式错误/Block 引用无效
    """
    p = Path(profile_path)
    if not p.exists():
        raise ProfileError(f"profile not found: {p}")

    raw = p.read_text(encoding="utf-8")
    # 未插值版本：${VAR} 是合法 YAML 字符串，可先解析出 blocks 结构做环境变量校验
    try:
        raw_data = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        raise ProfileError(f"invalid yaml: {e}") from e

    interpolated, missing_envs = _interpolate_env(raw)
    try:
        data = yaml.safe_load(interpolated)
    except yaml.YAMLError as e:
        raise ProfileError(f"invalid yaml: {e}") from e

    if not isinstance(data, dict):
        raise ProfileError("profile root must be a mapping")

    if data.get("kind") and data.get("kind") != "RuntimeProfile":
        raise ProfileError(f"unexpected kind: {data.get('kind')}, expected RuntimeProfile")

    metadata = data.get("metadata") or {}
    profile_id = str(metadata.get("id") or p.stem)

    blocks_raw = data.get("blocks") or {}
    if not isinstance(blocks_raw, dict):
        raise ProfileError("blocks must be a mapping")

    blocks: dict[str, BlockRef] = {}
    for category, block_data in blocks_raw.items():
        if not isinstance(block_data, dict):
            raise ProfileError(f"block {category!r} must be a mapping")
        block_id = block_data.get("id")
        if not block_id:
            raise ProfileError(f"block {category!r} missing 'id'")
        blocks[category] = BlockRef(
            id=str(block_id),
            deployment=block_data.get("deployment", "local"),
            config=block_data.get("config") or {},
            optional=bool(block_data.get("optional", False)),
            fallback=block_data.get("fallback"),
        )

    sync_raw = data.get("sync") or {}
    sync = SyncConfig(
        audio_delay_ms=int(sync_raw.get("audio_delay_ms", sync_raw.get("audioDelayMs", 600))),
        video_lag_frames=int(sync_raw.get("video_lag_frames", sync_raw.get("videoLagFrames", 0))),
        max_video_behind_ms=int(
            sync_raw.get("max_video_behind_ms", sync_raw.get("maxVideoBehindMs", 1000))
        ),
        drop_policy=sync_raw.get("drop_policy", sync_raw.get("dropPolicy", "drop_oldest_video")),
    )

    session_raw = data.get("session") or {}

    # 校验：所有非 optional、无 fallback 的 block id 必须在 BLOCK_REGISTRY 中
    _validate_block_ids(blocks, profile_id=profile_id)

    # 缺失环境变量检查：非 optional、无 fallback 的 block 依赖 ${VAR} 时，
    # 缺变量会在运行期才暴露（空串 baseUrl → 连接错误），加载阶段直接报错更快定位。
    _validate_required_env(raw_data, missing_envs, profile_id=profile_id)

    return OrchestratorConfig(
        profile_id=profile_id,
        blocks=blocks,
        sync=sync,
        allow_interruption=bool(
            session_raw.get("allowInterruption", session_raw.get("allow_interruption", True))
        ),
        event_log=bool(session_raw.get("eventLog", session_raw.get("event_log", True))),
        session_mode=session_raw.get("mode", "single"),
        vision_timeout_s=float(
            session_raw.get("visionTimeoutS", session_raw.get("vision_timeout_s", 8.0))
        ),
    )


def _validate_block_ids(
    blocks: dict[str, BlockRef],
    *,
    profile_id: str,
) -> None:
    """校验所有 block id 是否在 BLOCK_REGISTRY 中。

    策略与 orchestrator._setup_block 保持一致：
    - 在 registry 中 → 通过
    - 不在 registry 但声明了 fallback → 通过（运行时走降级）
    - 不在 registry 但 optional → 通过（运行时跳过）
    - 否则 raise ProfileError，并给出 fuzzy 匹配建议
    """
    unknown: list[tuple[str, str]] = []  # (category, block_id)
    for category, ref in blocks.items():
        if ref.id in BLOCK_REGISTRY:
            continue
        if ref.fallback:
            continue
        if ref.optional:
            continue
        unknown.append((category, ref.id))

    if not unknown:
        return

    known_ids = list(BLOCK_REGISTRY.keys())
    details: list[str] = []
    for category, block_id in unknown:
        suggestions = difflib.get_close_matches(block_id, known_ids, n=3, cutoff=0.5)
        hint = (
            f"（你是不是想用：{', '.join(suggestions)}？）" if suggestions else ""
        )
        details.append(f"  - blocks.{category}.id={block_id!r}{hint}")

    raise ProfileError(
        f"profile {profile_id!r} 引用了未注册的 block id：\n"
        + "\n".join(details)
        + "\n请检查 id 拼写，或通过 register_block() 注册自定义 Block。"
    )


def _interpolate_env(text: str) -> tuple[str, set[str]]:
    """${VAR} -> env value。返回 (插值后文本, 未设置的变量名集合)。"""

    missing: set[str] = set()

    def repl(m: re.Match[str]) -> str:
        name = m.group(1)
        value = os.environ.get(name)
        if value is None:
            missing.add(name)
            return ""
        return value

    return _ENV_PATTERN.sub(repl, text), missing


def _validate_required_env(
    raw_data: dict[str, Any],
    missing_envs: set[str],
    *,
    profile_id: str,
) -> None:
    """非 optional、无 fallback 的 block 若引用缺失环境变量，直接 ProfileError。

    在未插值的 YAML 结构上检查：block.config 里字面 ${VAR} 命中缺失变量即报错，
    避免空串配置带到运行期才暴露（baseUrl="" → 连接错误，排障绕远）。
    """
    if not missing_envs:
        return

    blocks_raw = raw_data.get("blocks") or {}
    affected: list[str] = []
    for category, block_data in blocks_raw.items():
        if not isinstance(block_data, dict):
            continue
        if block_data.get("optional") or block_data.get("fallback"):
            continue
        cfg_text = str(block_data.get("config") or {})
        for var in sorted(missing_envs):
            if f"${{{var}}}" in cfg_text:
                affected.append(f"  - blocks.{category}.config 引用 ${{{var}}}")
                break

    if affected:
        raise ProfileError(
            f"profile {profile_id!r} 引用了未设置的环境变量：\n"
            + "\n".join(affected)
            + "\n请在 .env 中设置（或 export 后重启服务）。"
        )


def list_profiles(profiles_dir: str | Path = "profiles") -> list[dict[str, Any]]:
    """列出 profiles 目录下所有 yaml profile 的元数据。"""
    d = Path(profiles_dir)
    if not d.exists():
        return []
    result = []
    for f in sorted(d.glob("*.yaml")):
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("kind") == "RuntimeProfile":
                meta = data.get("metadata") or {}
                result.append(
                    {
                        "id": meta.get("id", f.stem),
                        "name": meta.get("name", f.stem),
                        "file": str(f),
                        "description": meta.get("description", ""),
                    }
                )
        except Exception:
            continue
    return result
