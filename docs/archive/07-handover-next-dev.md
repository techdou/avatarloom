# AvatarLoom AutoDL RTX 5090 开发交接文档

> 交接时间：2026-08-06 01:45（Asia/Shanghai）
> 交接人：上一轮开发 Agent（root）
> 接棒人：下一轮开发 Agent
> 一句话交接：**真实语音数字人链路已全部打通（VAD→STT→LLM→TTS→MuseTalk 真口型视频，E2E PASS），
> 正在升级 SoulX-FlashHead 流式说话头（代码已写好待环境装完验证）；前端 bug 已修、UI 已重构。**

---

## 0. 交接摘要

1. 服务器上能跑通的真实链路：Silero VAD → SenseVoiceSmall STT → DeepSeek 流式 LLM → VoxCPM2 流式 TTS → MuseTalk 口型视频。最终 E2E PASS（103.9s 端到端，56.6s 回复 31.6s 渲染完）。
2. 用户最在意的三件事：**GPU 按小时计费别浪费、数字人质量（嘴假/眼睛不动）、前端能正常用**。前两项的答案都是 FlashHead（SoulX-1.3B 流式说话头，眼睛/头部会动）。
3. 本交接文档给出：环境访问方式、已完成清单（含证据）、未完成任务的**具体执行步骤**、所有踩坑记录。下一个 agent 按 P0→P4 顺序执行即可。

---

## 1. 服务器访问与环境

### SSH
- 主机：`connect.westd.seetacloud.com`，端口 `35460`，用户 `root`
- 密码文件：`E:\projects\avatarloom\.omx\autodl-cred.json`（本机）
- 助手脚本（Windows PowerShell 用）：
  - 执行 bash：`@'<bash>...'@ | python E:\projects\avatarloom\.omx\scripts\ssh_run.py --script`
  - 单条命令：`python E:\projects\avatarloom\.omx\scripts\ssh_run.py --cmd "<bash>"`
  - 上传：`python E:\projects\avatarloom\.omx\scripts\ssh_run.py --put <本地> <远端>`
  - 下载：`python E:\projects\avatarloom\.omx\scripts\ssh_run.py --get <远端> <本地>`

### 本地隧道（浏览器访问服务器 Studio）
- 脚本：`E:\projects\avatarloom\.omx\scripts\tunnel.py`（已加 keepalive + 断线自动重连）
- 启动方式（PowerShell，WScript 分离进程）：
  ```powershell
  $ws = New-Object -ComObject WScript.Shell
  $ws.Run('"D:\anaconda3\python.exe" "E:\projects\avatarloom\.omx\scripts\tunnel.py"', 0, $false)
  ```
- 本地地址：`http://127.0.0.1:3000/playground`（Studio）、`ws://127.0.0.1:8101/ws/realtime`（Gateway）、`http://127.0.0.1:8100/api/...`（Control API）
- 隧道进程若断：先 `netstat -ano | findstr ":3000"` 找 PID，杀掉后用上面命令重启。

### API 与模型环境
- 服务器 `.env`：`/root/autodl-tmp/avatarloom/.env`（DeepSeek `LLM_BASE_URL/LLM_API_KEY/LLM_MODEL=deepseek-v4-flash`；MiniMax 备用）
- 模型全部在数据盘 `/root/autodl-tmp`（系统盘 30G 只装最小依赖）：
  - Silero VAD：`$TORCH_HOME/hub/snakers4_silero-vad_master`
  - SenseVoiceSmall：`/root/autodl-tmp/modelscope/models/iic--SenseVoiceSmall`
  - VoxCPM2：`/root/autodl-tmp/modelscope-voxcpm`（`VOXCPM_MODEL_PATH`）
  - MuseTalk v1：`/root/autodl-tmp/musetalk/models/`（venv：`/root/autodl-tmp/musetalk-venv`）
  - MuseTalk v1.5：`/root/autodl-tmp/musetalk/models/musetalkV15/unet.pth`（99.5% 下载中，见 P1）
  - FlashHead：`/root/autodl-tmp/models/SoulX-FlashHead-1_3B` + `wav2vec2-base-960h`（安装中，见 P0）
- 端口：Control API 8100 / Gateway 8101 / Studio 3000 / FlashHead 服务 8767（内部）

### 计费提醒（用户非常在意）
- GPU 按小时计费。**下载/安装/IO 阶段 GPU 必然空闲**，应切 AutoDL 无卡模式（0.1 元/h，数据盘保留，需控制台操作，SSH 无法切换）。
- 链路 GPU 利用率低是结构性的（云 LLM 网络等待占大头），不要为了“跑满 GPU”做无意义渲染；FlashHead 流式说话头会让 GPU 持续工作。

---

## 2. 仓库与分支

- 本地：`E:\projects\avatarloom`，分支 `feat/autodl-rtx5090-real-e2e`，已推 GitHub `techdou/avatarloom`（最新本地提交 `99a4de7`）。
- 服务器：`/root/autodl-tmp/avatarloom` 同分支（服务器 git 落后几个提交；**以本地为准，改完用 `--put` 同步**，或拉取/打 bundle）。
- 备份 bundle：`E:\tmp\avatarloom-e2e.bundle`（服务器 `git bundle create` 生成）。

### 关键文件索引

| 作用 | 本地路径 | 服务器路径 |
|---|---|---|
| MuseTalk 真实块 | `blocks/avatar/musetalk.py` | 同路径 |
| MuseTalk 常驻 worker | `scripts/muse_worker.py` | 同路径 |
| FlashHead 服务（新，待验证） | `scripts/flashhead_service.py` | 同路径 |
| FlashHead 块（新，待验证） | `blocks/avatar/flashhead.py` | 同路径 |
| FlashHead 验证探针（新） | `scripts/flashhead_probe.py` | 同路径 |
| FlashHead 安装脚本（新） | `scripts/setup_flashhead.sh` | 同路径 |
| 真实 E2E 脚本 | `scripts/e2e_real.py`（支持 `E2E_PROFILE`） | 同路径 |
| 素材矩阵批量渲染 | `scripts/generate_asset_matrix.sh` | 同路径 |
| 真实配置（MuseTalk） | `profiles/autodl-best.yaml` | 同路径 |
| FlashHead 配置（新） | `profiles/autodl-flashhead.yaml` | 同路径 |
| 块注册表 | `runtime/orchestrator/orchestrator.py`（已注册 `avatar.flashhead`） | 同路径 |
| Studio 前端 | `apps/studio/` | 同路径 |
| 验收报告 | `docs/06-MuseTalk-real-lipsync-ui-report.md` | 同路径 |

---

## 3. 已完成并验证（证据）

### 3.1 真实链路 E2E（MuseTalk）
- 产物：`/root/autodl-tmp/avatarloom/runs/e2e-real/20260806-010140/`（manifest.json 全 true，`avatar_musetalk.mp4` 4.7MB）
- 指标：总 E2E 103.87s；TTS 回复 56.64s；MuseTalk infer 31.59s（1260 帧 ≈ 40fps，约 1.8x 实时）
- 另一组：`runs/e2e-real/20260805-225311/`（同样 PASS）
- 本地副本：`E:\tmp\final_e2e_musetalk.mp4`、`E:\tmp\musetalk_v1_demo.mp4`
- 视频质检（MiniMax/视频分析）：嘴部随语音张合、面部稳定、无闪烁，真实感 7.5/10；v1 局限＝牙齿细节、眼睛不动 → 由 FlashHead 解决

### 3.2 性能优化（MuseTalk）
- 渲染速度：8.7fps → 49.6fps（portrait.jpg）；超清 4000px 图 2.6fps → 44.3fps（`max_side=1280`）
- 关键手段：融合蒙版预计算（`get_image_prepare_material` 一次）+ numpy `fast_blend`（等价官方，maxdiff≤1）；JPEG 帧输出；全链路 fp16；worker 预热（7.5s 模型加载移到会话建立）
- 单位：单测 208 passed / 2 skipped

### 3.3 前端修复（全部验证 200）
- SSR API 报错“Failed to parse URL from /api/control/...”→ `apps/studio/lib/api.ts`：SSR 用绝对地址 `http://127.0.0.1:8100/api`，浏览器走 Next rewrite
- `/runs` 404 → 服务器缺 `apps/studio/app/runs/page.tsx`，已补上并重建；9 个页面全部 200
- 听不到声音 → `lib/audio/player.ts` 新增 `resume()`，在“连接/开麦”用户手势内解锁 AudioContext
- mock 之谜 → `playground-client.tsx` 原写死 `profile_id:"mock"`，已改 `autodl-best`；gateway `default_profile` 也改 `autodl-best`
- Studio UI 重构已上线：靛蓝强调色、分组侧边栏、对话式 Playground（角色卡+气泡）、配置页统一设计

### 3.4 素材矩阵
- `/root/autodl-tmp/avatarloom/runs/asset-matrix/` 12 个 mp4（2 肖像 × 3 音色 × 2 输入）已全部生成

---

## 4. 未完成项（按优先级执行）

### P0：FlashHead 流式说话头——验证并接入（最高价值）

**为什么**：用户明确不满意 MuseTalk v1 的“嘴假、眼睛不动”。VoxEMW 参考项目用的 SoulX-FlashHead-1.3B Lite 是端到端说话头（单图+TTS 音频流→25fps 说话头，头部/眼睛自然运动）。

**当前状态（2026-08-06 01:45）**：
- 代码已写好并上传（`scripts/flashhead_service.py`、`blocks/avatar/flashhead.py`、`profiles/autodl-flashhead.yaml`、`scripts/flashhead_probe.py`），py_compile 通过
- 环境安装中：`/root/autodl-tmp/avatarloom/scripts/setup_flashhead.sh` 在跑（py310 venv + torch 2.7.1 cu128 wheels 下载中，随后装 FlashHead requirements + ModelScope 下载 `Soul-AILab/SoulX-FlashHead-1_3B`（Model_Lite+VAE_LTX，约 8GB）与 `AI-ModelScope/wav2vec2-base-960h`）
- 安装日志：`/tmp/flashhead_setup.log`；完成标志：`FLASHHEAD_SETUP_DONE`

**安装完成后的验证步骤**：
```bash
# 1) 启动服务（py310 venv）
cd /root/autodl-tmp/avatarloom
setsid nohup /root/autodl-tmp/avatarloom-avatar-venv/bin/python scripts/flashhead_service.py \
  --model-dir /root/autodl-tmp/models/SoulX-FlashHead-1_3B \
  --wav2vec-dir /root/autodl-tmp/models/wav2vec2-base-960h \
  --port 8767 --image /root/autodl-tmp/avatarloom/personas/demo-assistant/avatar/portrait.jpg \
  </dev/null >/tmp/flashhead_service.log 2>&1 &

# 2) 探针验证（收帧 + 出 mp4）
/root/autodl-tmp/musetalk-venv/bin/python scripts/flashhead_probe.py \
  --port 8767 \
  --image /root/autodl-tmp/avatarloom/personas/demo-assistant/avatar/portrait.jpg \
  --audio /root/autodl-tmp/musetalk/demo_10s.wav \
  --out /tmp/flashhead_probe.mp4

# 3) 全链路 E2E（FlashHead profile，流式帧即视频）
cd /root/autodl-tmp/avatarloom
set -a; . ./.env; set +a
export VOXCPM_MODEL_PATH=/root/autodl-tmp/modelscope-voxcpm
export HF_ENDPOINT=https://hf-mirror.com HF_HUB_DISABLE_XET=1
export HF_HOME=/root/autodl-tmp/huggingface MODELSCOPE_CACHE=/root/autodl-tmp/modelscope TORCH_HOME=/root/autodl-tmp/torch
E2E_PROFILE=autodl-flashhead E2E_TIMEOUT=480 python3 -u scripts/e2e_real.py
```

**验收标准**：probe 收到 ≥50 帧且 mp4 可播放；E2E PASS；用视频分析确认“眼睛/头部有自然运动、嘴型与音频同步”。
**通过后**：把 Studio playground 默认 profile 切到 `autodl-flashhead`（`playground-client.tsx` 与 gateway `default_profile`），并跑一组对比（MuseTalk vs FlashHead）。

**风险与兜底**：
- flash_attn/xformers 若装不上（Blackwell/glibc），`setup_flashhead.sh` 里有 `SKIP_FLASH_ATTN` 思路，SDPA 可兜底（慢一些）
- torch.compile 首次 chunk 很慢 → 服务启动时已用 2 chunk 静音预热
- 服务端口 8767 冲突 → 改 `servicePort` 配置
- 块连接失败会抛 `BlockSetupError` → profile 自动降级到 `avatar.musetalk`

### P1：MuseTalk v1.5 质量对比（权重已 99.5%，可选）
- `lite_driver.py` 已支持 `--version v15 --extra-margin 10`
- 下完后：`python lite_driver.py --portrait ... --audio demo_10s.wav --out /tmp/v15.mp4 --version v15 --extra-margin 10`
- 与 v1 对比（嘴部指标 + 视觉）；若更好，把 `autodl-best.yaml` 的 avatar 配置加 `version: v15`、`extraMargin: 10`（v15 自动用 jaw 模式）

### P2：延迟优化（用户会关心）
- 当前首音约 35-40s（SenseVoice 加载 9.5s + LLM 网络 + VoxCPM 整段合成）
- 参考 VoxEMW：句级流式 TTS（首音 ~2s）+ Qwen3-ASR；可作为下一阶段大改

### P3：前端体验确认
- 让用户实测 Playground（音频 resume 修复后应能出声）；收集反馈继续调
- 可参考 `apps/studio` 现有设计，新增视觉优化按需做

### P4：仓库收尾
- 服务器 git commit 落后本地，记得同步并 push；刷新 `E:\tmp\avatarloom-e2e.bundle`
- `docs/06-*` 报告按新成果更新

---

## 5. 复现命令速查

```bash
# MuseTalk demo（v1）
cd /root/autodl-tmp/musetalk
/root/autodl-tmp/musetalk-venv/bin/python lite_driver.py \
  --portrait /root/autodl-tmp/avatarloom/personas/demo-assistant/avatar/portrait.jpg \
  --audio demo_10s.wav --out /tmp/demo.mp4 --keep-frames

# 单测
cd /root/autodl-tmp/avatarloom && python3 -m pytest tests -q

# Studio 重建 + 启动
cd /root/autodl-tmp/avatarloom/apps/studio
/usr/local/lib/node22/bin/pnpm build
/usr/local/lib/node22/bin/pnpm start   # 监听 3000
```

---

## 6. 踩坑记录（重要，避免重复踩）

1. **mediapipe 1.0.0 移除了 `solutions` API** → 装 `mediapipe==0.10.14`。
2. **torch 2.6+ `torch.load` 默认 `weights_only=True`**：BiSeNet/旧 .tar 权重必须 `weights_only=False`（已补丁在 `musetalk/utils/face_parsing/`）。
3. **hf-mirror 不稳**：xet 403/限速常见；大权重优先 ModelScope（`Kedreamix/Linly-Talker` 有 MuseTalk v1、`Soul-AILab/SoulX-FlashHead-1_3B` 有 FlashHead）；`curl -C -` 可断点续传；pip 下载必须加 `--retries 20 --timeout 120 --progress-bar off`（否则会静默卡死数小时）。
4. **ffmpeg libx264 拒绝奇数宽高** → 缩放时强制偶数（`//2*2`）。
5. **orchestrator 传 `workspace_root="."`（相对路径）** → block 里必须 `Path(ctx.workspace_root).resolve()`，否则子进程在错误 cwd 找不到脚本/wav。
6. **两个进程并发写同一权重文件会损坏**（curl+aria2 或双 aria2）→ 只能一个下载器。
7. **SSH 通道挂起**：后台进程若继承 ssh stdin/stdout，会话不退出 → 一律 `setsid nohup ... </dev/null >log 2>&1 &`。
8. **subagent 通道当前不可用**：官方 subagent（DeepSeek/MiniMax）多次返回空；原生 spawn/followup 任务消息投递失败（agent 只收到系统上下文）。**不要依赖 agent 通道，直接自己写代码**；若后续环境恢复再试。
9. **浏览器 AudioContext 必须用户手势内 resume**，否则无声。
10. **SSR 页面 fetch 不能用相对 URL**（Next rewrites 只对浏览器生效）。

---

## 7. 服务器当前状态快照（2026-08-06 01:45）

- 服务：gateway 8101 ✅ / studio 3000 ✅ / control-api 8100 ✅（全部 200）
- FlashHead 安装：进行中（torch cu128 wheels 下载，日志 `/tmp/flashhead_setup.log`）
- MuseTalk v1.5：99.5%（还剩 ~16MB）
- GPU：0% 利用率 / 9.2GB 显存（gateway 持模型）；数据盘 30G/200G（15%）
- 隧道：正常（本地 3000/8100/8101 可达）

**给接棒 Agent 的第一句话**：先 `tail -3 /tmp/flashhead_setup.log` 看安装是否完成；完成就按第 4 节 P0 的验证步骤跑；没完成就等/排障，同时可以先把 P1 的 v1.5 对比做了。
