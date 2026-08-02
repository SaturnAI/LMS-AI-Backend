import base64
import hashlib
import json
import math
import os
import threading
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from io import BytesIO
from typing import Any, Generator

import numpy as np
import requests

try:
    from pypdf import PdfReader  # type: ignore[import-not-found]
except Exception:
    PdfReader = None  # type: ignore[assignment]
from pydantic import ValidationError

from config import ProjectConfig
from src.ai_service.stitcher import Stitcher
from src.cred import Credentials
from src.enums import GPTModels, MongoCollectionsNames
from src.mongodb.base import BaseDatabase
from src.schema import AskQuestionRequest, IndexTextRequest

OPENAI_API_KEY = Credentials.openai_api_key
OPENAI_EMBEDDINGS_URL = "https://api.openai.com/v1/embeddings"
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
EMBEDDING_MODEL = ProjectConfig.CODE_EMBEDDING_MODEL
MODEL = GPTModels.GPT_5_6_LUNA.value
REASONING_EFFORT = "low"

CHUNK_SIZE_CHARS = ProjectConfig.CODE_INDEX_CHUNK_SIZE_CHARS
CHUNK_OVERLAP_LINES = ProjectConfig.CODE_INDEX_CHUNK_OVERLAP_LINES
MAX_FILE_SIZE_BYTES = ProjectConfig.CODE_INDEX_MAX_FILE_SIZE_MB * 1024 * 1024
MAX_FILES = ProjectConfig.CODE_INDEX_MAX_FILES
EMBEDDING_BATCH_SIZE = 64
EMBEDDING_CONCURRENCY = 3
FILE_PROCESS_CONCURRENCY = min(8, (os.cpu_count() or 4) * 2)
TOP_K = ProjectConfig.CODE_QA_TOP_K
EMBED_CACHE_TTL_SECONDS = ProjectConfig.CODE_QA_EMBED_CACHE_TTL_SECONDS
EMBED_CACHE_MAX_PROJECTS = ProjectConfig.CODE_QA_EMBED_CACHE_MAX_PROJECTS
CHAT_CONTEXT_LAST_N = ProjectConfig.CHAT_CONTEXT_LAST_N
CHAT_SUMMARY_BATCH_SIZE = ProjectConfig.CHAT_SUMMARY_BATCH_SIZE
CHAT_SUMMARY_MAX_CHARS = ProjectConfig.CHAT_SUMMARY_MAX_CHARS
LEAD_CONTEXT_COMMENTS_LIMIT = 25
INDEX_JOB_RESULTS_MAX_ITEMS = 500
IST_TZ = timezone(timedelta(hours=5, minutes=30))


class LeadRAGService:
    files_collection = BaseDatabase.get_collection(MongoCollectionsNames.AI_LEAD_FILES)
    chunks_collection = BaseDatabase.get_collection(MongoCollectionsNames.AI_LEAD_CHUNKS)
    query_cache_collection = BaseDatabase.get_collection(MongoCollectionsNames.AI_LEAD_QUERY_CACHE)
    index_jobs_collection = BaseDatabase.get_collection(MongoCollectionsNames.AI_LEAD_INDEX_JOBS)
    leads_collection = BaseDatabase.get_collection(MongoCollectionsNames.LEADS)
    comments_collection = BaseDatabase.get_collection(MongoCollectionsNames.LEAD_COMMENTS)

    # Per-project embedding cache with TTL and max-project guardrails.
    _embedding_cache: OrderedDict[str, dict[str, Any]] = OrderedDict()

    def _project_key(self, tenant_id: str, lead_code: str) -> str:
        return f"{tenant_id}:{lead_code}"

    def _lead_exists(self, tenant_id: str, lead_code: str) -> bool:
        return (
            self.leads_collection.find_one(
                {"tenant_id": tenant_id, "lead_code": lead_code},
                {"_id": 1},
            )
            is not None
        )

    def _invalidate_project_cache(self, tenant_id: str, lead_code: str) -> None:
        key = self._project_key(tenant_id=tenant_id, lead_code=lead_code)
        self._embedding_cache.pop(key, None)

    def _invalidate_query_cache(self, tenant_id: str, lead_code: str) -> None:
        self.query_cache_collection.delete_many({"tenant_id": tenant_id, "lead_code": lead_code})

    def _evict_cache_if_needed(self) -> None:
        while len(self._embedding_cache) > EMBED_CACHE_MAX_PROJECTS:
            self._embedding_cache.popitem(last=False)

    @staticmethod
    def _normalize_rows(matrix: np.ndarray) -> np.ndarray:
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1.0, norms)
        return matrix / norms

    @staticmethod
    def _normalize_vector(vector: np.ndarray) -> np.ndarray:
        norm = np.linalg.norm(vector)
        if norm == 0:
            return vector
        return vector / norm

    def _load_project_embeddings(self, tenant_id: str, lead_code: str) -> dict[str, Any]:
        key = self._project_key(tenant_id=tenant_id, lead_code=lead_code)
        now = datetime.now(timezone.utc)

        cached = self._embedding_cache.get(key)
        if cached and cached["expires_at"] > now:
            self._embedding_cache.move_to_end(key)
            return cached

        rows = list(
            self.chunks_collection.find(
                {
                    "tenant_id": tenant_id,
                    "lead_code": lead_code,
                },
                {
                    "_id": 0,
                    "chunk_id": 1,
                    "file_id": 1,
                    "chunk_text": 1,
                    "metadata_text": 1,
                    "embedding": 1,
                    "source": 1,
                },
            )
        )

        if not rows:
            entry = {
                "expires_at": now + timedelta(seconds=EMBED_CACHE_TTL_SECONDS),
                "matrix": np.empty((0, 0), dtype=np.float32),
                "rows": [],
            }
            self._embedding_cache[key] = entry
            self._evict_cache_if_needed()
            return entry

        embeddings = np.asarray([row["embedding"] for row in rows], dtype=np.float32)
        matrix = self._normalize_rows(embeddings)

        entry = {
            "expires_at": now + timedelta(seconds=EMBED_CACHE_TTL_SECONDS),
            "matrix": matrix,
            "rows": rows,
        }
        self._embedding_cache[key] = entry
        self._embedding_cache.move_to_end(key)
        self._evict_cache_if_needed()
        return entry

    @staticmethod
    def _sanitize_lead_data(value: Any) -> Any:
        if isinstance(value, dict):
            filtered: dict[str, Any] = {}
            for key, item in value.items():
                lowered = str(key).lower()
                if any(token in lowered for token in ("email", "phone", "mobile")):
                    continue
                if lowered in {"_id", "tenant_id", "created_by", "updated_by", "sales_representative_emails"}:
                    continue

                sanitized_item = LeadRAGService._sanitize_lead_data(item)
                if sanitized_item is None:
                    continue
                filtered[key] = sanitized_item
            return filtered

        if isinstance(value, list):
            sanitized_list = [LeadRAGService._sanitize_lead_data(item) for item in value]
            return [item for item in sanitized_list if item is not None]

        return value

    def _build_lead_context(self, tenant_id: str, lead_code: str) -> dict[str, Any]:
        lead_row = self.leads_collection.find_one(
            {
                "tenant_id": tenant_id,
                "lead_code": lead_code,
            },
            {"_id": 0},
        )

        sanitized_lead = self._sanitize_lead_data(lead_row or {})

        comments_rows = list(
            self.comments_collection.find(
                {
                    "tenant_id": tenant_id,
                    "lead_code": lead_code,
                },
                {
                    "_id": 0,
                    "comment": 1,
                    "created_at": 1,
                },
            )
            .sort("created_at", -1)
            .limit(LEAD_CONTEXT_COMMENTS_LIMIT)
        )

        comments_context: list[dict[str, str]] = []
        for row in comments_rows:
            comment_text = str(row.get("comment", "")).strip()
            if not comment_text:
                continue

            created_at = row.get("created_at")
            created_at_text = ""
            if isinstance(created_at, datetime):
                created_at_text = self._format_dt_ist(created_at)

            comments_context.append(
                {
                    "comment": comment_text,
                    "created_at": created_at_text,
                }
            )

        context_payload = {
            "lead": sanitized_lead,
            "comments": comments_context,
        }
        context_signature = hashlib.sha256(
            json.dumps(context_payload, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()

        return {
            "payload": context_payload,
            "signature": context_signature,
        }

    @staticmethod
    def _format_lead_context(context_payload: dict[str, Any]) -> str:
        lead_json = json.dumps(context_payload.get("lead", {}), indent=2, default=str)
        comments = context_payload.get("comments", [])

        if comments:
            comments_lines = []
            for idx, row in enumerate(comments, start=1):
                created_at = row.get("created_at", "")
                comment_text = row.get("comment", "")
                comments_lines.append(
                    f"{idx}. [{created_at}] {comment_text}" if created_at else f"{idx}. {comment_text}"
                )
            comments_text = "\n".join(comments_lines)
        else:
            comments_text = "No comments available."

        return (
            "Lead profile (without email/phone fields):\n"
            f"```json\n{lead_json}\n```\n\n"
            "Recent lead comments:\n"
            f"{comments_text}"
        )

    def _build_prompt(self, question: str, chunks: list[dict], lead_context_text: str) -> str:
        base_prompt = Stitcher().stitch_context(filename="lead_rag_qa_prompt")
        context = self._format_context(chunks)
        return (
            f"{base_prompt}\n\n"
            f"[Lead Context]\n{lead_context_text}\n\n"
            f"[Knowledge Context]\n{context}\n\n"
            f"[User Question]\n{question}\n\n"
            "Respond in markdown only."
        )

    @staticmethod
    def _decode_text_file(file_bytes: bytes) -> str:
        return file_bytes.decode("utf-8", errors="ignore").strip()

    @staticmethod
    def _format_dt_ist(value: datetime) -> str:
        dt_value = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return dt_value.astimezone(IST_TZ).strftime("%H:%M:%S %d-%m-%Y IST")

    @staticmethod
    def _decode_pdf_text(file_bytes: bytes) -> str:
        if PdfReader is None:
            return ""
        try:
            reader = PdfReader(BytesIO(file_bytes))
            texts: list[str] = []
            for page in reader.pages:
                page_text = (page.extract_text() or "").strip()
                if page_text:
                    texts.append(page_text)
            return "\n\n".join(texts).strip()
        except Exception:
            return ""

    def _extract_scanned_pdf_text_via_ai(self, file_name: str, file_bytes: bytes) -> str:
        if not OPENAI_API_KEY:
            return ""

        try:
            encoded_pdf = base64.b64encode(file_bytes).decode("utf-8")
            payload = {
                "model": MODEL,
                "reasoning": {"effort": REASONING_EFFORT},
                "input": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": (
                                    "Extract readable text from this PDF document. "
                                    "Return plain text only, preserving headings, bullets and table lines where possible."
                                ),
                            },
                            {
                                "type": "input_file",
                                "filename": file_name,
                                "file_data": f"data:application/pdf;base64,{encoded_pdf}",
                            },
                        ],
                    }
                ],
            }
            response = requests.post(
                OPENAI_RESPONSES_URL,
                headers=self._headers(),
                json=payload,
                timeout=240,
            )
            if response.status_code >= 400:
                return ""
            return self._extract_output_text(response.json()).strip()
        except Exception:
            return ""

    def _extract_text_for_embedding(self, file_name: str, content_type: str, file_bytes: bytes) -> tuple[str, str]:
        if content_type == "application/pdf":
            extracted = self._decode_pdf_text(file_bytes)
            if extracted:
                return extracted, "pdf_native"

            extracted = self._extract_scanned_pdf_text_via_ai(file_name=file_name, file_bytes=file_bytes)
            if extracted:
                return extracted, "pdf_ai_ocr"

            return "", "pdf_unreadable"

        return self._decode_text_file(file_bytes), "text"

    @staticmethod
    def _safe_content_type(filename: str, content_type: str | None) -> str:
        if content_type:
            return content_type
        lowered = filename.lower()
        if lowered.endswith(".pdf"):
            return "application/pdf"
        if lowered.endswith(".json"):
            return "application/json"
        if lowered.endswith(".csv"):
            return "text/csv"
        if lowered.endswith(".md"):
            return "text/markdown"
        if lowered.endswith(".txt"):
            return "text/plain"
        return "application/octet-stream"

    @staticmethod
    def _is_supported_text_content(content_type: str) -> bool:
        return content_type.startswith("text/") or content_type in {
            "application/pdf",
            "application/json",
            "application/csv",
            "text/csv",
        }

    @staticmethod
    def _chunk_text(text: str) -> list[str]:
        lines = text.splitlines()
        if not lines:
            return []

        chunks: list[str] = []
        current: list[str] = []
        current_chars = 0

        for line in lines:
            line_chars = len(line) + 1
            if line_chars > CHUNK_SIZE_CHARS:
                if current:
                    chunks.append("\n".join(current).strip())
                    current = current[-CHUNK_OVERLAP_LINES:] if CHUNK_OVERLAP_LINES > 0 else []
                    current_chars = sum(len(x) + 1 for x in current)

                start = 0
                while start < len(line):
                    end = min(start + CHUNK_SIZE_CHARS, len(line))
                    part = line[start:end]
                    if part.strip():
                        chunks.append(part.strip())
                    start = end
                continue

            if current_chars + line_chars > CHUNK_SIZE_CHARS and current:
                chunks.append("\n".join(current).strip())
                current = current[-CHUNK_OVERLAP_LINES:] if CHUNK_OVERLAP_LINES > 0 else []
                current_chars = sum(len(x) + 1 for x in current)

            current.append(line)
            current_chars += line_chars

        if current:
            chunks.append("\n".join(current).strip())

        return [chunk for chunk in chunks if chunk]

    @staticmethod
    def _headers() -> dict[str, str]:
        return {
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        }

    def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        payload = {
            "model": EMBEDDING_MODEL,
            "input": batch,
        }
        response = requests.post(OPENAI_EMBEDDINGS_URL, headers=self._headers(), json=payload, timeout=60)
        response.raise_for_status()
        data = response.json().get("data", [])
        return [item.get("embedding", []) for item in data]

    def _embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        batches: list[tuple[int, list[str]]] = []
        for i in range(0, len(texts), EMBEDDING_BATCH_SIZE):
            batches.append((i, texts[i : i + EMBEDDING_BATCH_SIZE]))

        all_vectors: list[list[float]] = [[] for _ in texts]
        with ThreadPoolExecutor(max_workers=EMBEDDING_CONCURRENCY) as executor:
            futures = {executor.submit(self._embed_batch, batch): start for start, batch in batches}
            for future in as_completed(futures):
                start = futures[future]
                vectors = future.result()
                for offset, vector in enumerate(vectors):
                    all_vectors[start + offset] = vector

        return all_vectors

    def _retrieve_top_chunks(
        self, tenant_id: str, lead_code: str, query_embedding: list[float], top_k: int
    ) -> list[dict]:
        cache = self._load_project_embeddings(tenant_id=tenant_id, lead_code=lead_code)
        matrix: np.ndarray = cache["matrix"]
        rows: list[dict] = cache["rows"]

        if matrix.size == 0 or not rows:
            return []

        query_vec = self._normalize_vector(np.asarray(query_embedding, dtype=np.float32))
        scores = matrix.dot(query_vec)
        k = min(max(top_k, 1), len(rows))

        if k == len(rows):
            top_indices = np.argsort(scores)[::-1]
        else:
            top_indices = np.argpartition(scores, -k)[-k:]
            top_indices = top_indices[np.argsort(scores[top_indices])[::-1]]

        results: list[dict] = []
        for idx in top_indices:
            row = rows[int(idx)]
            results.append(
                {
                    "chunk_id": row.get("chunk_id"),
                    "file_id": row.get("file_id"),
                    "source": row.get("source", ""),
                    "metadata_text": row.get("metadata_text", ""),
                    "chunk_text": row.get("chunk_text", ""),
                    "score": float(scores[int(idx)]),
                }
            )
        return results

    @staticmethod
    def _build_metadata_text(
        title: str,
        source: str,
        lead_code: str,
        tenant_id: str,
        actor: str,
        content_type: str,
    ) -> str:
        # Keep metadata minimal for model context quality and privacy.
        parts = [
            f"title: {title}",
            f"source: {source}",
        ]
        return " | ".join(parts)

    def _set_index_job_status(self, job_id: str, status: str, extra_fields: dict | None = None) -> None:
        update_data: dict[str, Any] = {
            "status": status,
            "updated_at": datetime.now(timezone.utc),
        }
        if extra_fields:
            update_data.update(extra_fields)

        self.index_jobs_collection.update_one(
            {"job_id": job_id},
            {"$set": update_data},
        )

    def _push_index_job_result(self, job_id: str, row: dict[str, Any]) -> None:
        self.index_jobs_collection.update_one(
            {"job_id": job_id},
            {
                "$push": {
                    "results": {
                        "$each": [row],
                        "$slice": -INDEX_JOB_RESULTS_MAX_ITEMS,
                    }
                },
                "$inc": {"processed_files": 1},
                "$set": {"updated_at": datetime.now(timezone.utc)},
            },
        )

    def _process_single_uploaded_file(
        self,
        file_obj: dict[str, Any],
        lead_code: str,
        tenant_id: str,
        current_user_email: str,
        source: str,
    ) -> dict[str, Any]:
        file_name = str(file_obj.get("file_name", "")).strip()
        file_bytes = file_obj.get("file_bytes", b"")
        content_type = self._safe_content_type(file_name, file_obj.get("content_type"))

        if not file_name:
            return {"status": "skipped", "file_name": "", "message": "Invalid file name."}

        if not file_bytes:
            return {"status": "skipped", "file_name": file_name, "message": "Empty file."}

        if len(file_bytes) > MAX_FILE_SIZE_BYTES:
            return {
                "status": "skipped",
                "file_name": file_name,
                "message": f"File size exceeds {ProjectConfig.CODE_INDEX_MAX_FILE_SIZE_MB}MB.",
            }

        if not self._is_supported_text_content(content_type):
            return {
                "status": "skipped",
                "file_name": file_name,
                "message": "Only text, markdown, csv, json and pdf files are supported.",
            }

        file_id = str(uuid.uuid4())
        uploaded_at = datetime.now(timezone.utc)

        self.files_collection.insert_one(
            {
                "file_id": file_id,
                "tenant_id": tenant_id,
                "lead_code": lead_code,
                "file_name": file_name,
                "content_type": content_type,
                "size_bytes": len(file_bytes),
                "file_bytes": file_bytes,
                "source": source,
                "is_indexed": False,
                "indexing_status": "processing",
                "chunk_count": 0,
                "uploaded_by": current_user_email,
                "uploaded_at": uploaded_at,
            }
        )

        text, extraction_mode = self._extract_text_for_embedding(
            file_name=file_name,
            content_type=content_type,
            file_bytes=file_bytes,
        )
        if not text:
            self.files_collection.update_one(
                {
                    "tenant_id": tenant_id,
                    "lead_code": lead_code,
                    "file_id": file_id,
                },
                {
                    "$set": {
                        "indexing_status": "failed",
                        "indexing_error": "No readable text found.",
                        "is_indexed": False,
                        "indexing_mode": extraction_mode,
                        "indexed_at": datetime.now(timezone.utc),
                    }
                },
            )
            return {
                "status": "failed",
                "file_id": file_id,
                "file_name": file_name,
                "message": "No readable text found.",
            }

        chunks = self._chunk_text(text)
        if not chunks:
            self.files_collection.update_one(
                {
                    "tenant_id": tenant_id,
                    "lead_code": lead_code,
                    "file_id": file_id,
                },
                {
                    "$set": {
                        "indexing_status": "failed",
                        "indexing_error": "No chunkable content found.",
                        "is_indexed": False,
                        "indexing_mode": extraction_mode,
                        "indexed_at": datetime.now(timezone.utc),
                    }
                },
            )
            return {
                "status": "failed",
                "file_id": file_id,
                "file_name": file_name,
                "message": "No chunkable content found.",
            }

        metadata_text = self._build_metadata_text(
            title=file_name,
            source=source,
            lead_code=lead_code,
            tenant_id=tenant_id,
            actor=current_user_email,
            content_type=content_type,
        )

        chunk_docs: list[dict[str, Any]] = []
        for index, chunk in enumerate(chunks):
            chunk_docs.append(
                {
                    "chunk_id": str(uuid.uuid4()),
                    "file_id": file_id,
                    "tenant_id": tenant_id,
                    "lead_code": lead_code,
                    "source": source,
                    "chunk_number": index + 1,
                    "chunk_text": chunk,
                    "metadata_text": metadata_text,
                    "created_by": current_user_email,
                    "created_at": uploaded_at,
                }
            )

        try:
            vectors = self._embed_texts([chunk["chunk_text"] for chunk in chunk_docs])
            for i, vector in enumerate(vectors):
                chunk_docs[i]["embedding"] = vector
            self.chunks_collection.insert_many(chunk_docs)

            self.files_collection.update_one(
                {
                    "tenant_id": tenant_id,
                    "lead_code": lead_code,
                    "file_id": file_id,
                },
                {
                    "$set": {
                        "is_indexed": True,
                        "indexing_status": "completed",
                        "indexing_error": "",
                        "indexing_mode": extraction_mode,
                        "chunk_count": len(chunk_docs),
                        "indexed_at": datetime.now(timezone.utc),
                    }
                },
            )
        except Exception:
            self.files_collection.update_one(
                {
                    "tenant_id": tenant_id,
                    "lead_code": lead_code,
                    "file_id": file_id,
                },
                {
                    "$set": {
                        "is_indexed": False,
                        "indexing_status": "failed",
                        "indexing_error": "Failed to generate embeddings.",
                        "indexing_mode": extraction_mode,
                        "indexed_at": datetime.now(timezone.utc),
                    }
                },
            )
            self.chunks_collection.delete_many(
                {
                    "tenant_id": tenant_id,
                    "lead_code": lead_code,
                    "file_id": file_id,
                }
            )
            return {
                "status": "failed",
                "file_id": file_id,
                "file_name": file_name,
                "message": "Failed to index file content.",
            }

        return {
            "status": "completed",
            "file_id": file_id,
            "file_name": file_name,
            "chunk_count": len(chunk_docs),
            "size_bytes": len(file_bytes),
        }

    def _run_index_job(
        self,
        job_id: str,
        files: list[dict[str, Any]],
        lead_code: str,
        tenant_id: str,
        current_user_email: str,
        source: str,
    ) -> None:
        self._set_index_job_status(job_id=job_id, status="processing")

        indexed_count = 0
        failed_count = 0
        skipped_count = 0

        try:
            for file_obj in files:
                result = self._process_single_uploaded_file(
                    file_obj=file_obj,
                    lead_code=lead_code,
                    tenant_id=tenant_id,
                    current_user_email=current_user_email,
                    source=source,
                )
                result_status = result.get("status", "failed")
                if result_status == "completed":
                    indexed_count += 1
                elif result_status == "skipped":
                    skipped_count += 1
                else:
                    failed_count += 1

                self._push_index_job_result(job_id=job_id, row=result)

            final_status = "completed" if failed_count == 0 else "completed_with_errors"
            self._set_index_job_status(
                job_id=job_id,
                status=final_status,
                extra_fields={
                    "indexed_files": indexed_count,
                    "failed_files": failed_count,
                    "skipped_files": skipped_count,
                    "finished_at": datetime.now(timezone.utc),
                },
            )
        except Exception:
            self._set_index_job_status(
                job_id=job_id,
                status="failed",
                extra_fields={
                    "failed_files": failed_count + 1,
                    "finished_at": datetime.now(timezone.utc),
                    "error_message": "Background indexing failed.",
                },
            )
        finally:
            self._invalidate_project_cache(tenant_id=tenant_id, lead_code=lead_code)
            self._invalidate_query_cache(tenant_id=tenant_id, lead_code=lead_code)

    def index_files(
        self,
        files: list[dict[str, Any]],
        lead_code: str,
        tenant_id: str,
        current_user_email: str,
        source: str = "uploaded_file",
    ) -> tuple[dict, int]:
        if not OPENAI_API_KEY:
            return {"is_successful": False, "message": "AI service is not configured."}, HTTPStatus.BAD_REQUEST

        if not lead_code.strip():
            return {"is_successful": False, "message": "lead_code is required."}, HTTPStatus.BAD_REQUEST

        if not self._lead_exists(tenant_id=tenant_id, lead_code=lead_code):
            return {"is_successful": False, "message": "Lead not found."}, HTTPStatus.NOT_FOUND

        if not files:
            return {"is_successful": False, "message": "No files provided."}, HTTPStatus.BAD_REQUEST

        if len(files) > MAX_FILES:
            return {
                "is_successful": False,
                "message": f"Maximum {MAX_FILES} files are allowed in one request.",
            }, HTTPStatus.BAD_REQUEST

        job_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc)
        self.index_jobs_collection.insert_one(
            {
                "job_id": job_id,
                "tenant_id": tenant_id,
                "lead_code": lead_code,
                "status": "queued",
                "total_files": len(files),
                "processed_files": 0,
                "indexed_files": 0,
                "failed_files": 0,
                "skipped_files": 0,
                "results": [],
                "error_message": "",
                "created_by": current_user_email,
                "created_at": created_at,
                "updated_at": created_at,
            }
        )

        worker = threading.Thread(
            target=self._run_index_job,
            kwargs={
                "job_id": job_id,
                "files": files,
                "lead_code": lead_code,
                "tenant_id": tenant_id,
                "current_user_email": current_user_email,
                "source": source,
            },
            name=f"rag-index-job-{job_id[:8]}",
            daemon=True,
        )
        worker.start()

        return {
            "is_successful": True,
            "message": "File indexing started in background.",
            "job_id": job_id,
            "status": "queued",
            "total_files": len(files),
        }, HTTPStatus.ACCEPTED

    def get_index_job_status(self, tenant_id: str, lead_code: str, job_id: str) -> tuple[dict, int]:
        row = self.index_jobs_collection.find_one(
            {
                "job_id": job_id,
                "tenant_id": tenant_id,
                "lead_code": lead_code,
            },
            {"_id": 0},
        )
        if not row:
            return {"is_successful": False, "message": "Index job not found."}, HTTPStatus.NOT_FOUND

        created_at = row.get("created_at")
        if isinstance(created_at, datetime):
            row["created_at"] = self._format_dt_ist(created_at)
        updated_at = row.get("updated_at")
        if isinstance(updated_at, datetime):
            row["updated_at"] = self._format_dt_ist(updated_at)
        finished_at = row.get("finished_at")
        if isinstance(finished_at, datetime):
            row["finished_at"] = self._format_dt_ist(finished_at)

        return {"is_successful": True, "job": row}, HTTPStatus.OK

    def index_text(
        self,
        request_data: dict,
        tenant_id: str,
        current_user_email: str,
    ) -> tuple[dict, int]:
        if not OPENAI_API_KEY:
            return {"is_successful": False, "message": "AI service is not configured."}, HTTPStatus.BAD_REQUEST

        try:
            parsed = IndexTextRequest.model_validate(request_data)
        except ValidationError:
            return {"is_successful": False, "message": "Invalid text indexing request."}, HTTPStatus.BAD_REQUEST

        if not self._lead_exists(tenant_id=tenant_id, lead_code=parsed.lead_code):
            return {"is_successful": False, "message": "Lead not found."}, HTTPStatus.NOT_FOUND

        chunks = self._chunk_text(parsed.text)
        if not chunks:
            return {
                "is_successful": False,
                "message": "Text does not contain indexable content.",
            }, HTTPStatus.BAD_REQUEST

        created_at = datetime.now(timezone.utc)
        metadata_text = self._build_metadata_text(
            title=parsed.title,
            source=parsed.source,
            lead_code=parsed.lead_code,
            tenant_id=tenant_id,
            actor=current_user_email,
            content_type="text/plain",
        )

        chunk_docs = []
        for index, chunk in enumerate(chunks):
            chunk_docs.append(
                {
                    "chunk_id": str(uuid.uuid4()),
                    "file_id": None,
                    "tenant_id": tenant_id,
                    "lead_code": parsed.lead_code,
                    "source": parsed.source,
                    "chunk_number": index + 1,
                    "chunk_text": chunk,
                    "metadata_text": metadata_text,
                    "created_by": current_user_email,
                    "created_at": created_at,
                }
            )

        try:
            vectors = self._embed_texts([chunk["chunk_text"] for chunk in chunk_docs])
            for i, vector in enumerate(vectors):
                chunk_docs[i]["embedding"] = vector

            self.chunks_collection.insert_many(chunk_docs)
            self._invalidate_project_cache(tenant_id=tenant_id, lead_code=parsed.lead_code)
            self._invalidate_query_cache(tenant_id=tenant_id, lead_code=parsed.lead_code)
        except Exception:
            return {
                "is_successful": False,
                "message": "Failed to index text.",
            }, HTTPStatus.BAD_GATEWAY

        return {
            "is_successful": True,
            "message": "Text indexed successfully.",
            "chunks_indexed": len(chunk_docs),
        }, HTTPStatus.OK

    def fetch_files(self, tenant_id: str, lead_code: str, batch_number: int, batch_size: int) -> tuple[dict, int]:
        if batch_size <= 0:
            return {"is_successful": False, "message": "batch_size must be greater than 0."}, HTTPStatus.BAD_REQUEST

        if not self._lead_exists(tenant_id=tenant_id, lead_code=lead_code):
            return {"is_successful": False, "message": "Lead not found."}, HTTPStatus.NOT_FOUND

        batch_number = max(batch_number, 1)
        skip = (batch_number - 1) * batch_size

        query = {
            "tenant_id": tenant_id,
            "lead_code": lead_code,
        }

        total = self.files_collection.count_documents(query)
        rows = list(
            self.files_collection.find(
                query,
                {
                    "_id": 0,
                    "file_id": 1,
                    "file_name": 1,
                    "content_type": 1,
                    "size_bytes": 1,
                    "source": 1,
                    "is_indexed": 1,
                    "chunk_count": 1,
                    "uploaded_by": 1,
                    "uploaded_at": 1,
                },
            )
            .sort("uploaded_at", -1)
            .skip(skip)
            .limit(batch_size)
        )

        for row in rows:
            uploaded_at = row.get("uploaded_at")
            if isinstance(uploaded_at, datetime):
                row["uploaded_at"] = self._format_dt_ist(uploaded_at)

        total_pages = max(math.ceil(total / batch_size), 1) if total else 0

        return {
            "is_successful": True,
            "files": rows,
            "total": total,
            "total_pages": total_pages,
        }, HTTPStatus.OK

    def download_file(self, tenant_id: str, lead_code: str, file_id: str) -> tuple[dict, int]:
        if not self._lead_exists(tenant_id=tenant_id, lead_code=lead_code):
            return {"is_successful": False, "message": "Lead not found."}, HTTPStatus.NOT_FOUND

        row = self.files_collection.find_one(
            {
                "tenant_id": tenant_id,
                "lead_code": lead_code,
                "file_id": file_id,
            },
            {
                "_id": 0,
                "file_id": 1,
                "file_name": 1,
                "content_type": 1,
                "file_bytes": 1,
            },
        )
        if not row:
            return {"is_successful": False, "message": "File not found."}, HTTPStatus.NOT_FOUND

        return {
            "is_successful": True,
            "file_id": row["file_id"],
            "file_name": row["file_name"],
            "content_type": row.get("content_type", "application/octet-stream"),
            "file_bytes": row.get("file_bytes", b""),
        }, HTTPStatus.OK

    def delete_indexed_file(self, tenant_id: str, lead_code: str, file_id: str) -> tuple[dict, int]:
        if not self._lead_exists(tenant_id=tenant_id, lead_code=lead_code):
            return {"is_successful": False, "message": "Lead not found."}, HTTPStatus.NOT_FOUND

        file_row = self.files_collection.find_one(
            {
                "tenant_id": tenant_id,
                "lead_code": lead_code,
                "file_id": file_id,
            },
            {"_id": 0, "file_name": 1},
        )
        if not file_row:
            return {"is_successful": False, "message": "File not found."}, HTTPStatus.NOT_FOUND

        self.files_collection.delete_one(
            {
                "tenant_id": tenant_id,
                "lead_code": lead_code,
                "file_id": file_id,
            }
        )
        deleted_chunks = self.chunks_collection.delete_many(
            {
                "tenant_id": tenant_id,
                "lead_code": lead_code,
                "file_id": file_id,
            }
        )

        self._invalidate_project_cache(tenant_id=tenant_id, lead_code=lead_code)
        self._invalidate_query_cache(tenant_id=tenant_id, lead_code=lead_code)

        return {
            "is_successful": True,
            "message": "File deleted successfully.",
            "file_id": file_id,
            "file_name": file_row.get("file_name", ""),
            "deleted_chunks": deleted_chunks.deleted_count,
        }, HTTPStatus.OK

    def reindex_file(self, tenant_id: str, lead_code: str, file_id: str, current_user_email: str) -> tuple[dict, int]:
        if not self._lead_exists(tenant_id=tenant_id, lead_code=lead_code):
            return {"is_successful": False, "message": "Lead not found."}, HTTPStatus.NOT_FOUND

        file_row = self.files_collection.find_one(
            {
                "tenant_id": tenant_id,
                "lead_code": lead_code,
                "file_id": file_id,
            },
            {
                "_id": 0,
                "file_name": 1,
                "content_type": 1,
                "file_bytes": 1,
                "source": 1,
            },
        )
        if not file_row:
            return {"is_successful": False, "message": "File not found."}, HTTPStatus.NOT_FOUND

        file_name = str(file_row.get("file_name", "")).strip()
        content_type = self._safe_content_type(file_name, file_row.get("content_type"))
        file_bytes = file_row.get("file_bytes", b"")

        if not file_name or not file_bytes:
            return {
                "is_successful": False,
                "message": "File content is missing and cannot be reindexed.",
            }, HTTPStatus.BAD_REQUEST

        if not self._is_supported_text_content(content_type):
            return {
                "is_successful": False,
                "message": "Only text, markdown, csv, json and pdf files can be reindexed.",
            }, HTTPStatus.BAD_REQUEST

        text, extraction_mode = self._extract_text_for_embedding(
            file_name=file_name,
            content_type=content_type,
            file_bytes=file_bytes,
        )
        chunks = self._chunk_text(text)
        if not chunks:
            return {
                "is_successful": False,
                "message": "No chunkable content found.",
            }, HTTPStatus.BAD_REQUEST

        metadata_text = self._build_metadata_text(
            title=file_name,
            source=file_row.get("source", "uploaded_file"),
            lead_code=lead_code,
            tenant_id=tenant_id,
            actor=current_user_email,
            content_type=content_type,
        )

        chunk_docs = []
        created_at = datetime.now(timezone.utc)
        for index, chunk in enumerate(chunks):
            chunk_docs.append(
                {
                    "chunk_id": str(uuid.uuid4()),
                    "file_id": file_id,
                    "tenant_id": tenant_id,
                    "lead_code": lead_code,
                    "source": file_row.get("source", "uploaded_file"),
                    "chunk_number": index + 1,
                    "chunk_text": chunk,
                    "metadata_text": metadata_text,
                    "created_by": current_user_email,
                    "created_at": created_at,
                }
            )

        try:
            vectors = self._embed_texts([chunk["chunk_text"] for chunk in chunk_docs])
            for i, vector in enumerate(vectors):
                chunk_docs[i]["embedding"] = vector

            self.chunks_collection.delete_many(
                {
                    "tenant_id": tenant_id,
                    "lead_code": lead_code,
                    "file_id": file_id,
                }
            )
            self.chunks_collection.insert_many(chunk_docs)
            self.files_collection.update_one(
                {
                    "tenant_id": tenant_id,
                    "lead_code": lead_code,
                    "file_id": file_id,
                },
                {
                    "$set": {
                        "is_indexed": True,
                        "chunk_count": len(chunk_docs),
                        "indexing_mode": extraction_mode,
                        "reindexed_by": current_user_email,
                        "reindexed_at": created_at,
                    }
                },
            )

            self._invalidate_project_cache(tenant_id=tenant_id, lead_code=lead_code)
            self._invalidate_query_cache(tenant_id=tenant_id, lead_code=lead_code)
        except Exception:
            return {
                "is_successful": False,
                "message": "Failed to reindex file.",
            }, HTTPStatus.BAD_GATEWAY

        return {
            "is_successful": True,
            "message": "File reindexed successfully.",
            "file_id": file_id,
            "file_name": file_name,
            "chunk_count": len(chunk_docs),
        }, HTTPStatus.OK

    @staticmethod
    def _format_context(chunks: list[dict]) -> str:
        blocks = []
        for idx, chunk in enumerate(chunks, start=1):
            block = (
                f"[Chunk {idx}]\n"
                f"Source: {chunk.get('source', '')}\n"
                f"Metadata: {chunk.get('metadata_text', '')}\n"
                f"Text:\n{chunk.get('chunk_text', '')}"
            )
            blocks.append(block)
        return "\n\n".join(blocks)

    def _find_semantic_cache(
        self,
        tenant_id: str,
        lead_code: str,
        query_embedding: list[float],
        context_signature: str,
    ) -> dict | None:
        if not ProjectConfig.QUERY_CACHE_ENABLED:
            return None

        rows = list(
            self.query_cache_collection.find(
                {
                    "tenant_id": tenant_id,
                    "lead_code": lead_code,
                    "context_signature": context_signature,
                },
                {
                    "_id": 0,
                    "response_markdown": 1,
                    "citations": 1,
                    "question_embedding": 1,
                },
            )
            .sort("created_at", -1)
            .limit(200)
        )

        if not rows:
            return None

        query_vec = self._normalize_vector(np.asarray(query_embedding, dtype=np.float32))
        threshold = ProjectConfig.QUERY_CACHE_SIMILARITY_THRESHOLD

        best_row = None
        best_score = -1.0

        for row in rows:
            emb = row.get("question_embedding")
            if not emb:
                continue
            emb_vec = self._normalize_vector(np.asarray(emb, dtype=np.float32))
            score = float(query_vec.dot(emb_vec))
            if score > best_score:
                best_score = score
                best_row = row

        if best_row and best_score >= threshold:
            return {
                "markdown": best_row.get("response_markdown", ""),
                "citations": best_row.get("citations", []),
                "cache_score": best_score,
            }

        return None

    def _save_query_cache(
        self,
        tenant_id: str,
        lead_code: str,
        current_user_email: str,
        question: str,
        question_embedding: list[float],
        markdown: str,
        citations: list[dict],
        context_signature: str,
    ) -> None:
        if not ProjectConfig.QUERY_CACHE_ENABLED:
            return

        self.query_cache_collection.insert_one(
            {
                "query_id": str(uuid.uuid4()),
                "tenant_id": tenant_id,
                "lead_code": lead_code,
                "question": question,
                "question_embedding": question_embedding,
                "response_markdown": markdown,
                "citations": citations,
                "context_signature": context_signature,
                "created_by": current_user_email,
                "created_at": datetime.now(timezone.utc),
            }
        )

    def _responses_payload(self, prompt_text: str) -> dict[str, Any]:
        return {
            "model": MODEL,
            "reasoning": {"effort": REASONING_EFFORT},
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": prompt_text,
                        }
                    ],
                }
            ],
        }

    @staticmethod
    def _extract_output_text(response_json: dict) -> str:
        if isinstance(response_json.get("output_text"), str):
            return response_json["output_text"]

        output = response_json.get("output", [])
        chunks: list[str] = []
        for item in output:
            for content in item.get("content", []):
                text = content.get("text")
                if isinstance(text, str):
                    chunks.append(text)
        return "\n".join(chunks).strip()

    def ask_question(self, request_data: dict, tenant_id: str, current_user_email: str) -> tuple[dict, int]:
        if not OPENAI_API_KEY:
            return {"is_successful": False, "message": "AI service is not configured."}, HTTPStatus.BAD_REQUEST

        try:
            parsed = AskQuestionRequest.model_validate(request_data)
        except ValidationError:
            return {"is_successful": False, "message": "Invalid ask-question request."}, HTTPStatus.BAD_REQUEST

        if not self._lead_exists(tenant_id=tenant_id, lead_code=parsed.lead_code):
            return {"is_successful": False, "message": "Lead not found."}, HTTPStatus.NOT_FOUND

        lead_context = self._build_lead_context(tenant_id=tenant_id, lead_code=parsed.lead_code)
        lead_context_text = self._format_lead_context(lead_context["payload"])

        k = parsed.top_k if parsed.top_k and parsed.top_k > 0 else TOP_K
        try:
            question_embedding = self._embed_texts([parsed.question])[0]
        except Exception:
            return {
                "is_successful": False,
                "message": "Failed to process question embedding.",
            }, HTTPStatus.BAD_GATEWAY

        cached = self._find_semantic_cache(
            tenant_id=tenant_id,
            lead_code=parsed.lead_code,
            query_embedding=question_embedding,
            context_signature=lead_context["signature"],
        )
        if cached:
            return {
                "is_successful": True,
                "is_cached": True,
                "markdown_answer": cached["markdown"],
                "citations": cached.get("citations", []),
            }, HTTPStatus.OK

        chunks = self._retrieve_top_chunks(
            tenant_id=tenant_id,
            lead_code=parsed.lead_code,
            query_embedding=question_embedding,
            top_k=k,
        )

        if not chunks:
            return {
                "is_successful": False,
                "message": "No indexed content found for this lead.",
            }, HTTPStatus.NOT_FOUND

        prompt_text = self._build_prompt(
            question=parsed.question,
            chunks=chunks,
            lead_context_text=lead_context_text,
        )
        payload = self._responses_payload(prompt_text=prompt_text)

        try:
            response = requests.post(
                OPENAI_RESPONSES_URL,
                headers=self._headers(),
                json=payload,
                timeout=120,
            )
        except Exception:
            return {
                "is_successful": False,
                "message": "Failed to generate answer.",
            }, HTTPStatus.BAD_GATEWAY
        if response.status_code >= 400:
            return {
                "is_successful": False,
                "message": "Failed to generate answer.",
            }, HTTPStatus.BAD_GATEWAY

        answer_markdown = self._extract_output_text(response.json())

        citations = [
            {
                "chunk_id": chunk.get("chunk_id"),
                "file_id": chunk.get("file_id"),
                "source": chunk.get("source"),
                "score": round(chunk.get("score", 0.0), 5),
            }
            for chunk in chunks
        ]

        self._save_query_cache(
            tenant_id=tenant_id,
            lead_code=parsed.lead_code,
            current_user_email=current_user_email,
            question=parsed.question,
            question_embedding=question_embedding,
            markdown=answer_markdown,
            citations=citations,
            context_signature=lead_context["signature"],
        )

        return {
            "is_successful": True,
            "is_cached": False,
            "markdown_answer": answer_markdown,
            "citations": citations,
        }, HTTPStatus.OK

    def ask_question_stream(
        self,
        request_data: dict,
        tenant_id: str,
        current_user_email: str,
    ) -> tuple[Generator[str, None, None], dict, int]:
        if not OPENAI_API_KEY:
            return iter(["AI service is not configured."]), {}, HTTPStatus.BAD_REQUEST  # type: ignore

        try:
            parsed = AskQuestionRequest.model_validate(request_data)
        except ValidationError:
            return iter(["Invalid ask-question request."]), {}, HTTPStatus.BAD_REQUEST  # type: ignore

        if not self._lead_exists(tenant_id=tenant_id, lead_code=parsed.lead_code):
            return iter(["Lead not found."]), {}, HTTPStatus.NOT_FOUND  # type: ignore

        lead_context = self._build_lead_context(tenant_id=tenant_id, lead_code=parsed.lead_code)
        lead_context_text = self._format_lead_context(lead_context["payload"])

        k = parsed.top_k if parsed.top_k and parsed.top_k > 0 else TOP_K
        try:
            question_embedding = self._embed_texts([parsed.question])[0]
        except Exception:
            return iter(["Failed to process question embedding."]), {}, HTTPStatus.BAD_GATEWAY  # type: ignore

        cached = self._find_semantic_cache(
            tenant_id=tenant_id,
            lead_code=parsed.lead_code,
            query_embedding=question_embedding,
            context_signature=lead_context["signature"],
        )
        if cached:
            markdown = cached.get("markdown", "")

            def _cached_stream() -> Generator[str, None, None]:
                yield markdown

            meta = {
                "is_cached": True,
                "citations": cached.get("citations", []),
            }
            return _cached_stream(), meta, HTTPStatus.OK

        chunks = self._retrieve_top_chunks(
            tenant_id=tenant_id,
            lead_code=parsed.lead_code,
            query_embedding=question_embedding,
            top_k=k,
        )

        if not chunks:
            return iter(["No indexed content found for this lead."]), {}, HTTPStatus.NOT_FOUND  # type: ignore

        prompt_text = self._build_prompt(
            question=parsed.question,
            chunks=chunks,
            lead_context_text=lead_context_text,
        )
        print("\n\n\n PROMPT TEXT:\n", prompt_text, "\n\n\n")
        payload = self._responses_payload(prompt_text=prompt_text)
        payload["stream"] = True

        try:
            response = requests.post(
                OPENAI_RESPONSES_URL,
                headers=self._headers(),
                json=payload,
                timeout=180,
                stream=True,
            )
        except Exception:
            return iter(["Failed to generate answer."]), {}, HTTPStatus.BAD_GATEWAY  # type: ignore

        if response.status_code >= 400:
            return iter(["Failed to generate answer."]), {}, HTTPStatus.BAD_GATEWAY  # type: ignore

        citations = [
            {
                "chunk_id": chunk.get("chunk_id"),
                "file_id": chunk.get("file_id"),
                "source": chunk.get("source"),
                "score": round(chunk.get("score", 0.0), 5),
            }
            for chunk in chunks
        ]

        def _streamer() -> Generator[str, None, None]:
            collected: list[str] = []
            for raw_line in response.iter_lines(decode_unicode=True):
                if not raw_line:
                    continue
                if not raw_line.startswith("data: "):  # type: ignore
                    continue

                data = raw_line[6:].strip()
                if data == "[DONE]":
                    break

                try:
                    event = json.loads(data)
                except json.JSONDecodeError:
                    continue

                if event.get("type") == "response.output_text.delta":
                    delta = event.get("delta", "")
                    if delta:
                        collected.append(delta)
                        yield delta

            markdown = "".join(collected).strip()
            if markdown:
                self._save_query_cache(
                    tenant_id=tenant_id,
                    lead_code=parsed.lead_code,
                    current_user_email=current_user_email,
                    question=parsed.question,
                    question_embedding=question_embedding,
                    markdown=markdown,
                    citations=citations,
                    context_signature=lead_context["signature"],
                )

        meta = {
            "is_cached": False,
            "citations": citations,
        }
        return _streamer(), meta, HTTPStatus.OK
