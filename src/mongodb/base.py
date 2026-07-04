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
