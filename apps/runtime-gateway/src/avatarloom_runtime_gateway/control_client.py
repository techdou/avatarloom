"""Control API client used by the runtime as its configuration source of truth."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx

from avatarloom_runtime_gateway.config import Settings, control_api_auth_headers
from runtime.orchestrator.config import OrchestratorConfig
from runtime.orchestrator.profile_loader import load_profile_data


class CatalogError(RuntimeError):
    """Control-plane catalog could not satisfy a runtime lookup."""


class CatalogNotFound(CatalogError):
    """Requested catalog object does not exist."""


class CatalogUnavailable(CatalogError):
    """Control API cannot be reached, so an offline mirror may be used."""


async def _get_json(settings: Settings, path: str) -> Any:
    url = f"{settings.control_api_url.rstrip('/')}/api/{path.lstrip('/')}"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(url, headers=control_api_auth_headers(settings))
    except httpx.RequestError as exc:
        raise CatalogUnavailable("control API unavailable") from exc
    if response.status_code == 404:
        raise CatalogNotFound(path)
    try:
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise CatalogError(f"invalid control API response for {path}") from exc
    return payload


async def _get(settings: Settings, path: str) -> dict[str, Any]:
    payload = await _get_json(settings, path)
    if not isinstance(payload, dict):
        raise CatalogError(f"invalid control API payload for {path}")
    return payload


async def list_runtime_profile_ids(settings: Settings) -> list[str]:
    """Return the live Control API profile catalog, rejecting malformed entries."""
    payload = await _get_json(settings, "profiles")
    if not isinstance(payload, list):
        raise CatalogError("invalid control API payload for profiles")
    profile_ids: list[str] = []
    for item in payload:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise CatalogError("invalid profile entry from control API")
        profile_ids.append(item["id"])
    return profile_ids


async def load_runtime_profile(settings: Settings, profile_id: str) -> OrchestratorConfig:
    profile = await _get(settings, f"profiles/{profile_id}")
    sync = dict(profile.get("sync") or {})
    session = sync.pop("_session", {})
    document = {
        "apiVersion": "avatarloom.io/v1alpha1",
        "kind": "RuntimeProfile",
        "metadata": {
            "id": profile.get("id") or profile_id,
            "name": profile.get("name") or profile_id,
            "description": profile.get("description") or "",
        },
        "blocks": profile.get("blocks") or {},
        "sync": sync,
        "session": session if isinstance(session, dict) else {},
    }
    return load_profile_data(document, source=f"control-api:{profile_id}")


async def load_runtime_persona(settings: Settings, persona_id: str) -> Any:
    data = await _get(settings, f"personas/{persona_id}")
    voice = data.get("voice_ref") or {}
    avatar = data.get("avatar_ref") or {}
    behavior = data.get("behavior") or {}
    return SimpleNamespace(
        id=data.get("id") or persona_id,
        name=data.get("name") or persona_id,
        label=data.get("label"),
        version=data.get("version") or "0.1.0",
        prompt=data.get("prompt") or "",
        voice_block=voice.get("block"),
        voice_ref_audio=voice.get("refAudio") or voice.get("ref_audio"),
        voice_ref_text=voice.get("refText") or voice.get("ref_text"),
        avatar_block=avatar.get("block"),
        avatar_portrait=avatar.get("portrait"),
        avatar_idle_video=avatar.get("idleVideo") or avatar.get("idle_video"),
        behavior=behavior,
        package_path=data.get("package_path") or "",
        memory_namespace=behavior.get("memory_namespace") or persona_id,
        skills_allow=(behavior.get("skills") or {}).get("allow", []),
    )
