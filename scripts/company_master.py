from http import HTTPStatus
from io import BytesIO

from fastapi import APIRouter, File, Query, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from src.constants import MAX_AGE_AUTH_TOKEN_SECONDS
from src.enums import UserRoles
from src.mongodb.company_master import CompanyMaster
from src.utils import requires_verification, super_admin_only

router = APIRouter()
company_master_db = CompanyMaster()


@router.post("/add_company")
@requires_verification
@super_admin_only
async def add_company(request: Request, decoded_data: dict = {}, company_logo: UploadFile = File(None)):
    form_data = await request.form()
    request_data = dict(form_data)

    company_logo_file = None
    if company_logo:
        file_bytes = await company_logo.read()
        company_logo_file = BytesIO(file_bytes)

    response_data, status_code = company_master_db.add_company(
        request_data=request_data, current_user_email=decoded_data["email"], company_logo=company_logo_file
    )
    return JSONResponse(response_data, status_code=status_code)


@router.post("/update_company")
@requires_verification
@super_admin_only
async def update_company(request: Request, decoded_data: dict = {}, company_logo: UploadFile = File(None)):
    form_data = await request.form()
    request_data = dict(form_data)

    company_logo_file = None
    if company_logo:
        file_bytes = await company_logo.read()
        company_logo_file = BytesIO(file_bytes)

    response_data, status_code = company_master_db.update_company(
        request_data=request_data, current_user_email=decoded_data["email"], company_logo=company_logo_file
    )

    return JSONResponse(response_data, status_code=status_code)


@router.get("/fetch_company_logo_for_super_admin")
@requires_verification
@super_admin_only
async def fetch_company_logo_for_super_admin(
    request: Request,
    decoded_data: dict = {},
    tenant_id: str = Query(..., description="The tenant_id to fetch logo for"),
):
    response_data, status_code = company_master_db.fetch_company_logo(tenant_id=tenant_id.strip())

    if not response_data or "company_logo" not in response_data:
        return JSONResponse({"is_successful": False, "message": "Company logo not found."}, status_code=status_code)

    return StreamingResponse(content=BytesIO(response_data["company_logo"]))


@router.post("/update_company_profile")
@requires_verification
async def update_company_profile(request: Request, decoded_data: dict = {}, company_logo: UploadFile = File(None)):
    form_data = await request.form()
    request_data = dict(form_data)

    if decoded_data["role"] != UserRoles.COMPANY_ADMIN:
        return JSONResponse(
            {"is_successful": False, "message": "Only Company Admin can update company profile."}, HTTPStatus.FORBIDDEN
        )

    company_logo_file = None
    if company_logo:
        file_bytes = await company_logo.read()
        company_logo_file = BytesIO(file_bytes)

    response_data, status_code = company_master_db.update_company_profile(
        current_user_email=decoded_data["email"], profile_data=request_data, company_logo=company_logo_file
    )

    return JSONResponse(response_data, status_code=status_code)


@router.get("/fetch_company_logo")
@requires_verification
async def fetch_company_logo(
    request: Request,
    decoded_data: dict = {},
):
    response_data, status_code = company_master_db.fetch_company_logo(tenant_id=decoded_data["tenant_id"])

    if not response_data or "company_logo" not in response_data:
        return JSONResponse({"is_successful": False, "message": "Company logo not found."}, status_code=status_code)

    return StreamingResponse(content=BytesIO(response_data["company_logo"]))


@router.get("/disable_company")
@requires_verification
@super_admin_only
async def disable_company(
    request: Request,
    company_code: str = Query(..., description="The code of the company to disable"),
    decoded_data: dict = {},
):
    response_data, status_code = company_master_db.disable_company_admin_and_employees(
        company_code=company_code, current_user_email=decoded_data["email"]
    )
    return JSONResponse(response_data, status_code=status_code)


@router.get("/enable_company")
@requires_verification
@super_admin_only
async def enable_company(
    request: Request,
    company_code: str = Query(..., description="The code of the company to disable"),
    decoded_data: dict = {},
):
    response_data, status_code = company_master_db.enable_company_admin(
        company_code=company_code, current_user_email=decoded_data["email"]
    )
    return JSONResponse(response_data, status_code=status_code)


@router.get("/fetch_all_companies")
@requires_verification
@super_admin_only
async def fetch_all_companies(request: Request, decoded_data: dict = {}):
    response_data, status_code = company_master_db.fetch_all_companies()
    return JSONResponse(response_data, status_code=status_code)


@router.get("/set_tenant_id")
@requires_verification
@super_admin_only
async def set_tenant_id(
    request: Request,
    company_code: str = Query(..., description="The company_code of the company to switch context to"),
    decoded_data: dict = {},
):
    from src.encryption_system import EncryptionSystem

    company_admin = company_master_db.get_company_from_company_code(company_code=company_code)

    if not company_admin:
        return JSONResponse(
            {"is_successful": False, "message": "Company admin not found or is disabled."},
            status_code=HTTPStatus.NOT_FOUND,
        )

    decoded_data["tenant_id"] = company_admin["tenant_id"]
    encryption_system = EncryptionSystem()
    auth_token = encryption_system.encrypt_dict(input_json=decoded_data)

    response = JSONResponse(
        {
            "is_successful": True,
            "message": "Tenant ID set successfully.",
        },
        status_code=HTTPStatus.OK,
    )
    response.set_cookie(
        key="auth_token",
        value=auth_token,
        secure=True,
        httponly=True,
        samesite="lax",
        max_age=MAX_AGE_AUTH_TOKEN_SECONDS,
    )

    return response


@router.get("/remove_tenant_id")
@requires_verification
@super_admin_only
async def remove_tenant_id(request: Request, decoded_data: dict = {}):
    from src.encryption_system import EncryptionSystem

    decoded_data.pop("tenant_id", None)
    encryption_system = EncryptionSystem()
    auth_token = encryption_system.encrypt_dict(input_json=decoded_data)

    response = JSONResponse(
        {"is_successful": True, "message": "Tenant ID removed successfully."}, status_code=HTTPStatus.OK
    )
    response.set_cookie(
        key="auth_token",
        value=auth_token,
        secure=True,
        httponly=True,
        samesite="lax",
        max_age=MAX_AGE_AUTH_TOKEN_SECONDS,
    )

    return response
