# 台股盤中動量回放 Repo Notes

目前 repo 的權威實作是 Python：

- 主程式：`src/tw_signal_engine/`
- 入口：`tw_signal_engine.cli.run_daily_replay`、`tw_signal_engine.cli.run_batch_replay`
- 舊版 C++：`legacy/cpp/`，僅保留做 parity 與歷史參考

## 先看這些文件

- Repo 地圖：[AGENTS.md](AGENTS.md)
- 架構摘要：[ARCHITECTURE.md](ARCHITECTURE.md)
- 文件首頁：[docs/index.md](docs/index.md)
- 目前策略行為：[docs/product-specs/current-strategy-spec.md](docs/product-specs/current-strategy-spec.md)

## 常用命令

```bash
uv sync
uv run pytest tests -q
uv run ruff check src tests
uv run mypy src
```

```bash
uv run python -m tw_signal_engine.cli.run_daily_replay \
  --date 20260129 \
  --data-dir exec/data \
  --files-dir exec/files \
  --group-file exec/files/group.csv \
  --config exec/cfg/parameter.cfg
```

## Git 工作流程

- PR 一律發到 `yichingleee/signal`，除非另有指示。

## 重要約定

- 價格一律用 `price * 10000` 的整數表示。
- `match_time_str` 是像 `91500000000` 的整數時間戳。
- `match_time_us` 是從午夜起算的微秒，用在 rolling window。
- `exec/cfg/parameter.cfg` 是目前 replay 使用的設定來源。
- `exec/files/Symbols_YYYYMMDD.csv` 與 `exec/files/group.csv` 是必要輸入。

若文件內容與程式不一致，以 Python 程式碼與 `docs/` 內的 indexed docs 為準，不以舊版 C++ 或歷史設計筆記為準。
