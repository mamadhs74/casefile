"""FastAPI app factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from apps.api.routers import health, sources, strategies, subjects
from packages.db.session import create_all
from packages.research.dispatch import (
    InvalidSubjectAttributesError,
    UnknownRiskFlagError,
    UnknownStrategyError,
)
from packages.research.eligibility import SubjectNotEligibleError
from packages.research.gate import UnknownSubjectError


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

    @app.exception_handler(SubjectNotEligibleError)
    async def handle_subject_not_eligible(
        request: Request, exc: SubjectNotEligibleError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"detail": "subject not eligible for production", "notes": exc.result.notes},
        )

    @app.exception_handler(UnknownStrategyError)
    async def handle_unknown_strategy(request: Request, exc: UnknownStrategyError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"detail": f"unknown strategy: {exc.strategy_slug!r}"},
        )

    @app.exception_handler(UnknownRiskFlagError)
    async def handle_unknown_risk_flag(
        request: Request, exc: UnknownRiskFlagError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "detail": f"strategy {exc.strategy_slug!r} has no risk flag {exc.flag!r}",
            },
        )

    @app.exception_handler(InvalidSubjectAttributesError)
    async def handle_invalid_attributes(
        request: Request, exc: InvalidSubjectAttributesError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"detail": exc.detail},
        )

    @app.exception_handler(UnknownSubjectError)
    async def handle_unknown_subject(request: Request, exc: UnknownSubjectError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": "subject not found"})

    app.include_router(health.router)
    app.include_router(subjects.router)
    app.include_router(sources.router)
    app.include_router(strategies.router)

    return app


app = create_app()
