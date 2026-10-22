"""F10 经营数据代理 (issue #5/#6): 主营构成 / 公司概况 / 同行清单。

数据来自 AKShare 桥侧车容器 (docker compose service `akshare-bridge`,
见 bridge/main.py)。本模块只做: 代理 + 字段标准化 + 桥不可达时的
优雅降级 (503 + 明确提示), 不做任何落盘 — F10 数据按财报季更新,
由前端按需拉取即可; 需要历史留痕时走扩展表拉取配方。

桥地址: 环境变量 AKSHARE_BRIDGE_URL 覆盖, 默认容器网络名
(dev 模式下本机跑桥时设为 http://127.0.0.1:3020)。
"""
from __future__ import annotations

import os
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/f10", tags=["f10"])

_BRIDGE_TIMEOUT_S = 30.0


def _bridge_url() -> str:
    return os.environ.get("AKSHARE_BRIDGE_URL", "http://akshare-bridge:3020").rstrip("/")


async def _bridge_get(path: str) -> dict[str, Any]:
    url = f"{_bridge_url()}{path}"
    try:
        async with httpx.AsyncClient(timeout=_BRIDGE_TIMEOUT_S) as client:
            resp = await client.get(url)
    except httpx.HTTPError as exc:
        raise HTTPException(
            503,
            f"AKShare 数据桥不可达 ({exc.__class__.__name__}) — "
            "请确认 akshare-bridge 容器已启动 (docker compose up -d akshare-bridge)",
        ) from exc
    if resp.status_code == 404:
        raise HTTPException(404, resp.json().get("detail", "无数据"))
    if resp.status_code >= 400:
        raise HTTPException(502, f"数据桥上游失败: {resp.text[:200]}")
    return resp.json()


# 东财主营构成列 → 标准化字段 (数值比例统一 ×100 转百分比口径展示由前端处理,
# 这里保持原值 + 明确字段名, 避免双处换算)。
_ZYGC_COLUMN_MAP: dict[str, str] = {
    "报告日期": "report_date",
    "分类类型": "category",
    "主营构成": "name",
    "主营收入": "revenue",
    "收入比例": "revenue_ratio",
    "主营成本": "cost",
    "成本比例": "cost_ratio",
    "主营利润": "profit",
    "利润比例": "profit_ratio",
    "毛利率": "gross_margin",
}


def _normalize_zygc(payload: dict[str, Any]) -> dict[str, Any]:
    periods: dict[str, list[dict[str, Any]]] = {}
    for row in payload.get("rows") or []:
        item: dict[str, Any] = {}
        for src, dst in _ZYGC_COLUMN_MAP.items():
            if src in row:
                item[dst] = row.get(src)
        date = str(item.get("report_date") or "")
        if not date or not item.get("name"):
            continue
        periods.setdefault(date, []).append(item)
    ordered = sorted(periods.items(), reverse=True)
    return {
        "symbol": payload.get("symbol"),
        "latest_date": ordered[0][0] if ordered else None,
        "periods": [
            {"report_date": date, "items": items} for date, items in ordered
        ],
    }


@router.get("/zygc/{symbol}")
async def main_business_composition(symbol: str) -> dict:
    """主营构成: 分产品/分地区/分行业收入与毛利率, 按报告期倒序。"""
    payload = await _bridge_get(f"/f10/zygc/{symbol}")
    return _normalize_zygc(payload)


@router.get("/profile/{symbol}")
async def company_profile(symbol: str) -> dict:
    """公司概况: 主营业务全文/所属行业/上市日期等 (巨潮源)。"""
    return await _bridge_get(f"/f10/profile/{symbol}")


@router.get("/peers/{symbol}")
async def industry_peers(symbol: str) -> dict:
    """同行清单: 所属行业 + 同行业成分股 (成付认知不稳时降级为行业名)。"""
    return await _bridge_get(f"/f10/peers/{symbol}")
