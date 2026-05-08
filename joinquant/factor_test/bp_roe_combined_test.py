# -*- coding: utf-8 -*-
"""
双因子合成 IC 检验：BP + ROE 等权 Z-score

理论依据：
- BP 和 ROE 在极端行情中 IC 方向相反（2017/2020/2021/2022 均如此）
- 合成后两者噪音互相抵消，IC_IR 应显著高于单因子（0.16 → 预期 0.3+）

合成方式：等权 Z-score
  1. 各期横截面对 BP、ROE 分别做 Z-score 标准化
  2. 取均值：score = (z_bp + z_roe) / 2
  3. 计算 score 与下期收益的 Rank IC

运行环境：聚宽研究环境
"""

from jqdata import *
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt


# ──────────────────────────────────────────────
# 参数
# ──────────────────────────────────────────────
START_DATE  = "2016-01-01"
END_DATE    = "2023-12-31"
UNIVERSE    = "000300.XSHG"
N_QUANTILES = 5


# ──────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────
def zscore(s):
    """横截面 Z-score 标准化"""
    return (s - s.mean()) / s.std()


def mad_winsorize(s, n=3):
    """MAD 去极值，减少离群值对 Z-score 的干扰"""
    median = s.median()
    mad = (s - median).abs().median() * 1.4826
    return s.clip(median - n * mad, median + n * mad)


# ──────────────────────────────────────────────
# 1. 调仓日期
# ──────────────────────────────────────────────
all_trade_days = pd.DatetimeIndex(get_trade_days(start_date=START_DATE, end_date=END_DATE))
monthly_dates = (pd.Series(all_trade_days)
                 .groupby([all_trade_days.year, all_trade_days.month])
                 .first()
                 .values)
monthly_dates = pd.DatetimeIndex(monthly_dates)
print(f"调仓日期：{len(monthly_dates)} 个月，{monthly_dates[0].date()} ~ {monthly_dates[-1].date()}")


# ──────────────────────────────────────────────
# 2. 逐月计算三组 IC（BP / ROE / 合成）
# ──────────────────────────────────────────────
ic_bp_list   = []
ic_roe_list  = []
ic_comb_list = []

for i, date in enumerate(monthly_dates[:-1]):
    next_date = monthly_dates[i + 1]

    # 2.1 获取因子数据
    try:
        stocks = get_index_stocks(UNIVERSE, date=date)
        fund_df = get_fundamentals(
            query(valuation.code, valuation.pb_ratio, indicator.roe)
            .filter(valuation.code.in_(stocks),
                    valuation.pb_ratio > 0,
                    indicator.roe != None),
            date=date
        ).set_index("code")
    except Exception:
        continue

    fund_df["bp"]  = 1.0 / fund_df["pb_ratio"]
    fund_df["roe"] = fund_df["roe"]
    fund_df = fund_df[["bp", "roe"]].dropna()

    if len(fund_df) < 30:
        continue

    # 2.2 去极值 + Z-score 标准化
    fund_df["z_bp"]  = zscore(mad_winsorize(fund_df["bp"]))
    fund_df["z_roe"] = zscore(mad_winsorize(fund_df["roe"]))

    # 2.3 等权合成综合得分
    fund_df["score"] = (fund_df["z_bp"] + fund_df["z_roe"]) / 2

    # 2.4 未来收益
    try:
        price_data = get_price(
            list(fund_df.index), start_date=date, end_date=next_date,
            frequency="daily", fields=["close"], skip_paused=False,
            fq="pre", panel=False,
        )
    except Exception:
        continue

    close_pivot = price_data.pivot(index="time", columns="code", values="close")
    close_start = close_pivot.iloc[0]
    close_end   = close_pivot.iloc[-1]
    forward_ret = (close_end / close_start - 1).rename("forward_ret")

    merged = fund_df.join(forward_ret, how="inner").dropna()
    if len(merged) < 20:
        continue

    ret_rank = merged["forward_ret"].rank()
    ic_bp_list.append({
        "date": date,
        "rank_ic": merged["bp"].rank().corr(ret_rank)
    })
    ic_roe_list.append({
        "date": date,
        "rank_ic": merged["roe"].rank().corr(ret_rank)
    })
    ic_comb_list.append({
        "date": date,
        "rank_ic": merged["score"].rank().corr(ret_rank)
    })

    if (i + 1) % 12 == 0:
        print(f"  {date.date()} | BP IC={ic_bp_list[-1]['rank_ic']:+.3f}  "
              f"ROE IC={ic_roe_list[-1]['rank_ic']:+.3f}  "
              f"合成 IC={ic_comb_list[-1]['rank_ic']:+.3f}")

ic_bp   = pd.DataFrame(ic_bp_list).set_index("date")
ic_roe  = pd.DataFrame(ic_roe_list).set_index("date")
ic_comb = pd.DataFrame(ic_comb_list).set_index("date")
print(f"\n计算完成：{len(ic_comb)} 个月度 IC 值")


# ──────────────────────────────────────────────
# 3. 对比统计汇总
# ──────────────────────────────────────────────
def stats(df, label):
    m   = df["rank_ic"].mean()
    std = df["rank_ic"].std()
    ir  = m / std if std > 0 else 0
    pos = (df["rank_ic"] > 0).mean()
    print(f"  {label:<10} IC均值={m:+.4f}  std={std:.4f}  IC_IR={ir:+.4f}  正IC={pos:.1%}")

print("\n======== 三因子 IC 对比 ========")
stats(ic_bp,   "BP")
stats(ic_roe,  "ROE")
stats(ic_comb, "BP+ROE合成")


# ──────────────────────────────────────────────
# 4. IC 时间序列对比图
# ──────────────────────────────────────────────
fig, axes = plt.subplots(2, 1, figsize=(14, 9))

ax = axes[0]
ic_bp["rank_ic"].rolling(6).mean().plot(ax=ax, label="BP 6M rolling", alpha=0.7)
ic_roe["rank_ic"].rolling(6).mean().plot(ax=ax, label="ROE 6M rolling", alpha=0.7)
ic_comb["rank_ic"].rolling(6).mean().plot(ax=ax, linewidth=2.5, label="BP+ROE Combined")
ax.axhline(0, color="black", linewidth=0.8)
ax.set_title("BP / ROE / Combined — 6M Rolling Rank IC")
ax.set_ylabel("Rank IC (6M avg)")
ax.legend()

ax2 = axes[1]
ic_bp["rank_ic"].plot(ax=ax2, alpha=0.4, label="BP monthly")
ic_roe["rank_ic"].plot(ax=ax2, alpha=0.4, label="ROE monthly")
ic_comb["rank_ic"].plot(ax=ax2, linewidth=1.5, color="purple", label="Combined monthly")
ax2.axhline(0, color="black", linewidth=0.8)
ax2.set_title("Monthly IC — BP / ROE / Combined")
ax2.set_ylabel("Rank IC")
ax2.legend()

plt.tight_layout()
plt.show()


# ──────────────────────────────────────────────
# 5. 合成因子分层回测
# ──────────────────────────────────────────────
print("\n======== BP+ROE 合成因子分层回测 ========")
quantile_returns = {q: [] for q in range(1, N_QUANTILES + 1)}

for i, date in enumerate(monthly_dates[:-1]):
    next_date = monthly_dates[i + 1]

    try:
        stocks = get_index_stocks(UNIVERSE, date=date)
        fund_df = get_fundamentals(
            query(valuation.code, valuation.pb_ratio, indicator.roe)
            .filter(valuation.code.in_(stocks),
                    valuation.pb_ratio > 0, indicator.roe != None),
            date=date
        ).set_index("code")
    except Exception:
        continue

    fund_df["bp"]  = 1.0 / fund_df["pb_ratio"]
    fund_df = fund_df[["bp", "roe"]].dropna()
    fund_df["z_bp"]  = zscore(mad_winsorize(fund_df["bp"]))
    fund_df["z_roe"] = zscore(mad_winsorize(fund_df["roe"]))
    fund_df["score"] = (fund_df["z_bp"] + fund_df["z_roe"]) / 2

    try:
        price_data = get_price(
            list(fund_df.index), start_date=date, end_date=next_date,
            frequency="daily", fields=["close"], skip_paused=False,
            fq="pre", panel=False,
        )
    except Exception:
        continue

    close_pivot = price_data.pivot(index="time", columns="code", values="close")
    forward_ret = (close_pivot.iloc[-1] / close_pivot.iloc[0] - 1).rename("forward_ret")

    merged = fund_df["score"].to_frame().join(forward_ret, how="inner").dropna()
    if len(merged) < N_QUANTILES * 5:
        continue

    merged["quantile"] = pd.qcut(merged["score"], N_QUANTILES, labels=False) + 1
    for q in range(1, N_QUANTILES + 1):
        quantile_returns[q].append(merged[merged["quantile"] == q]["forward_ret"].mean())

fig, ax = plt.subplots(figsize=(14, 5))
for q in range(1, N_QUANTILES + 1):
    rets = pd.Series(quantile_returns[q])
    cumret = (1 + rets).cumprod() - 1
    suffix = " (质量价值)" if q == N_QUANTILES else (" (低分)" if q == 1 else "")
    ax.plot(cumret.values, label=f"Q{q}{suffix}")

ax.axhline(0, color="black", linewidth=0.5)
ax.set_title("BP+ROE Combined — 5-Quantile Cumulative Returns")
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
print("\n期望：IC_IR 从单因子 ~0.15 提升到 0.25+，多空差从 ~5% 提升到 7%+")
