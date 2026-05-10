from .agents import router as agents_router
from .admin import router as admin_router
from .admin_automation import router as admin_automation_router
from .auth import router as auth_router
from .auth_boundary import router as auth_boundary_router
from .faq import router as faq_router
from .internal import router as internal_router

__all__ = [
    "agents_router",
    "admin_router",
    "admin_automation_router",
    "auth_boundary_router",
    "auth_router",
    "faq_router",
    "internal_router",
]
