"""Persona 包加载器。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class PersonaError(Exception):
    """Persona 加载错误。"""


class PersonaPackage(BaseModel):
    """加载后的 Persona 包。"""

    id: str
    name: str
    label: str | None = None
    version: str = "0.1.0"
    # system prompt 正文（从 persona.md 读取）
    prompt: str = ""
    # voice 引用
    voice_block: str | None = None
    voice_ref_audio: str | None = None
    voice_ref_text: str | None = None
    # avatar 引用
    avatar_block: str | None = None
    avatar_portrait: str | None = None
    avatar_idle_video: str | None = None
    # 行为规则
    behavior: dict[str, Any] = Field(default_factory=dict)
    # 包根路径（绝对）
    package_path: str = ""
    # 元数据
    memory_namespace: str | None = None
    skills_allow: list[str] = Field(default_factory=list)


def load_persona(package_dir: str | Path, workspace_root: str | Path = ".") -> PersonaPackage:
    """从目录加载 Persona 包。

    Args:
        package_dir: persona 包目录（含 persona.yaml + persona.md）
        workspace_root: workspace 根，用于解析相对路径

    Returns:
        PersonaPackage 实例。

    Raises:
        PersonaError: 文件缺失或格式错误。
    """
    root = Path(package_dir)
    if not root.is_absolute():
        root = Path(workspace_root) / root
    if not root.exists():
        raise PersonaError(f"persona package not found: {root}")

    yaml_path = root / "persona.yaml"
    md_path = root / "persona.md"

    if not yaml_path.exists():
        raise PersonaError(f"persona.yaml not found in {root}")
    if not md_path.exists():
        raise PersonaError(f"persona.md not found in {root}")

    # 解析 yaml
    try:
        with yaml_path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise PersonaError(f"invalid persona.yaml: {e}") from e
    if not isinstance(data, dict):
        raise PersonaError("persona.yaml root must be a mapping")

    metadata = data.get("metadata") or {}
    persona_id = str(metadata.get("id") or root.name)
    persona_name = str(metadata.get("name") or persona_id)
    persona_label = metadata.get("label")
    persona_version = str(metadata.get("version") or "0.1.0")

    # prompt 文件引用
    prompt_cfg = data.get("prompt") or {}
    prompt_file = prompt_cfg.get("file") if isinstance(prompt_cfg, dict) else None
    prompt_path = root / (prompt_file or "persona.md")
    try:
        prompt_text = prompt_path.read_text(encoding="utf-8").strip()
    except OSError as e:
        raise PersonaError(f"failed to read prompt file {prompt_path}: {e}") from e

    # voice 引用
    voice = data.get("voice") or {}
    voice_block = voice.get("block") if isinstance(voice, dict) else None
    voice_ref_audio = _resolve_ref(voice.get("refAudio"), root)
    voice_ref_text = _resolve_ref_text(voice.get("refText"), root)

    # avatar 引用
    avatar = data.get("avatar") or {}
    avatar_block = avatar.get("block") if isinstance(avatar, dict) else None
    avatar_portrait = _resolve_ref(avatar.get("portrait"), root)
    avatar_idle_video = _resolve_ref(avatar.get("idleVideo"), root)

    # behavior
    behavior = data.get("behavior") or {}
    memory_namespace = behavior.get("memory_namespace") or behavior.get("namespace") or persona_id
    skills_allow = (
        behavior.get("skills", {}).get("allow", [])
        if isinstance(behavior.get("skills"), dict)
        else []
    )

    return PersonaPackage(
        id=persona_id,
        name=persona_name,
        label=persona_label,
        version=persona_version,
        prompt=prompt_text,
        voice_block=voice_block,
        voice_ref_audio=voice_ref_audio,
        voice_ref_text=voice_ref_text,
        avatar_block=avatar_block,
        avatar_portrait=avatar_portrait,
        avatar_idle_video=avatar_idle_video,
        behavior=behavior if isinstance(behavior, dict) else {},
        package_path=str(root),
        memory_namespace=memory_namespace,
        skills_allow=list(skills_allow),
    )


def _resolve_ref(ref: Any, root: Path) -> str | None:
    """解析文件引用为绝对路径字符串。"""
    if not ref:
        return None
    p = Path(str(ref))
    if not p.is_absolute():
        p = root / p
    return str(p) if p.exists() else None


def _resolve_ref_text(ref: Any, root: Path) -> str | None:
    """ref.txt 类文本引用——读成内容。"""
    if not ref:
        return None
    p = Path(str(ref))
    if not p.is_absolute():
        p = root / p
    if not p.exists():
        return None
    try:
        return p.read_text(encoding="utf-8").strip()
    except OSError:
        return None
