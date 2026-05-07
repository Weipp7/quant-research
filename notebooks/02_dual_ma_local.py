# %% [markdown]
# # 02 — Phase 3: 本地复现双均线策略
#
# 目标: 用本地引擎复现聚宽 dual_ma_v1 的回测结果，偏差 < 1%。
# 对不上时逐项排查差异来源。
#
# 聚宽策略逻辑（market_open, 用昨日数据判断）：
#   - close_data = get_bars(count=5)   → 最近 5 个已收盘交易日的收盘价
#   - MA5 = mean(close_data)           → 包含昨日在内的 5 日均线
#   - current_price = close_data[-1]   → 昨日收盘价
#   - 买入: current_price > 1.01 × MA5 AND 有现金 → order_value(全部现金)
#   - 卖出: current_price < MA5 AND 有持仓 → order_target(0)
#
# 本地实现差异（记录在 docs/concepts.md）：
#   - 执行价格：聚宽在开盘后不久成交；本地用收盘价（偏差来源 1）
#   - 复权方式：聚宽动态复权；本地用 qfq 前复权（偏差来源 2）
#   - 手续费：两者相同（万三佣金 + 千一卖出印花税 + ¥5 最低佣金）

# %%
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent if "__file__" in globals() else Path.cwd().parent
sys.path.insert(0, str(REPO_ROOT))

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from utils.data_loader import load_daily
from strategies.backtest import run_backtest

# %% [markdown]
# ## 参数（与聚宽保持一致）

# %%
SYMBOL        = "000001"
START         = "2019-12-30"
END           = "2024-12-31"
INITIAL_CASH  = 100_000.0
ADJUST        = "qfq"

# 聚宽手续费设置
COMMISSION_RATE = 0.0003   # 万三
MIN_COMMISSION  = 5.0      # 最低 ¥5
STAMP_TAX_RATE  = 0.001    # 千一（仅卖出）

MA_WINDOW     = 5          # 均线窗口
BUY_THRESHOLD = 1.01       # 价格 > 1.01 × MA 才买

# %% [markdown]
# ## 1. 加载数据 & 预计算信号
#
# 信号计算方式（还原聚宽 get_bars(count=5) at market_open 的行为）：
#   - 在第 t 个交易日, 看第 t-1 到 t-5 共 5 个收盘价（不含当日）
#   - 因此 MA5[t] = shift(1).rolling(5).mean()[t]
#   - signal_price[t] = close[t-1]（昨日收盘 = close_data[-1]）

# %%
df = load_daily(SYMBOL, start=START, end=END, adjust=ADJUST)
df.index = pd.to_datetime(df.index)

df["ma5"]          = df["close"].shift(1).rolling(MA_WINDOW).mean()
df["signal_price"] = df["close"].shift(1)

df["buy_signal"]  = (df["signal_price"] > BUY_THRESHOLD * df["ma5"])
df["sell_signal"] = (df["signal_price"] < df["ma5"])

# 前 MA_WINDOW 天没有足够历史，信号为 NaN → 当天不操作
print(f"有效信号起始日: {df['ma5'].dropna().index[0].date()}")
print(f"数据总行数: {len(df)}")
print(df[["close", "signal_price", "ma5", "buy_signal", "sell_signal"]].head(8))

# %% [markdown]
# ## 2. 策略函数

# %%
def dual_ma_strategy(ctx, date):
    ts = pd.Timestamp(date)
    row = df.loc[ts]

    # 信号不足（MA5 为 NaN）时跳过
    if pd.isna(row["ma5"]):
        return

    has_position = ctx.positions.get(SYMBOL, 0) > 0

    if row["buy_signal"] and ctx.cash > MIN_COMMISSION:
        # 用所有现金买入，含手续费
        ctx.buy_with_value(SYMBOL, ctx.cash)

    elif row["sell_signal"] and has_position:
        ctx.sell_all(SYMBOL)

# %% [markdown]
# ## 3. 执行回测

# %%
bars = {SYMBOL: df}
result = run_backtest(
    bars, dual_ma_strategy, INITIAL_CASH,
    commission_rate=COMMISSION_RATE,
    min_commission=MIN_COMMISSION,
    stamp_tax_rate=STAMP_TAX_RATE,
)

nav = result.nav
final_nav = nav.iloc[-1]["nav"]
total_return = (final_nav - INITIAL_CASH) / INITIAL_CASH * 100

print(f"\n=== 本地回测结果 ===")
print(f"初始资金:   ¥{INITIAL_CASH:,.0f}")
print(f"最终 NAV:   ¥{final_nav:,.2f}")
print(f"策略收益:   {total_return:.2f}%")
print(f"总交易次数: {len(result.trades)}")

# %% [markdown]
# ## 4. 胜率与盈亏统计

# %%
trips = result.round_trips()
if not trips.empty:
    wins   = trips["profitable"].sum()
    losses = (~trips["profitable"]).sum()
    win_rate = wins / len(trips) if len(trips) else 0
    print(f"\n=== 交易统计 ===")
    print(f"完整交易次数: {len(trips)}（买入→卖出）")
    print(f"盈利次数: {wins}")
    print(f"亏损次数: {losses}")
    print(f"胜率:     {win_rate:.3f}")

# %% [markdown]
# ## 5. 与聚宽对比

# %%
JQ = {
    "策略收益":   -44.27,
    "胜率":        0.284,
    "盈利次数":   31,
    "亏损次数":   78,
}

local = {
    "策略收益":   round(total_return, 2),
    "胜率":        round(win_rate, 3) if not trips.empty else None,
    "盈利次数":   int(wins) if not trips.empty else None,
    "亏损次数":   int(losses) if not trips.empty else None,
}

print("\n=== 对比表 ===")
print(f"{'指标':<12} {'聚宽':>10} {'本地':>10} {'差异':>10}")
print("-" * 44)
for k in JQ:
    jq_v  = JQ[k]
    loc_v = local[k]
    if loc_v is not None and isinstance(jq_v, float):
        diff = loc_v - jq_v
        print(f"{k:<12} {jq_v:>10.3f} {loc_v:>10.3f} {diff:>+10.3f}")
    else:
        print(f"{k:<12} {str(jq_v):>10} {str(loc_v):>10}")

# %% [markdown]
# ## 6. 开盘价执行对比实验
#
# 聚宽在 market_open 时下单，实际执行价接近开盘价，而非收盘价。
# 把 bars 里的 close 替换成 open，其余不变，看差距能缩小多少。

# %%
df_open_exec = df.copy()
df_open_exec["close"] = df_open_exec["open"]   # 让引擎用开盘价"成交"

bars_open = {SYMBOL: df_open_exec}
result_open = run_backtest(
    bars_open, dual_ma_strategy, INITIAL_CASH,
    commission_rate=COMMISSION_RATE,
    min_commission=MIN_COMMISSION,
    stamp_tax_rate=STAMP_TAX_RATE,
)
nav_open    = result_open.nav
return_open = (nav_open.iloc[-1]["nav"] - INITIAL_CASH) / INITIAL_CASH * 100

print(f"\n=== 开盘价执行结果 ===")
print(f"最终 NAV:  ¥{nav_open.iloc[-1]['nav']:,.2f}")
print(f"策略收益:  {return_open:.2f}%")

print(f"\n=== 差距分析 ===")
print(f"聚宽:          -44.27%")
print(f"本地(收盘价):  {total_return:.2f}%   差距 {total_return - (-44.27):+.2f}pp")
print(f"本地(开盘价):  {return_open:.2f}%   差距 {return_open - (-44.27):+.2f}pp")
print(f"\n→ 执行价格解释了约 {abs((return_open - total_return)):.1f}pp 的差距")
print(f"→ 剩余约 {abs(return_open - (-44.27)):.1f}pp 差距来自复权方式等其他因素")

# %% [markdown]
# ## 7. NAV 曲线图

# %%
fig, ax = plt.subplots(figsize=(12, 4))
(nav["nav"] / INITIAL_CASH - 1).mul(100).plot(ax=ax, label="local close-price exec")
(nav_open["nav"] / INITIAL_CASH - 1).mul(100).plot(ax=ax, label="local open-price exec", linestyle="--")
ax.axhline(-44.27, color="red", linewidth=1.5, label="JoinQuant -44.27%")
ax.axhline(0, color="black", linewidth=0.5)
ax.set_title(f"{SYMBOL} dual_ma_v1 — local vs JoinQuant")
ax.set_ylabel("return (%)")
ax.legend()
plt.tight_layout()
out = REPO_ROOT / "notebooks" / "02_dual_ma_nav.png"
fig.savefig(out)
plt.close()
print(f"NAV 曲线已保存: {out.name}")
