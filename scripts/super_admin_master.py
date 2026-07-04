from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from src.mongodb.super_admin_master import SuperAdminMaster
from src.utils import requires_verification, super_admin_only

router = APIRouter()
super_admin_master_db = SuperAdminMaster()


@router.post("/add_super_admin")
@requires_verification
@super_admin_only
async def add_super_admin(request: Request, decoded_data: dict = {}):
    request_data = await request.json()
    response_data, status_code = super_admin_master_db.add_super_admin(
        request_data=request_data, current_user_email=decoded_data["email"]
    )
    return JSONResponse(response_data, status_code=status_code)


@router.post("/update_super_admin")
@requires_verification
@super_admin_only
async def update_super_admin(request: Request, decoded_data: dict = {}):
    request_data = await request.json()
    response_data, status_code = super_admin_master_db.update_super_admin(
        request_data=request_data, current_user_email=decoded_data["email"]
    )
    return JSONResponse(response_data, status_code=status_code)


@router.get("/fetch_all_super_admins")
@requires_verification
@super_admin_only
async def fetch_all_super_admins(request: Request, decoded_data: dict = {}):
    response_data, status_code = super_admin_master_db.fetch_all_super_admins()
    return JSONResponse(response_data, status_code=status_code)


@router.get("/disable_super_admin")
@requires_verification
@super_admin_only
async def disable_super_admin(
    request: Request,
    disable_user_email: str = Query("", description="Email of super admin to disable"),
    decoded_data: dict = {},
):
    response_data, status_code = super_admin_master_db.disable_super_admin(
        disable_user_email=disable_user_email, current_super_admin_email=decoded_data["email"]
    )
    return JSONResponse(response_data, status_code=status_code)


@router.get("/enable_super_admin")
@requires_verification
@super_admin_only
async def enable_super_admin(
    request: Request,
    enable_user_email: str = Query("", description="Email of super admin to enable"),
    decoded_data: dict = {},
):
    response_data, status_code = super_admin_master_db.enable_super_admin(enable_user_email=enable_user_email)
    return JSONResponse(response_data, status_code=status_code)
