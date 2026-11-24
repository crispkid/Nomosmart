from fastapi import APIRouter

from app.api.routes import approval_administration, approvals, auth, chunk_references, compatibility, data_sources, documents, health, identity, integration_clients, models, projects, public_api, references, reports, responses, roles, serving, system, system_prompts, users
from app.api.routes import protocol_auth, protocol_identity, system_project_settings


api_router = APIRouter(prefix="/api/v1")
public_api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(protocol_auth.router)
api_router.include_router(identity.router)
api_router.include_router(protocol_identity.router)
api_router.include_router(users.router)
api_router.include_router(roles.router)
api_router.include_router(projects.router)
api_router.include_router(documents.router)
api_router.include_router(chunk_references.router)
api_router.include_router(data_sources.router)
api_router.include_router(references.router)
api_router.include_router(approvals.router)
api_router.include_router(approval_administration.router)
api_router.include_router(serving.router)
api_router.include_router(responses.router)
api_router.include_router(reports.router)
api_router.include_router(system.router)
api_router.include_router(system_project_settings.router)  # CHG-486 PSET486
api_router.include_router(integration_clients.router)
api_router.include_router(system_prompts.router)
api_router.include_router(system_prompts.model_prompt_router)
api_router.include_router(models.router)
api_router.include_router(compatibility.router)
public_api_router.include_router(public_api.router)
