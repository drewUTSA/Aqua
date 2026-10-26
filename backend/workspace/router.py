"""Versioned workspace route assembly."""

from fastapi import APIRouter
from workspace.chat_router import router as chats
from workspace.catalog_router import router as catalog

router = APIRouter(prefix="/api/v1", tags=["private workspace"])
router.include_router(chats)
router.include_router(catalog)
