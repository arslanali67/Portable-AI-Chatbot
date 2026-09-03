from fastapi import APIRouter

from app.api.v1 import (
    ai_credentials,
    ai_management,
    auth,
    chatbots,
    conversations,
    health,
    knowledge,
    organizations,
    platform,
    public_widget,
)

api_router = APIRouter()

api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(organizations.router)
api_router.include_router(chatbots.router)
api_router.include_router(conversations.router)
api_router.include_router(ai_management.router)
api_router.include_router(ai_credentials.router)
api_router.include_router(knowledge.router)
api_router.include_router(platform.router)
api_router.include_router(public_widget.router)
