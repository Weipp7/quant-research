# quant-research

A 股个人量化研究项目（渐进式搭建）。

## 当前阶段

Phase 1 末尾 — 已在聚宽跑出双均线 + 两个网格策略变体，正在收尾观察笔记。下一步进入 Phase 2（本地数据仓 + 回测引擎）。

## 目录说明

- `joinquant/` — 聚宽云端跑过的策略归档（代码 / 截图 / 指标 / 观察）
- `design-20260424.md` — 项目早期设计文档（office-hours 产出）
- `eng-review-test-plan-20260424.md` — 配套的工程评审 + 测试计划

## 技术栈（计划）

- Python 3
- 回测平台：聚宽（已用） → 后续 Phase 2 起本地化（akshare + duckdb）
- Phase 3 本地回测引擎：`backtrader` 或自写循环

## 状态

WIP — Phase 1 策略产出已归档，本地化工作未开始。
