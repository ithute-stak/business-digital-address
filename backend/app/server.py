from .health import router as health_router
from .integration_api import router as integration_router
from .main import app
from .platform_config_api import router as platform_config_router
from .portal_api import router as portal_router

app.include_router(health_router)
app.include_router(platform_config_router)
app.include_router(portal_router)
app.include_router(integration_router)
