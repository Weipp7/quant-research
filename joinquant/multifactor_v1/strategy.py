# -*- coding: utf-8 -*-
"""
多因子选股策略 V1

因子：BP（账面市值比）+ ROE（盈利质量）+ MOM（12-1月动量）等权合成
股票池：沪深300成分股
选股：综合得分 Top 30，等权持仓
调仓：月度（每月第一个交易日开盘）
过滤：ST / 停牌 / 上市不足 250 天

IC 测试结果（2016-2023，沪深300）：
  BP 单因子    IC_IR=0.156  Q5-Q1=+5.3%
  BP+ROE       IC_IR=0.309  Q5-Q1=+10.7%
  BP+ROE+MOM   IC_IR=0.363  Q5-Q1=+16.9%  Q5年化=+11.7%

手续费：买入万三，卖出万三+千一印花税，最低5元；滑点0.1%
"""

from jqdata import *
import pandas as pd
import numpy as np
import datetime


# ────────────────────────────────────────────
# 初始化
# ────────────────────────────────────────────
def initialize(context):
    set_benchmark('000300.XSHG')
    set_option('use_real_price', True)
    log.info('多因子选股 V1 (BP+ROE+MOM, Top30, 沪深300, 月度调仓)')

    set_order_cost(OrderCost(
        close_tax=0.001,
        open_commission=0.0003,
        close_commission=0.0003,
        min_commission=5
    ), type='stock')
    set_slippage(PriceRelatedSlippage(0.001))

    g.universe    = '000300.XSHG'
    g.top_n       = 30
    g.mom_long    = 252    # 动量回看期（约12个月交易日）
    g.mom_short   = 21     # 短期反转剔除（约1个月）
    # 无创业板/科创板权限时设为 True（默认开启）
    g.exclude_kcyb = True  # 排除 300xxx（创业板）和 688xxx（科创板）

    run_monthly(rebalance, monthday=1, time='open',
                reference_security='000300.XSHG')


# ────────────────────────────────────────────
# 因子工具
# ────────────────────────────────────────────
def mad_winsorize(s, n=3):
    """MAD 去极值"""
    median = s.median()
    mad = (s - median).abs().median() * 1.4826
    return s.clip(median - n * mad, median + n * mad)


def zscore(s):
    """Z-score 标准化"""
    std = s.std()
    if std == 0:
        return s * 0
    return (s - s.mean()) / std


def get_factor_scores(context, stocks):
    """
    计算 BP / ROE / MOM 因子并合成综合评分。
    返回 Series（index=stock_code, values=score），按得分降序。
    """
    prev_date = context.previous_date

    # ── 1. BP 和 ROE（财务数据，昨日可得）──
    try:
        fund_df = get_fundamentals(
            query(valuation.code, valuation.pb_ratio, indicator.roe)
            .filter(valuation.code.in_(stocks),
                    valuation.pb_ratio > 0,
                    indicator.roe != None),
            date=prev_date
        ).set_index('code')
    except Exception as e:
        log.warning('get_fundamentals 失败: %s' % str(e))
        return pd.Series(dtype=float)

    fund_df['bp'] = 1.0 / fund_df['pb_ratio']
    fund_df = fund_df[['bp', 'roe']].dropna()

    if len(fund_df) < g.top_n:
        log.warning('因子数据不足 %d 只' % len(fund_df))
        return pd.Series(dtype=float)

    # ── 2. 动量（12月-1月）──
    try:
        hist = get_price(
            list(fund_df.index),
            end_date=prev_date,
            count=g.mom_long + 1,
            frequency='daily',
            fields=['close'],
            skip_paused=False,
            fq='pre',
            panel=False,
        )
    except Exception as e:
        log.warning('get_price(历史) 失败: %s' % str(e))
        # 动量数据缺失时退化为 BP+ROE 双因子
        fund_df['z_bp']  = zscore(mad_winsorize(fund_df['bp']))
        fund_df['z_roe'] = zscore(mad_winsorize(fund_df['roe']))
        fund_df['score'] = (fund_df['z_bp'] + fund_df['z_roe']) / 2
        return fund_df['score'].sort_values(ascending=False)

    close_p = hist.pivot(index='time', columns='code', values='close')

    if len(close_p) < g.mom_long:
        log.warning('动量历史数据不足，退化为 BP+ROE')
        fund_df['z_bp']  = zscore(mad_winsorize(fund_df['bp']))
        fund_df['z_roe'] = zscore(mad_winsorize(fund_df['roe']))
        fund_df['score'] = (fund_df['z_bp'] + fund_df['z_roe']) / 2
        return fund_df['score'].sort_values(ascending=False)

    ret_long  = close_p.iloc[-1] / close_p.iloc[0] - 1
    ret_short = close_p.iloc[-1] / close_p.iloc[-g.mom_short] - 1
    mom = (ret_long - ret_short).rename('mom')

    # ── 3. 合并 & 标准化 ──
    df = fund_df.join(mom, how='inner').dropna()
    if len(df) < g.top_n:
        log.warning('合并后因子数据不足 %d 只' % len(df))
        return pd.Series(dtype=float)

    df['z_bp']  = zscore(mad_winsorize(df['bp']))
    df['z_roe'] = zscore(mad_winsorize(df['roe']))
    df['z_mom'] = zscore(mad_winsorize(df['mom']))
    df['score'] = (df['z_bp'] + df['z_roe'] + df['z_mom']) / 3

    return df['score'].sort_values(ascending=False)


def filter_stocks(context, stocks):
    """过滤 ST / 停牌 / 上市不足 250 天 / 创业板 / 科创板"""
    current_data = get_current_data()
    today = context.current_dt.date()
    filtered = []
    for s in stocks:
        # 排除创业板（300xxx）和科创板（688xxx）
        if g.exclude_kcyb:
            code = s.split('.')[0]
            if code.startswith('300') or code.startswith('688'):
                continue
        try:
            if current_data[s].is_st:
                continue
            if current_data[s].paused:
                continue
            info = get_security_info(s)
            if info is None:
                continue
            if (today - info.start_date).days < 250:
                continue
            filtered.append(s)
        except Exception:
            continue
    return filtered


# ────────────────────────────────────────────
# 调仓主逻辑
# ────────────────────────────────────────────
def rebalance(context):
    log.info('======= 月度调仓 %s =======' % str(context.current_dt.date()))

    # 1. 获取当前成分股
    try:
        universe = get_index_stocks(g.universe, context.previous_date)
    except Exception:
        log.warning('获取成分股失败，跳过本次调仓')
        return

    # 2. 过滤
    tradable = filter_stocks(context, universe)
    log.info('可交易标的：%d 只（原 %d 只）' % (len(tradable), len(universe)))

    if len(tradable) < g.top_n:
        log.warning('可交易标的不足，跳过')
        return

    # 3. 计算因子得分
    scores = get_factor_scores(context, tradable)
    if scores.empty:
        log.warning('因子计算失败，跳过本次调仓')
        return

    # 4. 选 Top N
    target_stocks = list(scores.head(g.top_n).index)
    log.info('目标持仓 %d 只，Top5: %s' % (g.top_n, target_stocks[:5]))

    # 5. 卖出不在目标中的
    for stock in list(context.portfolio.positions.keys()):
        if stock not in target_stocks:
            order_target(stock, 0)

    # 6. 等权买入目标股票
    target_value = context.portfolio.total_value / g.top_n
    for stock in target_stocks:
        order_target_value(stock, target_value)

    log.info('调仓完成，目标单股市值 ¥%.0f' % target_value)


# ────────────────────────────────────────────
# 收盘记录
# ────────────────────────────────────────────
def after_market_close(context):
    positions = context.portfolio.positions
    held = sum(1 for p in positions.values() if p.total_amount > 0)
    nav  = context.portfolio.total_value
    log.info('NAV=%.2f，持仓=%d只' % (nav, held))
