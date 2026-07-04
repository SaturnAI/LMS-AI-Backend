from fastapi import APIRouter, Query, Request

from src.enums import MongoCollectionsNames
from src.mongodb.log_manager import LogManager
from src.utils import employee_page_permission, requires_verification

router = APIRouter()
log_manager_db = LogManager()


@router.get("/get_logs")
@requires_verification
@employee_page_permission(page_name=MongoCollectionsNames.LOG_MANAGER)
def get_logs(
    request: Request,
    page_number: int = Query(1, description="Page number"),
    search_query: str = Query("", description="Search query"),
    decoded_data: dict = {},
):
    return LogManager.fetch_logs(
        page_number=page_number,
        search_query=search_query,
        tenant_id=decoded_data["tenant_id"],
    )
