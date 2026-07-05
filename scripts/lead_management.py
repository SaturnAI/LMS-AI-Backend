from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from src.mongodb.lead_management import LeadManagement
from src.utils import requires_verification

router = APIRouter()
lead_management_db = LeadManagement()


@router.post("/add_lead")
@requires_verification
async def add_lead(request: Request, decoded_data: dict = {}):
    request_data = await request.json()
    response_data, status_code = lead_management_db.create_lead(
        request_data=request_data,
        current_user_email=decoded_data["email"],
        tenant_id=decoded_data["tenant_id"],
    )
    return JSONResponse(response_data, status_code=status_code)


@router.post("/update_lead")
@requires_verification
async def update_lead(request: Request, decoded_data: dict = {}):
    request_data = await request.json()
    response_data, status_code = lead_management_db.update_lead(
        request_data=request_data,
        current_user_email=decoded_data["email"],
        tenant_id=decoded_data["tenant_id"],
    )
    return JSONResponse(response_data, status_code=status_code)


@router.get("/fetch_leads")
@requires_verification
async def fetch_leads(
    request: Request,
    batch_number: int = Query(1, description="Batch number"),
    batch_size: int = Query(10, description="Batch size"),
    search_query: str = Query("", description="Search query"),
    decoded_data: dict = {},
):
    response_data, status_code = lead_management_db.fetch_leads(
        tenant_id=decoded_data["tenant_id"],
        batch_number=batch_number,
        batch_size=batch_size,
        search_query=search_query,
        current_user_email=decoded_data["email"],
        role=decoded_data["role"],
    )
    return JSONResponse(response_data, status_code=status_code)


@router.get("/fetch_dropdown_sales_representatives")
@requires_verification
async def fetch_dropdown_sales_representatives(request: Request, decoded_data: dict = {}):
    response_data, status_code = lead_management_db.fetch_dropdown_sales_representatives(
        tenant_id=decoded_data["tenant_id"]
    )
    return JSONResponse(response_data, status_code=status_code)


@router.post("/add_comment")
@requires_verification
async def add_comment(request: Request, decoded_data: dict = {}):
    request_data = await request.json()
    response_data, status_code = lead_management_db.add_comment(
        lead_code=request_data.get("lead_code", ""),
        comment_text=request_data.get("comment", ""),
        current_user_email=decoded_data["email"],
        tenant_id=decoded_data["tenant_id"],
    )
    return JSONResponse(response_data, status_code=status_code)
