# -*- coding: utf-8 -*-
"""
单因子 IC 检验：BP（账面市值比，即 1/PB）

运行环境：聚宽研究环境（非回测，直接在"研究"tab里跑）
目的：验证 BP 因子在沪深300成分股上的预测能力

输出：
  - IC 时间序列图
  - IC 均值 / IC_IR / 正IC比例
  - 5分位分层收益图（多空收益）
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib
from jqdatasdk import *

matplotlib.use("Agg")   # 聚宽研究环境用 Agg 后端

# ──────────────────────────────────────────────
# 参数
# ──────────────────────────────────────────────
START_DATE   = "2016-01-01"
END_DATE     = "2023-12-31"
UNIVERSE     = "000300.XSHG"    # 沪深300
FORWARD_DAYS = 21               # 持有期：约1个月（约21个交易日）
N_QUANTILES  = 5                # 分层数

# ──────────────────────────────────────────────
# 1. 生成调仓日期（每月第一个交易日）
# ──────────────────────────────────────────────
all_trade_days = pd.DatetimeIndex(get_all_trade_days())
all_trade_days = all_trade_days[(all_trade_days >= START_DATE) & (all_trade_days <= END_DATE)]

monthly_dates = (pd.Series(all_trade_days)
                 .groupby([all_trade_days.year, all_trade_days.month])
                 .first()
                 .values)
monthly_dates = pd.DatetimeIndex(monthly_dates)

print(f"调仓日期数量：{len(monthly_dates)}，首尾：{monthly_dates[0].date()} ~ {monthly_dates[-1].date()}")

# ──────────────────────────────────────────────
# 2. 逐月计算 BP 因子值 & 未来收益 → Rank IC
# ──────────────────────────────────────────────
ic_records = []

for i, date in enumerate(monthly_dates[:-1]):
    next_date = monthly_dates[i + 1]          # 下一个调仓日（持有到这天）

    # 2.1 当月成分股（用真实历史成分，避免未来偏差）
    try:
        stocks = get_index_stocks(UNIVERSE, date=date)
    except Exception:
        continue

    # 2.2 过滤 ST / 停牌
    current_data = get_current_data(stocks)   # 注意：研究环境不支持当日数据，此处仅做结构示意
    # 实际过滤：用 get_extras + get_security_info 或直接跳过，保持简单
    # 这里先不做 ST 过滤，第一版看整体方向

    # 2.3 获取 BP 因子值（= 1/PB）
    try:
        fund_df = get_fundamentals(
            query(valuation.code, valuation.pb_ratio)
            .filter(valuation.code.in_(stocks),
                    valuation.pb_ratio > 0),    # 过滤负PB（亏损股）
            date=date
        )
    except Exception:
        continue

    fund_df = fund_df.set_index("code")
    fund_df["bp"] = 1.0 / fund_df["pb_ratio"]

    if len(fund_df) < 20:                       # 样本不足则跳过
        continue

    # 2.4 计算未来收益（date → next_date 的简单收益）
    price_data = get_price(
        list(fund_df.index),
        start_date=date,
        end_date=next_date,
        frequency="daily",
        fields=["close"],
        skip_paused=False,
        fq="pre"
    )
    # price_data 是 panel：(date × stock)
    close_start = price_data["close"].iloc[0]
    close_end   = price_data["close"].iloc[-1]
    forward_ret = (close_end / close_start - 1).rename("forward_ret")

    # 2.5 合并，计算 Rank IC（Spearman 相关）
    merged = fund_df["bp"].to_frame().join(forward_ret, how="inner").dropna()
    if len(merged) < 20:
        continue

    rank_ic = merged["bp"].rank().corr(merged["forward_ret"].rank())
    ic_records.append({"date": date, "rank_ic": rank_ic, "n_stocks": len(merged)})

    if (i + 1) % 12 == 0:
        print(f"  进度：{date.date()}，IC={rank_ic:.4f}，样本股数={len(merged)}")

ic_df = pd.DataFrame(ic_records).set_index("date")
print(f"\n计算完成：共 {len(ic_df)} 个月度 IC 值")

# ──────────────────────────────────────────────
# 3. IC 统计汇总
# ──────────────────────────────────────────────
ic_mean = ic_df["rank_ic"].mean()
ic_std  = ic_df["rank_ic"].std()
ic_ir   = ic_mean / ic_std if ic_std > 0 else 0
ic_pos  = (ic_df["rank_ic"] > 0).mean()

print("\n======== BP 因子 IC 统计 ========")
print(f"IC 均值  : {ic_mean:+.4f}   (|IC|>0.02 为弱有效，>0.05 为有效)")
print(f"IC 标准差: {ic_std:.4f}")
print(f"IC_IR    : {ic_ir:+.4f}   (>0.5 为不错的因子)")
print(f"正IC比例 : {ic_pos:.2%}   (>55% 代表稳定性较好)")
print(f"月度数   : {len(ic_df)}")

# 结论判断
if abs(ic_mean) < 0.02:
    conclusion = "基本无效"
elif abs(ic_mean) < 0.05:
    conclusion = "弱有效"
elif abs(ic_mean) < 0.10:
    conclusion = "有效"
else:
    conclusion = "强有效（注意过拟合风险）"
print(f"结论     : {conclusion}")

# ──────────────────────────────────────────────
# 4. IC 时间序列图
# ──────────────────────────────────────────────
fig, axes = plt.subplots(2, 1, figsize=(14, 8))

ax = axes[0]
ic_df["rank_ic"].plot(ax=ax, alpha=0.7, label="Monthly Rank IC")
ic_df["rank_ic"].rolling(6).mean().plot(ax=ax, linewidth=2, label="6M Rolling Mean")
ax.axhline(0, color="black", linewidth=0.8)
ax.axhline(ic_mean, color="red", linewidth=1.2, linestyle="--",
           label=f"Mean={ic_mean:+.4f}")
ax.set_title(f"BP Factor — Rank IC Time Series  |  IC_IR={ic_ir:.3f}")
ax.set_ylabel("Rank IC")
ax.legend()

# IC 分布直方图
ax2 = axes[1]
ic_df["rank_ic"].hist(bins=30, ax=ax2, edgecolor="black", alpha=0.7)
ax2.axvline(0, color="black", linewidth=0.8)
ax2.axvline(ic_mean, color="red", linewidth=1.5, linestyle="--",
            label=f"Mean={ic_mean:+.4f}")
ax2.set_title("IC Distribution")
ax2.set_xlabel("Rank IC")
ax2.legend()

plt.tight_layout()
plt.savefig("/tmp/bp_ic_timeseries.png", dpi=120)
plt.close()
print("\nIC 图已保存：/tmp/bp_ic_timeseries.png")

# ──────────────────────────────────────────────
# 5. 分层回测（5分位多空）
# ──────────────────────────────────────────────
print("\n======== BP 因子分层回测 ========")

# 把每期数据收集后做分层累计收益
quantile_returns = {q: [] for q in range(1, N_QUANTILES + 1)}

for i, date in enumerate(monthly_dates[:-1]):
    next_date = monthly_dates[i + 1]

    try:
        stocks = get_index_stocks(UNIVERSE, date=date)
        fund_df = get_fundamentals(
            query(valuation.code, valuation.pb_ratio)
            .filter(valuation.code.in_(stocks), valuation.pb_ratio > 0),
            date=date
        ).set_index("code")
    except Exception:
        continue

    fund_df["bp"] = 1.0 / fund_df["pb_ratio"]

    price_data = get_price(
        list(fund_df.index), start_date=date, end_date=next_date,
        frequency="daily", fields=["close"], skip_paused=False, fq="pre"
    )
    close_start = price_data["close"].iloc[0]
    close_end   = price_data["close"].iloc[-1]
    forward_ret = (close_end / close_start - 1).rename("forward_ret")

    merged = fund_df["bp"].to_frame().join(forward_ret, how="inner").dropna()
    if len(merged) < N_QUANTILES * 5:
        continue

    merged["quantile"] = pd.qcut(merged["bp"], N_QUANTILES, labels=False) + 1
    for q in range(1, N_QUANTILES + 1):
        group_ret = merged[merged["quantile"] == q]["forward_ret"].mean()
        quantile_returns[q].append(group_ret)

# 累计收益
fig, ax = plt.subplots(figsize=(14, 5))
for q in range(1, N_QUANTILES + 1):
    rets = pd.Series(quantile_returns[q])
    cumret = (1 + rets).cumprod() - 1
    label = f"Q{q}" + (" (高BP/低估值)" if q == N_QUANTILES else "") + (" (低BP/高估值)" if q == 1 else "")
    ax.plot(cumret.values, label=label)

ax.axhline(0, color="black", linewidth=0.5)
ax.set_title("BP Factor — 5-Quantile Cumulative Returns  (Q5=高BP=价值股)")
ax.set_xlabel("月数")
ax.set_ylabel("累计收益")
ax.legend()
plt.tight_layout()
plt.savefig("/tmp/bp_quantile_returns.png", dpi=120)
plt.close()
print("分层图已保存：/tmp/bp_quantile_returns.png")

# 打印各分位年化收益
print("\n各分位平均月收益（年化）：")
for q in range(1, N_QUANTILES + 1):
    monthly_avg = np.mean(quantile_returns[q])
    ann = (1 + monthly_avg) ** 12 - 1
    print(f"  Q{q}: 月均 {monthly_avg:+.4f}  年化 {ann:+.2%}")

long_ret  = np.mean(quantile_returns[N_QUANTILES])
short_ret = np.mean(quantile_returns[1])
ls_ann    = ((1 + long_ret) ** 12 - 1) - ((1 + short_ret) ** 12 - 1)
print(f"\n多空（Q5-Q1）年化收益差：{ls_ann:+.2%}")
