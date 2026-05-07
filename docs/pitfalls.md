# 踩坑记录

按时间倒序。每次遇到让结果出乎意料、或调试花了超过 10 分钟的问题，记在这里。

格式：
```
## YYYY-MM-DD — 标题（一句话描述）
**现象**：我看到了什么
**原因**：为什么会这样
**解决**：怎么修的
**教训**：下次注意什么
```

---

## 2026-05-07 — akshare 东财源在 WSL 下经常连接被拒

**现象**：`ak.stock_zh_a_hist()` 报 `ConnectionError: Remote end closed connection without response`，但 `curl --noproxy '*'` 直接访问该 URL 偶尔能通、偶尔也不通。

**原因**：东财 API 对 Python `requests` 的 TLS 指纹敏感，且本身有限流/WAF。WSL 继承了宿主的 Clash 代理（`HTTP_PROXY / HTTPS_PROXY / ALL_PROXY`），代理对境内数据源反而造成干扰。

**解决**：
1. 切换到新浪源 `ak.stock_zh_a_daily()`，稳定性好很多。
2. 在 `utils/data_loader.py` 启动时把 proxy env 清空（保留 `QR_KEEP_PROXY=1` 开关）。

**教训**：
- akshare 有多个后端，不同函数调不同数据源。遇到连接问题先换函数，而不是折腾网络配置。
- WSL 的代理对境内金融 API 帮倒忙，在数据层入口统一清掉最省心。

---

## 2026-05-07 — 新浪源的股票代码格式与聚宽不同

**现象**：直接把聚宽的 `"000001.XSHE"` 传给 `ak.stock_zh_a_daily()` 报错。

**原因**：新浪源要求 `"sz000001"`（深交所加 sz 前缀）或 `"sh600519"`（上交所加 sh 前缀）。

**解决**：`data_loader._to_sina_code()` 根据首字符自动判断交易所并加前缀。

**教训**：不同平台的股票代码格式是个长期摩擦点，统一在数据层转换，策略层只用 6 位数字代码。

---

## 2026-05-07 — GBK 编码导致 CSV 在 GitHub 上乱码

**现象**：聚宽导出的 `result_1.csv` 在 GitHub 网页端显示乱码。

**原因**：聚宽 CSV 是 GBK 编码，GitHub 默认 UTF-8 渲染。

**解决**：入库时用 `iconv -f gbk -t utf-8` 转换，只存 UTF-8 版本。

**教训**：境内金融平台导出文件几乎都是 GBK，入库第一步先转码。

---

## 2026-05-07 — mplfinance 中文标题乱码

**现象**：K 线图标题里的中文变成方块（"□□ 60 □□□□"）。

**原因**：matplotlib 默认字体 DejaVu Sans 不含 CJK 字形。

**解决**：改用英文标题（简单） 或 安装 Noto CJK 字体后设置 `plt.rcParams["font.family"]`（完整解法）。

**教训**：Linux 上用 matplotlib 做中文图表，要么装 `fonts-noto-cjk`（`sudo apt install fonts-noto-cjk`），要么坚持英文标题。
