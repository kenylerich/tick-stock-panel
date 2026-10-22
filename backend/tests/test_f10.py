"""F10 经营数据代理 (issue #5/#6): 字段标准化 / 桥不可达降级 / 助手工具契约。"""
from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import f10 as f10_api
from app.custom.assistant import tools as assistant_tools


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    app.include_router(f10_api.router)
    return TestClient(app)


def _zygc_payload() -> dict[str, Any]:
    return {
        "symbol": "600519.SH",
        "rows": [
            {
                "股票代码": "600519", "报告日期": "2026-06-30", "分类类型": "按产品分类",
                "主营构成": "茅台酒", "主营收入": 7.77e10, "收入比例": 0.8569,
                "主营成本": 6.0e9, "成本比例": 0.6334, "主营利润": 7.17e10,
                "利润比例": 0.8829, "毛利率": 0.9228,
            },
            {
                "股票代码": "600519", "报告日期": "2026-06-30", "分类类型": "按地区分类",
                "主营构成": "国内", "主营收入": 9.0e10, "收入比例": 0.99,
                "主营成本": 9.5e9, "成本比例": 0.99, "主营利润": 8.0e10,
                "利润比例": 0.99, "毛利率": 0.889,
            },
            {
                "股票代码": "600519", "报告日期": "2025-06-30", "分类类型": "按产品分类",
                "主营构成": "茅台酒(旧期)", "主营收入": 6.0e10, "收入比例": 0.85,
                "毛利率": 0.91,
            },
        ],
        "count": 3,
    }


def test_zygc_normalizes_and_orders_desc(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(path: str) -> dict[str, Any]:
        return _zygc_payload()

    monkeypatch.setattr(f10_api, "_bridge_get", fake)
    resp = client.get("/api/f10/zygc/600519.SH")
    assert resp.status_code == 200
    body = resp.json()
    assert body["latest_date"] == "2026-06-30"
    assert [p["report_date"] for p in body["periods"]] == ["2026-06-30", "2025-06-30"]
    item = body["periods"][0]["items"][0]
    assert item["name"] == "茅台酒"
    assert item["category"] == "按产品分类"
    assert abs(item["gross_margin"] - 0.9228) < 1e-9


def test_bridge_unreachable_maps_to_503_with_hint(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """真实 _bridge_get 路径: httpx 连接失败 → 503 + 启动提示 (不打桩 _bridge_get,
    否则绕过了被测的异常转换层)。"""
    class _RefusedClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None: ...
        async def __aenter__(self) -> _RefusedClient:
            return self
        async def __aexit__(self, *args: Any) -> None: ...
        async def get(self, url: str) -> Any:
            raise httpx.ConnectError("refused")

    monkeypatch.setattr(f10_api.httpx, "AsyncClient", _RefusedClient)
    resp = client.get("/api/f10/zygc/600519.SH")
    assert resp.status_code == 503
    assert "akshare-bridge" in resp.json()["detail"]


async def test_assistant_get_company_f10_tool(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """助手工具: 三段聚合 + zygc 只取最新期 + 桥失败走错误契约。"""
    from fastapi import HTTPException

    async def fake(path: str) -> dict[str, Any]:
        if path.startswith("/f10/zygc"):
            return _zygc_payload()
        if path.startswith("/f10/profile"):
            return {"symbol": "600519.SH", "profile": {
                "公司名称": "贵州茅台", "主营业务": "茅台酒生产销售",
                "所属行业": "酒、饮料和精制茶制造业", "无关字段": "x",
            }}
        return {"symbol": "600519.SH", "industry": "白酒", "degraded": True, "peers": []}

    monkeypatch.setattr(f10_api, "_bridge_get", fake)
    ctx = assistant_tools.ToolContext.build(data_dir=tmp_path)

    payload = await assistant_tools.execute_assistant_tool(
        "get_company_f10", {"symbol": "600519.SH"}, ctx,
    )
    result = payload["result"]
    assert payload["ok"] is True
    assert result["zygc"]["latest_date"] == "2026-06-30"
    assert all(i["report_date"] != "2025-06-30" for i in result["zygc"]["items"])
    assert result["profile"]["主营业务"] == "茅台酒生产销售"
    assert "无关字段" not in result["profile"]
    assert result["peers"]["industry"] == "白酒" and result["peers"]["degraded"] is True

    # 分段查询
    payload2 = await assistant_tools.execute_assistant_tool(
        "get_company_f10", {"symbol": "600519.SH", "section": "peers"}, ctx,
    )
    assert payload2["ok"] is True and "zygc" not in payload2["result"]

    # 桥不可达: HTTPException 503 → 工具错误契约 ok=False
    async def unreachable(path: str) -> dict[str, Any]:
        raise HTTPException(503, "AKShare 数据桥不可达")

    monkeypatch.setattr(f10_api, "_bridge_get", unreachable)
    payload3 = await assistant_tools.execute_assistant_tool(
        "get_company_f10", {"symbol": "600519.SH"}, ctx,
    )
    assert payload3["ok"] is False
    assert "不可达" in payload3["error"]


def test_summarize_get_company_f10() -> None:
    summary = assistant_tools.summarize_tool_result("get_company_f10", {
        "ok": True,
        "result": {
            "zygc": {"latest_date": "2026-06-30", "items": [{"name": "a"}]},
            "peers": {"industry": "白酒", "degraded": False, "list": [{"symbol": "1"}, {"symbol": "2"}]},
        },
    })
    assert "主营构成 2026-06-30 1 项" in summary
    assert "行业「白酒」同行 2 只" in summary
