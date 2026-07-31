"""FastAPI app factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from apps.api.routers import cases, health, sources
from packages.db.session import create_all
from packages.research.eligibility import CaseNotEligibleError


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    create_all()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="casefile", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(CaseNotEligibleError)
    async def handle_case_not_eligible(
        request: Request, exc: CaseNotEligibleError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"detail": "case not eligible for production", "notes": exc.result.notes},
        )

    app.include_router(health.router)
    app.include_router(cases.router)
    app.include_router(sources.router)

    return app


app = create_app()
