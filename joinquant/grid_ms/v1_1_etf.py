# -*- coding: utf-8 -*-
"""
网格策略 V1.1-ETF - 股票池替换为全ETF

版本说明：
- 用ETF替代个股，降低单边下跌风险
- ETF无印花税，单次往返成本从0.16%降到0.06%
- 选了10只ETF：宽基(4) + 行业(3) + 红利(1) + 黄金(1) + 海外(1)

回测结果（2015-01-01 ~ 2024-12-31, 10万本金）：
- 总收益: 25.47%（远低于V1）
- 年化收益: 2.36%
- 最大回撤: 18.89%（改善）
- 夏普比率: -0.177

教训：ETF天然低波动，对网格策略反而是劣势
- 网格依赖波动赚钱，ETF稀释了波动
- 创业板ETF、酒ETF等仍有2021后单边下跌问题
- 部分ETF成立晚，早期数据不全

后续衍生：v1_2_etf_atr 加入动态网格间距
"""

from jqdata import *

def initialize(context):
    set_benchmark('000300.XSHG')
    set_option('use_real_price', True)
    log.info('网格策略 V1.1：ETF组合替代个股')

    # ETF手续费（无印花税）
    set_order_cost(OrderCost(close_tax=0,
                             open_commission=0.0003, 
                             close_commission=0.0003, 
                             min_commission=5), type='fund')
    set_slippage(PriceRelatedSlippage(0.001))

    g.stock_pool = [
        '510300.XSHG',  # 沪深300ETF
        '510500.XSHG',  # 中证500ETF
        '159915.XSHE',  # 创业板ETF
        '510050.XSHG',  # 上证50ETF
        '510880.XSHG',  # 红利ETF
        '512880.XSHG',  # 证券ETF
        '512690.XSHG',  # 酒ETF
        '512660.XSHG',  # 军工ETF
        '518880.XSHG',  # 黄金ETF
        '513100.XSHG',  # 纳指ETF
    ]
    
    g.index_code = '000300.XSHG'

    g.step = 0.03
    g.position_per_stock = 0.10
    g.grid_count = 5
    g.max_position_ratio = 1.5
    g.index_ma_days = 20
    
    g.last_price = {}
    g.initialized = {}
    
    for stock in g.stock_pool:
        g.last_price[stock] = None
        g.initialized[stock] = False

    run_daily(before_market_open, time='before_open', reference_security='000300.XSHG')
    run_daily(market_open, time='open', reference_security='000300.XSHG')
    run_daily(after_market_close, time='after_close', reference_security='000300.XSHG')


def before_market_open(context):
    log.info('========== %s ==========' % context.current_dt.date())


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
    """检查ETF是否已上市"""
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
    
    if not g.initialized[stock]:
        stock_budget = total_value * g.position_per_stock
        init_cash = stock_budget * 0.5
        
        if context.portfolio.available_cash < init_cash:
            return
        
        order_value(stock, init_cash)
        g.last_price[stock] = current_price
        g.initialized[stock] = True
        log.info('[%s] 建仓：%.3f，投入 %.2f 元' % (stock, current_price, init_cash))
        return
    
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
            log.info('[%s] 买入：%.3f（跌%.1f%%），%.2f元' %
                     (stock, current_price, g.step*100, grid_amount))
            g.last_price[stock] = current_price
    
    elif current_price >= last_price * (1 + g.step):
        if current_value < grid_amount:
            g.last_price[stock] = current_price
            return
        
        sell_shares = int(grid_amount / current_price / 100) * 100
        if sell_shares > 0 and current_holdings >= sell_shares:
            order(stock, -sell_shares)
            log.info('[%s] 卖出：%.3f（涨%.1f%%），%d份' %
                     (stock, current_price, g.step*100, sell_shares))
            g.last_price[stock] = current_price


def after_market_close(context):
    positions = context.portfolio.positions
    held_count = sum(1 for p in positions.values() if p.total_amount > 0)
    log.info('收盘：总资产 %.2f，持仓 %d 只' % (context.portfolio.total_value, held_count))
    log.info('##############################################################')
