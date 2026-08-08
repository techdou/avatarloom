#!/bin/bash
# AvatarLoom AutoDL 一键环境部署
#
# 用法（在 AutoDL 实例上，克隆项目后）：
#   git clone https://github.com/techdou/avatarloom.git
#   cd avatarloom
#   bash scripts/autodl_setup.sh
#
# 脚本幂等——可多次运行。
# 首次约 30-60 分钟（主要时间花在下载模型权重）。

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

# 颜色
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log()  { echo -e "${GREEN}[$(date +%H:%M:%S)]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }
err()  { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# ---------------------------------------------------------------------------
# 环境检查
# ---------------------------------------------------------------------------
log "=== AvatarLoom AutoDL 环境部署 ==="

# GPU 检查
if ! command -v nvidia-smi &>/dev/null; then
    err "未检测到 GPU（nvidia-smi 不可用）"
    err "请在 AutoDL 控制台选择带 GPU 的实例"
    exit 1
fi
GPU_INFO=$(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader | head -1)
log "GPU: $GPU_INFO"
VRAM_MB=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -1)
log "显存: ${VRAM_MB} MB"
if [ "$VRAM_MB" -lt 20000 ]; then
    warn "显存 < 20GB，VoxCPM2 + MuseTalk 可能 OOM"
    warn "建议用 24GB 以上实例（RTX 4090/3090）"
fi

# AutoDL 数据盘路径（/root/autodl-tmp）
AUTODL_TMP="/root/autodl-tmp"
if [ ! -d "$AUTODL_TMP" ]; then
    warn "非 AutoDL 环境或无 autodl-tmp，模型存到项目目录"
    AUTODL_TMP="$PROJECT_ROOT/models"
fi
mkdir -p "$AUTODL_TMP/huggingface"
mkdir -p "$AUTODL_TMP/modelscope"

# ---------------------------------------------------------------------------
# 系统依赖
# ---------------------------------------------------------------------------
log "=== 安装系统依赖 ==="
if command -v apt-get &>/dev/null; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq ffmpeg gcc g++ curl git >/dev/null
    log "系统依赖已装（ffmpeg/gcc 等）"
fi

# ---------------------------------------------------------------------------
# Python 环境（uv）
# ---------------------------------------------------------------------------
log "=== 安装 uv（Python 包管理器）==="
if ! command -v uv &>/dev/null; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
    # 让后续 shell 也能用
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
fi
log "uv 版本: $(uv --version)"

# ---------------------------------------------------------------------------
# HuggingFace 镜像（国内网络必需）
# ---------------------------------------------------------------------------
# 上次完整安装会在 shell 中开启离线模式；重跑安装时先关闭，确保缺失模型可续传。
unset HF_HUB_OFFLINE
log "=== 配置 HuggingFace 国内镜像 ==="
export HF_ENDPOINT=https://hf-mirror.com
export HF_HOME="$AUTODL_TMP/huggingface"
export HF_HUB_DISABLE_XET=1
# 持久化到 .bashrc——带标记守卫，重复运行不重复追加（幂等）
if ! grep -q "AvatarLoom HuggingFace" ~/.bashrc 2>/dev/null; then
    cat >> ~/.bashrc << EOF

# AvatarLoom HuggingFace 镜像配置
export HF_ENDPOINT=https://hf-mirror.com
export HF_HUB_DISABLE_XET=1
export HF_HOME="$AUTODL_TMP/huggingface"
EOF
fi
log "HF_ENDPOINT=$HF_ENDPOINT  HF_HOME=$HF_HOME"

# ---------------------------------------------------------------------------
# Node.js + pnpm（Studio 前端用）
# ---------------------------------------------------------------------------
log "=== 安装 Node.js + pnpm ==="
if ! command -v node &>/dev/null; then
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
    apt-get install -y -qq nodejs >/dev/null
fi
log "Node: $(node --version)"

if ! command -v pnpm &>/dev/null; then
    npm install -g pnpm@11 2>/dev/null || corepack enable pnpm
fi
log "pnpm: $(pnpm --version)"

# ---------------------------------------------------------------------------
# 安装 AvatarLoom Python 依赖（GPU 全套）
# ---------------------------------------------------------------------------
log "=== 安装 Python 依赖（GPU 全套 extras）==="
cd "$PROJECT_ROOT"
uv sync --extra dev --extra gpu-full 2>&1 | tail -3 || {
    err "gpu-full 依赖安装失败——缺少 torch/funasr 等，后续模型下载必然全部失败，直接停止"
    exit 1
}
log "Python 依赖装完"

# ---------------------------------------------------------------------------
# Studio 前端依赖
# ---------------------------------------------------------------------------
log "=== 安装 Studio 前端依赖 ==="
pnpm install 2>&1 | tail -3
log "前端依赖装完"

# ---------------------------------------------------------------------------
# 下载模型权重（首次，最耗时）
# ---------------------------------------------------------------------------
log "=== 下载模型权重（首次约 15-30 分钟）==="

# 下载失败统一记账，结尾汇总并非零退出——调用方（SSH/CI）能看到真实状态；
# 重跑本脚本可续传（HF/modelscope 缓存幂等）。
FAILED_MODELS=()

# 1. Silero VAD（torch hub，~30MB）
log "[1/4] Silero VAD..."
if ! uv run python -c "
import torch
torch.hub.load(repo_or_dir='snakers4/silero-vad', model='silero_vad', trust_repo=True, force_reload=False)
print('Silero VAD 已缓存')
" 2>&1 | tail -2; then
    warn "Silero VAD 下载失败（网络问题，重跑本脚本续传）"
    FAILED_MODELS+=("silero-vad")
fi

# 2. SenseVoiceSmall（FunASR，~900MB）
log "[2/4] SenseVoiceSmall..."
if ! uv run python -c "
from funasr import AutoModel
AutoModel(model='iic/SenseVoiceSmall', trust_remote_code=True, device='cpu', disable_update=True)
print('SenseVoiceSmall 已缓存')
" 2>&1 | tail -2; then
    warn "SenseVoice 下载失败（重跑续传，或用 openai-compatible STT 替代）"
    FAILED_MODELS+=("sensevoice")
fi

# 3. VoxCPM2（~1.5GB）
log "[3/4] VoxCPM2..."
if ! uv run python -c "
from huggingface_hub import snapshot_download
snapshot_download(repo_id='openbmb/VoxCPM2', cache_dir='$AUTODL_TMP/huggingface')
print('VoxCPM2 已缓存')
" 2>&1 | tail -2; then
    warn "VoxCPM2 下载失败（重跑续传）"
    FAILED_MODELS+=("voxcpm2")
fi

# 4. MuseTalk 权重（按 MuseTalk 官方文档，~2GB）
log "[4/4] MuseTalk（可选，按官方仓库说明）..."
warn "MuseTalk 需手动按官方仓库下载（依赖结构特殊）"
warn "参考：https://github.com/TMElyralab/MuseTalk"

# ---------------------------------------------------------------------------
# 创建 .env（如果不存在）
# ---------------------------------------------------------------------------
log "=== 配置 .env ==="
if [ ! -f "$PROJECT_ROOT/.env" ]; then
    cp "$PROJECT_ROOT/.env.autodl.example" "$PROJECT_ROOT/.env"
    log ".env 已从 AutoDL 模板创建——你需要编辑填 LLM API key"
    warn "运行 nano .env 填 LLM_API_KEY"
else
    log ".env 已存在，跳过"
fi

# ---------------------------------------------------------------------------
# 完成
# ---------------------------------------------------------------------------
echo ""
if [ "${#FAILED_MODELS[@]}" -gt 0 ]; then
    err "以下模型下载失败：${FAILED_MODELS[*]}"
    err "环境其余部分已就绪——网络恢复后重跑本脚本即可续传（幂等）"
    exit 1
fi

# 所有模型检查成功后才启用离线模式，避免下载失败把后续重试毒化。
log "=== 启用离线模式（加速启动）==="
if ! grep -q "AvatarLoom 离线模式" ~/.bashrc 2>/dev/null; then
    cat >> ~/.bashrc << 'EOF'

# AvatarLoom 离线模式
export HF_HUB_OFFLINE=1
EOF
fi
export HF_HUB_OFFLINE=1

log "========================================"
log "AvatarLoom 环境部署完成"
log "========================================"
echo ""
echo "下一步："
echo "  1. 编辑 .env 填 LLM API key："
echo "     nano .env"
echo "     # 找到 LLM_API_KEY= 行，填上你的 key（DeepSeek 等 OpenAI 兼容端点）"
echo ""
echo "  2. 跑 Mock 冒烟测试（验证基础链路）："
echo "     uv run python scripts/smoke_mock.py"
echo ""
echo "  3. 起 Studio 服务（浏览器访问）："
echo "     bash scripts/autodl_start.sh"
echo ""
echo "  4. 浏览器开 http://<你的 AutoDL IP>:3000"
echo "     （AutoDL 需在控制台做端口映射，或用 SSH 隧道）"
echo ""
log "本脚本可随时重跑；安装阶段会临时关闭离线模式并校验缺失模型"
