"""
cidah_mcp_bridge.py — CIDAH MCP Bridge (SSE · mcp SDK רשמי)
"""
from __future__ import annotations
import logging, os, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from dotenv import load_dotenv
load_dotenv("setup/.env")

import anyio
import mcp.types as types
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.routing import Route, Mount
import uvicorn

log = logging.getLogger("cidah_bridge")
logging.basicConfig(level=logging.INFO)

LILACH_WORKSPACE = "wrkspc_01KN44oHJcxSPRyojkG8DeBV"
VALID_ROUTES = [
    "mechanical","fast_lane","legal_draft","legal_research",
    "email","meili","scrape","crawl","summarize","analyze","incognito_lite",
]

server = Server("cidah-brain")

@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="cidah_ping",
            description="בדוק שה-bridge חי ושה-CIDAH brain מאותחל.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        types.Tool(
            name="cidah_routes",
            description="קבל את רשימת הנתיבים הזמינים.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        types.Tool(
            name="cidah_call",
            description=(
                "שלח בקשה למוח CIDAH. "
                "route: mechanical|fast_lane|legal_draft|legal_research|"
                "email|meili|scrape|crawl|summarize|analyze|incognito_lite"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "route":  {"type": "string"},
                    "prompt": {"type": "string"},
                },
                "required": ["route", "prompt"],
            },
        ),
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "cidah_ping":
        try:
            from core.claude_master import get_master
            master = get_master()
            text = (
                f"✅ CIDAH bridge · {len(master.workspaces)} workspaces loaded\n"
                f"Lilach workspace: {LILACH_WORKSPACE}\n"
                f"Routes: {len(VALID_ROUTES)} active"
            )
        except Exception as e:
            text = f"❌ bridge error: {e}"

    elif name == "cidah_routes":
        info = {
            "mechanical": "שאלות קצרות · Haiku 4",
            "fast_lane":  "מהיר · incognito_lite · Haiku 4",
            "legal_draft": "טיוטות משפטיות עם letterhead",
            "legal_research": "מחקר משפטי · Opus 4",
            "email":      "Gmail OAuth",
            "meili":      "חיפוש זיכרון פנימי",
            "scrape":     "חילוץ מדף אינטרנט",
            "crawl":      "סריקת אתר",
            "summarize":  "סיכום מסמך",
            "analyze":    "ניתוח מסמך",
            "incognito_lite": "מצב פרטי · ללא auto-memory",
        }
        text = "\n".join(f"• `{r}` — {d}" for r, d in info.items())

    elif name == "cidah_call":
        route  = arguments.get("route", "")
        prompt = arguments.get("prompt", "")
        if route not in VALID_ROUTES:
            text = f"❌ route לא חוקי: {route}"
        else:
            try:
                from core.claude_master import get_master
                master = get_master()
                result = master.call(route=route, prompt=prompt,
                                     workspace_id=LILACH_WORKSPACE)
                text = result.content if hasattr(result, "content") else str(result)
            except Exception as e:
                text = f"❌ שגיאה: {e}"
    else:
        text = f"❌ tool לא מוכר: {name}"

    return [types.TextContent(type="text", text=text)]


def make_app() -> Starlette:
    sse = SseServerTransport("/messages/")

    async def handle_sse(request):
        async with sse.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await server.run(streams[0], streams[1],
                             server.create_initialization_options())

    return Starlette(routes=[
        Route("/sse", endpoint=handle_sse),
        Mount("/messages/", app=sse.handle_post_message),
    ])


if __name__ == "__main__":
    host = os.getenv("BRIDGE_HOST", "0.0.0.0")
    port = int(os.getenv("BRIDGE_PORT", "8765"))
    log.info(f"CIDAH MCP Bridge (SSE) → http://{host}:{port}/sse")
    uvicorn.run(make_app(), host=host, port=port)
