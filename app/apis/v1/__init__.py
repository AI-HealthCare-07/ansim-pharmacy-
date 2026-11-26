from fastapi import APIRouter

from app.apis.v1.auth_routers import auth_router
from app.apis.v1.document_routers import document_router
from app.apis.v1.user_routers import user_router

v1_routers = APIRouter(prefix="/api/v1")
v1_routers.include_router(auth_router)
v1_routers.include_router(user_router)
v1_routers.include_router(document_router)
