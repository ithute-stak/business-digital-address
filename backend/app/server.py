from .main import app
from .portal_api import router as portal_router

app.include_router(portal_router)
