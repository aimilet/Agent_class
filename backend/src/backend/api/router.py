from __future__ import annotations

from fastapi import APIRouter

from backend.api.routes import approvals, assignments, audits, courses, naming, review_prep, review_run, rosters, submissions, system


def build_api_router() -> APIRouter:
    router = APIRouter()
    router.include_router(system.router)
    router.include_router(courses.router)
    router.include_router(rosters.router)
    router.include_router(assignments.router)
    router.include_router(submissions.router)
    router.include_router(naming.router)
    router.include_router(review_prep.router)
    router.include_router(review_run.router)
    router.include_router(approvals.router)
    router.include_router(audits.router)
    return router
