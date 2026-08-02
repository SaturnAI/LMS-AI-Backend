from datetime import datetime, timezone

from src.enums import LogActionType, MongoCollectionsNames
from src.mongodb.base import BaseDatabase
from src.utils import fetch_profile


class LogManager:
    collection = BaseDatabase.get_collection(collection_name=MongoCollectionsNames.LOG_MANAGER)

    @classmethod
    def add_log(
        cls,
        current_user_email: str,
        tenant_id: str,
        log_action_type: LogActionType,
        message: str,
    ) -> dict:
        user_data = fetch_profile(email=current_user_email)
        message = f"{user_data['name']}({user_data['email']}) {message}"

        log = {
            "created_at": datetime.now(timezone.utc),
            "action_performer_name": user_data["name"],
            "action_performer_email": user_data["email"],
            "message": message,
            "action_type": log_action_type.value,
            "tenant_id": tenant_id,
        }

        # Perform the upsert operation
        result = cls.collection.insert_one(log)

        # Check the operation result
        if result.inserted_id is not None:
            return {"is_successful": True, "message": "Log successfully added."}

        return {"is_successful": False, "message": "Failed to add the log. Please try again."}

    @classmethod
    def fetch_logs(cls, tenant_id: str, page_number: int, search_query: str = "") -> dict:
        BATCH_SIZE = 50
        skip = BATCH_SIZE * (page_number - 1)

        search_query = search_query.strip()

        query: dict = {"tenant_id": tenant_id}
        if search_query:
            query["$or"] = [
                {"date": {"$regex": search_query, "$options": "i"}},
                {"action_performer_name": {"$regex": search_query, "$options": "i"}},
                {"action_performer_email": {"$regex": search_query, "$options": "i"}},
                {"action_type": {"$regex": search_query, "$options": "i"}},
                {"message": {"$regex": search_query, "$options": "i"}},
            ]

        total_logs = cls.collection.count_documents(query)
        total_pages = (total_logs + BATCH_SIZE - 1) // BATCH_SIZE

        pipeline = [
            {"$match": query},
            {"$sort": {"created_at": -1}},
            {"$skip": skip},
            {"$limit": BATCH_SIZE},
            {
                "$project": {
                    "_id": 0,
                    "created_at": {
                        "$dateToString": {
                            "format": "%H:%M:%S %d-%m-%Y IST",
                            "date": "$created_at",
                            "timezone": "Asia/Kolkata",
                        }
                    },
                    "action_performer_name": 1,
                    "action_performer_email": 1,
                    "message": 1,
                    "action_type": 1,
                }
            },
        ]

        logs = list(cls.collection.aggregate(pipeline))

        return {
            "activity_logs": logs,
            "is_successful": True,
            "total_pages": total_pages,
        }
