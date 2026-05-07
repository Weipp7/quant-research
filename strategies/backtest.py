"""最小回测引擎。

接口:
  run_backtest(bars, strategy_fn, initial_cash, **cost_params) -> BacktestResult

strategy_fn(ctx, date) 每个交易日被调用一次。
ctx 提供 buy / sell / sell_all / buy_with_value / price / cash / positions。
所有成交按当日收盘价执行（无滑点）。

手续费模型（与聚宽一致）:
  买入: commission = max(value × commission_rate, min_commission)
  卖出: commission = max(value × commission_rate, min_commission) + value × stamp_tax_rate
默认值均为 0（Phase 2.5 验证用），Phase 3 传入实际参数。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

import pandas as pd


@dataclass
class _Trade:
    date: object
    symbol: str
    direction: str      # "buy" | "sell"
    shares: int
    price: float
    value: float        # shares × price
    commission: float
    stamp_tax: float
    net_cash_flow: float  # negative for buy, positive for sell


@dataclass
class Context:
    _bars: dict
    _commission_rate: float
    _min_commission: float
    _stamp_tax_rate: float
    _date: object = field(default=None, repr=False)
    cash: float = 100_000.0
    positions: dict = field(default_factory=dict)
    trades: list = field(default_factory=list)

    # ------------------------------------------------------------------ #
    # Price helpers                                                        #
    # ------------------------------------------------------------------ #
    def price(self, symbol: str) -> float:
        return float(self._bars[symbol].loc[self._date, "close"])

    # ------------------------------------------------------------------ #
    # Order execution                                                      #
    # ------------------------------------------------------------------ #
    def buy(self, symbol: str, shares: int) -> None:
        """按整手买入，成本 = 股价 × 股数 + 佣金（最低 min_commission）。"""
        assert shares > 0 and shares % 100 == 0, f"shares must be positive multiple of 100, got {shares}"
        p = self.price(symbol)
        value = shares * p
        commission = max(value * self._commission_rate, self._min_commission) if shares else 0
        total_cost = value + commission
        if total_cost > self.cash + 1e-6:
            raise ValueError(f"insufficient cash: need {total_cost:.2f}, have {self.cash:.2f}")
        self.cash -= total_cost
        self.positions[symbol] = self.positions.get(symbol, 0) + shares
        self.trades.append(_Trade(
            date=self._date, symbol=symbol, direction="buy",
            shares=shares, price=p, value=value,
            commission=commission, stamp_tax=0.0,
            net_cash_flow=-total_cost,
        ))

    def sell(self, symbol: str, shares: int) -> None:
        """按整手卖出，到账 = 股价 × 股数 - 佣金 - 印花税。"""
        assert shares > 0 and shares % 100 == 0
        held = self.positions.get(symbol, 0)
        if shares > held:
            raise ValueError(f"insufficient shares: need {shares}, have {held}")
        p = self.price(symbol)
        value = shares * p
        commission = max(value * self._commission_rate, self._min_commission) if shares else 0
        stamp_tax = value * self._stamp_tax_rate
        proceeds = value - commission - stamp_tax
        self.cash += proceeds
        self.positions[symbol] = held - shares
        self.trades.append(_Trade(
            date=self._date, symbol=symbol, direction="sell",
            shares=shares, price=p, value=value,
            commission=commission, stamp_tax=stamp_tax,
            net_cash_flow=proceeds,
        ))

    def sell_all(self, symbol: str) -> None:
        held = self.positions.get(symbol, 0)
        if held > 0:
            self.sell(symbol, held)

    def buy_with_value(self, symbol: str, target_value: float) -> int:
        """用最多 target_value 元（含佣金）买入尽量多的整手。

        对应聚宽 order_value(security, cash)。
        返回实际买入股数。
        """
        p = self.price(symbol)
        if p <= 0:
            return 0
        # 先尝试按比例佣金估算
        r = self._commission_rate
        m = self._min_commission
        # 最多能买 N 手使得 N×100×P×(1+r) ≤ target_value（比例佣金情形）
        shares_prop = math.floor(target_value / (p * (1 + r)) / 100) * 100
        # 验证：如果实际佣金 < min_commission，改用最低佣金公式
        if shares_prop > 0 and shares_prop * p * r < m:
            shares = math.floor((target_value - m) / p / 100) * 100
        else:
            shares = shares_prop
        shares = max(shares, 0)
        if shares > 0:
            self.buy(symbol, shares)
        return shares

    # ------------------------------------------------------------------ #
    # Position helpers                                                     #
    # ------------------------------------------------------------------ #
    def max_lots(self, symbol: str, budget: float | None = None) -> int:
        """不考虑手续费的最大整手数（粗估）。精确下单用 buy_with_value。"""
        avail = budget if budget is not None else self.cash
        return math.floor(avail / self.price(symbol) / 100) * 100

    def nav(self) -> float:
        stock_value = sum(
            qty * float(self._bars[s].loc[self._date, "close"])
            for s, qty in self.positions.items()
            if qty > 0
        )
        return self.cash + stock_value


@dataclass
class BacktestResult:
    nav: pd.DataFrame          # columns=['nav'], index=date
    trades: list[_Trade]

    def total_return(self, initial_cash: float) -> float:
        return (self.nav.iloc[-1]["nav"] - initial_cash) / initial_cash

    def round_trips(self):
        """配对每次买入/卖出，返回每笔完整交易的盈亏。"""
        trips = []
        open_positions = {}  # symbol -> list of (cost_basis, shares)
        for t in self.trades:
            if t.direction == "buy":
                open_positions.setdefault(t.symbol, []).append(
                    (-(t.net_cash_flow), t.shares)  # cost paid
                )
            else:  # sell
                cost_basis = open_positions.get(t.symbol, [(0, t.shares)])[0][0]
                pnl = t.net_cash_flow - cost_basis  # rough P&L
                trips.append({"date": t.date, "symbol": t.symbol, "pnl": pnl, "profitable": pnl > 0})
                if open_positions.get(t.symbol):
                    open_positions[t.symbol].pop(0)
        return pd.DataFrame(trips) if trips else pd.DataFrame()


def run_backtest(
    bars: dict[str, pd.DataFrame],
    strategy_fn: Callable[[Context, object], None],
    initial_cash: float = 100_000.0,
    commission_rate: float = 0.0,
    min_commission: float = 0.0,
    stamp_tax_rate: float = 0.0,
) -> BacktestResult:
    """执行回测。

    Args:
        bars: {symbol: DataFrame with 'close' column, date index (datetime or date)}
        strategy_fn: 每个交易日调用，在此执行买卖
        initial_cash: 初始资金
        commission_rate: 佣金比例（如 0.0003 = 万三）
        min_commission: 最低佣金（如 5.0 元）
        stamp_tax_rate: 卖出印花税比例（如 0.001 = 千一）

    Returns:
        BacktestResult(nav DataFrame, trades list)
    """
    dates = sorted(set.intersection(*[set(df.index) for df in bars.values()]))
    ctx = Context(
        _bars=bars,
        _commission_rate=commission_rate,
        _min_commission=min_commission,
        _stamp_tax_rate=stamp_tax_rate,
        cash=initial_cash,
    )
    records = []
    for date in dates:
        ctx._date = date
        strategy_fn(ctx, date)
        records.append({"date": date, "nav": ctx.nav()})
    nav_df = pd.DataFrame(records).set_index("date")
    return BacktestResult(nav=nav_df, trades=ctx.trades)
