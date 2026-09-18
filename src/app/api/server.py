import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from app.api.errors import register_error_handlers
from app.api.middleware import RequestContextMiddleware
from app.api.routers import register_routes
from app.config import Settings, configure_telemetry, get_settings, setup_logging
from app.orchestrator import build_graphs

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Compile graphs once per process and expose them on app.state."""
    app.state.graphs = build_graphs()
    logger.info("Server up and running")
    yield
    logger.info("Server shutting down")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    setup_logging(level=settings.log_level, log_format=settings.log_format)
    configure_telemetry(settings)
    logger.info("Starting server version=%s", settings.api_version)

    app = FastAPI(
        title=settings.api_title,
        description=settings.api_description,
        version=settings.api_version,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # Added last, so it wraps everything else and every log line gets a request id.
    app.add_middleware(RequestContextMiddleware)

    register_error_handlers(app)
    register_routes(app)
    FastAPIInstrumentor.instrument_app(app)
    return app
