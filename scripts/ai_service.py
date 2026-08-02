import json
from http import HTTPStatus
from io import BytesIO

from fastapi import APIRouter, File, Form, Query, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from src.ai_service.rag_service import LeadRAGService
from src.utils import requires_verification

router = APIRouter()
lead_rag_service = LeadRAGService()


@router.post("/index_files")
@requires_verification
async def index_files(
    request: Request,
    decoded_data: dict = {},
    lead_code: str = Form(...),
    files: list[UploadFile] = File(...),
):
    payload_files = []
    for uploaded_file in files:
        file_bytes = await uploaded_file.read()
        payload_files.append(
            {
                "file_name": uploaded_file.filename or "",
                "content_type": uploaded_file.content_type,
                "file_bytes": file_bytes,
            }
        )

    response_data, status_code = lead_rag_service.index_files(
        files=payload_files,
        lead_code=lead_code,
        tenant_id=decoded_data["tenant_id"],
        current_user_email=decoded_data["email"],
        source="uploaded_file",
    )
    return JSONResponse(content=response_data, status_code=status_code)


@router.post("/index_text")
@requires_verification
async def index_text(request: Request, decoded_data: dict = {}):
    request_data = await request.json()
    response_data, status_code = lead_rag_service.index_text(
        request_data=request_data,
        tenant_id=decoded_data["tenant_id"],
        current_user_email=decoded_data["email"],
    )
    return JSONResponse(content=response_data, status_code=status_code)


@router.get("/index_files_status")
@requires_verification
async def index_files_status(
    request: Request,
    lead_code: str = Query(..., description="Lead code"),
    job_id: str = Query(..., description="Background indexing job id"),
    decoded_data: dict = {},
):
    response_data, status_code = lead_rag_service.get_index_job_status(
        tenant_id=decoded_data["tenant_id"],
        lead_code=lead_code,
        job_id=job_id,
    )
    return JSONResponse(content=response_data, status_code=status_code)


@router.get("/fetch_files")
@requires_verification
async def fetch_files(
    request: Request,
    lead_code: str = Query(..., description="Lead code"),
    batch_number: int = Query(1, description="Batch number"),
    batch_size: int = Query(10, description="Batch size"),
    decoded_data: dict = {},
):
    response_data, status_code = lead_rag_service.fetch_files(
        tenant_id=decoded_data["tenant_id"],
        lead_code=lead_code,
        batch_number=batch_number,
        batch_size=batch_size,
    )
    return JSONResponse(content=response_data, status_code=status_code)


@router.get("/download_file")
@requires_verification
async def download_file(
    request: Request,
    lead_code: str = Query(..., description="Lead code"),
    file_id: str = Query(..., description="File id to download"),
    decoded_data: dict = {},
):
    response_data, status_code = lead_rag_service.download_file(
        tenant_id=decoded_data["tenant_id"],
        lead_code=lead_code,
        file_id=file_id,
    )

    if status_code != HTTPStatus.OK:
        return JSONResponse(content=response_data, status_code=status_code)

    return StreamingResponse(
        content=BytesIO(response_data["file_bytes"]),
        media_type=response_data["content_type"],
        headers={
            "Content-Disposition": f"attachment; filename={response_data['file_name']}",
        },
    )


@router.post("/delete_file")
@requires_verification
async def delete_file(
    request: Request,
    lead_code: str = Query(..., description="Lead code"),
    file_id: str = Query(..., description="File id to delete"),
    decoded_data: dict = {},
):
    response_data, status_code = lead_rag_service.delete_indexed_file(
        tenant_id=decoded_data["tenant_id"],
        lead_code=lead_code,
        file_id=file_id,
    )
    return JSONResponse(content=response_data, status_code=status_code)


@router.post("/reindex_file")
@requires_verification
async def reindex_file(
    request: Request,
    lead_code: str = Query(..., description="Lead code"),
    file_id: str = Query(..., description="File id to reindex"),
    decoded_data: dict = {},
):
    response_data, status_code = lead_rag_service.reindex_file(
        tenant_id=decoded_data["tenant_id"],
        lead_code=lead_code,
        file_id=file_id,
        current_user_email=decoded_data["email"],
    )
    return JSONResponse(content=response_data, status_code=status_code)


@router.post("/ask_question")
@requires_verification
async def ask_question(request: Request, decoded_data: dict = {}):
    request_data = await request.json()

    if bool(request_data.get("stream", True)):
        stream_generator, stream_meta, status_code = lead_rag_service.ask_question_stream(
            request_data=request_data,
            tenant_id=decoded_data["tenant_id"],
            current_user_email=decoded_data["email"],
        )

        if status_code != HTTPStatus.OK:
            return JSONResponse(
                content={
                    "is_successful": False,
                    "message": "".join(list(stream_generator)),
                },
                status_code=status_code,
            )

        headers = {
            "X-RAG-Is-Cached": str(stream_meta.get("is_cached", False)).lower(),
            "X-RAG-Citations": json.dumps(stream_meta.get("citations", [])),
        }
        return StreamingResponse(
            stream_generator,
            media_type="text/markdown; charset=utf-8",
            headers=headers,
        )

    response_data, status_code = lead_rag_service.ask_question(
        request_data=request_data,
        tenant_id=decoded_data["tenant_id"],
        current_user_email=decoded_data["email"],
    )
    return JSONResponse(content=response_data, status_code=status_code)
