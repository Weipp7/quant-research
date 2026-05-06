# %% [markdown]
# # 01 — 下载 A 股日线数据并入库
#
# 本脚本/notebook 是 Phase 2 的最小验收切片:
# 1. 用 akshare 拉一只股票的日线
# 2. 写入本地 DuckDB
# 3. 读回来画 K 线
#
# 同一份文件既能 `python notebooks/01_download_data.py` 直接跑,
# 也能在 VS Code / Jupyter (装了 jupytext) 里当 notebook 打开,
# `# %%` 标记会被识别为 cell 边界。

# %%
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent if "__file__" in globals() else Path.cwd().parent
sys.path.insert(0, str(REPO_ROOT))

from utils.data_loader import download_daily, load_daily

# %% [markdown]
# ## 参数
#
# 起止日期对齐 Phase 1 聚宽回测区间 (2019-12-30 至 2024-12-31),
# Phase 3 复现时无需重拉。

# %%
SYMBOL = "000001"      # 平安银行
START = "2019-12-30"
END = "2024-12-31"
ADJUST = "qfq"         # 前复权: 历史价向当前调整, 适合大多数研究

# %% [markdown]
# ## 1. 下载并入库

# %%
n_rows = download_daily(SYMBOL, start=START, end=END, adjust=ADJUST)
print(f"已写入 {n_rows} 行 -> data/a_stocks.duckdb (symbol={SYMBOL}, adjust={ADJUST})")

# %% [markdown]
# ## 2. 读回来检查

# %%
df = load_daily(SYMBOL, start=START, end=END, adjust=ADJUST)
print(df.shape)
print(df.head(3))
print("...")
print(df.tail(3))

# %% [markdown]
# ## 3. K 线图
#
# 用 mplfinance 画蜡烛图 + 成交量。只画最近 60 个交易日,避免 5 年数据挤成一团。

# %%
import mplfinance as mpf
import pandas as pd

ohlc = df[["open", "high", "low", "close", "volume"]].copy()
ohlc.index = pd.to_datetime(ohlc.index)
ohlc = ohlc.tail(60)

mpf.plot(
    ohlc,
    type="candle",
    volume=True,
    style="yahoo",
    title=f"{SYMBOL} last 60 trading days (adjust={ADJUST})",
    figsize=(12, 6),
    savefig=str(REPO_ROOT / "notebooks" / "01_kline_preview.png"),
)
print("已保存 K 线图: notebooks/01_kline_preview.png")
