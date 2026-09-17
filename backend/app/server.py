from .health import router as health_router
from .integration_api import router as integration_router
from .launch_features import router as launch_features_router
from .main import app
from .membership_api import router as membership_router
from .platform_config_api import router as platform_config_router
from .portal_api import router as portal_router


# main.py retains the original business-list route for source compatibility.
# At the runtime composition boundary replace only that GET route with the
# membership-aware version, which reconciles trusted Ithute invitations before
# returning the signed-in user's active businesses. POST /api/v1/businesses and
# every other business route remain untouched.
app.router.routes = [
    route
    for route in app.router.routes
    if not (
        getattr(route, "path", None) == "/api/v1/businesses"
        and "GET" in (getattr(route, "methods", set()) or set())
    )
]

app.include_router(health_router)
app.include_router(platform_config_router)
app.include_router(membership_router)
app.include_router(portal_router)
app.include_router(integration_router)
app.include_router(launch_features_router)
