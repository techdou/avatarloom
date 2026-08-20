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

    def test_load_local_profile(self, monkeypatch) -> None:
        # local-5070 的 llm 是远程 OpenAI 兼容端点，缺 env 加载会 ProfileError——
        # 补上测试环境变量，语义与生产一致（缺变量早报错，不带空串到运行期）
        monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:9999/v1")
        monkeypatch.setenv("LLM_MODEL", "test-model")
        cfg = load_profile("profiles/local-5070.yaml")
        assert cfg.profile_id == "local-5070"
        assert cfg.blocks["vad"].id == "vad.silero"
        assert cfg.blocks["llm"].deployment == "remote"

    def test_load_local_profile_missing_env_raises(self, monkeypatch) -> None:
        # 远程 LLM 无 fallback、缺必需 env——加载阶段直接报错，不带到运行期
        monkeypatch.delenv("LLM_BASE_URL", raising=False)
        monkeypatch.delenv("LLM_MODEL", raising=False)
        with pytest.raises(ProfileError, match="LLM_BASE_URL"):
            load_profile("profiles/local-5070.yaml")

    def test_load_autodl_best_profile(self, monkeypatch) -> None:
        # 生产档：tts 是 VoxCPM2 流式克隆（2026-08-21 精简后替代 full-24gb 的覆盖位）
        monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:9999/v1")
        monkeypatch.setenv("LLM_MODEL", "test-model")
        monkeypatch.setenv("VISION_BASE_URL", "http://127.0.0.1:9999/v1")
        monkeypatch.setenv("VISION_MODEL", "test-vision")
        cfg = load_profile("profiles/autodl-best.yaml")
        assert cfg.profile_id == "autodl-best"
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
        assert "local-5070" in ids
        assert "autodl-best" in ids
        # attic 归档档不出现在可选列表（glob 不递归）
        assert "lite-12gb" not in ids
        assert "full-24gb" not in ids

    def test_missing_dir_returns_empty(self) -> None:
        assert list_profiles("/nonexistent") == []
