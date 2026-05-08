# -*- coding: utf-8 -*-
"""
网格策略 V1.2-ETF-ATR - ETF组合 + 动态ATR网格间距

版本说明：
- 在V1.1基础上加入动态网格间距
- 间距 = 1.5 × (ATR / 价格)，每月初更新
- 间距下限1.2%，上限5%

回测结果（2015-01-01 ~ 2024-12-31, 10万本金）：
- 总收益: 31.40%
- 年化收益: 2.85%
- 最大回撤: 17.63%
- 夏普比率: -0.129
- 交易笔数: 751（比V1.1多21%）

教训：动态间距确实生效（交易笔数增加），但收益提升有限
- 说明问题不在间距而在标的本身
- ETF框架的天花板就在3-5%年化
- 这版让我们意识到要回到个股或混合方案
"""

from jqdata import *
import numpy as np

def initialize(context):
    set_benchmark('000300.XSHG')
    set_option('use_real_price', True)
    log.info('网格策略 V1.2：ETF组合 + 动态网格间距')

    set_order_cost(OrderCost(close_tax=0,
                             open_commission=0.0003, 
                             close_commission=0.0003, 
                             min_commission=5), type='fund')
    set_slippage(PriceRelatedSlippage(0.001))

    g.stock_pool = [
        '510300.XSHG', '510500.XSHG', '159915.XSHE', '510050.XSHG',
        '510880.XSHG', '512880.XSHG', '512690.XSHG', '512660.XSHG',
        '518880.XSHG', '513100.XSHG',
    ]
    
    g.index_code = '000300.XSHG'

    g.position_per_stock = 0.10
    g.grid_count = 5
    g.max_position_ratio = 1.5

    # 动态网格间距参数
    g.atr_period = 14
    g.atr_multiplier = 1.5
    g.min_step = 0.012
    g.max_step = 0.05

    g.index_ma_days = 20
    
    g.last_price = {}
    g.initialized = {}
    g.dynamic_step = {}
    
    for stock in g.stock_pool:
        g.last_price[stock] = None
        g.initialized[stock] = False
        g.dynamic_step[stock] = 0.03

    run_daily(before_market_open, time='before_open', reference_security='000300.XSHG')
    run_daily(market_open, time='open', reference_security='000300.XSHG')
    run_daily(after_market_close, time='after_close', reference_security='000300.XSHG')
    run_monthly(update_dynamic_steps, monthday=1, time='before_open', 
                reference_security='000300.XSHG')


def calculate_atr(stock, period):
    """计算ATR（真实波幅均值）"""
    bars = get_bars(stock, count=period+1, unit='1d', fields=['high', 'low', 'close'])
    
    if len(bars) < period+1:
        return None, None, None
    
    highs = bars['high']
    lows = bars['low']
    closes = bars['close']
    
    tr_list = []
    for i in range(1, len(bars)):
        tr1 = highs[i] - lows[i]
        tr2 = abs(highs[i] - closes[i-1])
        tr3 = abs(lows[i] - closes[i-1])
        tr_list.append(max(tr1, tr2, tr3))
    
    atr = np.mean(tr_list)
    current_price = closes[-1]
    atr_ratio = atr / current_price if current_price > 0 else 0
    
    return atr, current_price, atr_ratio


def update_dynamic_steps(context):
    """月初更新动态间距"""
    log.info('========== 月初更新网格间距 ==========')
    
    for stock in g.stock_pool:
        if not is_etf_listed(context, stock):
            continue
        
        atr, price, atr_ratio = calculate_atr(stock, g.atr_period)
        
        if atr is None:
            g.dynamic_step[stock] = 0.03
            continue
        
        raw_step = g.atr_multiplier * atr_ratio
        step = max(g.min_step, min(g.max_step, raw_step))
        g.dynamic_step[stock] = step
        
        log.info('[%s] 价格 %.3f, ATR %.4f (%.2f%%), 间距 %.2f%%' %
                 (stock, price, atr, atr_ratio*100, step*100))


def before_market_open(context):
    log.info('========== %s ==========' % context.current_dt.date())
    
    if not any(g.dynamic_step[s] != 0.03 for s in g.stock_pool):
        update_dynamic_steps(context)


def check_market_filter(context):
    bars = get_bars(g.index_code, count=g.index_ma_days+1, unit='1d', fields=['close'])
    if len(bars) < g.index_ma_days+1:
        return False, 0, 0
    yesterday_close = bars['close'][-1]
    ma = bars['close'][:-1].mean()
    return yesterday_close > ma, yesterday_close, ma


def is_tradable(context, stock):
    current_data = get_current_data()
    
    if current_data[stock].paused:
        return False, '停牌'
    
    day_open = current_data[stock].day_open
    if day_open is None or day_open <= 0:
        return False, '无效数据'
    
    high_limit = current_data[stock].high_limit
    low_limit = current_data[stock].low_limit
    
    if day_open >= high_limit:
        return False, '一字涨停'
    if day_open <= low_limit:
        return False, '一字跌停'
    
    return True, 'OK'


def is_etf_listed(context, stock):
    try:
        bars = get_bars(stock, count=1, unit='1d', fields=['close'])
        if len(bars) == 0:
            return False
        return True
    except:
        return False


def market_open(context):
    is_bull, idx_close, idx_ma = check_market_filter(context)
    
    if not is_bull:
        log.info("大盘过滤：HS300 %.2f <= MA20 %.2f，今日不交易" % (idx_close, idx_ma))
        return
    
    log.info("大盘过滤：HS300 %.2f > MA20 %.2f" % (idx_close, idx_ma))

    total_value = context.portfolio.total_value
    
    for stock in g.stock_pool:
        if not is_etf_listed(context, stock):
            continue
        
        tradable, reason = is_tradable(context, stock)
        if not tradable:
            continue
        
        run_grid_for_stock(context, stock, total_value)


def run_grid_for_stock(context, stock, total_value):
    current_data = get_current_data()
    current_price = current_data[stock].day_open
    
    if current_price is None or current_price <= 0:
        return
    
    step = g.dynamic_step[stock]  # 关键：使用动态间距
    
    if not g.initialized[stock]:
        stock_budget = total_value * g.position_per_stock
        init_cash = stock_budget * 0.5
        
        if context.portfolio.available_cash < init_cash:
            return
        
        order_value(stock, init_cash)
        g.last_price[stock] = current_price
        g.initialized[stock] = True
        log.info('[%s] 建仓：%.3f，投入 %.2f 元，间距 %.2f%%' % 
                 (stock, current_price, init_cash, step*100))
        return
    
    stock_budget = total_value * g.position_per_stock
    grid_amount = stock_budget / g.grid_count
    
    cash = context.portfolio.available_cash
    position = context.portfolio.positions[stock]
    current_holdings = position.total_amount
    current_value = current_holdings * current_price
    
    last_price = g.last_price[stock]
    
    if current_price <= last_price * (1 - step):
        if current_value >= stock_budget * g.max_position_ratio:
            g.last_price[stock] = current_price
            return
        
        if cash >= grid_amount:
            order_value(stock, grid_amount)
            log.info('[%s] 买入：%.3f（跌%.1f%%），%.2f元' %
                     (stock, current_price, step*100, grid_amount))
            g.last_price[stock] = current_price
    
    elif current_price >= last_price * (1 + step):
        if current_value < grid_amount:
            g.last_price[stock] = current_price
            return
        
        sell_shares = int(grid_amount / current_price / 100) * 100
        if sell_shares > 0 and current_holdings >= sell_shares:
            order(stock, -sell_shares)
            log.info('[%s] 卖出：%.3f（涨%.1f%%），%d份' %
                     (stock, current_price, step*100, sell_shares))
            g.last_price[stock] = current_price


def after_market_close(context):
    positions = context.portfolio.positions
    held_count = sum(1 for p in positions.values() if p.total_amount > 0)
    log.info('收盘：总资产 %.2f，持仓 %d 只' % (context.portfolio.total_value, held_count))
    log.info('##############################################################')
