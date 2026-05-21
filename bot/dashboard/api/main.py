from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Query, Response
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis

from bot.config import get_settings
from bot.dashboard.api.owner import router as owner_router
from bot.dashboard.api.scraper import router as scraper_router
from bot.dashboard.api.routers import auth_router
from bot.dashboard.api.routers.admin import router as admin_router
from bot.dashboard.api.routers.admin_automation import router as admin_automation_router
from bot.dashboard.api.routers.admin_summaries import router as admin_summaries_router
from bot.dashboard.api.routers.agents import router as agents_router
from bot.dashboard.api.routers.faq import router as faq_router
from bot.dashboard.api.routers.messaging import router as messaging_router
from bot.dashboard.api.routers.subscription import router as subscription_router
from bot.dashboard.api.routers.group_subscriptions import router as group_subscription_router
from bot.dashboard.api.routers.auth_boundary import router as auth_boundary_router
from bot.dashboard.api.routers.internal import router as internal_router
from bot.dashboard.api.middleware.rate_limit import RateLimitMiddleware
from bot.db.bootstrap import ensure_schema
from bot.db.session import engine, get_session
from bot.agents.session import shutdown_client_pool


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    if settings.run_schema_bootstrap:
        await ensure_schema(engine)
    yield
    await shutdown_client_pool()
    await engine.dispose()
    redis = getattr(app.state, "redis", None)
    if redis is not None:
        await redis.aclose()


app = FastAPI(title="ModBot Dashboard API", version="1.1.0", lifespan=lifespan)

settings = get_settings()
app.state.redis = Redis.from_url(settings.redis_url, decode_responses=True)
cors_origins = [
    origin for origin in [
        settings.dashboard_url,
        settings.webapp_url,
        settings.admin_webapp_url,
        settings.agents_webapp_url,
    ] if origin
] or [
    "http://localhost:5173",
    "http://localhost:5174",
    "http://localhost:5175",
    "http://localhost:5176",
    "http://localhost:5177",
    "http://localhost:8000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:5174",
    "http://127.0.0.1:5175",
    "http://127.0.0.1:5176",
    "http://127.0.0.1:5177",
    "http://127.0.0.1:8000",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(
    RateLimitMiddleware,
    redis=app.state.redis,
    requests_per_minute=settings.rate_limit_requests_per_minute,
    burst=settings.rate_limit_burst,
)

logger = logging.getLogger(__name__)

dashboard_root_dir = Path(__file__).resolve().parent.parent
webapp_frontend_dir = dashboard_root_dir / "frontend"
webapp_assets_dir = webapp_frontend_dir / "assets"
webapp_admin_dir = webapp_frontend_dir / "admin"
webapp_admin_assets_dir = webapp_admin_dir / "assets"
webapp_agents_dir = webapp_frontend_dir / "agents"
webapp_agents_assets_dir = webapp_agents_dir / "assets"
webapp_channels_dir = webapp_frontend_dir / "channels"
webapp_channels_assets_dir = webapp_channels_dir / "assets"
webapp_modbot_dir = webapp_frontend_dir / "modbot"
webapp_modbot_assets_dir = webapp_modbot_dir / "assets"
browser_frontend_dir = dashboard_root_dir / "browser"
browser_assets_dir = browser_frontend_dir / "assets"

if webapp_assets_dir.exists():
    app.mount("/webapp/assets", StaticFiles(directory=str(webapp_assets_dir)), name="webapp-assets")
if webapp_admin_assets_dir.exists():
    app.mount("/webapp/admin/assets", StaticFiles(directory=str(webapp_admin_assets_dir)), name="webapp-admin-assets")
if webapp_agents_assets_dir.exists():
    app.mount("/webapp/agents/assets", StaticFiles(directory=str(webapp_agents_assets_dir)), name="webapp-agents-assets")
if webapp_channels_assets_dir.exists():
    app.mount("/webapp/channels/assets", StaticFiles(directory=str(webapp_channels_assets_dir)), name="webapp-channels-assets")
if webapp_modbot_assets_dir.exists():
    app.mount("/webapp/modbot/assets", StaticFiles(directory=str(webapp_modbot_assets_dir)), name="webapp-modbot-assets")
if browser_assets_dir.exists():
    app.mount("/dashboard/assets", StaticFiles(directory=str(browser_assets_dir)), name="dashboard-assets")

app.include_router(owner_router)
app.include_router(scraper_router)
app.include_router(auth_router)
app.include_router(auth_boundary_router)
app.include_router(admin_router)
app.include_router(admin_automation_router)
app.include_router(admin_summaries_router)
app.include_router(faq_router)
app.include_router(agents_router)
app.include_router(messaging_router)
app.include_router(subscription_router)
app.include_router(group_subscription_router)
app.include_router(internal_router)
app.include_router(internal_router, prefix="/api/internal")


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "service": "modbot-dashboard-api",
        "status": "ok",
        "health": "/health",
        "webapp_admin": "/webapp/admin",
        "webapp_agents": "/webapp/agents",
        "webapp_modbot": "/webapp/modbot",
        "dashboard": "/dashboard",
    }


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/favicon.ico", include_in_schema=False)
async def favicon_ico():
    return Response(status_code=204)


@app.get("/api/stripe/publishable-key")
async def stripe_publishable_key() -> dict[str, str | None]:
    settings = get_settings()
    return {"publishable_key": settings.stripe_publishable_key}


@app.get("/modbot-dashboard-api")
async def service_root() -> dict[str, str]:
    return await root()


@app.get("/webapp")
async def webapp_shell(init_data: str | None = Query(default=None)) -> Response:
    location = "/webapp/admin"
    if init_data:
        location = f"{location}?init_data={init_data}"
    return RedirectResponse(location, status_code=307)


def _frontend_shell(frontend_dir: Path, missing_label: str) -> Response:
    index_file = frontend_dir / "index.html"
    if not index_file.exists():
        return HTMLResponse(f"<h3>{missing_label} frontend not found</h3>", status_code=404)
    return FileResponse(index_file)


@app.get("/webapp/admin")
async def webapp_admin_shell() -> Response:
    return _frontend_shell(webapp_admin_dir, "WebApp admin")


@app.get("/webapp/admin/{path:path}")
async def webapp_admin_shell_path(path: str) -> Response:
    _ = path
    return _frontend_shell(webapp_admin_dir, "WebApp admin")


@app.get("/webapp/agents")
async def webapp_agents_shell() -> Response:
    return _frontend_shell(webapp_agents_dir, "WebApp agents")


@app.get("/webapp/agents/{path:path}")
async def webapp_agents_shell_path(path: str) -> Response:
    _ = path
    return _frontend_shell(webapp_agents_dir, "WebApp agents")


@app.get("/webapp/agents-app")
async def webapp_agents_legacy_shell() -> Response:
    return RedirectResponse("/webapp/agents", status_code=307)


@app.get("/webapp/agents-app/{path:path}")
async def webapp_agents_legacy_shell_path(path: str) -> Response:
    return RedirectResponse(f"/webapp/agents/{path}", status_code=307)


@app.get("/webapp/channels")
async def webapp_channels_shell() -> Response:
    return _frontend_shell(webapp_channels_dir, "Channels")


@app.get("/webapp/channels/{path:path}")
async def webapp_channels_shell_path(path: str) -> Response:
    _ = path
    return _frontend_shell(webapp_channels_dir, "Channels")


@app.get("/webapp/modbot")
async def webapp_modbot_shell() -> Response:
    return _frontend_shell(webapp_modbot_dir, "Modbot")


@app.get("/webapp/modbot/{path:path}")
async def webapp_modbot_shell_path(path: str) -> Response:
    _ = path
    return _frontend_shell(webapp_modbot_dir, "Modbot")


@app.get("/payment/success")
async def payment_success() -> HTMLResponse:
    return HTMLResponse("""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Payment Successful</title></head>
<body style="font-family:system-ui,sans-serif;display:grid;place-items:center;min-height:100vh;margin:0;background:#0e0e10;color:#e4e4e7;text-align:center">
<div><div style="font-size:64px">✅</div><h1 style="margin:16px 0 0">Payment Successful</h1><p style="color:#a1a1aa;margin:8px 0 24px">Your subscription has been activated. You can close this page.</p></div></body></html>""")


def _dashboard_shell() -> Response:
    index_file = browser_frontend_dir / "index.html"
    if not index_file.exists():
        return HTMLResponse("<h3>Browser dashboard frontend not found</h3>", status_code=404)
    return FileResponse(index_file)


@app.get("/dashboard")
async def dashboard_shell() -> Response:
    return _dashboard_shell()


@app.get("/dashboard/{path:path}")
async def dashboard_shell_path(path: str) -> Response:
    _ = path
    return _dashboard_shell()
