"""Keep the database catalog and runtime-readable files in sync.

The Control API database is the live source of truth. Repository YAML/persona packages
seed an empty database and remain an inspectable/exportable mirror for local workflows.
"""

from __future__ import annotations

from contextlib import suppress
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from avatarloom_control_api.config import Settings
from avatarloom_control_api.models import Persona, RuntimeProfile


def _profile_values(path: Path) -> dict[str, Any] | None:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("kind") != "RuntimeProfile":
        return None
    metadata = data.get("metadata") or {}
    sync = dict(data.get("sync") or {})
    session = data.get("session") or {}
    if session:
        sync["_session"] = session
    return {
        "id": str(metadata.get("id") or path.stem),
        "name": str(metadata.get("name") or path.stem),
        "description": metadata.get("description"),
        "blocks": data.get("blocks") or {},
        "sync": sync or None,
    }


def _persona_values(package_dir: Path) -> dict[str, Any] | None:
    yaml_path = package_dir / "persona.yaml"
    prompt_path = package_dir / "persona.md"
    if not yaml_path.exists() or not prompt_path.exists():
        return None
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("kind") != "PersonaPackage":
        return None
    metadata = data.get("metadata") or {}
    return {
        "id": str(metadata.get("id") or package_dir.name),
        "name": str(metadata.get("name") or package_dir.name),
        "label": metadata.get("label"),
        "version": str(metadata.get("version") or "0.1.0"),
        "prompt": prompt_path.read_text(encoding="utf-8").strip(),
        "package_path": f"personas/{package_dir.name}",
        "voice_ref": data.get("voice") or None,
        "avatar_ref": data.get("avatar") or None,
        "behavior": data.get("behavior") or None,
    }


async def seed_runtime_catalog(
    session_factory: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    """Seed missing DB rows from repository packages without overwriting Studio edits."""
    workspace = Path(settings.workspace_root)
    async with session_factory() as db:
        for path in sorted((workspace / "profiles").glob("*.yaml")):
            values = _profile_values(path)
            if values and await db.get(RuntimeProfile, values["id"]) is None:
                db.add(RuntimeProfile(**values))
        personas_dir = workspace / "personas"
        if personas_dir.exists():
            for package in sorted(p for p in personas_dir.iterdir() if p.is_dir()):
                values = _persona_values(package)
                if values and await db.get(Persona, values["id"]) is None:
                    db.add(Persona(**values))
        await db.commit()


def write_profile_mirror(settings: Settings, profile: RuntimeProfile) -> None:
    sync = dict(profile.sync or {})
    session = sync.pop("_session", None)
    document: dict[str, Any] = {
        "apiVersion": "avatarloom.io/v1alpha1",
        "kind": "RuntimeProfile",
        "metadata": {
            "id": profile.id,
            "name": profile.name,
            "description": profile.description or "",
        },
        "blocks": profile.blocks,
    }
    if sync:
        document["sync"] = sync
    if isinstance(session, dict) and session:
        document["session"] = session
    root = Path(settings.workspace_root) / "profiles"
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{profile.id}.yaml"
    temporary = target.with_suffix(".yaml.tmp")
    temporary.write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    temporary.replace(target)


def remove_profile_mirror(settings: Settings, profile_id: str) -> None:
    (Path(settings.workspace_root) / "profiles" / f"{profile_id}.yaml").unlink(
        missing_ok=True
    )


def write_persona_mirror(settings: Settings, persona: Persona) -> None:
    root = Path(settings.workspace_root) / "personas" / persona.id
    root.mkdir(parents=True, exist_ok=True)
    document = {
        "apiVersion": "avatarloom.io/v1alpha1",
        "kind": "PersonaPackage",
        "metadata": {
            "id": persona.id,
            "name": persona.name,
            "label": persona.label,
            "version": persona.version,
        },
        "prompt": {"file": "persona.md"},
        "voice": persona.voice_ref or {},
        "avatar": persona.avatar_ref or {},
        "behavior": persona.behavior or {},
    }
    (root / "persona.md").write_text(persona.prompt, encoding="utf-8")
    target = root / "persona.yaml"
    temporary = target.with_suffix(".yaml.tmp")
    temporary.write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    temporary.replace(target)


def remove_persona_mirror(settings: Settings, persona_id: str) -> None:
    root = Path(settings.workspace_root) / "personas" / persona_id
    for name in ("persona.yaml", "persona.md"):
        (root / name).unlink(missing_ok=True)
    # Preserve uploaded assets; callers may clean them explicitly after review.
    with suppress(OSError):
        root.rmdir()
