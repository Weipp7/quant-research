# -*- coding: utf-8 -*-
"""
网格策略 V2.0 - 混合标的池 + 仓位管理（实验失败版）

版本说明：
- 5股+5ETF混合池，全部价格<50元，10万资金可用
- 加入四档仓位管理：STRONG/BALANCED/WEAK/BEAR
- 弱市降仓位但不停止交易

回测结果（2015-01-01 ~ 2024-12-31, 10万本金）：
- 总收益: 52.66%
- 年化收益: 4.45%
- 最大回撤: 21.23%（确实降了）
- 夏普比率: 0.043（变差）
- 胜率: 64.7%
- 盈亏比: 2.10

教训（重要）：仓位管理设计有几个问题
1. 现金占比频繁50%+，目标100%仓位也达不到
2. 状态切换太敏感，几天一切，反复踏空
3. 单标的资金被进一步稀释
4. 网格哲学和仓位管理的"主动判断"冲突

结论：抛弃仓位管理，回归V1风格的简洁框架（见v1_final.py）
"""

from jqdata import *

def initialize(context):
    set_benchmark('000300.XSHG')
    set_option('use_real_price', True)
    log.info('网格策略 V2.0：股票+ETF混合 + 仓位管理（实验版）')

    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, 
                             close_commission=0.0003, min_commission=5), type='stock')
    set_order_cost(OrderCost(close_tax=0,
                             open_commission=0.0003, 
                             close_commission=0.0003, 
                             min_commission=5), type='fund')
    set_slippage(PriceRelatedSlippage(0.001))

    g.stocks = [
        '000001.XSHE', '600036.XSHG', '600900.XSHG',
        '601088.XSHG', '600276.XSHG',
    ]
    
    g.etfs = [
        '510300.XSHG', '510500.XSHG', '510880.XSHG',
        '518880.XSHG', '513100.XSHG',
    ]
    
    g.stock_pool = g.stocks + g.etfs
    g.index_code = '000300.XSHG'

    g.step = 0.03
    g.base_position_per_stock = 0.10
    g.grid_count = 5
    g.max_position_ratio = 1.5

    # 仓位管理参数
    g.market_state = 'BALANCED'
    g.target_position_ratio = 1.0
    g.position_map = {
        'STRONG': 1.0, 'BALANCED': 0.7, 'WEAK': 0.5, 'BEAR': 0.3,
    }

    g.short_ma = 20
    g.long_ma = 60
    
    g.last_price = {}
    g.initialized = {}
    
    for stock in g.stock_pool:
        g.last_price[stock] = None
        g.initialized[stock] = False

    run_daily(before_market_open, time='before_open', reference_security='000300.XSHG')
    run_daily(market_open, time='open', reference_security='000300.XSHG')
    run_daily(after_market_close, time='after_close', reference_security='000300.XSHG')
    run_monthly(evaluate_market_state, monthday=1, time='before_open',
                reference_security='000300.XSHG')


def calculate_shares(amount, price):
    if price <= 0:
        return 0
    return int(amount / price / 100) * 100


def evaluate_market_state(context):
    """每月初评估市场状态，调整目标仓位"""
    log.info('========== 月初评估市场状态 ==========')
    
    bars = get_bars(g.index_code, count=g.long_ma + 1, unit='1d', fields=['close'])
    if len(bars) < g.long_ma + 1:
        return
    
    closes = bars['close']
    yesterday_close = closes[-1]
    ma_short = closes[-g.short_ma-1:-1].mean()
    ma_long = closes[-g.long_ma-1:-1].mean()
    
    above_short = yesterday_close > ma_short
    above_long = yesterday_close > ma_long
    short_above_long = ma_short > ma_long
    
    if above_short and short_above_long:
        new_state = 'STRONG'
    elif above_short and not short_above_long:
        new_state = 'BALANCED'
    elif not above_short and above_long:
        new_state = 'WEAK'
    else:
        new_state = 'BEAR'
    
    g.market_state = new_state
    g.target_position_ratio = g.position_map[new_state]
    
    log.info('市场状态：%s（HS300=%.2f, MA20=%.2f, MA60=%.2f）目标仓位：%.0f%%' %
             (new_state, yesterday_close, ma_short, ma_long, g.target_position_ratio*100))


def before_market_open(context):
    log.info('========== %s [%s 仓位%.0f%%] ==========' % 
             (context.current_dt.date(), g.market_state, g.target_position_ratio*100))
    
    if g.market_state == 'BALANCED' and g.target_position_ratio == 1.0:
        evaluate_market_state(context)


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


def market_open(context):
    total_value = context.portfolio.total_value
    
    for stock in g.stock_pool:
        tradable, reason = is_tradable(context, stock)
        if not tradable:
            continue
        run_grid_for_stock(context, stock, total_value)


def get_current_target_position(stock):
    return g.base_position_per_stock * g.target_position_ratio


def run_grid_for_stock(context, stock, total_value):
    current_data = get_current_data()
    current_price = current_data[stock].day_open
    
    if current_price is None or current_price <= 0:
        return
    
    target_ratio = get_current_target_position(stock)
    stock_budget = total_value * target_ratio
    
    if not g.initialized[stock]:
        if g.market_state in ['WEAK', 'BEAR']:
            return
        
        init_cash = stock_budget * 0.5
        init_shares = calculate_shares(init_cash, current_price)
        
        if init_shares < 100:
            return
        
        actual_cost = init_shares * current_price * 1.001
        if context.portfolio.available_cash < actual_cost:
            return
        
        order(stock, init_shares)
        g.last_price[stock] = current_price
        g.initialized[stock] = True
        log.info('[%s] 建仓：%.2f × %d股' % (stock, current_price, init_shares))
        return
    
    grid_amount = stock_budget / g.grid_count
    
    cash = context.portfolio.available_cash
    position = context.portfolio.positions[stock]
    current_holdings = position.total_amount
    current_value = current_holdings * current_price
    
    last_price = g.last_price[stock]
    
    if current_price <= last_price * (1 - g.step):
        max_value = stock_budget * g.max_position_ratio
        if current_value >= max_value:
            g.last_price[stock] = current_price
            return
        
        buy_shares = calculate_shares(grid_amount, current_price)
        if buy_shares < 100:
            g.last_price[stock] = current_price
            return
        
        actual_cost = buy_shares * current_price * 1.001
        if cash >= actual_cost:
            order(stock, buy_shares)
            log.info('[%s] 买入：%.2f × %d股（跌%.1f%%）' % 
                     (stock, current_price, buy_shares, g.step*100))
            g.last_price[stock] = current_price
    
    elif current_price >= last_price * (1 + g.step):
        if current_value < grid_amount:
            g.last_price[stock] = current_price
            return
        
        sell_shares = calculate_shares(grid_amount, current_price)
        if sell_shares > 0 and current_holdings >= sell_shares:
            order(stock, -sell_shares)
            log.info('[%s] 卖出：%.2f × %d股（涨%.1f%%）' % 
                     (stock, current_price, sell_shares, g.step*100))
            g.last_price[stock] = current_price


def after_market_close(context):
    positions = context.portfolio.positions
    held_count = sum(1 for p in positions.values() if p.total_amount > 0)
    total_value = context.portfolio.total_value
    cash_ratio = context.portfolio.available_cash / total_value if total_value > 0 else 0
    
    log.info('收盘：总资产 %.2f，持仓 %d 只，现金占比 %.1f%%（市场%s 目标仓位%.0f%%）' % 
             (total_value, held_count, cash_ratio*100, g.market_state, g.target_position_ratio*100))
    log.info('##############################################################')
