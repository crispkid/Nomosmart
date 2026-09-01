from fastapi import APIRouter

from app.api.routes import approvals, auth, compatibility, data_sources, documents, health, identity, identity_settings, integration_clients, models, projects, public_api, references, reports, roles, serving, system, system_prompts, users


api_router = APIRouter(prefix="/api/v1")
public_api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(identity.router)
api_router.include_router(identity_settings.router)
api_router.include_router(users.router)
api_router.include_router(roles.router)
api_router.include_router(projects.router)
api_router.include_router(documents.router)
api_router.include_router(data_sources.router)
api_router.include_router(references.router)
api_router.include_router(approvals.router)
api_router.include_router(serving.router)
api_router.include_router(reports.router)
api_router.include_router(system.router)
api_router.include_router(integration_clients.router)
api_router.include_router(system_prompts.router)
api_router.include_router(system_prompts.model_prompt_router)
api_router.include_router(models.router)
api_router.include_router(compatibility.router)
public_api_router.include_router(public_api.router)
