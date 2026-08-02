from pymongo import ASCENDING, DESCENDING, MongoClient, collection

from src.cred import Credentials
from src.enums import MongoCollectionsNames


class BaseDatabase:
    mongo_client = MongoClient(Credentials.mongo_url)
    db = mongo_client[Credentials.db_name]

    @classmethod
    def get_collection(cls, collection_name) -> collection.Collection:
        return cls.db[collection_name]

    @classmethod
    def ensure_indexes(cls):
        """Create required indexes in an idempotent, multi-worker-safe way."""

        user_master = cls.get_collection(MongoCollectionsNames.USER_MASTER)
        company_master = cls.get_collection(MongoCollectionsNames.COMPANY_MASTER)
        log_manager = cls.get_collection(MongoCollectionsNames.LOG_MANAGER)

        # USER_MASTER: email-driven auth/profile access and tenant+role employee listings.
        user_master.create_index([("email", ASCENDING)], name="idx_user_email", unique=True)
        user_master.create_index([("code", ASCENDING)], name="idx_user_code", unique=True)
        user_master.create_index(
            [("tenant_id", ASCENDING), ("role", ASCENDING), ("is_disabled", ASCENDING)],
            name="idx_user_tenant_role_disabled",
        )
        user_master.create_index(
            [("company_code", ASCENDING), ("role", ASCENDING), ("is_disabled", ASCENDING)],
            name="idx_user_company_role_disabled",
        )
        user_master.create_index([("role", ASCENDING), ("is_disabled", ASCENDING)], name="idx_user_role_disabled")

        # COMPANY_MASTER: reads/updates by company_code and company-admin email.
        company_master.create_index([("company_code", ASCENDING)], name="idx_company_code", unique=True)
        company_master.create_index([("email", ASCENDING)], name="idx_company_email", unique=True)

        # LOG_MANAGER: tenant-scoped pagination ordered by newest first.
        log_manager.create_index(
            [("tenant_id", ASCENDING), ("timestamp", DESCENDING)],
            name="idx_log_tenant_timestamp_desc",
        )

        # LEADS: unique lead_code and tenant-scoped queries

        leads = cls.get_collection(MongoCollectionsNames.LEADS)
        leads.create_index([("lead_code", ASCENDING)], name="idx_lead_code", unique=True)
        leads.create_index(
            [("tenant_id", ASCENDING), ("created_at", DESCENDING)],
            name="idx_lead_tenant_created_at",
        )

        lead_comments = cls.get_collection(MongoCollectionsNames.LEAD_COMMENTS)
        lead_comments.create_index([("lead_code", ASCENDING)], name="idx_lead_comments_lead_code")
        lead_comments.create_index(
            [("tenant_id", ASCENDING), ("created_at", DESCENDING)],
            name="idx_lead_comments_tenant_created_at",
        )

        ai_lead_files = cls.get_collection(MongoCollectionsNames.AI_LEAD_FILES)
        ai_lead_files.create_index([("file_id", ASCENDING)], name="idx_ai_lead_file_id", unique=True)
        ai_lead_files.create_index(
            [("tenant_id", ASCENDING), ("lead_code", ASCENDING), ("uploaded_at", DESCENDING)],
            name="idx_ai_lead_files_tenant_lead_uploaded_at",
        )

        ai_lead_chunks = cls.get_collection(MongoCollectionsNames.AI_LEAD_CHUNKS)
        ai_lead_chunks.create_index([("chunk_id", ASCENDING)], name="idx_ai_lead_chunk_id", unique=True)
        ai_lead_chunks.create_index(
            [("tenant_id", ASCENDING), ("lead_code", ASCENDING), ("created_at", DESCENDING)],
            name="idx_ai_lead_chunks_tenant_lead_created_at",
        )
        ai_lead_chunks.create_index(
            [("tenant_id", ASCENDING), ("lead_code", ASCENDING), ("file_id", ASCENDING)],
            name="idx_ai_lead_chunks_tenant_lead_file",
        )

        ai_lead_query_cache = cls.get_collection(MongoCollectionsNames.AI_LEAD_QUERY_CACHE)
        ai_lead_query_cache.create_index([("query_id", ASCENDING)], name="idx_ai_lead_query_id", unique=True)
        ai_lead_query_cache.create_index(
            [("tenant_id", ASCENDING), ("lead_code", ASCENDING), ("created_at", DESCENDING)],
            name="idx_ai_lead_query_cache_tenant_lead_created_at",
        )

        ai_lead_index_jobs = cls.get_collection(MongoCollectionsNames.AI_LEAD_INDEX_JOBS)
        ai_lead_index_jobs.create_index([("job_id", ASCENDING)], name="idx_ai_lead_index_jobs_job_id", unique=True)
        ai_lead_index_jobs.create_index(
            [("tenant_id", ASCENDING), ("lead_code", ASCENDING), ("job_id", ASCENDING)],
            name="idx_ai_lead_index_jobs_tenant_lead_job",
        )
