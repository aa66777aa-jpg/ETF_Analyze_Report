.PHONY: lint run all update sync help

# 顯示所有可用指令說明（make 或 make help）
help:
	@echo "Available targets:"
	@echo "  all    - Update uv, sync dependencies, lint, and run"
	@echo "  sync   - Sync project dependencies with uv sync"
	@echo "  lint   - Check and format code with ruff, then clean cache"
	@echo "  run    - Execute main.py"
	@echo "  update - Update uv itself"

# 依序執行 update → sync → lint → run，一次到位完成環境更新與分析
all: update sync lint run

# 依 pyproject.toml / uv.lock 安裝（或校正）虛擬環境相依套件
sync:
	uv sync

# 用 ruff 檢查並自動修正程式碼問題、統一格式化，最後清除 ruff 快取
lint:
	uvx ruff check --fix .
	uvx ruff format .
	uvx ruff clean

# 更新 uv 工具本身到最新版本（與專案依賴無關）
update:
	uv self update

# 執行主程式：下載股價、計算指標、產生圖表與 HTML 報告
run:
	uv run python main.py
