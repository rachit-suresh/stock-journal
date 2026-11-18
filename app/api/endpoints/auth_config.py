from fastapi import APIRouter

from app.core.config import settings

# Public: the sign-in page needs this before anyone is signed in (SPEC-API-12).
router = APIRouter()


@router.get("/auth/config")
async def auth_config():
    """Tell the SPA which Supabase project to sign in against.

    Both values are public by design: the anon key only identifies the
    project, and RLS keeps it away from the tables (SPEC-PER-10). Serving
    them from here keeps every deployment value in the backend's env.
    """
    if settings.AUTH_DISABLED:
        return {"provider": "none"}
    return {
        "provider": "supabase",
        "url": settings.SUPABASE_URL,
        "anonKey": settings.SUPABASE_ANON_KEY,
    }
