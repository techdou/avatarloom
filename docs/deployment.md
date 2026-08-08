# AvatarLoom 部署与启动

三种形态：**本地 dev**（开发调试）、**Docker Compose**（单机自包含）、**AutoDL GPU**（真实模型生产）。
默认配置全部指向 Mock 链路——不配任何 Key、没有 GPU，起来就能对话。

## 通用配置（.env）

所有形态共用一套环境变量，完整样板见根目录 `.env.example`（AutoDL 用 `.env.autodl.example`）。关键项：

| 变量 | 默认 | 说明 |
|---|---|---|
| `AVATARLOOM_CONTROL_API_PORT` | 8100 | Control API 端口（独立别名，勿再用共享旧名 `AVATARLOOM_PORT`） |
| `AVATARLOOM_RUNTIME_GATEWAY_PORT` | 8101 | Runtime Gateway 端口（同上） |
| `STUDIO_PORT` | 3000 | Studio 端口（经 `PORT` 传给 Next.js） |
| `AVATARLOOM_DEFAULT_PROFILE` | `mock` | WS 客户端不带 `profile_id` 时的默认档位；GPU 部署改成 `autodl-best` 等 |
| `AVATARLOOM_API_TOKEN` | 空 | Bearer token，**留空=鉴权关闭**。填值后同时保护 control-api HTTP 与 gateway WS |
| `AVATARLOOM_CONTROL_API_TOKEN` | 空 | gateway 调 control-api 用的 token，与上一项同值即可 |
| `LLM_API_KEY` 等 | 空 | 真实 Adapter 的 Key；全空 = Mock 链路 |

## 本地 dev

```bash
uv sync --extra dev && pnpm install
make dev          # = uv run python scripts/dev.py
```

- 启动前做端口占用预检，冲突直接退出码 1 并点名端口。
- 任一服务拉起后 3 秒内死亡（模块缺失、bind 失败）判启动失败，停掉其余服务并非零退出。
- 运行中任一服务退出 → 停掉其余服务，**透传该服务的退出码**；Ctrl+C 正常停止退出 0。
- Windows：pnpm 经 `shutil.which` 解析 `pnpm.cmd` 全路径；停止时用 `taskkill /T` 杀整棵进程树，不留孤儿 node 占 3000 端口。
- 环境自检：`make doctor`；Mock 链路冒烟：`make smoke`。

## Docker Compose

```bash
docker compose -f deploy/docker-compose.yml config   # 校验（make docker 同效）
docker compose -f deploy/docker-compose.yml up --build
```

- 默认 Mock Profile，无 GPU 无 Key 直接可用；浏览器开 `http://localhost:3000`。
- 构建可复现：Python 侧 `uv sync --frozen --no-dev` 严格按 `uv.lock`，Node 侧 `pnpm install --frozen-lockfile` 严格按 `pnpm-lock.yaml`——**失败即报错，没有静默兜底**。
- 构建上下文由根目录 `.dockerignore` 收敛（`.env`、node_modules、data、模型权重不进镜像）。
- 宿主端口覆盖：`CONTROL_API_PORT=18100 STUDIO_PORT=13000 docker compose -f deploy/docker-compose.yml up`。
- 开鉴权：在同名 `.env` 或 shell 设 `AVATARLOOM_API_TOKEN=<随机串>`，control-api 与 gateway 自动共用；healthcheck 自动带 token。
- 真实 GPU：取消 compose 文件里 `deploy.resources` 注释（需 NVIDIA Container Toolkit），并把 `AVATARLOOM_DEFAULT_PROFILE` 改成真实档位。

## AutoDL GPU

```bash
# 1. 环境部署（幂等——可反复跑；模型下载失败会记账并非零退出，网络恢复后重跑续传）
bash scripts/autodl_setup.sh

# 2. 填 Key
cp .env.autodl.example .env   # 首次由 setup 脚本自动拷贝；编辑填 LLM_API_KEY

# 3. 启停（幂等——已在运行的服务自动跳过）
bash scripts/autodl_start.sh          # start：等端口就绪才算成功，失败自动回滚
bash scripts/autodl_start.sh status   # 有服务没起来时退出码 1
bash scripts/autodl_start.sh stop
```

- `.env.autodl.example` 已显式 `AVATARLOOM_DEFAULT_PROFILE=autodl-best`（全局默认是 mock，GPU 部署必须显式锁真实档位）。
- pid 文件在 `data/*.pid`，`make stop` 与 `autodl_start.sh stop` 通用。
- 外部访问走 SSH 隧道（见 README 端口约定）：Studio `3000→13000`、Control API `8100→18100`、Gateway `8101→18101`；浏览器开 `http://localhost:13000/playground`。6006/6008 先按实例实际进程识别，不替代上述三端口。
- 脚本不读 `.bashrc`（非交互 shell），uv/pnpm 路径在脚本内显式 export。

## 鉴权约定

一套 token 三处生效，全部由 `AVATARLOOM_API_TOKEN` 驱动：

1. control-api：所有 HTTP 端点要求 `Authorization: Bearer <token>`（留空则全开放）。
2. gateway `/ws/realtime`：浏览器由 Studio 通过首条 `{"type":"auth","token":"..."}` 消息鉴权；脚本/服务端客户端使用 `Authorization: Bearer <token>`。不要把 token 放进 URL 查询参数。
   Docker Compose 会在构建 Studio 时把 `AVATARLOOM_API_TOKEN` 传给 `NEXT_PUBLIC_WS_TOKEN`；这是单用户受控隧道的共享密钥模型，多用户场景应改为服务端会话 token。
3. gateway → control-api：自动带 `AVATARLOOM_CONTROL_API_TOKEN`（本地/compose 同值即可）。

## 部署后验证清单

```bash
make docker                                   # compose 配置静态校验
uv run python scripts/doctor.py               # 环境/端口/依赖自检
uv run python scripts/smoke_mock.py           # Mock 全链路冒烟
curl http://127.0.0.1:8100/api/health         # control-api
curl http://127.0.0.1:8101/api/health         # gateway
```
