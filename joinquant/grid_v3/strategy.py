# 导入函数库
from jqdata import *

# 初始化函数，设定基准等等
def initialize(context):
    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    log.info('网格交易策略初始化（v3：熊市清仓）')

    # 手续费：买入佣金万分之三，卖出佣金万分之三+千分之一印花税，最低5元
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003,
                             close_commission=0.0003, min_commission=5), type='stock')

    # 全局变量：操作的股票（平安银行）
    g.security = '000001.XSHE'
    # 大盘指数（沪深300）
    g.index_code = '000300.XSHG'

    # ========== 网格参数 ==========
    g.step = 0.02          # 网格间距 2%
    g.grid_amount = 10000  # 每格交易金额（元）
    g.last_price = None    # 上一次触发交易时的价格；None 表示需要重建底仓

    # ========== 大盘过滤参数 ==========
    g.N = 20               # 使用20日均线作为过滤条件
    g.index_ma = None      # 暂存当天的均线值（用于日志）

    # 运行函数
    run_daily(before_market_open, time='before_open', reference_security='000300.XSHG')
    run_daily(market_open, time='open', reference_security='000300.XSHG')
    run_daily(after_market_close, time='after_close', reference_security='000300.XSHG')


def before_market_open(context):
    log.info('开盘前运行：' + str(context.current_dt.time()))


def market_open(context):
    log.info('开盘时运行：' + str(context.current_dt.time()))
    security = g.security
    index_code = g.index_code

    # ------------------------------
    # 第一步：大盘过滤判断（无未来函数）
    # ------------------------------
    index_close_data = get_bars(index_code, count=g.N+1, unit='1d', fields=['close'])
    if len(index_close_data) < g.N+1:
        log.warning('指数数据不足，跳过今天的交易')
        return

    index_yesterday_close = index_close_data['close'][-1]
    index_ma = index_close_data['close'][:-1].mean()
    g.index_ma = index_ma

    # v3 改动：大盘转熊时清仓，并重置 last_price
    if index_yesterday_close <= index_ma:
        log.info("大盘转熊：沪深300昨日收盘 %.2f <= %.2f（%d日均线）"
                 % (index_yesterday_close, index_ma, g.N))
        closeable = context.portfolio.positions[security].closeable_amount
        if closeable > 0:
            order_target(security, 0)
            g.last_price = None  # 清仓后重置，下次转牛时重建底仓
            log.info("熊市清仓：卖出 %d 股，等待大盘回到均线上方" % closeable)
        else:
            log.info("已无持仓，继续等待")
        return
    else:
        log.info("大盘允许交易：沪深300昨日收盘 %.2f > %.2f（%d日均线）"
                 % (index_yesterday_close, index_ma, g.N))

    # ------------------------------
    # 第二步：网格交易主逻辑
    # ------------------------------
    current_price = get_current_data()[security].day_open
    if current_price is None:
        bars = get_bars(security, count=1, unit='1d', fields=['close'], include_now=True)
        current_price = bars['close'][-1]

    # 首次运行 或 清仓后重入：建立底仓
    if g.last_price is None:
        total_asset = context.portfolio.total_value
        init_cash = total_asset * 0.5
        order_value(security, init_cash)
        g.last_price = current_price
        log.info('建立底仓：价格 %.2f，投入 %.2f 元' % (current_price, init_cash))
        return

    cash = context.portfolio.available_cash
    position = context.portfolio.positions[security]
    current_holdings = position.total_amount
    current_value = current_holdings * current_price

    # 向下触发买入（价格下跌 ≥ 一个网格间距）
    if current_price <= g.last_price * (1 - g.step):
        if cash >= g.grid_amount:
            order_value(security, g.grid_amount)
            g.last_price = current_price
            log.info('网格买入触发：价格 %.2f（较上次 %.2f 下跌 %.1f%%），买入 %.2f 元' %
                     (current_price, g.last_price/(1-g.step), g.step*100, g.grid_amount))
        else:
            log.warning('现金不足，无法买入一格（需要 %.2f 元，剩余 %.2f 元）' % (g.grid_amount, cash))

    # 向上触发卖出（价格上涨 ≥ 一个网格间距）
    elif current_price >= g.last_price * (1 + g.step):
        if current_value >= g.grid_amount:
            sell_shares = int(g.grid_amount / current_price)
            if sell_shares > 0 and current_holdings >= sell_shares:
                order(security, -sell_shares)
                g.last_price = current_price
                log.info('网格卖出触发：价格 %.2f（较上次 %.2f 上涨 %.1f%%），卖出 %.2f 元（%d 股）' %
                         (current_price, g.last_price/(1+g.step), g.step*100, g.grid_amount, sell_shares))
        else:
            log.warning('持仓市值不足，无法卖出一格（需要 %.2f 元，持仓市值 %.2f 元）' % (g.grid_amount, current_value))


def after_market_close(context):
    log.info('收盘后运行：' + str(context.current_dt.time()))
    trades = get_trades()
    for _trade in trades.values():
        log.info('成交记录：' + str(_trade))
    log.info('一天结束')
    log.info('##############################################################')
