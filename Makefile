.PHONY: help setup dev stop test lint type fmt clean doctor smoke docker

PYTHON ?= uv run python
UV      ?= uv
PNPM    ?= pnpm

help: ## 显示所有可用命令
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

setup: ## 安装 Python + Node 全部依赖（不含 GPU extras）
	$(UV) sync --extra dev
	$(PNPM) install
	@echo "✓ 依赖安装完成。运行 'make dev' 启动开发环境。"

setup-gpu: ## 安装包含 GPU 全套重型依赖
	$(UV) sync --extra dev --extra gpu-full
	$(PNPM) install

dev: ## 启动三服务（Control API + Runtime Gateway + Studio）
	$(PYTHON) scripts/dev.py

stop: ## 停止所有 AvatarLoom 服务
	-@for pid in .data/control-api.pid .data/runtime-gateway.pid; do \
	  [ -f $$pid ] && kill `cat $$pid` 2>/dev/null && rm -f $$pid; \
	done
	@echo "✓ 服务已停止"

test: ## 运行 Python + TypeScript 测试
	$(UV) run pytest tests/unit tests/integration -v
	$(PNPM) test

test-py: ## 仅 Python 测试
	$(UV) run pytest tests/unit tests/integration -v

test-ts: ## 仅 TypeScript 测试
	$(PNPM) test

test-e2e: ## Playwright E2E（需先 make dev 起服务）
	$(PNPM) --filter @avatarloom/studio exec playwright test

lint: ## ruff + ESLint
	$(UV) run ruff check .
	$(PNPM) lint

type: ## mypy + tsc 类型检查
	$(UV) run mypy packages runtime blocks apps
	$(PNPM) --filter @avatarloom/studio exec tsc --noEmit

fmt: ## 格式化代码
	$(UV) run ruff format .
	$(UV) run ruff check --fix .
	$(PNPM) exec prettier --write "apps/**/*.{ts,tsx,css}" "packages/**/*.{ts,tsx}"

doctor: ## 环境自检
	$(PYTHON) scripts/doctor.py

smoke: ## Mock 全链路冒烟测试
	$(PYTHON) scripts/smoke_mock.py

build: ## 构建 Studio 生产版本 + SDK
	$(PNPM) build

docker: ## Docker Compose 配置校验
	docker compose -f deploy/docker-compose.yml config > /dev/null && echo "✓ docker-compose.yml 配置有效"

clean: ## 清理构建产物和缓存
	rm -rf .next node_modules/.cache .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
