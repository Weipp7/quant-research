"""Phase 2.5 — 回测引擎验证 (Engine Validation)

设计文档要求: 2 个 Golden Backtest, 偏差 < 0.01%。

Test 1: 买入持有 (Buy & Hold)
  黄金值 = 纯算术常量, 不依赖引擎。
  600519 (贵州茅台), 2020-01-02 买入 1 手 (100 股) @ qfq 收盘 979.04,
  持有到 2023-12-29 (最后一个交易日, 2023-12-31 非交易日)。
  手算:
    买入成本 = 100 × 979.04 = 97,904.00
    剩余现金 = 100,000.00 - 97,904.00 = 2,096.00
    末日收盘 = 1,605.60 (qfq)
    最终 NAV  = 100 × 1,605.60 + 2,096.00 = 162,656.00

Test 2: 月初等权再平衡 (Monthly Equal-Weight Rebalance)
  黄金值 = reference_rebalance() 函数, 用 DataFrame 直接算, 不经过引擎。
  000001 + 000002, 2020-01 至 2020-03, 初始 10 万。
  每月第一个交易日卖光再等权买入 (整手)。
"""

import math
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from strategies.backtest import run_backtest
from utils.data_loader import load_daily

TOLERANCE = 0.0001          # 0.01%
INITIAL_CASH = 100_000.0


# ---------------------------------------------------------------------------
# Test 1 helpers
# ---------------------------------------------------------------------------

# 手算常量 (见模块 docstring)
T1_BUY_DATE  = "2020-01-02"
T1_SELL_DATE = "2023-12-29"
T1_SYMBOL    = "600519"
T1_SHARES    = 100
T1_BUY_CLOSE = 979.04
T1_END_CLOSE = 1605.60
T1_EXPECTED_NAV = T1_SHARES * T1_END_CLOSE + (INITIAL_CASH - T1_SHARES * T1_BUY_CLOSE)
# = 100 × 1605.60 + 2096 = 162,656.00


def test_buy_and_hold_moutai():
    """引擎 NAV 与纯算术黄金值偏差 < 0.01%。"""
    bars = {"600519": load_daily(T1_SYMBOL, adjust="qfq")}

    bought = False

    def strategy(ctx, date):
        nonlocal bought
        if not bought and str(date)[:10] == T1_BUY_DATE:
            ctx.buy(T1_SYMBOL, T1_SHARES)
            bought = True

    result = run_backtest(bars, strategy, INITIAL_CASH)

    # 取最接近 T1_SELL_DATE 的那一天 (应该精确命中, 但 date 类型可能是 datetime.date)
    last_nav = result.nav.iloc[-1]["nav"]

    rel_err = abs(last_nav - T1_EXPECTED_NAV) / T1_EXPECTED_NAV
    assert rel_err < TOLERANCE, (
        f"Buy&Hold NAV mismatch: engine={last_nav:.4f}, "
        f"expected={T1_EXPECTED_NAV:.4f}, rel_err={rel_err:.6f}"
    )


# ---------------------------------------------------------------------------
# Test 2 helpers
# ---------------------------------------------------------------------------

T2_SYMBOLS = ["000001", "000002"]
T2_START   = "2020-01-01"
T2_END     = "2020-03-31"


def _monthly_first_dates(index) -> set:
    """给定日期索引, 返回每月第一个交易日的集合。"""
    s = pd.Series(index, index=index)
    return set(s.groupby([s.dt.year, s.dt.month]).first())


def reference_rebalance(bars: dict, symbols: list, initial_cash: float) -> float:
    """月初等权再平衡黄金参考实现 (不使用 run_backtest 引擎)。

    每月第一个交易日: 卖清所有持仓 → 按整手等权买入。
    返回末日 NAV。
    """
    all_idx = pd.DatetimeIndex(bars[symbols[0]].index)
    monthly_firsts = _monthly_first_dates(all_idx)

    cash = initial_cash
    positions = {s: 0 for s in symbols}

    for date in all_idx:
        if date in monthly_firsts:
            # 卖清
            for s in symbols:
                if positions[s] > 0:
                    cash += positions[s] * float(bars[s].loc[date, "close"])
                    positions[s] = 0
            # 等权买入 (整手)
            per_stock = cash / len(symbols)
            for s in symbols:
                price = float(bars[s].loc[date, "close"])
                shares = math.floor(per_stock / price / 100) * 100
                positions[s] = shares
                cash -= shares * price

    last_date = all_idx[-1]
    final_nav = cash + sum(
        positions[s] * float(bars[s].loc[last_date, "close"]) for s in symbols
    )
    return final_nav


def test_monthly_equal_weight_rebalance():
    """引擎 NAV 与 reference_rebalance() 黄金值偏差 < 0.01%。"""
    bars = {
        s: load_daily(s, start=T2_START, end=T2_END, adjust="qfq")
        for s in T2_SYMBOLS
    }
    # 确保两只股票的 index 是 DatetimeIndex (引擎内部用到 dt 属性)
    for s in T2_SYMBOLS:
        bars[s].index = pd.to_datetime(bars[s].index)

    golden = reference_rebalance(bars, T2_SYMBOLS, INITIAL_CASH)

    # --- 引擎策略 ---
    monthly_firsts = _monthly_first_dates(pd.DatetimeIndex(bars[T2_SYMBOLS[0]].index))

    def strategy(ctx, date):
        if pd.Timestamp(date) in monthly_firsts:
            for s in T2_SYMBOLS:
                ctx.sell_all(s)
            per_stock = ctx.cash / len(T2_SYMBOLS)
            for s in T2_SYMBOLS:
                shares = ctx.max_lots(s, budget=per_stock)
                if shares > 0:
                    ctx.buy(s, shares)

    result = run_backtest(bars, strategy, INITIAL_CASH)
    engine_nav = result.nav.iloc[-1]["nav"]

    rel_err = abs(engine_nav - golden) / golden
    assert rel_err < TOLERANCE, (
        f"Rebalance NAV mismatch: engine={engine_nav:.4f}, "
        f"golden={golden:.4f}, rel_err={rel_err:.6f}"
    )
