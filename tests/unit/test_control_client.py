from __future__ import annotations

import avatarloom_runtime_gateway.ws_handler as ws_handler
import httpx
import pytest
from avatarloom_runtime_gateway.config import Settings
from avatarloom_runtime_gateway.control_client import (
    CatalogError,
    CatalogNotFound,
    CatalogUnavailable,
    list_runtime_profile_ids,
    load_runtime_persona,
    load_runtime_profile,
)


def _patch_client(monkeypatch, handler) -> None:
    original = httpx.AsyncClient.__init__

    def patched(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        original(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched)


async def test_profile_comes_from_control_api_with_auth(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer control-secret"
        assert request.url.path == "/api/profiles/edited"
        return httpx.Response(
            200,
            json={
                "id": "edited",
                "name": "Edited",
                "description": None,
                "blocks": {
                    "vad": {"id": "vad.mock", "deployment": "mock"},
                    "llm": {"id": "llm.mock", "deployment": "mock"},
                },
                "sync": {"audioDelayMs": 123, "_session": {"mode": "single"}},
            },
        )

    _patch_client(monkeypatch, handler)
    config = await load_runtime_profile(
        Settings(control_api_token="control-secret", auth_disabled=True), "edited"
    )
    assert config.profile_id == "edited"
    assert config.sync.audio_delay_ms == 123
    assert config.session_mode == "single"


async def test_missing_profile_is_not_silently_mocked(monkeypatch) -> None:
    _patch_client(monkeypatch, lambda request: httpx.Response(404))
    with pytest.raises(CatalogNotFound):
        await load_runtime_profile(Settings(auth_disabled=True), "does-not-exist")


async def test_persona_mapping(monkeypatch) -> None:
    _patch_client(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            json={
                "id": "guide",
                "name": "Guide",
                "prompt": "Be concise",
                "voice_ref": {"block": "tts.mock", "refText": "hello"},
                "avatar_ref": {"block": "avatar.static", "portrait": "portrait.png"},
                "behavior": {"memory_namespace": "guide-memory"},
            },
        ),
    )
    persona = await load_runtime_persona(Settings(auth_disabled=True), "guide")
    assert persona.prompt == "Be concise"
    assert persona.voice_ref_text == "hello"
    assert persona.memory_namespace == "guide-memory"


async def test_profile_listing_comes_from_live_control_catalog(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/profiles"
        return httpx.Response(200, json=[{"id": "edited"}, {"id": "gpu"}])

    _patch_client(monkeypatch, handler)
    assert await list_runtime_profile_ids(Settings(auth_disabled=True)) == [
        "edited",
        "gpu",
    ]


@pytest.mark.parametrize(
    ("response", "expected_error"),
    [
        (httpx.Response(401, json={"detail": "bad token"}), CatalogError),
        (httpx.Response(200, content=b"not-json"), CatalogError),
    ],
)
async def test_control_contract_failures_do_not_use_stale_profile_mirror(
    monkeypatch, tmp_path, response: httpx.Response, expected_error: type[Exception]
) -> None:
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles / "edited.yaml").write_text(
        """apiVersion: avatarloom.io/v1alpha1
kind: RuntimeProfile
metadata: {id: edited, name: Stale}
blocks: {vad: {id: vad.mock, deployment: mock}}
""",
        encoding="utf-8",
    )
    _patch_client(monkeypatch, lambda request: response)

    with pytest.raises(expected_error) as captured:
        await ws_handler._load_profile_config(
            Settings(workspace_root=str(tmp_path), auth_disabled=True), "edited"
        )
    assert not isinstance(captured.value, CatalogUnavailable)
