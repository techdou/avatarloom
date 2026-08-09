# AvatarLoom 交接文档 — Agent Teams 协作

> 交接时间：2026-08-06 19:55（Asia/Shanghai）
> 交接人：主对话 Agent
> 一句话：**后端 7 个 CRITICAL/HIGH 修复 + Studio 对话优先重构（五步）全部完成；FlashHead 环境就绪待 GPU 验证；服务已起，隧道已通。**

---

## 0. 当前状态摘要

| 项 | 状态 |
|---|---|
| 后端修复（7 个 CRITICAL/HIGH） | ✅ 完成，172 测试通过 |
| Studio 对话优先重构（五步） | ✅ 完成，16 路由 build 通过 |
| FlashHead 环境（权重+依赖） | ✅ 就绪（SoulX 7.3G + wav2vec2 1.1G + avatar-venv） |
| 服务器三服务 | ✅ 运行中（8100/8101/3000） |
| 本地隧道 | ✅ 已通（13000/18100/18101） |
| FlashHead probe 验证 | ⏳ 待跑（环境就绪，GPU 在线） |
| MuseTalk E2E 回归验证 | ⏳ 待跑 |

---

## 1. 服务器访问

### SSH
- 主机：`connect.westb.seetacloud.com`，端口 `22207`，用户 `root`
- 密码文件：`E:\projects\avatarloom\.omx\autodl-cred.json`
- 助手脚本：
  - bash：`python .omx\scripts\ssh_run.py --script`（stdin 传 bash）
  - 单条命令：`python .omx\scripts\ssh_run.py --cmd "<bash>"`
  - 上传：`python .omx\scripts\ssh_run.py --put <本地Win路径> <远端相对路径>`
  - **注意**：sftp `--put` 必须用 Windows 绝对路径（`C:/Users/...`），不能用 `/tmp/`；远端用相对路径（上传到 home 再 mv）

### 本地隧道
- 端口映射：`13000→3000`、`18100→8100`、`18101→8101`
- 启动：用 VBS 脚本（Git Bash 里 PowerShell 引号嵌套会失败）
  ```bash
  cat > /tmp/start_tunnel.vbs << 'EOF'
  Set ws = CreateObject("WScript.Shell")
  ws.Run "D:\anaconda3\python.exe E:\projects\avatarloom\.omx\scripts\tunnel.py", 0, False
  EOF
  cmd //c "wscript $(cygpath -w /tmp/start_tunnel.vbs)"
  ```
- 断了先 `taskkill //F //IM python.exe` 杀残留，再重启

### 本地访问
- Studio：`http://localhost:13000`（自动跳 /playground）
- Playground（含 WS）：`http://localhost:13000/playground?wsPort=18101`
- 演示模式（移动端）：`http://localhost:13000/show?wsPort=18101`
- **wsPort 参数必须带**——前端 WS 默认连 8101，隧道是 18101

---

## 2. 代码版本

### Git
- 分支：`feat/autodl-rtx5090-real-e2e`
- GitHub：`techdou/avatarloom`
- 最新提交：`ac0cbc6`（已推送）

### 本轮提交（按时间倒序）
| commit | 说明 |
|---|---|
| `ac0cbc6` | fix(vad): silero forward needs explicit sr arg — torch 2.8 raises NoneType |
| `bc3b363` | fix(studio): WS port from URL param ?wsPort= for tunnel scenarios |
| `a74a042` | fix(probe): add 3s frame idle timeout |
| `21738f0` | fix(flashhead): idle branch blocked by _reset_motion |
| `ea878b7` | fix(probe): strip frame tag byte — protocol changed |
| `c4d5cbd` | fix(review): 2 CRITICAL + 4 HIGH + 2 frontend issues（辅助对话 agent） |
| `1221205` | feat(studio): conversation-first IA refactor（五步重构） |
| `10dc9cc` | fix(critical): C-warmup + C1 persona_voice_ref + VoxCPM2 API |
| `cd0e6ec` | fix(runtime): 5 HIGH — profile deadlock + orphan process + recorder + auth + CORS |

### 服务器代码
- **不是通过 git 同步的**——通过 `git archive` + sftp tar 覆盖
- 服务器 git HEAD 是旧的（`c28a7bd`），但文件系统是最新代码
- 如需精确同步：本地 `git archive --format=tar HEAD -o /tmp/latest.tar` → sftp 上传 → 服务器 `tar xf`

---

## 3. 已完成的修复

### CRITICAL（2 个）
1. **C-warmup**：`flashhead_service.py` 的 `websockets.serve` 移到 `warmup` 之前——torch.compile 首次编译（Blackwell 上可能 >180s）不再阻塞端口绑定，block 能立即连上
2. **C1 persona_voice_ref**：
   - `orchestrator.py` `_make_block_handler` 从 `_persona_contexts` 注入 persona_voice_ref/instructions/avatar_ref（之前恒 None）
   - `voxcpm2.py` `_infer` 参数名从 `prompt_audio` 改为 `prompt_wav_path`（VoxCPM2 真实 API）；setup 读 config voiceRef 作为 fallback

### HIGH（5 个）
1. **H1+H2 profile 死锁**：`orchestrator._setup_block` registry 找不到 block 时走 fallback/raise（之前静默 skip 导致死锁）；`profile_loader` 加载时校验 block id + difflib 模糊建议
2. **H3 孤儿子进程**：`flashhead.py` WS 连接超时分支 raise 前调 `_stop()` 清理子进程（之前泄漏 GPU 显存）；frame_reader 异常退出自愈；ws 重连有日志；warmup 有超时+错误标志
3. **H4 recorder 丢指标**：`session.py` emit `RUN_STARTED` 事件；`ws_handler` 在 run.started 时 `start_run`（之前在 llm.text.done 才调，首字/首音延迟全丢）
4. **H6 鉴权**：control-api 加 Bearer token（`AVATARLOOM_API_TOKEN`，默认关闭开发友好，`secrets.compare_digest` 防侧信道）
5. **H7 CORS**：`*` + `credentials=True` 非法组合 → 白名单（默认 `localhost:3000`）

### profile 修正
- `lite-12gb.yaml`：`stt.sensevoice-onnx` → `stt.sensevoice`
- `distributed.yaml`：`stt.sensevoice-onnx` 加 `fallback: stt.sensevoice`；`tts.mlx-remote` 加 `fallback: tts.qwen3`

### FlashHead 额外修复
- `flashhead_service.py`：`use_face_crop=True`（之前 False，1254px portrait 不裁脸产坏帧）
- warmup 放后台线程（不再阻塞端口绑定）

---

## 4. Studio 对话优先重构

### 信息架构变化
- `/` 直达 Playground（不再经过 Dashboard）
- Sidebar 从 8 页 3 组简化为 2 组（对话 + 管理）
- 路由组 `(studio)/` 承载 sidebar 页面；`/show` 独立无 sidebar

### 新增组件
| 文件 | 作用 |
|---|---|
| `hooks/use-realtime-session.ts` | WS/PCM/AVMux/Recorder 生命周期封装为 hook，Playground 和 Showcase 共享 |
| `components/playground/context-bar.tsx` | 顶部上下文栏：profile/persona 下拉 + 连接状态 + 调试开关 |
| `components/playground/showcase-client.tsx` | /show 演示模式：全屏画面 + 字幕条 + 悬浮麦克风 |
| `components/playground/debug-drawer.tsx` | 底部调试抽屉：管线时间轴 + 实时指标 |
| `components/playground/runs-panel.tsx` | 右侧运行记录面板：最近 10 条 run |
| `components/playground/pipeline-timeline.tsx` | 管线时间轴组件（runs 详情页也复用） |

### 关键约束
- WS 端口从 URL 参数 `?wsPort=xxxxx` 读（隧道场景），默认 8101
- SVG 假脸已删（AvatarPortrait），改用 lucide UserCircle2
- 反 AI slop：删 radial-gradient、blur-2xl、btn-primary shadow-accent

---

## 5. FlashHead 环境

### Python 环境
| 环境 | Python | torch | 用途 |
|---|---|---|---|
| `avatar-venv`（→py310） | 3.10.20 | 2.7.1+cu128 | **FlashHead 推理** |
| `musetalk-venv` | 3.12.3 | 2.8.0+cu128 | MuseTalk 推理 |
| `miniconda3`（系统） | 3.12 | 2.8.0+cu128 | gateway/control-api（uv run） |

### 模型权重
- SoulX-FlashHead-1_3B：`/root/autodl-tmp/models/SoulX-FlashHead-1_3B/`（7.3GB，Model_Lite + VAE_LTX）
- wav2vec2-base-960h：`/root/autodl-tmp/models/wav2vec2-base-960h/`（1.1GB）
- MuseTalk v1：`/root/autodl-tmp/musetalk/models/`

### FlashHead 验证命令（待跑）
```bash
# 1) 启动 FlashHead 服务
cd /root/autodl-tmp/avatarloom
setsid nohup /root/autodl-tmp/avatarloom-avatar-venv/bin/python scripts/flashhead_service.py \
  --model-dir /root/autodl-tmp/models/SoulX-FlashHead-1_3B \
  --wav2vec-dir /root/autodl-tmp/models/wav2vec2-base-960h \
  --port 8767 --image personas/demo-assistant/avatar/portrait.jpg \
  </dev/null >/tmp/flashhead_service.log 2>&1 &

# 2) 探针验证（收帧 + 出 mp4）
/root/autodl-tmp/avatarloom-avatar-venv/bin/python scripts/flashhead_probe.py \
  --port 8767 \
  --image personas/demo-assistant/avatar/portrait.jpg \
  --audio /root/autodl-tmp/musetalk/demo_10s.wav \
  --out /tmp/flashhead_probe.mp4

# 3) 全链路 E2E
set -a; . ./.env; set +a
export VOXCPM_MODEL_PATH=/root/autodl-tmp/modelscope-voxcpm
export HF_ENDPOINT=https://hf-mirror.com HF_HUB_DISABLE_XET=1
export HF_HOME=/root/autodl-tmp/huggingface MODELSCOPE_CACHE=/root/autodl-tmp/modelscope TORCH_HOME=/root/autodl-tmp/torch
E2E_PROFILE=autodl-flashhead E2E_TIMEOUT=480 uv run python -u scripts/e2e_real.py
```

### MuseTalk E2E 验证
```bash
cd /root/autodl-tmp/avatarloom
set -a; . ./.env; set +a
export HF_ENDPOINT=https://hf-mirror.com HF_HUB_DISABLE_XET=1
export HF_HOME=/root/autodl-tmp/huggingface MODELSCOPE_CACHE=/root/autodl-tmp/modelscope TORCH_HOME=/root/autodl-tmp/torch
E2E_PROFILE=autodl-best E2E_TIMEOUT=300 uv run python -u scripts/e2e_real.py
```

---

## 6. 服务管理

### 起三服务
```bash
cd /root/autodl-tmp/avatarloom
export PATH=$HOME/.local/bin:$PATH
export HF_ENDPOINT=https://hf-mirror.com HF_HUB_DISABLE_XET=1
export HF_HOME=/root/autodl-tmp/huggingface MODELSCOPE_CACHE=/root/autodl-tmp/modelscope TORCH_HOME=/root/autodl-tmp/torch
set -a; . ./.env; set +a

# control-api
setsid nohup uv run python -m avatarloom_control_api </dev/null >/tmp/control-api.log 2>&1 &

# gateway
setsid nohup uv run python -m avatarloom_runtime_gateway </dev/null >/tmp/gateway.log 2>&1 &

# studio (需要 node22)
export PATH=/usr/local/lib/node22/bin:$PATH
setsid nohup pnpm --filter @avatarloom/studio start </dev/null >/tmp/studio.log 2>&1 &
```

### 端口
- Control API：8100（API 路径 `/api/personas`、`/api/avatars`、`/api/runs` 等，不是 `/api/control/personas`）
- Runtime Gateway：8101（WS：`ws://host:8101/ws/realtime`）
- Studio：3000
- FlashHead 服务：8767（内部，验证时起）

### 已知坑
1. **pkill 自杀**：`pkill -f 'git '` 或 `pkill -f 'pip'` 会匹配到执行命令的 shell 自身，用 `ps aux | grep | awk '{print $2}' | xargs kill` 替代
2. **autodl_start.sh 缺 export**：脚本没 export `HF_HOME/MODELSCOPE_CACHE/TORCH_HOME`，手动起服务时必须补
3. **数据盘拷贝路由冲突**：克隆实例后 `apps/studio/app/` 下可能同时有路由组内外的重复目录，build 报 `parallel pages` 错误，需手动删旧目录
4. **index.lock**：服务器 git 操作并发时容易留 `.git/index.lock`，用 `python3 -c "import os; os.remove('.git/index.lock')"` 清理
5. **pytorch.org 下载慢**：用 aria2c 多连接（`aria2c -x 4 -s 4`）代替 pip 单线程；torchvision/torchaudio 也可先 aria2c 下 wheel 再本地 pip install

---

## 7. 待验证项（按优先级）

### P0：MuseTalk E2E 回归
- 确认 7 个修复没破坏已验证链路
- 命令：`E2E_PROFILE=autodl-best E2E_TIMEOUT=300 uv run python -u scripts/e2e_real.py`
- PASS 标准：transcript + llm_delta + tts_delta + avatar + tts_done + video 全 True

### P0：FlashHead probe（第一次真跑）
- 环境 100% 就绪，只差执行
- 命令见第 5 节
- 验收：probe 收到 ≥50 帧且 mp4 可播放；视频分析确认"眼睛/头部有自然运动、嘴型与音频同步"

### P1：FlashHead 全链路 E2E
- probe 通过后跑
- `E2E_PROFILE=autodl-flashhead`

### P1：浏览器实测新 Studio
- 桌面端 `http://localhost:13000/playground?wsPort=18101`：对话 + 调试抽屉 + 运行记录面板
- 移动端 `http://localhost:13000/show?wsPort=18101`：全屏画面 + 字幕条 + 悬浮麦克风

### P2：MuseTalk v1.5 对比（权重已就绪）
- `/root/autodl-tmp/musetalk/models/musetalkV15/unet.pth`（3.4GB）
- `python lite_driver.py --version v15 --extra-margin 10`

---

## 8. 未完成 / 已知问题

1. **服务器 git 不同步**：HEAD 是 `c28a7bd`，文件是最新代码（tar 覆盖）。建议找时间 `git checkout` 对齐
2. **control-api 鉴权默认关闭**：`AVATARLOOM_API_TOKEN` 未设，开发模式无鉴权
3. **react-query 装了不用**：`@tanstack/react-query` 零引用，可卸载（减 70KB bundle）
4. **MuseTalk v1.5 权重 aria2 控制文件残留**：hf.co xet 链接过期，如需 v1.5 对比要重新下
5. **xformers 未装**：FlashHead 的 avatar-venv 没装 xformers（Blackwell 无预编译 kernel），用 PyTorch SDPA 兜底，可能慢一些
6. **Blocks API Explorer（P5）**：`app/(studio)/blocks/page.tsx` 标了 TODO，未实施

---

## 9. 关键文件索引

| 作用 | 本地路径 |
|---|---|
| WS/PCM hook | `apps/studio/hooks/use-realtime-session.ts` |
| Playground 主组件 | `apps/studio/components/audio/playground-client.tsx` |
| 演示模式 | `apps/studio/components/playground/showcase-client.tsx` |
| FlashHead block | `blocks/avatar/flashhead.py` |
| FlashHead 服务 | `scripts/flashhead_service.py` |
| FlashHead 探针 | `scripts/flashhead_probe.py` |
| FlashHead profile | `profiles/autodl-flashhead.yaml` |
| MuseTalk block | `blocks/avatar/musetalk.py` |
| MuseTalk worker | `scripts/muse_worker.py` |
| 编排器 | `runtime/orchestrator/orchestrator.py` |
| Profile 校验 | `runtime/orchestrator/profile_loader.py` |
| WS 处理 | `apps/runtime-gateway/src/avatarloom_runtime_gateway/ws_handler.py` |
| 鉴权 | `apps/control-api/src/avatarloom_control_api/auth.py` |
| 验证脚本 | `scripts/verify_after_gpu.sh` |
