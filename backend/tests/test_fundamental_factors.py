"""财务因子点时接入测试: 公告日门控 / 无数据 null 安全 / 双路径一致 / 历史累积同步。"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl

from app.backtest.fundamentals import (
    FUNDAMENTAL_FACTOR_NAMES,
    attach_fundamental_factors,
    build_fundamental_matrices,
    load_fundamental_snapshot,
)
from app.backtest.matrix import build_market_data_matrix


def _snapshot_frame(rows: list[dict]) -> pl.DataFrame:
    frame = pl.DataFrame({
        "period_end": ["2026-03-31"] * len(rows),
        "symbol": [r["symbol"] for r in rows],
        "announce_date": [r["announce"] for r in rows],
        "roe": [r.get("roe", 10.0) for r in rows],
        "bps": [r.get("bps", 5.0) for r in rows],
        "revenue_yoy": [r.get("revenue_yoy", 8.0) for r in rows],
    })
    return (
        frame.with_columns(
            pl.col("announce_date").str.slice(0, 10).str.to_date().alias("_announce")
        )
        .sort(["symbol", "_announce"])
    )


def _daily_panel(start: date, days: int, symbols: tuple[str, ...]) -> pl.DataFrame:
    rows = []
    for offset in range(days):
        for symbol in symbols:
            rows.append({
                "symbol": symbol,
                "date": start + timedelta(days=offset),
                "open": 10.0,
                "high": 10.5,
                "low": 9.5,
                "close": 10.0 + offset * 0.1,
                "volume": 1000.0,
            })
    return pl.DataFrame(rows).sort(["symbol", "date"])


def test_attach_gates_on_announce_date_strictly():
    panel = _daily_panel(date(2026, 4, 1), 10, ("600000.SH", "000001.SZ"))
    snapshot = _snapshot_frame([
        # 公告日 4-5: 4-5 当天不可用, 4-6 起 roe=20
        {"symbol": "600000.SH", "announce": "2026-04-05", "roe": 20.0, "bps": 4.0},
        # 无财务数据的标的
    ])
    attached = attach_fundamental_factors(panel, snapshot, ["roe_latest", "pb_latest"])

    values = attached.filter(pl.col("symbol") == "600000.SH").sort("date")
    roe = values["roe_latest"].to_list()
    assert roe[:5] == [None] * 5  # 4-1 ~ 4-5 均不可用 (含公告当日)
    assert roe[5:] == [20.0] * 5  # 4-6 起生效

    # 无财务数据标的全 null, 绝不填 0
    other = attached.filter(pl.col("symbol") == "000001.SZ")["roe_latest"]
    assert other.null_count() == other.len()

    # pb = close / bps, 公告前 null
    pb = values["pb_latest"].to_list()
    assert pb[:5] == [None] * 5
    close_6 = values.filter(pl.col("date") == date(2026, 4, 6))["close"].item()
    assert abs(pb[5] - close_6 / 4.0) < 1e-12


def test_attach_replaces_with_newer_announcement():
    panel = _daily_panel(date(2026, 4, 1), 20, ("600000.SH",))
    snapshot = _snapshot_frame([
        {"symbol": "600000.SH", "announce": "2026-04-05", "roe": 20.0},
        {"symbol": "600000.SH", "announce": "2026-04-15", "roe": 33.0},
    ])
    attached = attach_fundamental_factors(panel, snapshot, ["roe_latest"]).sort("date")
    roe = attached["roe_latest"].to_list()
    assert roe[4] is None            # 4-5 公告日
    assert roe[5] == 20.0            # 4-6 起 20.0
    assert roe[13] == 20.0           # 4-14
    assert roe[14] == 20.0           # 4-15 二次公告日: 新一期尚未生效, 仍保留上一期
    assert roe[15] == 33.0           # 4-16 起新公告生效


def test_attach_without_snapshot_keeps_null_columns():
    panel = _daily_panel(date(2026, 4, 1), 5, ("600000.SH",))
    attached = attach_fundamental_factors(panel, None, ["roe_latest", "pb_latest"])
    for name in ("roe_latest", "pb_latest"):
        assert name in attached.columns
        assert attached[name].null_count() == attached.height


def test_matrix_field_matches_polars_attach():
    panel = _daily_panel(date(2026, 4, 1), 12, ("600000.SH", "000001.SZ"))
    snapshot = _snapshot_frame([
        {"symbol": "600000.SH", "announce": "2026-04-05", "roe": 20.0, "bps": 4.0},
        {"symbol": "000001.SZ", "announce": "2026-04-08", "roe": -5.0, "bps": -1.0},
    ])
    attached = attach_fundamental_factors(panel, snapshot, ["roe_latest", "pb_latest"])
    market = build_market_data_matrix(panel)
    matrices = build_fundamental_matrices(market, snapshot, ["roe_latest", "pb_latest"])
    symbols = {s: i for i, s in enumerate(market.symbols)}
    dates = {str(d): t for t, d in enumerate(
        sorted({row["date"] for row in panel.iter_rows(named=True)})
    )}
    for name in ("roe_latest", "pb_latest"):
        matrix = matrices[name]
        for row in attached.iter_rows(named=True):
            expected = row[name]
            actual = matrix[dates[str(row["date"])], symbols[row["symbol"]]]
            if expected is None:
                assert np.isnan(actual), (name, row["date"], row["symbol"], actual)
            else:
                np.testing.assert_allclose(actual, expected, rtol=1e-6)


def test_matrix_field_matches_polars_attach_across_two_announcements():
    """换报告期时两条路径仍须一致: 新公告当日应保留上一期值(前向填充不断档)。"""
    panel = _daily_panel(date(2026, 4, 1), 20, ("600000.SH",))
    snapshot = _snapshot_frame([
        {"symbol": "600000.SH", "announce": "2026-04-05", "roe": 20.0},
        {"symbol": "600000.SH", "announce": "2026-04-15", "roe": 33.0},
    ])
    attached = attach_fundamental_factors(panel, snapshot, ["roe_latest"]).sort("date")
    market = build_market_data_matrix(panel)
    matrix = build_fundamental_matrices(market, snapshot, ["roe_latest"])["roe_latest"]
    column = market.symbols.index("600000.SH")
    for row_index, value in enumerate(attached["roe_latest"].to_list()):
        actual = matrix[row_index, column]
        if value is None:
            assert np.isnan(actual), (row_index, actual)
        else:
            np.testing.assert_allclose(actual, value, rtol=1e-6)


def test_matrix_field_clears_value_when_newer_report_lacks_metric():
    """新一期财报缺该指标时不得继续沿用上一期值, 否则同一行混用两期报告。

    矩阵路径逐列前向填充, 若跳过空值写入, 4-16 起 pb 已换到新期 bps=6,
    roe 却仍停在上一期的 20 —— polars 侧 join_asof 只认最新一期整行 (roe 为
    null), 两条路径给出不同的因子值。
    """
    panel = _daily_panel(date(2026, 4, 1), 20, ("600000.SH",))
    snapshot = _snapshot_frame([
        {"symbol": "600000.SH", "announce": "2026-04-05", "roe": 20.0, "bps": 4.0},
        {"symbol": "600000.SH", "announce": "2026-04-15", "roe": None, "bps": 6.0},
    ])
    attached = attach_fundamental_factors(panel, snapshot, ["roe_latest", "pb_latest"]).sort("date")
    market = build_market_data_matrix(panel)
    matrices = build_fundamental_matrices(market, snapshot, ["roe_latest", "pb_latest"])
    column = market.symbols.index("600000.SH")

    # polars 口径: 新公告生效 (4-16) 后 roe 无值, pb 走新一期 bps
    assert attached["roe_latest"].to_list()[15:] == [None] * 5
    assert all(value is not None for value in attached["pb_latest"].to_list()[15:])

    for name in ("roe_latest", "pb_latest"):
        for row_index, value in enumerate(attached[name].to_list()):
            actual = matrices[name][row_index, column]
            if value is None:
                assert np.isnan(actual), (name, row_index, actual)
            else:
                np.testing.assert_allclose(actual, value, rtol=1e-6)


def test_bps_nonpositive_gives_null_pb():
    panel = _daily_panel(date(2026, 4, 1), 8, ("000001.SZ",))
    snapshot = _snapshot_frame([
        {"symbol": "000001.SZ", "announce": "2026-04-02", "bps": -1.0},
    ])
    attached = attach_fundamental_factors(panel, snapshot, ["pb_latest"])
    assert attached["pb_latest"].null_count() == attached.height


def test_load_snapshot_from_missing_dir_returns_none(tmp_path: Path):
    assert load_fundamental_snapshot(tmp_path) is None
    assert load_fundamental_snapshot(None) is None


def test_snapshot_requires_announce_date(tmp_path: Path):
    out = tmp_path / "financials" / "metrics"
    out.mkdir(parents=True)
    pl.DataFrame({
        "symbol": ["600000.SH"],
        "announce_date": [None],
        "roe": [10.0],
        "gross_margin": [30.0],
        "net_margin": [5.0],
        "revenue_yoy": [8.0],
        "net_income_yoy": [6.0],
        "debt_to_asset_ratio": [40.0],
        "bps": [5.0],
    }).write_parquet(out / "part.parquet")
    # 公告日缺失的行无法做点时门控, 视为无有效快照
    assert load_fundamental_snapshot(tmp_path) is None


def test_fundamental_factor_names_are_catalogued():
    from app.backtest.factor import FACTOR_COLUMNS

    catalog_ids = {item["id"] for item in FACTOR_COLUMNS}
    assert catalog_ids >= FUNDAMENTAL_FACTOR_NAMES


def test_financial_sync_merges_history(tmp_path: Path):
    from app.services import financial_sync as fs

    old = pl.DataFrame({
        "symbol": ["600000.SH", "600000.SH"],
        "period_end": ["2025-09-30", "2025-12-31"],
        "announce_date": ["2025-10-28", "2026-01-20"],
        "roe": [8.0, 9.0],
    })
    latest = pl.DataFrame({
        "symbol": ["600000.SH", "000001.SZ"],
        "period_end": ["2026-03-31", "2026-03-31"],
        "announce_date": ["2026-04-25", "2026-04-24"],
        "roe": [10.0, 5.0],
    })
    merged = fs._merge_report_history(old, latest)
    assert merged.height == 4  # 旧各期保留 + 新一期并入
    # 同期修正: 旧 2025-12-31 公告 2026-01-20 vs 更晚的修正公告
    revised = pl.DataFrame({
        "symbol": ["600000.SH"],
        "period_end": ["2025-12-31"],
        "announce_date": ["2026-02-01"],
        "roe": [9.5],
    })
    merged2 = fs._merge_report_history(old, revised)
    row = merged2.filter(
        (pl.col("symbol") == "600000.SH") & (pl.col("period_end") == "2025-12-31")
    )
    assert row.height == 1
    assert row["roe"].item() == 9.5
    assert merged2.height == 2  # 修正不增加行数


def test_financial_sync_merge_unknown_announce_date_does_not_win():
    """公告日未知的旧行不得压过带公告日的新行。

    多源并存时旧行可能没有 announce_date (provider 不提供 / 上游缺该字段)。
    这类"公告日未知"的行若排在真实公告日之后, 逐列取最后一个非空值时反而胜出,
    合并结果会出现「announce_date 是新公告、数值仍是旧值」的自相矛盾行,
    点时因子据此在公告日之后放出的是修正前的数。
    """
    from app.services import financial_sync as fs

    revised = pl.DataFrame({
        "symbol": ["600000.SH"],
        "period_end": ["2025-12-31"],
        "announce_date": ["2026-02-01"],
        "roe": [9.5],
    })
    # 旧行有 announce_date 列但取值为空
    old_null = pl.DataFrame({
        "symbol": ["600000.SH"],
        "period_end": ["2025-12-31"],
        "announce_date": [None],
        "roe": [9.0],
    })
    row = fs._merge_report_history(old_null, revised).to_dicts()[0]
    assert row["announce_date"] == "2026-02-01"
    assert row["roe"] == 9.5

    # 旧帧整列缺失 (另一数据源不提供该字段) — 文档承诺"后写优先"
    old_missing = pl.DataFrame({
        "symbol": ["600000.SH"],
        "period_end": ["2025-12-31"],
        "roe": [9.0],
    })
    row = fs._merge_report_history(old_missing, revised).to_dicts()[0]
    assert row["announce_date"] == "2026-02-01"
    assert row["roe"] == 9.5


# ── A1/A2 扩充批次 (issue #2/#3) ────────────────────────────────

def test_pe_derived_from_pb_over_roe():
    """PE = (close/bps) / (roe/100); 亏损或 bps≤0 置 null; 双路径一致。"""
    panel = _daily_panel(date(2026, 4, 1), 10, ("600000.SH", "000001.SZ"))
    snapshot = _snapshot_frame([
        {"symbol": "600000.SH", "announce": "2026-04-05", "roe": 20.0, "bps": 4.0},
        {"symbol": "000001.SZ", "announce": "2026-04-05", "roe": -5.0, "bps": 4.0},
    ])
    names = ["pe_latest"]
    attached = attach_fundamental_factors(panel, snapshot, names).sort("date")
    pe = attached.filter(pl.col("symbol") == "600000.SH")["pe_latest"].to_list()
    assert pe[:5] == [None] * 5
    close_6 = attached.filter(
        (pl.col("symbol") == "600000.SH") & (pl.col("date") == date(2026, 4, 6)),
    )["close"].item()
    assert abs(pe[5] - (close_6 / 4.0) / 0.2) < 1e-9
    # 亏损股 PE 无意义 → null
    loss = attached.filter(pl.col("symbol") == "000001.SZ")["pe_latest"]
    assert loss.null_count() == loss.len()

    market = build_market_data_matrix(panel)
    matrices = build_fundamental_matrices(market, snapshot, names)
    symbols = {s: i for i, s in enumerate(market.symbols)}
    t6 = 5
    np.testing.assert_allclose(
        matrices["pe_latest"][t6, symbols["600000.SH"]],
        (close_6 / 4.0) / 0.2, rtol=1e-6,
    )
    assert np.isnan(matrices["pe_latest"][t6, symbols["000001.SZ"]])


def test_new_plain_column_factors_attach():
    """纯列新因子(roa/ocfps/净现比等)沿用同一门控与 null 语义。"""
    frame = _snapshot_frame([
        {"symbol": "600000.SH", "announce": "2026-04-05", "roe": 20.0, "bps": 4.0},
    ]).with_columns(
        pl.lit(5.5, dtype=pl.Float64).alias("roa"),
        pl.lit(1.2, dtype=pl.Float64).alias("ocfps"),
        pl.lit(130.0, dtype=pl.Float64).alias("net_profit_cash_content"),
    )
    panel = _daily_panel(date(2026, 4, 1), 8, ("600000.SH",))
    attached = attach_fundamental_factors(
        panel, frame, ["roa_latest", "ocfps_latest", "cash_content_latest"],
    ).sort("date")
    expected = {
        "roa_latest": 5.5, "ocfps_latest": 1.2, "cash_content_latest": 130.0,
    }
    for name, want in expected.items():
        values = attached[name].to_list()
        assert values[:5] == [None] * 5
        assert all(abs(v - want) < 1e-12 for v in values[5:])


def test_snapshot_missing_new_columns_degrades_to_null():
    """旧测试桩/旧缓存缺新列: 双路径优雅降级为 null, 不抛异常。"""
    panel = _daily_panel(date(2026, 4, 1), 6, ("600000.SH",))
    snapshot = _snapshot_frame([
        {"symbol": "600000.SH", "announce": "2026-04-05", "roe": 20.0, "bps": 4.0},
    ])  # 无 roa/ocfps/趋势列
    attached = attach_fundamental_factors(
        panel, snapshot, ["roa_latest", "roe_avg_4q", "pe_latest"],
    )
    for name in ("roa_latest", "roe_avg_4q"):
        series = attached[name]
        assert series.null_count() == series.len()
    market = build_market_data_matrix(panel)
    matrices = build_fundamental_matrices(market, snapshot, ["roa_latest", "roe_avg_4q"])
    assert np.isnan(matrices["roa_latest"]).all()
    assert np.isnan(matrices["roe_avg_4q"]).all()


def test_trend_columns_computed_on_period_series():
    """趋势列: 4期窗口均值 / 不足期 null / 跨 symbol 不串 / improving 对比4期前。"""
    from app.backtest.fundamentals import _add_trend_columns

    quarters = ["2025-06-30", "2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30"]
    rows = {
        "symbol": ["600000.SH"] * 5 + ["000001.SZ"] * 2,
        "period_end": quarters + ["2025-12-31", "2026-03-31"],
        "announce_date": ["2025-08-30", "2025-11-01", "2026-03-01", "2026-04-20", "2026-08-15",
                          "2026-03-05", "2026-04-25"],
        "roe": [10.0, 12.0, 11.0, 13.0, 14.0, 50.0, 51.0],
        "revenue_yoy": [5.0, 6.0, 4.0, 8.0, 10.0, 1.0, 2.0],
        "net_margin": [10.0, 11.0, 12.0, 13.0, 14.0, 30.0, 31.0],
        "eps_basic": [1.0, 1.1, 1.2, 1.3, 1.4, 2.0, 2.1],
    }
    out = _add_trend_columns(pl.DataFrame(rows))
    main = out.filter(pl.col("symbol") == "600000.SH").sort("period_end")
    avg4 = main["roe_avg_4q"].to_list()
    assert avg4[:3] == [None, None, None]          # 不足 4 期
    assert abs(avg4[3] - (10 + 12 + 11 + 13) / 4) < 1e-12
    assert abs(avg4[4] - (12 + 11 + 13 + 14) / 4) < 1e-12
    min8 = main["roe_min_8q"].to_list()
    assert min8[3] is None and min8[4] is None  # 窗口=8: 不足 8 期为 null
    improving = main["revenue_yoy_improving"].to_list()
    assert improving[3] is None                     # 第4期尚无"4期前"
    assert improving[4] == 1.0                      # 10.0 > 5.0 (4期前)
    margin_trend = main["net_margin_trend"].to_list()
    assert margin_trend[3] is None
    assert margin_trend[4] == 14.0 - 10.0          # 4期前 = 第1期(10.0)
    # 跨 symbol 不串: 另一只股票只有 2 期, 趋势列全 null
    other = out.filter(pl.col("symbol") == "000001.SZ")
    for col in ("roe_avg_4q", "revenue_yoy_improving", "net_margin_trend"):
        series = other[col]
        assert series.null_count() == series.len()


def test_trend_factor_pit_gated_on_announce():
    """趋势列沿公告日门控生效: 公告前 null, 生效后为该期趋势值。"""
    quarters = ["2025-06-30", "2025-09-30", "2025-12-31", "2026-03-31"]
    frame = pl.DataFrame({
        "symbol": ["600000.SH"] * 4,
        "period_end": quarters,
        "announce_date": ["2025-08-30", "2025-11-01", "2026-03-01", "2026-04-20"],
        "roe": [10.0, 12.0, 11.0, 13.0],
        "bps": [4.0] * 4,
        "revenue_yoy": [5.0, 6.0, 4.0, 8.0],
    }).with_columns(
        pl.col("announce_date").str.slice(0, 10).str.to_date().alias("_announce"),
    ).sort(["symbol", "_announce"])
    from app.backtest.fundamentals import _add_trend_columns
    snapshot = _add_trend_columns(frame).sort(["symbol", "_announce"])

    panel = _daily_panel(date(2026, 3, 25), 35, ("600000.SH",))
    attached = attach_fundamental_factors(panel, snapshot, ["roe_avg_4q"]).sort("date")
    values = attached["roe_avg_4q"].to_list()
    dates = attached["date"].to_list()
    idx_effective = dates.index(date(2026, 4, 21))  # 4-20 公告 → 次日起生效
    assert values[idx_effective - 1] is None
    assert abs(values[idx_effective] - (10 + 12 + 11 + 13) / 4) < 1e-12


def test_load_snapshot_includes_new_factor_columns(tmp_path: Path):
    """load 快照读取新因子列并预计算趋势列。"""
    out = tmp_path / "financials" / "metrics"
    out.mkdir(parents=True)
    quarters = ["2025-06-30", "2025-09-30", "2025-12-31", "2026-03-31"]
    pl.DataFrame({
        "symbol": ["600000.SH"] * 4,
        "period_end": quarters,
        "announce_date": ["2025-08-30", "2025-11-01", "2026-03-01", "2026-04-20"],
        "roe": [10.0, 12.0, 11.0, 13.0],
        "bps": [4.0] * 4,
        "revenue_yoy": [5.0, 6.0, 4.0, 8.0],
        "net_margin": [10.0, 11.0, 12.0, 13.0],
        "eps_basic": [1.0, 1.1, 1.2, 1.3],
        "roa": [3.0] * 4,
        "ocfps": [1.1] * 4,
        "net_profit_cash_content": [120.0] * 4,
        "operating_cash_to_revenue": [12.0] * 4,
        "current_ratio": [1.5] * 4,
        "quick_ratio": [1.0] * 4,
        "long_term_debt_equity_ratio": [20.0] * 4,
        "total_assets_growth_ratio": [8.0] * 4,
        "eps_diluted": [1.0] * 4,
    }).write_parquet(out / "part.parquet")
    snapshot = load_fundamental_snapshot(tmp_path)
    assert snapshot is not None
    for col in ("roa", "ocfps", "roe_avg_4q", "roe_min_8q", "net_margin_trend"):
        assert col in snapshot.columns
    last = snapshot.filter(pl.col("symbol") == "600000.SH").sort("_announce").row(-1, named=True)
    assert abs(last["roe_avg_4q"] - (10 + 12 + 11 + 13) / 4) < 1e-12
    # 只有 4 期: "对比4期前"类趋势尚无值 (需第 5 期)
    assert last["net_margin_trend"] is None
    assert last["eps_trend"] is None
