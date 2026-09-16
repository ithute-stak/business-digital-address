from .health import router as health_router
from .main import app
from .portal_api import router as portal_router

app.include_router(health_router)
app.include_router(portal_router)
