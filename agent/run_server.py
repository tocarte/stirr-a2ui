#!/usr/bin/env python3
# Copyright 2025 STIRR / Thinking Media
# Licensed under the Apache License, Version 2.0

"""
STIRR Content Agent — A2A server + simple /query endpoint for demo.

Run: uv run python run_server.py [--port 10002]
Port: 10002 (default)
"""

import json
import logging
import os
import re
from pathlib import Path

import click
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Route, Mount

# Load .env: STIRR_AGENT_ENV overrides path, else agent/.env
_env_file = os.getenv("STIRR_AGENT_ENV") or Path(__file__).parent / ".env"
load_dotenv(_env_file)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Require VODLIX credentials at startup — fail fast with clear message
def _require_vodlix():
    user = os.getenv("VODLIX_USERNAME", "").strip()
    pwd = os.getenv("VODLIX_PASSWORD", "").strip()
    if not user or not pwd:
        print("ERROR: VODLIX credentials required. Set in agent/.env:")
        print("  VODLIX_USERNAME=your-email")
        print("  VODLIX_PASSWORD=your-password")
        print("  (Copy from .env.example if needed)")
        raise SystemExit(1)

# Minimal tool context for direct tool calls (tools don't use state)
class _ToolContext:
    state = {}


def _dispatch_query(query: str) -> dict:
    """Dispatch query to tools, return structured response for demo UI."""
    from tools import get_breaking_news, get_chapters, search_content

    ctx = _ToolContext()
    q = query.lower().strip()

    # 1. Breaking news from Dallas
    if "breaking news" in q or "news" in q and ("dallas" in q or "from" in q):
        loc = "Dallas"
        if "from" in q:
            m = re.search(r"from\s+(\w+)", q, re.I)
            if m:
                loc = m.group(1)
        raw = get_breaking_news(loc, ctx, limit=5)
        data = json.loads(raw)
        return {"type": "NewsAlertBanner", "data": data}

    # 2. Chapters for documentary
    if "chapter" in q or "documentary" in q:
        raw = get_chapters("Documentary", ctx)
        data = json.loads(raw)
        return {"type": "ChapterNav", "data": data}

    # 3. Something to watch / content search
    # Use broad discovery term for generic "something to watch" queries; "tonight" returns few results
    if "tonight" in q and ("watch" in q or "something" in q):
        search_q = "movies"  # "tonight" rarely appears in metadata
    elif "watch" in q and "something" in q:
        search_q = "movies"
    else:
        search_q = query or "movies"
    raw = search_content(search_q, ctx, limit=10)
    data = json.loads(raw)
    return {"type": "ContentShelf", "data": data}


async def simple_query(request):
    """POST /query — simple endpoint for demo frontend."""
    body = await request.json()
    query = body.get("query", "")
    if not query:
        return JSONResponse({"error": "query required"}, status_code=400)
    try:
        result = _dispatch_query(query)
        return JSONResponse(result)
    except Exception as e:
        logger.exception("Query failed")
        return JSONResponse({"error": str(e)}, status_code=500)


async def news_search(request):
    """POST /news-search — Search news by topic (e.g. when user clicks a headline)."""
    market = ""
    query = ""
    if request.method == "POST":
        try:
            body = await request.json()
            market = (body.get("market") or "").strip()
            query = (body.get("query") or "").strip()
        except Exception:
            pass
    if not market:
        market = (request.query_params.get("market") or "").strip()
    if not query:
        query = (request.query_params.get("query") or "").strip()
    if not query:
        return JSONResponse({"error": "query required", "headlines": [], "summary": ""}, status_code=400)
    if not market:
        market = "Albany, NY"  # default
    try:
        from tools import fetch_news_search

        data = fetch_news_search(query, market, limit=3)
        return JSONResponse(data)
    except Exception as e:
        logger.exception("News search failed")
        return JSONResponse({"error": str(e), "headlines": [], "summary": ""}, status_code=500)


async def match_headline_to_segment_handler(request):
    """POST /match-headline-to-segment — P4-H12d: Match headline to transcript chunk for seek-to-moment."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    headline = (body.get("headline") or "").strip()
    chunks = body.get("chunks") or []
    if not headline:
        return JSONResponse({"error": "headline required"}, status_code=400)
    if not isinstance(chunks, list):
        return JSONResponse({"error": "chunks must be array of {start_ms, text}"}, status_code=400)
    try:
        from tools import match_headline_to_segment
        data = match_headline_to_segment(headline, chunks)
        return JSONResponse(data)
    except Exception as e:
        logger.exception("Match headline failed")
        return JSONResponse({"error": str(e), "start_ms": None}, status_code=500)


async def video_by_id(request):
    """GET /video?video_id=123 — P4-F2: Fetch VODLIX video by ID; return ContentShelf item (play_url, hls_url)."""
    video_id = (request.query_params.get("video_id") or request.query_params.get("id") or "").strip()
    if not video_id:
        return JSONResponse({"error": "video_id required (e.g. ?video_id=123)"}, status_code=400)
    try:
        from tools import fetch_video_by_id
        data = fetch_video_by_id(video_id)
        if data.get("error") and "not found" in str(data.get("error", "")).lower():
            return JSONResponse(data, status_code=404)
        return JSONResponse(data)
    except Exception as e:
        logger.exception("Video by ID failed")
        return JSONResponse({"error": str(e), "id": video_id}, status_code=500)


async def weather_widget(request):
    """GET/POST /weather — P4-H12b: Streaming Intelligence weather widget. location param required."""
    location = ""
    if request.method == "POST":
        try:
            body = await request.json()
            location = (body.get("location") or "").strip()
        except Exception:
            pass
    if not location:
        location = (request.query_params.get("location") or "").strip()
    if not location:
        return JSONResponse({"error": "location required (e.g. Albany, NY)"}, status_code=400)
    try:
        from tools import fetch_weather_widget
        data = fetch_weather_widget(location)
        return JSONResponse(data)
    except Exception as e:
        logger.exception("Weather widget failed")
        return JSONResponse({"error": str(e), "location": location}, status_code=500)


async def traffic_widget(request):
    """GET/POST /traffic — P4-H12b: Streaming Intelligence traffic widget. location param required."""
    location = ""
    if request.method == "POST":
        try:
            body = await request.json()
            location = (body.get("location") or "").strip()
        except Exception:
            pass
    if not location:
        location = (request.query_params.get("location") or "").strip()
    if not location:
        return JSONResponse({"error": "location required (e.g. Albany, NY)"}, status_code=400)
    try:
        from tools import fetch_traffic_widget
        data = fetch_traffic_widget(location)
        return JSONResponse(data)
    except Exception as e:
        logger.exception("Traffic widget failed")
        return JSONResponse({"error": str(e), "location": location}, status_code=500)


async def finance_widget(request):
    """GET/POST /finance — P4-H12b: Streaming Intelligence finance widget. query param (ticker or company name) required."""
    query = ""
    if request.method == "POST":
        try:
            body = await request.json()
            query = (body.get("query") or body.get("symbol") or "").strip()
        except Exception:
            pass
    if not query:
        query = (request.query_params.get("query") or request.query_params.get("symbol") or "").strip()
    if not query:
        return JSONResponse({"error": "query required (e.g. AAPL or Tesla)"}, status_code=400)
    try:
        from tools import fetch_finance_widget
        data = fetch_finance_widget(query)
        return JSONResponse(data)
    except Exception as e:
        logger.exception("Finance widget failed")
        return JSONResponse({"error": str(e), "query": query}, status_code=500)


async def breaking_news(request):
    """POST /breaking-news — P4-H12e: Fetch breaking news headlines for a market. Preload chat on station select."""
    market = ""
    if request.method == "POST":
        try:
            body = await request.json()
            market = (body.get("market") or "").strip()
        except Exception:
            pass
    if not market:
        market = (request.query_params.get("market") or "").strip()
    if not market:
        return JSONResponse({"error": "market required (e.g. Albany, NY)"}, status_code=400)
    try:
        from tools import fetch_breaking_news_headlines

        data = fetch_breaking_news_headlines(market, limit=5)
        return JSONResponse(data)
    except Exception as e:
        logger.exception("Breaking news failed")
        return JSONResponse({"error": str(e), "headlines": [], "summary": ""}, status_code=500)


async def moments_respond(request):
    """POST /moments/respond — STIRR Moments Engine MVP. Accepts normalized perception from rolling buffer."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    try:
        from tools import moments_respond as moments_tool

        raw = moments_tool(body)
        data = json.loads(raw)
        if "error" in data:
            return JSONResponse(data, status_code=400)
        return JSONResponse(data)
    except Exception as e:
        logger.exception("Moments respond failed")
        return JSONResponse({"error": str(e)}, status_code=500)


async def ask_about_video(request):
    """POST /ask-about-video — Phase 2/3: answer question about playing video. P4-H5: ocr_onscreen_text. P4-H5b: vision_local. Transcript from textTracks."""
    body = await request.json()
    video_id = body.get("video_id", "")
    question = body.get("question", "")
    ocr_onscreen_text = body.get("ocr_onscreen_text")
    vision_local = body.get("vision_local")
    frame_image_base64 = body.get("frame_image_base64")
    transcript_local = body.get("transcript_local")
    last_assistant_message = body.get("last_assistant_message")
    ad_break_state = body.get("ad_break_state")
    if not video_id or not question:
        return JSONResponse(
            {"error": "video_id and question required"},
            status_code=400,
        )
    try:
        from tools import ask_about_video as ask_tool

        ctx = _ToolContext()
        raw = ask_tool(
            str(video_id),
            question,
            ctx,
            ocr_onscreen_text=ocr_onscreen_text,
            vision_local=vision_local,
            frame_image_base64=frame_image_base64,
            transcript_local=transcript_local,
            last_assistant_message=last_assistant_message,
            ad_break_state=ad_break_state,
        )
        data = json.loads(raw)
        return JSONResponse({"type": "Answer", "data": data})
    except Exception as e:
        logger.exception("Ask about video failed")
        return JSONResponse({"error": str(e)}, status_code=500)


@click.command()
@click.option("--host", default="0.0.0.0")
@click.option("--port", default=10002)
@click.option("--query-only", is_flag=True, help="Only run /query endpoint (no A2A, no GEMINI needed)")
def main(host: str, port: int, query_only: bool):
    _require_vodlix()
    if not query_only and not os.getenv("GEMINI_API_KEY"):
        logger.error("GEMINI_API_KEY required for full A2A server. Use --query-only for tools-only demo.")
        raise SystemExit(1)

    if query_only:
        from starlette.applications import Starlette
        from starlette.routing import Route
        app = Starlette(routes=[
            Route("/query", simple_query, methods=["POST"]),
            Route("/moments/respond", moments_respond, methods=["POST"]),
        Route("/v1/moments/respond", moments_respond, methods=["POST"]),
            Route("/ask-about-video", ask_about_video, methods=["POST"]),
            Route("/breaking-news", breaking_news, methods=["POST", "GET"]),
            Route("/news-search", news_search, methods=["POST", "GET"]),
            Route("/weather", weather_widget, methods=["POST", "GET"]),
            Route("/traffic", traffic_widget, methods=["POST", "GET"]),
            Route("/finance", finance_widget, methods=["POST", "GET"]),
            Route("/video", video_by_id, methods=["GET"]),
            Route("/match-headline-to-segment", match_headline_to_segment_handler, methods=["POST"]),
        ])
        app.add_middleware(
            CORSMiddleware,
            allow_origin_regex=r"http://localhost:\d+",
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        import uvicorn
        logger.info(f"STIRR /query only on http://{host}:{port}")
        uvicorn.run(app, host=host, port=port)
        return

    from a2a.server.apps import A2AStarletteApplication
    from a2a.server.request_handlers import DefaultRequestHandler
    from a2a.server.tasks import InMemoryTaskStore

    from agent_executor import StirrContentAgentExecutor
    from stirr_content_agent import StirrContentAgent

    base_url = f"http://localhost:{port}"
    ui_agent = StirrContentAgent(base_url=base_url, use_ui=True)
    text_agent = StirrContentAgent(base_url=base_url, use_ui=False)
    executor = StirrContentAgentExecutor(ui_agent, text_agent)

    request_handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=InMemoryTaskStore(),
    )
    server = A2AStarletteApplication(
        agent_card=ui_agent.get_agent_card(),
        http_handler=request_handler,
    )
    app = server.build()

    # Add simple /query and /ask-about-video endpoints for demo (no A2A protocol)
    app.add_route("/query", simple_query, methods=["POST"])
    app.add_route("/moments/respond", moments_respond, methods=["POST"])
    app.add_route("/v1/moments/respond", moments_respond, methods=["POST"])
    app.add_route("/ask-about-video", ask_about_video, methods=["POST"])
    app.add_route("/breaking-news", breaking_news, methods=["POST", "GET"])
    app.add_route("/news-search", news_search, methods=["POST", "GET"])
    app.add_route("/weather", weather_widget, methods=["POST", "GET"])
    app.add_route("/traffic", traffic_widget, methods=["POST", "GET"])
    app.add_route("/finance", finance_widget, methods=["POST", "GET"])
    app.add_route("/video", video_by_id, methods=["GET"])
    app.add_route("/match-headline-to-segment", match_headline_to_segment_handler, methods=["POST"])

    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"http://localhost:\d+",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    import uvicorn
    logger.info(f"STIRR Content Agent on http://{host}:{port} (A2A + POST /query)")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
