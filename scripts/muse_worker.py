#!/usr/bin/env python
"""Warm MuseTalk worker for RTX 5090.

Long-lived subprocess that loads the MuseTalk models once and renders
reply-level lip-sync videos on demand.  The avatar.musetalk block talks to it
over newline-delimited JSON on stdin/stdout:

    {"cmd":"ping"}
    {"cmd":"render","portrait":P,"audio":W,"out":M,"fps":25,
     "batch_size":8,"crf":18,"extra_margin":0,"keep_frames":true}

Replies are single-line JSON.  No mmpose / face_detection dependency:
face bbox and blend mask both come from mediapipe.
"""

from __future__ import annotations

import argparse
import contextlib
import faulthandler
import json
import os
import subprocess
import sys
import time
from pathlib import Path

# 启动探针：worker 段错误（SIGSEGV）无输出时，用这些标记定位崩溃的 import。
# 同时写文件——block 侧 drain 与崩溃存在读取竞争，pipe 数据可能丢失
_DBG = open("/tmp/muse_worker_boot.log", "a", buffering=1)  # noqa: SIM115 -- 进程级探针日志，faulthandler 需持有句柄
faulthandler.enable(file=_DBG)


def _probe(msg: str) -> None:
    _DBG.write(f"{msg}\n")
    print(msg, flush=True)


_probe("M1_IMPORT_START")
import cv2  # noqa: E402

_probe("M2_CV2_OK")
import numpy as np  # noqa: E402

_probe("M3_NUMPY_OK")
import torch  # noqa: E402

_probe("M4_TORCH_OK")

MUSETALK_ROOT = Path("/root/autodl-tmp/musetalk")
sys.path.insert(0, str(MUSETALK_ROOT))
os.chdir(MUSETALK_ROOT)

# MediaPipe FaceMesh face-oval landmark indices.
FACE_OVAL = [
    10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379,
    378, 400, 377, 152, 148, 176, 149, 150, 136, 172, 58, 132, 93, 234, 127,
    162, 21, 54, 103, 67, 109,
]


def fast_blend(image, face, face_box, mask_array, crop_box):
    """numpy 快速融合：等价于官方 get_image_blending 的软蒙版粘贴（实测 maxdiff<=1）。"""
    x, y, x1, y1 = face_box
    xs, ys = max(0, crop_box[0]), max(0, crop_box[1])
    xe, ye = min(image.shape[1], crop_box[2]), min(image.shape[0], crop_box[3])
    mo = (max(0, crop_box[0]) - crop_box[0], max(0, crop_box[1]) - crop_box[1])
    m = (
        mask_array[mo[1]: mo[1] + (ye - ys), mo[0]: mo[0] + (xe - xs)]
        .astype(np.float32)
        / 255.0
    )[..., None]
    canvas = image.copy()
    region = canvas[ys:ye, xs:xe].astype(np.float32)
    fx, fy = x - xs, y - ys
    fw, fh = x1 - x, y1 - y
    r = region[fy:fy + fh, fx:fx + fw]
    mm = m[fy:fy + fh, fx:fx + fw]
    r[:] = face.astype(np.float32) * mm + r * (1.0 - mm)
    canvas[ys:ye, xs:xe] = region.astype(np.uint8)
    return canvas


class MediapipeFaceParsing:
    """Drop-in fp for blending.get_image(): PIL 'L' face mask with soft edge."""

    def __init__(self) -> None:
        import mediapipe as mp

        self._mesh = mp.solutions.face_mesh.FaceMesh(
            static_image_mode=True,
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.5,
        )

    def __call__(self, image, mode: str = "raw"):
        from PIL import Image

        rgb = np.asarray(image.convert("RGB"))
        h, w = rgb.shape[:2]
        res = self._mesh.process(rgb)
        if not res.multi_face_landmarks:
            return None
        pts = np.array(
            [(lm.x * w, lm.y * h) for lm in res.multi_face_landmarks[0].landmark]
        )
        poly = pts[FACE_OVAL].astype(np.int32).reshape(-1, 1, 2)
        mask = np.zeros((h, w), np.uint8)
        cv2.fillPoly(mask, [poly], 255)
        k = max(3, int(min(h, w) * 0.015 // 2 * 2 + 1))
        mask = cv2.GaussianBlur(mask, (k, k), 0)
        return Image.fromarray(mask)


def get_landmark_and_bbox(img_list, upperbondrange=0, max_side=0):
    """mediapipe face bbox, mirroring the official dwpose bbox rule."""
    import mediapipe as mp

    mp_face = mp.solutions.face_mesh.FaceMesh(
        static_image_mode=True,
        max_num_faces=1,
        refine_landmarks=True,
        min_detection_confidence=0.5,
    )
    coords = []
    frames = []
    placeholder = (0.0, 0.0, 0.0, 0.0)
    for img_path in img_list:
        frame = cv2.imread(str(img_path))
        if max_side > 0 and max(frame.shape[:2]) > max_side:
            scale = max_side / max(frame.shape[:2])
            nw = int(frame.shape[1] * scale) // 2 * 2
            nh = int(frame.shape[0] * scale) // 2 * 2
            frame = cv2.resize(
                frame,
                (max(2, nw), max(2, nh)),
                interpolation=cv2.INTER_LANCZOS4,
            )
        frames.append(frame)
        h, w = frame.shape[:2]
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        res = mp_face.process(rgb)
        if not res.multi_face_landmarks:
            coords.append(placeholder)
            continue
        pts = np.array([(p.x * w, p.y * h) for p in res.multi_face_landmarks[0].landmark])
        xs, ys = pts[:, 0], pts[:, 1]
        nose = pts[4]
        half_face_dist = ys.max() - nose[1]
        upper_bond = max(0.0, nose[1] + upperbondrange - half_face_dist)
        box = (
            float(max(0.0, xs.min())),
            float(upper_bond),
            float(min(w, xs.max())),
            float(min(h, ys.max())),
        )
        coords.append(box if box[3] - box[1] > 8 and box[2] - box[0] > 8 else placeholder)
    return coords, frames


class MuseEngine:
    def __init__(self, model_dir: str, device: str = "cuda", version: str = "v1") -> None:
        self.model_dir = Path(model_dir)
        self.device = torch.device(device)
        self.weight_dtype = torch.float16
        self.version = version
        self._models = None

    def _ensure_loaded(self) -> None:
        if self._models is not None:
            return
        from musetalk.utils.audio_processor import AudioProcessor
        from musetalk.utils.blending import get_image_prepare_material
        from musetalk.utils.utils import datagen, load_all_model
        from transformers import WhisperModel

        t0 = time.perf_counter()
        if self.version == "v15":
            unet_path = self.model_dir / "musetalkV15" / "unet.pth"
            unet_cfg = self.model_dir / "musetalkV15" / "musetalk.json"
        else:
            unet_path = self.model_dir / "musetalk" / "pytorch_model.bin"
            unet_cfg = self.model_dir / "musetalk" / "musetalk.json"
        vae, unet, pe = load_all_model(
            unet_model_path=str(unet_path),
            unet_config=str(unet_cfg),
            device=self.device,
        )
        pe = pe.to(self.device, dtype=self.weight_dtype)
        vae.vae = vae.vae.to(self.device).half()
        unet.model = unet.model.to(self.device).half()
        whisper = WhisperModel.from_pretrained(str(self.model_dir / "whisper")).to(
            self.device, dtype=self.weight_dtype
        )
        whisper.eval()
        whisper.requires_grad_(False)
        audio_processor = AudioProcessor(
            feature_extractor_path=str(self.model_dir / "whisper")
        )
        self._models = {
            "vae": vae,
            "unet": unet,
            "pe": pe,
            "whisper": whisper,
            "audio_processor": audio_processor,
            "fp": self._make_fp(),
            "datagen": datagen,
            "get_image_prepare_material": get_image_prepare_material,
            "load_s": round(time.perf_counter() - t0, 2),
        }

    def _make_fp(self):
        """优先官方 BiSeNet FaceParsing（嘴周蒙版更精细），缺失时回退 mediapipe。"""
        fp_dir = self.model_dir / "face-parse-bisent"
        if (fp_dir / "79999_iter.pth").exists() and (fp_dir / "resnet18-5c106cde.pth").exists():
            try:
                from musetalk.utils.face_parsing import FaceParsing

                return FaceParsing()
            except Exception as e:
                print(f"face-parsing load failed, fallback mediapipe: {e}", flush=True)
        return MediapipeFaceParsing()

    def render(
        self,
        portrait: str,
        audio: str,
        out: str,
        fps: int = 25,
        batch_size: int = 8,
        crf: int = 18,
        extra_margin: int = 0,
        max_side: int = 1280,
        parsing_mode: str = "auto",
        keep_frames: bool = True,
    ) -> dict:
        self._ensure_loaded()
        m = self._models
        vae, unet, pe = m["vae"], m["unet"], m["pe"]
        whisper, ap = m["whisper"], m["audio_processor"]
        fp, datagen = m["fp"], m["datagen"]
        get_image_prepare_material = m["get_image_prepare_material"]
        device, dtype = self.device, self.weight_dtype

        coords, frames = get_landmark_and_bbox([portrait], max_side=max_side)
        if coords[0] == (0.0, 0.0, 0.0, 0.0):
            raise RuntimeError("no face detected in portrait")
        x1, y1, x2, y2 = [int(v) for v in coords[0]]
        if self.version == "v15":
            y2 = min(y2 + int(extra_margin), frames[0].shape[0])
        crop_frame = frames[0][y1:y2, x1:x2]
        resized = cv2.resize(crop_frame, (256, 256), interpolation=cv2.INTER_LANCZOS4)
        latents_list = [vae.get_latents_for_unet(resized)]

        input_features, librosa_length = ap.get_audio_feature(
            audio, weight_dtype=dtype
        )
        whisper_chunks = ap.get_whisper_chunk(
            input_features, device, dtype, whisper, librosa_length, fps=fps
        )

        timesteps = torch.tensor([0], device=device)
        mode = parsing_mode if parsing_mode != "auto" else (
            "jaw" if self.version == "v15" else "raw"
        )
        # 静态肖像：融合蒙版只计算一次，每帧只做廉价粘贴
        mask_array, crop_box = get_image_prepare_material(
            frames[0], [x1, y1, x2, y2], fp=fp, mode=mode
        )
        out_path = Path(out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        frame_dir = out_path.parent / "frames"
        frame_dir.mkdir(parents=True, exist_ok=True)
        idx = 0
        t0 = time.perf_counter()
        gen = datagen(whisper_chunks, latents_list, batch_size=batch_size)
        for _i, (whisper_batch, latent_batch) in enumerate(gen):
            audio_feature_batch = pe(whisper_batch.to(device))
            latent_batch = latent_batch.to(device=device, dtype=unet.model.dtype)
            with torch.no_grad():
                pred = unet.model(
                    latent_batch, timesteps, encoder_hidden_states=audio_feature_batch
                ).sample
                pred = pred.to(device=device, dtype=vae.vae.dtype)
                recon = vae.decode_latents(pred)
            for res_frame in recon:
                ori = frames[0].copy()
                try:
                    res_frame = cv2.resize(
                        res_frame.astype(np.uint8), (x2 - x1, y2 - y1)
                    )
                    combine = fast_blend(
                        ori, res_frame, [x1, y1, x2, y2], mask_array, crop_box
                    )
                except Exception:
                    combine = ori
                    with contextlib.suppress(Exception):
                        combine[y1:y2, x1:x2] = res_frame
                cv2.imwrite(
                    str(frame_dir / f"{idx:06d}.jpg"),
                    combine,
                    [cv2.IMWRITE_JPEG_QUALITY, 92],
                )
                idx += 1
        infer_s = time.perf_counter() - t0

        cmd = [
            "ffmpeg", "-y", "-framerate", str(fps),
            "-i", str(frame_dir / "%06d.jpg"),
            "-i", audio,
            "-c:v", "libx264", "-crf", str(crf), "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest",
            str(out_path),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {r.stderr[-400:]}")
        if not keep_frames:
            subprocess.run(["rm", "-rf", str(frame_dir)], check=False)
        meta = {
            "mp4": str(out_path),
            "frames": idx,
            "frames_dir": str(frame_dir),
            "infer_s": round(infer_s, 2),
            "fps_actual": round(idx / infer_s, 2) if infer_s > 0 else 0.0,
            "audio_s": round(librosa_length / 16000, 2),
            "load_s": m["load_s"],
        }
        # 落盘兜底：即使 stdout 管道异常，块也能读到结果
        with contextlib.suppress(Exception):
            (out_path.parent / (out_path.stem + ".json")).write_text(
                json.dumps(meta, ensure_ascii=False), encoding="utf-8"
            )
        return meta


def _reply(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False), flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-dir", default="/root/autodl-tmp/musetalk/models")
    ap.add_argument("--version", default="v1", choices=["v1", "v15"])
    ap.add_argument("--device", default="cuda")
    args = ap.parse_args()
    engine = MuseEngine(args.model_dir, args.device, args.version)
    _reply({"ok": True, "cmd": "ready", "version": args.version})
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception as e:
            _reply({"ok": False, "error": f"bad json: {e}"})
            continue
        cmd = req.get("cmd")
        try:
            if cmd == "ping":
                _reply({"ok": True, "cmd": "ping", "version": args.version})
            elif cmd == "warm":
                t0 = time.perf_counter()
                engine._ensure_loaded()
                _reply(
                    {
                        "ok": True,
                        "cmd": "warm",
                        "load_s": engine._models["load_s"],
                        "warm_s": round(time.perf_counter() - t0, 2),
                    }
                )
            elif cmd == "render":
                t0 = time.perf_counter()
                meta = engine.render(
                    portrait=str(req["portrait"]),
                    audio=str(req["audio"]),
                    out=str(req["out"]),
                    fps=int(req.get("fps", 25)),
                    batch_size=int(req.get("batch_size", 8)),
                    crf=int(req.get("crf", 18)),
                    extra_margin=int(req.get("extra_margin", 0)),
                    max_side=int(req.get("max_side", 1280)),
                    parsing_mode=str(req.get("parsing_mode", "auto")),
                    keep_frames=bool(req.get("keep_frames", True)),
                )
                meta.update(
                    ok=True,
                    cmd="render",
                    version=args.version,
                    total_s=round(time.perf_counter() - t0, 2),
                )
                _reply(meta)
            else:
                _reply({"ok": False, "error": f"unknown cmd: {cmd}"})
        except Exception as e:
            _reply(
                {
                    "ok": False,
                    "cmd": cmd,
                    "error": f"{type(e).__name__}: {e}",
                }
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
