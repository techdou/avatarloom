"""Profile Loader 测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.orchestrator.profile_loader import (
    ProfileError,
    list_profiles,
    load_profile,
)


class TestProfileLoader:
    def test_load_mock_profile(self) -> None:
        cfg = load_profile("profiles/mock.yaml")
        assert cfg.profile_id == "mock"
        assert "vad" in cfg.blocks
        assert cfg.blocks["vad"].id == "vad.mock"
        assert cfg.blocks["llm"].id == "llm.mock"

    def test_load_lite_profile(self) -> None:
        cfg = load_profile("profiles/lite-12gb.yaml")
        assert cfg.profile_id == "lite-12gb"
        assert cfg.blocks["vad"].id == "vad.silero"
        assert cfg.blocks["llm"].deployment == "remote"

    def test_load_full_profile(self) -> None:
        cfg = load_profile("profiles/full-24gb.yaml")
        assert cfg.profile_id == "full-24gb"
        assert cfg.blocks["tts"].id == "tts.voxcpm2"

    def test_env_interpolation(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("MY_MODEL", "custom-model")
        yaml = """
apiVersion: avatarloom.io/v1alpha1
kind: RuntimeProfile
metadata:
  id: test
  name: Test
blocks:
  llm:
    id: llm.openai-compatible
    config:
      model: ${MY_MODEL}
"""
        p = tmp_path / "test.yaml"
        p.write_text(yaml, encoding="utf-8")
        cfg = load_profile(p)
        assert cfg.blocks["llm"].config["model"] == "custom-model"

    def test_missing_file_raises(self) -> None:
        with pytest.raises(ProfileError, match="not found"):
            load_profile("nonexistent.yaml")

    def test_missing_block_id_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.yaml"
        p.write_text(
            "metadata:\n  id: bad\nblocks:\n  vad:\n    deployment: local\n",
            encoding="utf-8",
        )
        with pytest.raises(ProfileError, match="missing 'id'"):
            load_profile(p)

    def test_wrong_kind_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "wrong.yaml"
        p.write_text("kind: NotProfile\n", encoding="utf-8")
        with pytest.raises(ProfileError, match="unexpected kind"):
            load_profile(p)


class TestListProfiles:
    def test_lists_all_profiles(self) -> None:
        profiles = list_profiles("profiles")
        ids = [p["id"] for p in profiles]
        assert "mock" in ids
        assert "lite-12gb" in ids
        assert "full-24gb" in ids

    def test_missing_dir_returns_empty(self) -> None:
        assert list_profiles("/nonexistent") == []
