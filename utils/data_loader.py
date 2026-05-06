"""DuckDB + akshare 日线数据访问层。

设计文档纪律:
- 模块负责"和外部数据源/数据库打交道"的脏活, notebook 只做探索。
- 所有写入用 INSERT OR REPLACE, 重跑幂等。
- adjust 字段写进主键, 同一只股票的 qfq/hfq/raw 可并存。

数据源:
- 当前使用 akshare 的新浪后端 (`stock_zh_a_daily`)。
- 之前试过东财 (`stock_zh_a_hist`) 多次连接被对端关闭, 切换到新浪后稳定。
  日后若新浪也不稳, 可改写为多源 fallback。

聚宽与 akshare 代码差异:
- 聚宽: "000001.XSHE" / "600519.XSHG"
- 新浪 (akshare): "sz000001" / "sh600519"
本模块对外仅接受 6 位数字代码, 内部根据首位字符决定交易所前缀。
"""

from __future__ import annotations

import os
from pathlib import Path

# WSL 默认会继承 Windows 宿主的代理(HTTP_PROXY/ALL_PROXY 等)。akshare 调用的
# 财经数据源(新浪/东财/...)都在境内,直连可达,走代理反而经常超时或被拒。
# 默认把 proxy 相关 env 清掉;用户若坚持要走代理,可在脚本前设 QR_KEEP_PROXY=1。
if not os.environ.get("QR_KEEP_PROXY"):
    for _k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
               "http_proxy", "https_proxy", "all_proxy"):
        os.environ.pop(_k, None)

import duckdb
import pandas as pd

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "a_stocks.duckdb"

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS daily_bars (
    symbol   VARCHAR NOT NULL,
    date     DATE    NOT NULL,
    adjust   VARCHAR NOT NULL,   -- 'qfq' | 'hfq' | 'raw'
    open     DOUBLE,
    high     DOUBLE,
    low      DOUBLE,
    close    DOUBLE,
    volume   DOUBLE,             -- 成交量(股, 新浪为 float)
    amount   DOUBLE,             -- 成交额(元)
    turnover DOUBLE,             -- 换手率(decimal, 0.01 = 1%)
    PRIMARY KEY (symbol, date, adjust)
);
"""


def _to_sina_code(symbol: str) -> str:
    if not symbol or not symbol[0].isdigit() or len(symbol) != 6:
        raise ValueError(f"expected 6-digit numeric symbol, got {symbol!r}")
    head = symbol[0]
    if head == "6":
        return "sh" + symbol
    if head in ("0", "3"):
        return "sz" + symbol
    if head in ("4", "8"):
        return "bj" + symbol
    raise ValueError(f"unknown exchange prefix for symbol {symbol!r}")


def _connect(db_path: Path | str = DEFAULT_DB_PATH) -> duckdb.DuckDBPyConnection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(db_path))
    conn.execute(_SCHEMA_SQL)
    return conn


def download_daily(
    symbol: str,
    start: str,
    end: str,
    adjust: str = "qfq",
    db_path: Path | str = DEFAULT_DB_PATH,
) -> int:
    """从 akshare(新浪源) 拉取日线 K 线并写入 DuckDB。

    Args:
        symbol: 6 位股票代码, 如 "000001"
        start: "YYYY-MM-DD"
        end:   "YYYY-MM-DD"
        adjust: "qfq" 前复权 / "hfq" 后复权 / "raw" 不复权
        db_path: DuckDB 文件路径

    Returns:
        写入的行数 (该范围内已有的会先删除再插入, 总是新版本)。
    """
    import akshare as ak

    sina_adjust = "" if adjust == "raw" else adjust
    df = ak.stock_zh_a_daily(
        symbol=_to_sina_code(symbol),
        start_date=start.replace("-", ""),
        end_date=end.replace("-", ""),
        adjust=sina_adjust,
    )
    if df.empty:
        return 0

    df = df.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["symbol"] = symbol
    df["adjust"] = adjust

    cols = [
        "symbol", "date", "adjust",
        "open", "high", "low", "close",
        "volume", "amount", "turnover",
    ]
    df = df[cols]

    with _connect(db_path) as conn:
        conn.register("staging", df)
        conn.execute(
            "DELETE FROM daily_bars WHERE symbol = ? AND adjust = ? "
            "AND date BETWEEN ? AND ?",
            [symbol, adjust, df["date"].min(), df["date"].max()],
        )
        conn.execute("INSERT INTO daily_bars SELECT * FROM staging")
    return len(df)


def load_daily(
    symbol: str,
    start: str | None = None,
    end: str | None = None,
    adjust: str = "qfq",
    db_path: Path | str = DEFAULT_DB_PATH,
) -> pd.DataFrame:
    """从 DuckDB 读出日线, 返回按日期升序的 DataFrame, date 列为索引。"""
    sql = "SELECT * FROM daily_bars WHERE symbol = ? AND adjust = ?"
    params: list = [symbol, adjust]
    if start:
        sql += " AND date >= ?"
        params.append(start)
    if end:
        sql += " AND date <= ?"
        params.append(end)
    sql += " ORDER BY date"

    with _connect(db_path) as conn:
        df = conn.execute(sql, params).df()
    if not df.empty:
        df = df.set_index("date")
    return df
