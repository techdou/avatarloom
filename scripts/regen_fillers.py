#!/usr/bin/env python3
"""重铸垫音：用修复后的链路重合成 persona 垫音（2026-08-21）。

背景：2026-08-20 合成的四条垫音全部是 VoxCPM badcase——97% 能量挤在
300-600Hz、1.2kHz 以上共振峰缺失，听感是纯音调"呜呜"声而非语音，
每轮对话先播它再播正常 TTS（"先怪声后正常"的根因）。

本脚本：
1. 读 profile 的 tts 配置（模型路径/voiceRef/promptText/rate 等）
2. 非流式 generate + retry_badcase=True（垫音短，不需要流式；开坏例重试）
3. 走与线上一致的后链：FirDecimator48to16（抗混叠）→ AtempoStretcher（保调变速）
4. 频谱门控：>1.2kHz 能量占比 <3% 判 badcase 自动重试（至多 6 次/条）
5. 旧文件备份到 fillers/neutral.bak-<date>/，新文件落盘 neutral/ 并更新 texts.json

用法（服务器 gateway venv）：
    cd /root/autodl-tmp/avatarloom
    .venv/bin/python scripts/regen_fillers.py [--profile autodl-best] [--persona demo-assistant]
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
import wave
from pathlib import Path

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blocks._audio import FirDecimator48to16  # noqa: E402
from blocks.tts.voxcpm2 import AtempoStretcher  # noqa: E402

# 全换成带真实词汇的口头禅——纯"嗯————"哼音本身就是 tonal，频谱门控无法区分
# badcase 与正常哼音，且听感最接近"怪诞音波"（豆哥反馈原话）
FILLERS = [
    ("filler_01", "嗯，让我想想。"),
    ("filler_02", "好的，稍等。"),
    ("filler_03", "诶，这个问题有意思。"),
    ("filler_04", "嗯，我看看。"),
]

MIN_FORMANT_SHARE = 0.03  # >1.2kHz 能量占比下限（真实语音必有共振峰）
MAX_TRIES = 6


def band_share(pcm: np.ndarray, sr: int, lo: int, hi: int) -> float:
    sp = np.abs(np.fft.rfft(pcm * np.hamming(len(pcm))))
    fr = np.fft.rfftfreq(len(pcm), 1 / sr)
    mask = (fr >= lo) & (fr < hi)
    total = sp.sum()
    return float(sp[mask].sum() / total) if total > 0 else 0.0


def synthesize_once(model, text: str, cfg: dict, voice_ref: str) -> np.ndarray:
    """非流式合成一句 → 48k float32。优先 retry_badcase=True。

    按 generate 的实时签名过滤 kwargs——voxcpm 各版本参数集不同
    （retry_badcase/denoise 等有无不一）， introspect 后只传受支持的。
    """
    import inspect

    kwargs = dict(
        prompt_wav_path=voice_ref,
        prompt_text=str(cfg.get("promptText") or cfg.get("stylePrefix") or ""),
        cfg_value=float(cfg.get("cfgValue", 2.0)),
        inference_timesteps=int(cfg.get("inferenceTimesteps", 5)),
        normalize=bool(cfg.get("normalize", True)),
        denoise=bool(cfg.get("denoise", False)),
        retry_badcase=True,
    )
    try:
        sig = inspect.signature(model.generate)
        if not any(p.kind == inspect.Parameter.VAR_KEYWORD
                   for p in sig.parameters.values()):
            kwargs = {k: v for k, v in kwargs.items() if k in sig.parameters}
    except (TypeError, ValueError):
        pass  # 签名不可 introspect（C 扩展包装等）——原样传，TypeError 由上层重试兜
    wav = model.generate(text, **kwargs)
    arr = np.asarray(wav.squeeze(0).cpu().numpy() if hasattr(wav, "cpu") else wav,
                     dtype=np.float32).reshape(-1)
    return arr


def post_chain(wav48: np.ndarray, rate: float) -> np.ndarray:
    """线上同款后链：FIR 抗混叠 48k→16k + atempo 保调变速。"""
    pcm16 = FirDecimator48to16().process(wav48)
    if rate != 1.0 and len(pcm16):
        st = AtempoStretcher(16000, rate)
        out = st.feed(pcm16)
        tail = st.flush()
        pcm16 = np.concatenate([out, tail]) if len(tail) else out
    return pcm16


def write_wav(path: Path, pcm16: np.ndarray, sr: int = 16000) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm16.astype(np.int16).tobytes())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="autodl-best")
    ap.add_argument("--persona", default="demo-assistant")
    args = ap.parse_args()

    profile = yaml.safe_load(
        (ROOT / "profiles" / f"{args.profile}.yaml").read_text(encoding="utf-8")
    )
    tts_cfg = (profile.get("blocks") or {}).get("tts", {}).get("config") or {}
    model_path = str(tts_cfg.get("model", "/root/autodl-tmp/modelscope-voxcpm"))
    voice_ref = str(ROOT / str(tts_cfg.get("voiceRef", f"personas/{args.persona}/voice/ref.wav")))
    rate = float(tts_cfg.get("rate", 0.886))

    from voxcpm import VoxCPM

    print(f"[regen] 加载模型 {model_path}")
    model = VoxCPM.from_pretrained(model_path, local_files_only=True)

    out_dir = ROOT / "personas" / args.persona / "fillers" / "neutral"
    bak_dir = out_dir.parent / f"neutral.bak-{time.strftime('%Y%m%d')}"
    if out_dir.is_dir() and any(out_dir.glob("*.wav")):
        bak_dir.mkdir(parents=True, exist_ok=True)
        for old in out_dir.glob("*.wav"):
            shutil.move(str(old), str(bak_dir / old.name))
        print(f"[regen] 旧垫音已备份到 {bak_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)

    failures: list[str] = []
    texts: dict[str, str] = {}
    for name, text in FILLERS:
        ok = False
        for attempt in range(1, MAX_TRIES + 1):
            try:
                wav48 = synthesize_once(model, text, tts_cfg, voice_ref)
            except Exception as e:  # noqa: BLE001 -- 重试逻辑要兜住一切模型异常
                print(f"[regen] {name} 第{attempt}次合成异常: {e}")
                continue
            pcm16 = post_chain(wav48, rate)
            if len(pcm16) < 16000 * 0.4:
                print(f"[regen] {name} 第{attempt}次输出过短 ({len(pcm16)/16000:.2f}s)，重试")
                continue
            f32 = pcm16.astype(np.float32) / 32768.0
            hi = band_share(f32, 16000, 1200, 8000)
            rms = float(np.sqrt(np.mean(f32**2)))
            dur = len(pcm16) / 16000
            print(f"[regen] {name} 第{attempt}次: dur={dur:.2f}s rms={rms:.3f} >1.2kHz={hi:.3f}")
            if hi >= MIN_FORMANT_SHARE and rms >= 0.02:
                write_wav(out_dir / f"{name}.wav", pcm16)
                texts[f"neutral/{name}.wav"] = text
                ok = True
                break
            print(f"[regen] {name} 第{attempt}次频谱门控未过（疑似 badcase），重试")
        if not ok:
            failures.append(name)

    import json

    texts_path = out_dir.parent / "texts.json"
    texts_path.write_text(json.dumps(texts, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[regen] texts.json 已更新: {texts_path}")

    if failures:
        print(f"[regen] 失败（{len(failures)} 条重试耗尽）: {failures}")
        return 1
    print("[regen] 全部垫音重铸完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
