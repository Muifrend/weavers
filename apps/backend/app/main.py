from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.responses import Response
from fastapi.responses import StreamingResponse
import httpx

from app.config import get_settings
from app.agents.persona_creation import PersonaCreationAgent
from app.orchestrator import CampaignOrchestrator
from app.providers.base import ProviderError
from app.schemas import PersonaGenerationRequest, PersonaGenerationResponse, PersonaSetSummary, RunRequest
from app.streaming.ag_ui_events import encode_sse


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

settings = get_settings()
app = FastAPI(title="Campaign Persona Agent", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|0\.0\.0\.0):\d+$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup() -> None:
    print(settings.safe_startup_summary())
    app.state.orchestrator = CampaignOrchestrator(settings)


@app.get("/health")
async def health() -> dict[str, object]:
    return {
        "status": "ok",
        "backend_env": settings.backend_env,
        "demo_mode": settings.demo_mode,
        "configured_providers": settings.configured_providers(),
        "census": "configured" if settings.census_api_key else "missing",
        "pums_data_dir": str(settings.pums_data_dir),
        "redis_agent_memory": "configured" if settings.redis_configured() else "missing",
        "weave": "configured" if settings.weave_configured() else "missing",
        "missing_required": settings.missing_required(),
    }


@app.get("/api/personas")
async def list_personas() -> dict[str, object]:
    orchestrator: CampaignOrchestrator = app.state.orchestrator
    try:
        personas = orchestrator.local_store.load_personas()
    except FileNotFoundError:
        return {"personas": [], "count": 0}
    return {
        "personas": [persona.model_dump(exclude_none=True) for persona in personas],
        "count": len(personas),
    }


@app.get("/api/models")
async def list_models() -> dict[str, object]:
    orchestrator: CampaignOrchestrator = app.state.orchestrator
    return {"providers": orchestrator.provider_router.available_models()}


@app.get("/api/persona-sets")
async def list_persona_sets() -> dict[str, object]:
    orchestrator: CampaignOrchestrator = app.state.orchestrator
    sets = [PersonaSetSummary(**summary) for summary in orchestrator.local_store.list_persona_sets()]
    return {"sets": [item.model_dump() for item in sets]}


@app.post("/api/personas/generate", response_model=PersonaGenerationResponse)
async def generate_personas(request: PersonaGenerationRequest) -> PersonaGenerationResponse:
    orchestrator: CampaignOrchestrator = app.state.orchestrator
    agent = PersonaCreationAgent(
        settings=settings,
        store=orchestrator.local_store,
    )
    try:
        return await agent.generate_state_personas(request)
    except ProviderError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error_code": exc.error_code, "message": exc.safe_message},
        ) from exc


@app.api_route(
    "/api/copilotkit",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
@app.api_route(
    "/api/copilotkit/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def copilotkit_proxy(request: Request, path: str = "") -> Response:
    target_url = f"{settings.copilot_runtime_url}{request.url.path}"
    if request.url.query:
        target_url = f"{target_url}?{request.url.query}"

    excluded_request_headers = {"host", "content-length", "connection"}
    request_headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in excluded_request_headers
    }

    excluded_response_headers = {
        "content-encoding",
        "content-length",
        "connection",
        "transfer-encoding",
    }

    body = await request.body()
    client = httpx.AsyncClient(
        timeout=httpx.Timeout(connect=5.0, read=None, write=30.0, pool=5.0)
    )
    upstream_request = client.build_request(
        request.method,
        target_url,
        headers=request_headers,
        content=body,
    )
    try:
        upstream_response = await client.send(upstream_request, stream=True)
    except httpx.RequestError as exc:
        await client.aclose()
        logger.warning(
            "CopilotKit runtime unavailable at %s: %s",
            settings.copilot_runtime_url,
            exc.__class__.__name__,
        )
        return JSONResponse(
            status_code=503,
            content={
                "detail": {
                    "error_code": "copilot_runtime_unavailable",
                    "message": (
                        "CopilotKit runtime is not reachable. Start it with `npm run dev` "
                        "from apps/copilot-runtime, or update COPILOT_RUNTIME_URL."
                    ),
                    "runtime_url": settings.copilot_runtime_url,
                }
            },
        )

    async def response_body():
        try:
            async for chunk in upstream_response.aiter_bytes():
                yield chunk
        finally:
            await upstream_response.aclose()
            await client.aclose()

    response_headers = {
        key: value
        for key, value in upstream_response.headers.items()
        if key.lower() not in excluded_response_headers
    }
    return StreamingResponse(
        response_body(),
        status_code=upstream_response.status_code,
        headers=response_headers,
        media_type=upstream_response.headers.get("content-type"),
    )


@app.post("/api/runs")
async def run_campaign(request: RunRequest) -> StreamingResponse:
    orchestrator: CampaignOrchestrator = app.state.orchestrator

    async def event_stream():
        async for event in orchestrator.stream_run(request):
            yield encode_sse(event)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
