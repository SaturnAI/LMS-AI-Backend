import logging as logger
import threading
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.middleware import SlowAPIMiddleware
from starlette.responses import JSONResponse

from config import ProjectConfig
from src.cred import Credentials
from src.enums import Environments
from src.mongodb.base import BaseDatabase

MAX_UPLOAD_SIZE = ProjectConfig.MAX_UPLOAD_SIZE_MB * 1024 * 1024


def create_app():
    app = FastAPI()

    app.add_middleware(SlowAPIMiddleware)

    # Origin validation middleware
    allowed_origins = list(ProjectConfig.PRODUCTION_ORIGINS)
    if Credentials.environment != Environments.PRODUCTION:
        allowed_origins.extend(ProjectConfig.NON_PRODUCTION_ORIGINS)

    # CORS setup
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Accept",
            "Origin",
            "X-Requested-With",
            # "Cache-Control",
        ],
    )

    logger.basicConfig(level=logger.INFO)

    # Handler for KeyError
    @app.exception_handler(KeyError)
    async def key_error_handler(request: Request, exc: KeyError):
        logger.error(f"KeyError: {exc}")
        return JSONResponse(
            status_code=400,
            content={"is_successful": False, "message": f"Missing required field {exc}"},
        )

    # Ensure MongoDB indexes
    BaseDatabase.ensure_indexes()

    # Start background auth-key rotation checker
    _start_key_rotation_thread()

    prefix = "/api"

    from scripts.authentication import router as authentication
    from scripts.company_master import router as company_master
    from scripts.employee_master import router as employee_master
    from scripts.log_manager import router as log_manager
    from scripts.super_admin_master import router as super_admin_master

    app.include_router(authentication, prefix=prefix)
    app.include_router(super_admin_master, prefix=prefix + "/super_admin_master")
    app.include_router(employee_master, prefix=prefix + "/employee_master")
    app.include_router(company_master, prefix=prefix + "/company_master")
    app.include_router(log_manager, prefix=prefix + "/log_manager")

    return app


def _start_key_rotation_thread():
    """Start a daemon thread that checks for auth key rotation every hour."""

    def _loop():
        from src.encryption_system import rotate_if_due

        # Stagger the first check by 30 s so the DB is fully ready
        time.sleep(30)
        while True:
            try:
                rotate_if_due()
            except Exception as exc:
                logger.error(f"Auth key rotation check failed: {exc}")
            time.sleep(ProjectConfig.KEY_ROTATION_CHECK_INTERVAL)  # check every hour

    t = threading.Thread(target=_loop, name="auth-key-rotation", daemon=True)
    t.start()
    logger.info("Auth key rotation thread started.")
