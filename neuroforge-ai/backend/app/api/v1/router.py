from fastapi import APIRouter

from app.api.v1 import audit, auth, comparison, documents, insights, knowledge, review, search, system, workflows

api_router = APIRouter()
for module in (system, auth, documents, search, knowledge, insights, review, workflows, comparison, audit):
    api_router.include_router(module.router)
