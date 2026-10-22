# AKShare 免费数据桥 — 主营构成 / 公司概况 / 同行清单 (issue #4/#5/#6)
#
# 定位: 面板扶摇数据源没有 F10 经营类数据(主营构成/主营业务/同行),
# 本桥把 AKShare 聚合的公开数据(东方财富/巨潮资讯 F10)转成简单 JSON,
# 供面板扩展表拉取配方 / AI 助手调用。设计取舍:
# - 无状态 + 进程内 TTL 缓存: F10 数据按财报季更新, 缓存 12h 对上游友好;
# - 上游接口失败返回 502 + 错误信息, 不伪装成空数据;
# - 同行成付认知上游端点不稳(东财板块接口偶发拒绝), 降级返回行业名;
# - 只读, 不落盘, 崩溃不影响面板主容器(独立 compose service, 可插拔)。
#
# 实测备注 (2026-10-21):
# - stock_zygc_em 需要 SH/SZ 前缀格式 (SH600519), 裸代码报 'zygcfx' 键错;
# - 公司概况用巨潮 stock_profile_cninfo (含主营业务全文), 东财个股信息
#   与同花顺主营介绍端点当前不稳定, 已弃用/降级。
from __future__ import annotations

import time
from typing import Any

import akshare as ak
from fastapi import FastAPI, HTTPException

app = FastAPI(title="tsp-akshare-bridge", docs_url="/docs")

_CACHE: dict[str, tuple[float, Any]] = {}
_TTL_S = 12 * 3600  # F10 类数据财报季才变, 12h 缓存足够


def _cached(key: str, producer):
    hit = _CACHE.get(key)
    if hit and time.monotonic() - hit[0] < _TTL_S:
        return hit[1]
    value = producer()
    _CACHE[key] = (time.monotonic(), value)
    return value


def _em_prefixed(symbol: str) -> str:
    """600519.SH → SH600519 (东财主营构成接口要求的前缀格式)。"""
    code, _, suffix = symbol.partition(".")
    if suffix:
        return f"{suffix.upper()}{code}"
    # 无后缀: 按代码规则推断 (6/9/5 开头沪市, 其余深市)
    return f"SH{code}" if code.startswith(("6", "9", "5")) else f"SZ{code}"


def _bare(symbol: str) -> str:
    return symbol.split(".")[0]


def _df_records(df) -> list[dict[str, Any]]:
    if df is None or df.empty:
        return []
    return df.replace("", None).to_dict(orient="records")


@app.get("/health")
def health() -> dict:
    return {"ok": True, "cache_entries": len(_CACHE)}


@app.get("/f10/zygc/{symbol}")
def main_business_composition(symbol: str) -> dict:
    """主营构成(东财 F10): 分产品/分地区/分行业的收入/成本/毛利率拆解。

    返回按报告期倒序的全部期数; 调用方(扩展表配方/AI)自行取最新期。
    """
    try:
        df = _cached(
            f"zygc:{symbol}",
            lambda: ak.stock_zygc_em(symbol=_em_prefixed(symbol)),
        )
    except Exception as exc:  # noqa: BLE001 — 上游任意异常都收敛为 502
        raise HTTPException(502, f"AKShare 主营构成拉取失败: {exc}") from exc
    records = _df_records(df)
    if not records:
        raise HTTPException(404, f"{symbol} 无主营构成数据")
    return {"symbol": symbol, "rows": records, "count": len(records)}


@app.get("/f10/profile/{symbol}")
def company_profile(symbol: str) -> dict:
    """公司概况(巨潮资讯): 主营业务全文/所属行业/上市日期/注册资本等。"""
    def load() -> dict:
        rows = _df_records(ak.stock_profile_cninfo(symbol=_bare(symbol)))
        if not rows:
            raise ValueError(f"{symbol} 无公司概况数据")
        return {k: v for k, v in rows[0].items() if v not in (None, "")}

    try:
        data = _cached(f"profile:{symbol}", load)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"AKShare 公司概况拉取失败: {exc}") from exc
    return {"symbol": symbol, "profile": data}


@app.get("/f10/peers/{symbol}")
def industry_peers(symbol: str, limit: int = 30) -> dict:
    """同行清单: 巨潮所属行业 + 尽力取同行业成股份(东财板块接口不稳时降级)。

    成分获取失败不报错: 返回 industry + peers=[] + degraded=true,
    调用方(AI)仍可用行业名走本地因子数据做行业对比。
    """
    def load():
        rows = _df_records(ak.stock_profile_cninfo(symbol=_bare(symbol)))
        if not rows:
            raise ValueError(f"{symbol} 无公司概况数据")
        industry = str(rows[0].get("所属行业") or "").strip()
        if not industry:
            raise ValueError("未取到所属行业")
        peers: list[dict[str, Any]] = []
        degraded = False
        try:
            cons = _df_records(ak.stock_board_industry_cons_em(symbol=industry))
            for row in cons[: max(1, min(limit, 100))]:
                code = str(row.get("代码") or "")
                if not code:
                    continue
                suffix = ".SH" if code.startswith(("6", "9", "5")) else ".SZ"
                peers.append({"symbol": code + suffix, "name": row.get("名称")})
        except Exception:  # noqa: BLE001, S110 — 板块端点不稳, 降级
            degraded = True
        return industry, peers, degraded

    try:
        industry, peers, degraded = _cached(f"peers:{symbol}", load)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"AKShare 同行清单拉取失败: {exc}") from exc
    return {
        "symbol": symbol, "industry": industry, "peers": peers,
        "count": len(peers), "degraded": degraded,
    }
