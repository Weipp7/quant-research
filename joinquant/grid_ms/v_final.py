# -*- coding: utf-8 -*-
"""
网格策略 V-Final - 网格框架的稳态最终版

版本说明：
- 这是网格策略系列的"交付版本"
- 设计原则：简洁、稳健、10万资金可用
- 5股+5ETF混合池，全部价格<50元
- 大盘MA20过滤，3%固定网格间距
- 不再追求高收益，作为底层配置工具

预期回测表现（待回测确认）：
- 总收益: 60-80%
- 年化收益: 6-7%
- 最大回撤: 20-25%
- 夏普比率: 0.2-0.3

设计哲学：
- 网格策略不创造alpha，只是分批吃震荡和趋势
- 接受网格的天花板，把它当作配置工具
- 想突破10%年化要走多因子路径
"""

from jqdata import *


def initialize(context):
    set_benchmark('000300.XSHG')
    set_option('use_real_price', True)
    log.info('网格策略 V-Final：稳态版（10万资金 / 5股+5ETF混合）')

    # 双手续费设置
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, 
                             close_commission=0.0003, min_commission=5), type='stock')
    set_order_cost(OrderCost(close_tax=0,
                             open_commission=0.0003, 
                             close_commission=0.0003, 
                             min_commission=5), type='fund')
    set_slippage(PriceRelatedSlippage(0.001))

    # 标的池：5股 + 5ETF
    g.stocks = [
        '000001.XSHE',  # 平安银行
        '600036.XSHG',  # 招商银行
        '600900.XSHG',  # 长江电力
        '601088.XSHG',  # 中国神华
        '600276.XSHG',  # 恒瑞医药
    ]
    
    g.etfs = [
        '510300.XSHG',  # 沪深300ETF
        '510500.XSHG',  # 中证500ETF
        '510880.XSHG',  # 红利ETF
        '518880.XSHG',  # 黄金ETF
        '513100.XSHG',  # 纳指ETF
    ]
    
    g.stock_pool = g.stocks + g.etfs
    g.index_code = '000300.XSHG'

    # 网格参数
    g.step = 0.03
    g.position_per_stock = 0.10
    g.grid_count = 5
    g.max_position_ratio = 1.5

    # 大盘过滤
    g.index_ma_days = 20
    
    # 状态记录
    g.last_price = {}
    g.initialized = {}
    
    for stock in g.stock_pool:
        g.last_price[stock] = None
        g.initialized[stock] = False

    run_daily(before_market_open, time='before_open', reference_security='000300.XSHG')
    run_daily(market_open, time='open', reference_security='000300.XSHG')
    run_daily(after_market_close, time='after_close', reference_security='000300.XSHG')


def calculate_shares(amount, price):
    """计算100整数倍手数"""
    if price <= 0:
        return 0
    return int(amount / price / 100) * 100


def before_market_open(context):
    log.info('========== %s ==========' % context.current_dt.date())


def check_market_filter(context):
    """大盘MA20过滤"""
    bars = get_bars(g.index_code, count=g.index_ma_days+1, unit='1d', fields=['close'])
    if len(bars) < g.index_ma_days+1:
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
    """开盘主逻辑"""
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
    """单股网格逻辑"""
    current_data = get_current_data()
    current_price = current_data[stock].day_open
    
    if current_price is None or current_price <= 0:
        return
    
    # 首次建仓
    if not g.initialized[stock]:
        stock_budget = total_value * g.position_per_stock
        init_cash = stock_budget * 0.5
        
        init_shares = calculate_shares(init_cash, current_price)
        if init_shares < 100:
            log.info('[%s] 建仓金额不足一手' % stock)
            return
        
        actual_cost = init_shares * current_price * 1.001
        if context.portfolio.available_cash < actual_cost:
            return
        
        order(stock, init_shares)
        g.last_price[stock] = current_price
        g.initialized[stock] = True
        log.info('[%s] 建仓：%.2f × %d股 = %.2f' %
                 (stock, current_price, init_shares, init_shares * current_price))
        return
    
    # 网格交易
    stock_budget = total_value * g.position_per_stock
    grid_amount = stock_budget / g.grid_count
    
    cash = context.portfolio.available_cash
    position = context.portfolio.positions[stock]
    current_holdings = position.total_amount
    current_value = current_holdings * current_price
    
    last_price = g.last_price[stock]
    
    # 向下买入
    if current_price <= last_price * (1 - g.step):
        if current_value >= stock_budget * g.max_position_ratio:
            g.last_price[stock] = current_price
            return
        
        buy_shares = calculate_shares(grid_amount, current_price)
        if buy_shares < 100:
            g.last_price[stock] = current_price
            return
        
        actual_cost = buy_shares * current_price * 1.001
        if cash >= actual_cost:
            order(stock, buy_shares)
            log.info('[%s] 买入：%.2f × %d股 = %.2f（跌%.1f%%）' %
                     (stock, current_price, buy_shares, buy_shares * current_price, g.step*100))
            g.last_price[stock] = current_price
    
    # 向上卖出
    elif current_price >= last_price * (1 + g.step):
        if current_value < grid_amount:
            g.last_price[stock] = current_price
            return
        
        sell_shares = calculate_shares(grid_amount, current_price)
        if sell_shares > 0 and current_holdings >= sell_shares:
            order(stock, -sell_shares)
            log.info('[%s] 卖出：%.2f × %d股 = %.2f（涨%.1f%%）' %
                     (stock, current_price, sell_shares, sell_shares * current_price, g.step*100))
            g.last_price[stock] = current_price


def after_market_close(context):
    positions = context.portfolio.positions
    held_count = sum(1 for p in positions.values() if p.total_amount > 0)
    total_value = context.portfolio.total_value
    cash_ratio = context.portfolio.available_cash / total_value if total_value > 0 else 0
    
    log.info('收盘：总资产 %.2f，持仓 %d 只，现金占比 %.1f%%' % 
             (total_value, held_count, cash_ratio*100))
    log.info('##############################################################')
