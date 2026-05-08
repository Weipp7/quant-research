# -*- coding: utf-8 -*-
"""
网格策略 V1 - 基线版（多股票扩展）

版本说明：
- 这是网格策略系列的起点版本
- 5股+5ETF的混合标的池在后面版本中演化
- 此版本：10只个股 + 大盘MA20过滤
- 注意：order_value存在取整bug（在v1_fixed中修复）

回测结果（2015-01-01 ~ 2024-12-31, 10万本金）：
- 总收益: 88.03%
- 年化收益: 6.71%
- 最大回撤: 27.31%
- 夏普比率: 0.213
- 胜率: 73.0%
- 盈亏比: 3.76
- 最大回撤区间: 2021/02 - 2022/10

适用场景：作为后续版本对比的基准
已知问题：order_value导致下单数量略有偏差；高价股(茅台/平安)建仓金额不足
"""

# 导入函数库
from jqdata import *

# 初始化函数
def initialize(context):
    set_benchmark('000300.XSHG')
    set_option('use_real_price', True)
    log.info('多股票网格交易策略 V1（基线版）')

    # 手续费
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, 
                             close_commission=0.0003, min_commission=5), type='stock')
    set_slippage(PriceRelatedSlippage(0.001))

    # 股票池
    g.stock_pool = [
        '000001.XSHE',  # 平安银行
        '600036.XSHG',  # 招商银行
        '601318.XSHG',  # 中国平安
        '600519.XSHG',  # 贵州茅台
        '000858.XSHE',  # 五粮液
        '600900.XSHG',  # 长江电力
        '601088.XSHG',  # 中国神华
        '600028.XSHG',  # 中国石化
        '601857.XSHG',  # 中国石油
        '600276.XSHG',  # 恒瑞医药
    ]
    
    g.index_code = '000300.XSHG'

    # 网格参数
    g.step = 0.03
    g.position_per_stock = 0.10
    g.grid_count = 5
    g.max_position_ratio = 1.5

    # 状态记录
    g.last_price = {}
    g.initialized = {}
    
    for stock in g.stock_pool:
        g.last_price[stock] = None
        g.initialized[stock] = False

    # 大盘过滤
    g.N = 20

    run_daily(before_market_open, time='before_open', reference_security='000300.XSHG')
    run_daily(market_open, time='open', reference_security='000300.XSHG')
    run_daily(after_market_close, time='after_close', reference_security='000300.XSHG')


def before_market_open(context):
    log.info('========== ' + str(context.current_dt.date()) + ' ==========')


def check_market_filter(context):
    """大盘过滤：HS300是否在MA20上方"""
    bars = get_bars(g.index_code, count=g.N+1, unit='1d', fields=['close'])
    if len(bars) < g.N+1:
        return False, 0, 0
    
    yesterday_close = bars['close'][-1]
    ma = bars['close'][:-1].mean()
    
    return yesterday_close > ma, yesterday_close, ma


def is_tradable(context, stock):
    """可交易性检查"""
    current_data = get_current_data()
    
    if current_data[stock].paused:
        return False, '停牌'
    
    day_open = current_data[stock].day_open
    high_limit = current_data[stock].high_limit
    low_limit = current_data[stock].low_limit
    
    if day_open >= high_limit:
        return False, '一字涨停'
    if day_open <= low_limit:
        return False, '一字跌停'
    
    return True, 'OK'


def market_open(context):
    is_bull, idx_close, idx_ma = check_market_filter(context)
    
    if not is_bull:
        log.info("大盘过滤：HS300 %.2f <= MA20 %.2f，今日不交易" % (idx_close, idx_ma))
        return
    
    log.info("大盘过滤：HS300 %.2f > MA20 %.2f" % (idx_close, idx_ma))

    total_value = context.portfolio.total_value
    
    for stock in g.stock_pool:
        tradable, reason = is_tradable(context, stock)
        if not tradable:
            continue
        
        run_grid_for_stock(context, stock, total_value)


def run_grid_for_stock(context, stock, total_value):
    current_data = get_current_data()
    current_price = current_data[stock].day_open
    
    if current_price is None or current_price <= 0:
        return
    
    # 首次建仓
    if not g.initialized[stock]:
        stock_budget = total_value * g.position_per_stock
        init_cash = stock_budget * 0.5
        
        if context.portfolio.available_cash < init_cash:
            return
        
        order_value(stock, init_cash)  # 注意：此处有取整bug，v1_fixed修复
        g.last_price[stock] = current_price
        g.initialized[stock] = True
        log.info('[%s] 建立底仓：价格 %.2f，投入 %.2f 元' % (stock, current_price, init_cash))
        return
    
    # 网格交易
    stock_budget = total_value * g.position_per_stock
    grid_amount = stock_budget / g.grid_count
    
    cash = context.portfolio.available_cash
    position = context.portfolio.positions[stock]
    current_holdings = position.total_amount
    current_value = current_holdings * current_price
    
    last_price = g.last_price[stock]
    
    if current_price <= last_price * (1 - g.step):
        if current_value >= stock_budget * g.max_position_ratio:
            g.last_price[stock] = current_price
            return
        
        if cash >= grid_amount:
            order_value(stock, grid_amount)
            log.info('[%s] 买入：%.2f 元（跌%.1f%%）' % (stock, grid_amount, g.step*100))
            g.last_price[stock] = current_price
    
    elif current_price >= last_price * (1 + g.step):
        if current_value < grid_amount:
            g.last_price[stock] = current_price
            return
        
        sell_shares = int(grid_amount / current_price / 100) * 100
        if sell_shares > 0 and current_holdings >= sell_shares:
            order(stock, -sell_shares)
            log.info('[%s] 卖出：%d 股（涨%.1f%%）' % (stock, sell_shares, g.step*100))
            g.last_price[stock] = current_price


def after_market_close(context):
    positions = context.portfolio.positions
    held_count = sum(1 for p in positions.values() if p.total_amount > 0)
    log.info('收盘：总资产 %.2f，持仓 %d 只' % (context.portfolio.total_value, held_count))
    log.info('##############################################################')
