# -*- coding: utf-8 -*-
"""
三因子合成 IC 检验：BP + ROE + 动量（12-1月）

动量因子构造：
  MOM = (过去12个月累计收益) - (过去1个月收益)
  即去掉最近1个月的反转效应，保留中期趋势

A股动量特点：
  - 短期（1月）是反转的
  - 中期（3-12月）是延续的
  - 动量在 2019 年贸易战反弹行情中应为正 → 弥补 BP+ROE 双失效的盲区

运行环境：聚宽研究环境
"""

from jqdata import *
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt


START_DATE  = "2016-01-01"
END_DATE    = "2023-12-31"
UNIVERSE    = "000300.XSHG"
N_QUANTILES = 5


def zscore(s):
    return (s - s.mean()) / s.std()


def mad_winsorize(s, n=3):
    median = s.median()
    mad = (s - median).abs().median() * 1.4826
    return s.clip(median - n * mad, median + n * mad)


# ──────────────────────────────────────────────
# 1. 调仓日期
# ──────────────────────────────────────────────
all_trade_days = pd.DatetimeIndex(get_trade_days(start_date="2015-01-01", end_date=END_DATE))
monthly_dates_all = pd.DatetimeIndex(
    pd.Series(all_trade_days)
    .groupby([all_trade_days.year, all_trade_days.month])
    .first()
    .values
)

# 因为动量需要回看12个月，实际信号从 START_DATE 开始
signal_dates = monthly_dates_all[monthly_dates_all >= START_DATE]
print(f"信号日期：{len(signal_dates)} 个月，{signal_dates[0].date()} ~ {signal_dates[-1].date()}")


# ──────────────────────────────────────────────
# 2. 逐月计算 BP / ROE / MOM / 三因子合成 IC
# ──────────────────────────────────────────────
records = []

for i, date in enumerate(signal_dates[:-1]):
    next_date = signal_dates[i + 1]

    try:
        stocks = get_index_stocks(UNIVERSE, date=date)
    except Exception:
        continue

    # 2.1 估值 + 质量因子
    try:
        fund_df = get_fundamentals(
            query(valuation.code, valuation.pb_ratio, indicator.roe)
            .filter(valuation.code.in_(stocks),
                    valuation.pb_ratio > 0,
                    indicator.roe != None),
            date=date
        ).set_index("code")
    except Exception:
        continue

    fund_df["bp"] = 1.0 / fund_df["pb_ratio"]
    fund_df = fund_df[["bp", "roe"]].dropna()

    if len(fund_df) < 30:
        continue

    # 2.2 动量因子：12月收益 - 1月收益（去掉短期反转）
    try:
        hist = get_price(
            list(fund_df.index),
            end_date=date,
            count=253,                  # 约12个月交易日
            frequency="daily",
            fields=["close"],
            skip_paused=False,
            fq="pre",
            panel=False,
        )
    except Exception:
        continue

    close_pivot = hist.pivot(index="time", columns="code", values="close")

    if len(close_pivot) < 253:
        continue

    ret_12m = close_pivot.iloc[-1] / close_pivot.iloc[0] - 1       # 全12月收益
    ret_1m  = close_pivot.iloc[-1] / close_pivot.iloc[-21] - 1     # 最近1月收益
    mom     = (ret_12m - ret_1m).rename("mom")

    # 2.3 合并三个因子
    df = fund_df.join(mom, how="inner").dropna()
    if len(df) < 30:
        continue

    df["z_bp"]  = zscore(mad_winsorize(df["bp"]))
    df["z_roe"] = zscore(mad_winsorize(df["roe"]))
    df["z_mom"] = zscore(mad_winsorize(df["mom"]))
    df["score_2"] = (df["z_bp"] + df["z_roe"]) / 2
    df["score_3"] = (df["z_bp"] + df["z_roe"] + df["z_mom"]) / 3

    # 2.4 未来收益
    try:
        price_fwd = get_price(
            list(df.index), start_date=date, end_date=next_date,
            frequency="daily", fields=["close"], skip_paused=False,
            fq="pre", panel=False,
        )
    except Exception:
        continue

    close_fwd = price_fwd.pivot(index="time", columns="code", values="close")
    forward_ret = (close_fwd.iloc[-1] / close_fwd.iloc[0] - 1).rename("fwd")

    merged = df.join(forward_ret, how="inner").dropna()
    if len(merged) < 20:
        continue

    ret_rank = merged["fwd"].rank()
    records.append({
        "date":    date,
        "ic_bp":   merged["bp"].rank().corr(ret_rank),
        "ic_roe":  merged["roe"].rank().corr(ret_rank),
        "ic_mom":  merged["mom"].rank().corr(ret_rank),
        "ic_2f":   merged["score_2"].rank().corr(ret_rank),
        "ic_3f":   merged["score_3"].rank().corr(ret_rank),
        "n":       len(merged),
    })

    if (i + 1) % 12 == 0:
        r = records[-1]
        print(f"  {date.date()} | BP={r['ic_bp']:+.3f}  ROE={r['ic_roe']:+.3f}  "
              f"MOM={r['ic_mom']:+.3f}  2F={r['ic_2f']:+.3f}  3F={r['ic_3f']:+.3f}")

ic_df = pd.DataFrame(records).set_index("date")
print(f"\n计算完成：{len(ic_df)} 个月度 IC 值")


# ──────────────────────────────────────────────
# 3. 统计汇总
# ──────────────────────────────────────────────
def stats(col, label):
    s   = ic_df[col]
    m   = s.mean()
    std = s.std()
    ir  = m / std if std > 0 else 0
    pos = (s > 0).mean()
    print(f"  {label:<14} IC均值={m:+.4f}  std={std:.4f}  IC_IR={ir:+.4f}  正IC={pos:.1%}")

print("\n======== 因子 IC 对比 ========")
stats("ic_bp",  "BP")
stats("ic_roe", "ROE")
stats("ic_mom", "MOM (12-1)")
stats("ic_2f",  "BP+ROE (2因子)")
stats("ic_3f",  "BP+ROE+MOM (3因子)")


# ──────────────────────────────────────────────
# 4. IC 时间序列图
# ──────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(14, 5))
ic_df["ic_bp"].rolling(6).mean().plot(ax=ax, alpha=0.6, label="BP 6M avg")
ic_df["ic_roe"].rolling(6).mean().plot(ax=ax, alpha=0.6, label="ROE 6M avg")
ic_df["ic_mom"].rolling(6).mean().plot(ax=ax, alpha=0.6, label="MOM 6M avg")
ic_df["ic_2f"].rolling(6).mean().plot(ax=ax, linewidth=2, linestyle="--", label="2F (BP+ROE)")
ic_df["ic_3f"].rolling(6).mean().plot(ax=ax, linewidth=2.5, color="purple", label="3F (BP+ROE+MOM)")
ax.axhline(0, color="black", linewidth=0.8)
ax.set_title("3-Factor IC Comparison — 6M Rolling Mean")
ax.legend()
ax.set_ylabel("Rank IC (6M avg)")
plt.tight_layout()
plt.show()


# ──────────────────────────────────────────────
# 5. 三因子合成分层回测
# ──────────────────────────────────────────────
print("\n======== BP+ROE+MOM 分层回测 ========")
quantile_returns_2f = {q: [] for q in range(1, N_QUANTILES + 1)}
quantile_returns_3f = {q: [] for q in range(1, N_QUANTILES + 1)}

for i, date in enumerate(signal_dates[:-1]):
    next_date = signal_dates[i + 1]
    if date not in ic_df.index:
        continue

    # 复用已计算的数据结构
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

    fund_df["bp"] = 1.0 / fund_df["pb_ratio"]
    fund_df = fund_df[["bp", "roe"]].dropna()

    try:
        hist = get_price(list(fund_df.index), end_date=date, count=253,
                         frequency="daily", fields=["close"],
                         skip_paused=False, fq="pre", panel=False)
    except Exception:
        continue

    cp = hist.pivot(index="time", columns="code", values="close")
    if len(cp) < 253:
        continue

    mom = (cp.iloc[-1] / cp.iloc[0] - 1 - (cp.iloc[-1] / cp.iloc[-21] - 1)).rename("mom")
    df = fund_df.join(mom, how="inner").dropna()
    df["z_bp"]  = zscore(mad_winsorize(df["bp"]))
    df["z_roe"] = zscore(mad_winsorize(df["roe"]))
    df["z_mom"] = zscore(mad_winsorize(df["mom"]))
    df["score_2"] = (df["z_bp"] + df["z_roe"]) / 2
    df["score_3"] = (df["z_bp"] + df["z_roe"] + df["z_mom"]) / 3

    try:
        price_fwd = get_price(list(df.index), start_date=date, end_date=next_date,
                              frequency="daily", fields=["close"],
                              skip_paused=False, fq="pre", panel=False)
    except Exception:
        continue

    close_fwd = price_fwd.pivot(index="time", columns="code", values="close")
    fwd_ret = (close_fwd.iloc[-1] / close_fwd.iloc[0] - 1).rename("fwd")

    for score_col, qret in [("score_2", quantile_returns_2f), ("score_3", quantile_returns_3f)]:
        merged = df[score_col].to_frame().join(fwd_ret, how="inner").dropna()
        if len(merged) < N_QUANTILES * 5:
            continue
        merged["q"] = pd.qcut(merged[score_col], N_QUANTILES, labels=False) + 1
        for q in range(1, N_QUANTILES + 1):
            qret[q].append(merged[merged["q"] == q]["fwd"].mean())

print("\n2因子 vs 3因子 各分位年化收益：")
print(f"  {'分位':<6} {'2F(BP+ROE)':<14} {'3F(BP+ROE+MOM)':<16}")
for q in range(1, N_QUANTILES + 1):
    a2 = (1 + np.mean(quantile_returns_2f[q])) ** 12 - 1
    a3 = (1 + np.mean(quantile_returns_3f[q])) ** 12 - 1
    tag = " ← top" if q == N_QUANTILES else ""
    print(f"  Q{q}    {a2:+.2%}        {a3:+.2%}{tag}")

ls2 = ((1+np.mean(quantile_returns_2f[5]))**12-1) - ((1+np.mean(quantile_returns_2f[1]))**12-1)
ls3 = ((1+np.mean(quantile_returns_3f[5]))**12-1) - ((1+np.mean(quantile_returns_3f[1]))**12-1)
print(f"\n  多空差  2F: {ls2:+.2%}   3F: {ls3:+.2%}")
