from fastapi import FastAPI

from app.api.v1.routes import health_router, poetry_router

API_V1_PREFIX = "/api/v1"


def register_routes(app: FastAPI) -> None:
    # Health is unversioned: probes should not break on an API version bump.
    app.include_router(health_router)
    app.include_router(poetry_router, prefix=API_V1_PREFIX)
