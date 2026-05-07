"""最小回测引擎。

接口:
  run_backtest(bars, strategy_fn, initial_cash) -> pd.DataFrame(date, nav)

strategy_fn(ctx, date) 每个交易日被调用一次。
ctx 提供 buy / sell / price / cash / positions，在收盘价成交。

注意:
- 所有成交按当日收盘价执行（无滑点、无手续费，Phase 2.5 验证用）。
- Phase 3 加入手续费时在 Context.buy/sell 里扣减。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

import pandas as pd


@dataclass
class Context:
    _bars: dict  # {symbol: DataFrame indexed by date}
    _date: object = field(default=None, repr=False)
    cash: float = 100_000.0
    positions: dict = field(default_factory=dict)

    def price(self, symbol: str) -> float:
        return float(self._bars[symbol].loc[self._date, "close"])

    def buy(self, symbol: str, shares: int) -> None:
        assert shares > 0 and shares % 100 == 0, "shares must be positive multiple of 100"
        cost = shares * self.price(symbol)
        if cost > self.cash + 1e-6:
            raise ValueError(f"insufficient cash: need {cost:.2f}, have {self.cash:.2f}")
        self.cash -= cost
        self.positions[symbol] = self.positions.get(symbol, 0) + shares

    def sell(self, symbol: str, shares: int) -> None:
        assert shares > 0 and shares % 100 == 0
        held = self.positions.get(symbol, 0)
        if shares > held:
            raise ValueError(f"insufficient shares: need {shares}, have {held}")
        self.cash += shares * self.price(symbol)
        self.positions[symbol] = held - shares

    def sell_all(self, symbol: str) -> None:
        held = self.positions.get(symbol, 0)
        if held > 0:
            self.sell(symbol, held)

    def nav(self) -> float:
        stock_value = sum(
            qty * float(self._bars[s].loc[self._date, "close"])
            for s, qty in self.positions.items()
            if qty > 0
        )
        return self.cash + stock_value

    def max_lots(self, symbol: str, budget: float | None = None) -> int:
        """最多能买多少整手 (100股/手)。"""
        avail = budget if budget is not None else self.cash
        return math.floor(avail / self.price(symbol) / 100) * 100


def run_backtest(
    bars: dict[str, pd.DataFrame],
    strategy_fn: Callable[[Context, object], None],
    initial_cash: float = 100_000.0,
) -> pd.DataFrame:
    """执行回测，返回每日 NAV Series。

    Args:
        bars: {symbol: DataFrame with 'close' column, date index}
        strategy_fn: 每个交易日收盘时调用，在此执行买卖
        initial_cash: 初始资金

    Returns:
        DataFrame columns=['nav'], index=date
    """
    # 取所有 symbol 共有的交易日，按日期升序
    dates = sorted(
        set.intersection(*[set(df.index) for df in bars.values()])
    )
    ctx = Context(_bars=bars, cash=initial_cash)
    records = []
    for date in dates:
        ctx._date = date
        strategy_fn(ctx, date)
        records.append({"date": date, "nav": ctx.nav()})
    return pd.DataFrame(records).set_index("date")
