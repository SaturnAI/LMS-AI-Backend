from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from src.enums import MongoCollectionsNames
from src.mongodb.employee_master import EmployeeMaster
from src.utils import (
    employee_edit_permission,
    employee_page_permission,
    requires_verification,
)

router = APIRouter()
employee_master_db = EmployeeMaster()


@router.post("/add_employee")
@requires_verification
@employee_edit_permission(page_name=MongoCollectionsNames.EMPLOYEE_MASTER)
async def add_employee(request: Request, decoded_data: dict = {}):
    request_data = await request.json()
    response_data, status_code = employee_master_db.add_employee(
        request_data=request_data,
        current_user_email=decoded_data["email"],
        tenant_id=decoded_data["tenant_id"],
    )
    return JSONResponse(response_data, status_code=status_code)


@router.post("/update_employee")
@requires_verification
@employee_edit_permission(page_name=MongoCollectionsNames.EMPLOYEE_MASTER)
async def update_employee(request: Request, decoded_data: dict = {}):
    request_data = await request.json()
    response_data, status_code = employee_master_db.update_employee(
        request_data=request_data,
        current_user_email=decoded_data["email"],
        tenant_id=decoded_data["tenant_id"],
    )
    return JSONResponse(response_data, status_code=status_code)


@router.get("/fetch_enabled_employees")
@requires_verification
@employee_page_permission(page_name=MongoCollectionsNames.EMPLOYEE_MASTER)
async def fetch_enabled_employees(request: Request, decoded_data: dict = {}):
    response_data, status_code = employee_master_db.fetch_enabled_employees(tenant_id=decoded_data["tenant_id"])
    return JSONResponse(response_data, status_code=status_code)


@router.get("/fetch_disabled_employees")
@requires_verification
@employee_page_permission(page_name=MongoCollectionsNames.EMPLOYEE_MASTER)
async def fetch_disabled_employees(request: Request, decoded_data: dict = {}):
    response_data, status_code = employee_master_db.fetch_disabled_employees(tenant_id=decoded_data["tenant_id"])
    return JSONResponse(response_data, status_code=status_code)


@router.get("/enable_employee")
@requires_verification
@employee_edit_permission(page_name=MongoCollectionsNames.EMPLOYEE_MASTER)
async def enable_employee(
    request: Request,
    employee_to_enable_email: str = Query("", description="Email of employee to enable"),
    decoded_data: dict = {},
):
    response_data, status_code = employee_master_db.enable_employee(
        enable_user_email=employee_to_enable_email,
        tenant_id=decoded_data["tenant_id"],
        current_user_email=decoded_data["email"],
    )
    return JSONResponse(response_data, status_code=status_code)


@router.get("/disable_employee")
@requires_verification
@employee_edit_permission(page_name=MongoCollectionsNames.EMPLOYEE_MASTER)
async def disable_employee(
    request: Request,
    employee_to_disable_email: str = Query("", description="Email of employee to disable"),
    decoded_data: dict = {},
):
    response_data, status_code = employee_master_db.disable_employee(
        disable_user_email=employee_to_disable_email,
        current_user_email=decoded_data["email"],
        tenant_id=decoded_data["tenant_id"],
    )
    return JSONResponse(response_data, status_code=status_code)
