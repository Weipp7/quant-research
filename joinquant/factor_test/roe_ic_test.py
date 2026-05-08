# -*- coding: utf-8 -*-
"""
单因子 IC 检验：ROE（净资产收益率，TTM）

运行环境：聚宽研究环境
目的：验证 ROE 因子的预测能力，为与 BP 合成"质量价值因子"做准备

与 bp_ic_test.py 结构相同，便于结果直接对比。
"""

from jqdata import *
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# ──────────────────────────────────────────────
# 参数（与 BP 测试保持一致）
# ──────────────────────────────────────────────
START_DATE   = "2016-01-01"
END_DATE     = "2023-12-31"
UNIVERSE     = "000300.XSHG"
N_QUANTILES  = 5

# ──────────────────────────────────────────────
# 1. 调仓日期
# ──────────────────────────────────────────────
all_trade_days = pd.DatetimeIndex(get_trade_days(start_date=START_DATE, end_date=END_DATE))
monthly_dates = (pd.Series(all_trade_days)
                 .groupby([all_trade_days.year, all_trade_days.month])
                 .first()
                 .values)
monthly_dates = pd.DatetimeIndex(monthly_dates)
print(f"调仓日期数量：{len(monthly_dates)}，首尾：{monthly_dates[0].date()} ~ {monthly_dates[-1].date()}")

# ──────────────────────────────────────────────
# 2. 逐月计算 ROE Rank IC
# ──────────────────────────────────────────────
ic_records = []

for i, date in enumerate(monthly_dates[:-1]):
    next_date = monthly_dates[i + 1]

    try:
        stocks = get_index_stocks(UNIVERSE, date=date)
        fund_df = get_fundamentals(
            query(valuation.code, indicator.roe)
            .filter(valuation.code.in_(stocks),
                    indicator.roe != None),
            date=date
        ).set_index("code")
    except Exception:
        continue

    fund_df = fund_df.rename(columns={"roe": "roe_val"})
    fund_df = fund_df[fund_df["roe_val"].notna()]

    if len(fund_df) < 20:
        continue

    try:
        price_data = get_price(
            list(fund_df.index),
            start_date=date,
            end_date=next_date,
            frequency="daily",
            fields=["close"],
            skip_paused=False,
            fq="pre",
            panel=False,
        )
    except Exception:
        continue

    close_pivot = price_data.pivot(index="time", columns="code", values="close")
    close_start = close_pivot.iloc[0]
    close_end   = close_pivot.iloc[-1]
    forward_ret = (close_end / close_start - 1).rename("forward_ret")

    merged = fund_df["roe_val"].to_frame().join(forward_ret, how="inner").dropna()
    if len(merged) < 20:
        continue

    rank_ic = merged["roe_val"].rank().corr(merged["forward_ret"].rank())
    ic_records.append({"date": date, "rank_ic": rank_ic, "n_stocks": len(merged)})

    if (i + 1) % 12 == 0:
        print(f"  进度：{date.date()}，IC={rank_ic:.4f}，样本股数={len(merged)}")

ic_df = pd.DataFrame(ic_records).set_index("date")
print(f"\n计算完成：共 {len(ic_df)} 个月度 IC 值")

# ──────────────────────────────────────────────
# 3. IC 统计
# ──────────────────────────────────────────────
ic_mean = ic_df["rank_ic"].mean()
ic_std  = ic_df["rank_ic"].std()
ic_ir   = ic_mean / ic_std if ic_std > 0 else 0
ic_pos  = (ic_df["rank_ic"] > 0).mean()

print("\n======== ROE 因子 IC 统计 ========")
print(f"IC 均值  : {ic_mean:+.4f}")
print(f"IC 标准差: {ic_std:.4f}")
print(f"IC_IR    : {ic_ir:+.4f}")
print(f"正IC比例 : {ic_pos:.2%}")

if abs(ic_mean) < 0.02:
    conclusion = "基本无效"
elif abs(ic_mean) < 0.05:
    conclusion = "弱有效"
elif abs(ic_mean) < 0.10:
    conclusion = "有效"
else:
    conclusion = "强有效（警惕过拟合）"
print(f"结论     : {conclusion}")

# ──────────────────────────────────────────────
# 4. IC 时间序列图（与 BP 对比标注）
# ──────────────────────────────────────────────
fig, axes = plt.subplots(2, 1, figsize=(14, 8))

ax = axes[0]
ic_df["rank_ic"].plot(ax=ax, alpha=0.7, label="Monthly Rank IC")
ic_df["rank_ic"].rolling(6).mean().plot(ax=ax, linewidth=2, label="6M Rolling Mean")
ax.axhline(0, color="black", linewidth=0.8)
ax.axhline(ic_mean, color="red", linewidth=1.2, linestyle="--",
           label=f"Mean={ic_mean:+.4f}")
ax.set_title(f"ROE Factor — Rank IC Time Series  |  IC_IR={ic_ir:.3f}")
ax.set_ylabel("Rank IC")
ax.legend()

ax2 = axes[1]
ic_df["rank_ic"].hist(bins=30, ax=ax2, edgecolor="black", alpha=0.7)
ax2.axvline(0, color="black", linewidth=0.8)
ax2.axvline(ic_mean, color="red", linewidth=1.5, linestyle="--",
            label=f"Mean={ic_mean:+.4f}")
ax2.set_title("IC Distribution")
ax2.set_xlabel("Rank IC")
ax2.legend()

plt.tight_layout()
plt.show()

# ──────────────────────────────────────────────
# 5. 分层回测
# ──────────────────────────────────────────────
print("\n======== ROE 因子分层回测 ========")
quantile_returns = {q: [] for q in range(1, N_QUANTILES + 1)}

for i, date in enumerate(monthly_dates[:-1]):
    next_date = monthly_dates[i + 1]

    try:
        stocks = get_index_stocks(UNIVERSE, date=date)
        fund_df = get_fundamentals(
            query(valuation.code, indicator.roe)
            .filter(valuation.code.in_(stocks), indicator.roe != None),
            date=date
        ).set_index("code").rename(columns={"roe": "roe_val"})
    except Exception:
        continue

    fund_df = fund_df[fund_df["roe_val"].notna()]

    try:
        price_data = get_price(
            list(fund_df.index), start_date=date, end_date=next_date,
            frequency="daily", fields=["close"], skip_paused=False, fq="pre",
            panel=False,
        )
    except Exception:
        continue

    close_pivot = price_data.pivot(index="time", columns="code", values="close")
    close_start = close_pivot.iloc[0]
    close_end   = close_pivot.iloc[-1]
    forward_ret = (close_end / close_start - 1).rename("forward_ret")

    merged = fund_df["roe_val"].to_frame().join(forward_ret, how="inner").dropna()
    if len(merged) < N_QUANTILES * 5:
        continue

    merged["quantile"] = pd.qcut(merged["roe_val"], N_QUANTILES, labels=False) + 1
    for q in range(1, N_QUANTILES + 1):
        quantile_returns[q].append(merged[merged["quantile"] == q]["forward_ret"].mean())

fig, ax = plt.subplots(figsize=(14, 5))
for q in range(1, N_QUANTILES + 1):
    rets = pd.Series(quantile_returns[q])
    cumret = (1 + rets).cumprod() - 1
    suffix = " (高ROE)" if q == N_QUANTILES else (" (低ROE)" if q == 1 else "")
    ax.plot(cumret.values, label=f"Q{q}{suffix}")

ax.axhline(0, color="black", linewidth=0.5)
ax.set_title("ROE Factor — 5-Quantile Cumulative Returns  (Q5=高ROE=优质股)")
ax.set_xlabel("月数")
ax.set_ylabel("累计收益")
ax.legend()
plt.tight_layout()
plt.show()

print("\n各分位平均月收益（年化）：")
for q in range(1, N_QUANTILES + 1):
    monthly_avg = np.mean(quantile_returns[q])
    ann = (1 + monthly_avg) ** 12 - 1
    print(f"  Q{q}: 月均 {monthly_avg:+.4f}  年化 {ann:+.2%}")

long_ret  = np.mean(quantile_returns[N_QUANTILES])
short_ret = np.mean(quantile_returns[1])
ls_ann    = ((1 + long_ret) ** 12 - 1) - ((1 + short_ret) ** 12 - 1)
print(f"\n多空（Q5-Q1）年化收益差：{ls_ann:+.2%}")
