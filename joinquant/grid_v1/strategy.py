# 导入函数库
from jqdata import *

# 初始化函数，设定基准等等
def initialize(context):
    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    # 输出内容到日志
    log.info('网格交易策略初始化')

    # 手续费：买入佣金万分之三，卖出佣金万分之三+千分之一印花税，最低5元
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, 
                             close_commission=0.0003, min_commission=5), type='stock')

    # 全局变量：操作的股票（平安银行）
    g.security = '000001.XSHE'

    # ========== 网格参数设置 ==========
    g.step = 0.02          # 网格间距 2%（价格每波动2%触发一次交易）
    g.grid_amount = 10000  # 每格交易的金额（单位：元），可根据总资金调整
    g.last_price = None    # 上一次触发交易时的价格（用于判断是否越过网格）

    # 运行函数
    run_daily(before_market_open, time='before_open', reference_security='000300.XSHG')
    run_daily(market_open, time='open', reference_security='000300.XSHG')
    run_daily(after_market_close, time='after_close', reference_security='000300.XSHG')


## 开盘前运行函数
def before_market_open(context):
    log.info('函数运行时间(before_market_open)：'+str(context.current_dt.time()))
    # 可在此处发送提醒或初始化其他数据


## 核心交易函数（每天开盘时执行）
def market_open(context):
    log.info('函数运行时间(market_open):'+str(context.current_dt.time()))
    security = g.security

    # 获取最近5个交易日的收盘价（主要为了得到最新价）
    close_data = get_bars(security, count=1, unit='1d', fields=['close'], include_now=True)
    current_price = close_data['close'][-1]   # 当前最新价格

    # 如果还没有基准价（首次运行），用当前价格建立初始头寸
    if g.last_price is None:
        # 初始建仓：投入总资金的一半，建立底仓
        total_asset = context.portfolio.total_value
        init_cash = total_asset * 0.5
        order_value(security, init_cash)
        g.last_price = current_price
        log.info('首次运行，建立底仓：价格%.2f，投入%.2f元' % (current_price, init_cash))
        return

    # 获取当前现金和持仓数量
    cash = context.portfolio.available_cash
    position = context.portfolio.positions[security]
    current_holdings = position.total_amount          # 持有股数
    current_value = current_holdings * current_price  # 持仓市值

    # 判断是否向下触发买入（价格下跌超过一个网格间距）
    if current_price <= g.last_price * (1 - g.step):
        # 买入一格（固定金额）
        if cash >= g.grid_amount:
            order_value(security, g.grid_amount)
            g.last_price = current_price   # 更新触发价格
            log.info('网格买入触发：价格%.2f（较上次%.2f下跌%.2f%%），买入%.2f元' % 
                     (current_price, g.last_price, g.step*100, g.grid_amount))
        else:
            log.warning('现金不足，无法买入一格（需要%.2f元，剩余%.2f元）' % (g.grid_amount, cash))

    # 判断是否向上触发卖出（价格上涨超过一个网格间距）
    elif current_price >= g.last_price * (1 + g.step):
        # 卖出一格（固定金额）
        if current_value >= g.grid_amount:
            sell_shares = int(g.grid_amount / current_price)   # 换算成股数
            if sell_shares > 0 and current_holdings >= sell_shares:
                order(security, -sell_shares)   # 卖出
                g.last_price = current_price
                log.info('网格卖出触发：价格%.2f（较上次%.2f上涨%.2f%%），卖出%.2f元（%d股）' % 
                         (current_price, g.last_price, g.step*100, g.grid_amount, sell_shares))
        else:
            log.warning('持仓市值不足，无法卖出一格（需要%.2f元，持仓市值%.2f元）' % (g.grid_amount, current_value))


## 收盘后运行函数
def after_market_close(context):
    log.info('函数运行时间(after_market_close):'+str(context.current_dt.time()))
    # 输出当天成交记录
    trades = get_trades()
    for _trade in trades.values():
        log.info('成交记录：'+str(_trade))
    log.info('一天结束')
    log.info('##############################################################')