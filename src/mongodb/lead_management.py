import uuid
from datetime import datetime, timezone
from http import HTTPStatus

from pydantic import ValidationError
from pymongo import ReturnDocument

from src.enums import MongoCollectionsNames, UserRoles
from src.mongodb.base import BaseDatabase
from src.mongodb.log_manager import LogActionType, LogManager
from src.schema import LeadDetails


class LeadManagement:
    collection = BaseDatabase.get_collection(collection_name=MongoCollectionsNames.LEADS)
    user_collection = BaseDatabase.get_collection(collection_name=MongoCollectionsNames.USER_MASTER)
    comments_collection = BaseDatabase.get_collection(collection_name=MongoCollectionsNames.LEAD_COMMENTS)

    def _check_all_sales_representatives_exist(self, emails: list[str], tenant_id: str) -> tuple[bool, list[str]]:
        normalized_emails = list({email.lower().strip() for email in emails if email.strip()})

        users = list(
            self.user_collection.find(
                {
                    "tenant_id": tenant_id,
                    "is_disabled": False,
                    "email": {"$in": normalized_emails},
                },
                {"email": 1, "_id": 0},
            )
        )

        found_emails = {user["email"] for user in users}
        missing_emails = set(normalized_emails) - found_emails

        return len(missing_emails) == 0, normalized_emails

    def create_lead(self, request_data: dict, current_user_email: str, tenant_id: str) -> tuple[dict, int]:
        try:
            validated_request_data = LeadDetails.model_validate(request_data)
        except ValidationError:
            return {"is_successful": False, "message": "Invalid or incomplete request data."}, HTTPStatus.BAD_REQUEST

        lead_data = validated_request_data.model_dump()

        if not validated_request_data.sales_representative_emails:
            return {
                "is_successful": False,
                "message": "At least one sales representative email is required.",
            }, HTTPStatus.BAD_REQUEST

        is_valid, normalized_emails = self._check_all_sales_representatives_exist(
            validated_request_data.sales_representative_emails, tenant_id
        )
        if not is_valid:
            return {
                "is_successful": False,
                "message": f"Sales representative(s) not found or disabled.)",
            }, HTTPStatus.BAD_REQUEST

        lead_data["sales_representative_emails"] = normalized_emails

        lead_code = str(uuid.uuid4())
        lead_record = {
            **lead_data,
            "lead_code": lead_code,
            "tenant_id": tenant_id,
            "created_at": datetime.now(timezone.utc),
            "created_by": current_user_email,
        }

        result = self.collection.insert_one(lead_record)
        if not result.acknowledged:
            return {"is_successful": False, "message": "Failed to create lead."}, HTTPStatus.INTERNAL_SERVER_ERROR

        LogManager.add_log(
            current_user_email=current_user_email,
            tenant_id=tenant_id,
            log_action_type=LogActionType.ADD,
            message=f"ADDED a new lead: {validated_request_data.name}({validated_request_data.email})",
        )

        return {"is_successful": True, "message": "Lead created successfully."}, HTTPStatus.OK

    def update_lead(self, request_data: dict, current_user_email: str, tenant_id: str) -> tuple[dict, int]:
        lead_code = request_data["lead_code"]

        try:
            validated_request_data = LeadDetails.model_validate(request_data)
        except ValidationError:
            return {"is_successful": False, "message": "Invalid or incomplete request data."}, HTTPStatus.BAD_REQUEST

        update_data = validated_request_data.model_dump()

        if not validated_request_data.sales_representative_emails:
            return {
                "is_successful": False,
                "message": "Sales representative emails cannot be empty.",
            }, HTTPStatus.BAD_REQUEST

        is_valid, normalized_emails = self._check_all_sales_representatives_exist(
            validated_request_data.sales_representative_emails, tenant_id
        )
        if not is_valid:
            return {
                "is_successful": False,
                "message": f"Sales representative(s) not found or disabled.",
            }, HTTPStatus.BAD_REQUEST

        update_data["sales_representative_emails"] = normalized_emails

        update_data.update({"updated_at": datetime.now(timezone.utc), "updated_by": current_user_email})

        result = self.collection.find_one_and_update(
            {"lead_code": lead_code, "tenant_id": tenant_id},
            {"$set": update_data},
            return_document=ReturnDocument.AFTER,
        )

        if not result:
            return {"is_successful": False, "message": "Lead not found."}, HTTPStatus.NOT_FOUND

        LogManager.add_log(
            current_user_email=current_user_email,
            tenant_id=tenant_id,
            log_action_type=LogActionType.EDIT,
            message=f"UPDATED lead: {result['name']}({result.get('email')})",
        )

        return {"is_successful": True, "message": "Lead updated successfully."}, HTTPStatus.OK

    def fetch_leads(
        self,
        tenant_id: str,
        current_user_email: str,
        role: str,
        batch_number: int = 1,
        batch_size: int = 10,
        search_query: str = "",
    ) -> tuple[dict, int]:
        skip = batch_size * (max(batch_number, 1) - 1)

        match_filter: dict = {"tenant_id": tenant_id}

        # Restrict visibility for sales representatives
        if role not in {UserRoles.SUPER_ADMIN.value, UserRoles.COMPANY_ADMIN.value}:
            match_filter["sales_representative_emails"] = current_user_email.lower().strip()

        if search_query:
            search_query = search_query.strip()

            match_filter["$or"] = [
                {"name": {"$regex": search_query, "$options": "i"}},
                {"company_name": {"$regex": search_query, "$options": "i"}},
                {"email": {"$regex": search_query, "$options": "i"}},
                {"alt_email": {"$regex": search_query, "$options": "i"}},
                {"phone_number": {"$regex": search_query, "$options": "i"}},
                {"alt_phone_number": {"$regex": search_query, "$options": "i"}},
                {"designation": {"$regex": search_query, "$options": "i"}},
                {"sales_representative_emails": {"$regex": search_query, "$options": "i"}},
            ]

        pipeline = [
            {"$match": match_filter},
            {"$sort": {"created_at": -1}},
            {
                "$lookup": {
                    "from": MongoCollectionsNames.USER_MASTER.value,
                    "let": {"sales_emails": "$sales_representative_emails"},
                    "pipeline": [
                        {
                            "$match": {
                                "$expr": {
                                    "$and": [
                                        {"$in": ["$email", {"$ifNull": ["$$sales_emails", []]}]},
                                        {"$eq": ["$is_disabled", False]},
                                    ]
                                }
                            }
                        },
                        {"$project": {"_id": 0, "name": 1, "email": 1, "phone_number": 1}},
                    ],
                    "as": "sales_representatives",
                }
            },
            {
                "$lookup": {
                    "from": MongoCollectionsNames.LEAD_COMMENTS.value,
                    "let": {"lead_code": "$lead_code", "tenant_id": "$tenant_id"},
                    "pipeline": [
                        {
                            "$match": {
                                "$expr": {
                                    "$and": [
                                        {"$eq": ["$lead_code", "$$lead_code"]},
                                        {"$eq": ["$tenant_id", "$$tenant_id"]},
                                    ]
                                }
                            }
                        },
                        {"$sort": {"created_at": -1}},
                        {
                            "$lookup": {
                                "from": MongoCollectionsNames.USER_MASTER.value,
                                "let": {"comment_by": "$created_by"},
                                "pipeline": [
                                    {"$match": {"$expr": {"$eq": ["$email", "$$comment_by"]}}},
                                    {"$project": {"_id": 0, "name": 1, "email": 1, "phone_number": 1}},
                                ],
                                "as": "commented_user",
                            }
                        },
                        {
                            "$addFields": {
                                "commented_user": {"$arrayElemAt": ["$commented_user", 0]},
                                "created_at": {
                                    "$dateToString": {
                                        "format": "%H:%M:%S %d-%m-%Y IST",
                                        "date": "$created_at",
                                        "timezone": "Asia/Kolkata",
                                    }
                                },
                            }
                        },
                        {"$project": {"_id": 0, "tenant_id": 0, "lead_code": 0, "created_by": 0}},
                    ],
                    "as": "comments",
                }
            },
            {
                "$addFields": {
                    "created_at": {
                        "$dateToString": {
                            "format": "%H:%M:%S %d-%m-%Y IST",
                            "date": "$created_at",
                            "timezone": "Asia/Kolkata",
                        }
                    }
                }
            },
            {
                "$project": {
                    "_id": 0,
                    "tenant_id": 0,
                    "updated_at": 0,
                    "updated_by": 0,
                    "sales_representative_emails": 0,
                }
            },
            {"$skip": skip},
            {"$limit": batch_size},
        ]

        leads = list(self.collection.aggregate(pipeline))

        # total count pipeline
        count_pipeline = [{"$match": match_filter}, {"$count": "total"}]
        count_res = list(self.collection.aggregate(count_pipeline))
        total = count_res[0]["total"] if count_res else 0
        total_pages = (total + batch_size - 1) // batch_size if batch_size > 0 else 1

        print(
            f"Fetched {len(leads)} leads for tenant_id: {tenant_id}, batch_number: {batch_number}, batch_size: {batch_size}, search_query: '{search_query}'"
        )

        return {
            "is_successful": True,
            "leads": leads,
            "total": total,
            "total_pages": total_pages,
        }, HTTPStatus.OK

    def fetch_dropdown_sales_representatives(self, tenant_id: str) -> tuple[dict, int]:
        # sales_representatives list
        sales_representatives_pipeline = [
            {
                "$match": {
                    "$and": [
                        {"tenant_id": tenant_id},
                        {"role": {"$in": [UserRoles.EMPLOYEE.value, UserRoles.COMPANY_ADMIN.value]}},
                        {"is_disabled": False},
                    ]
                }
            },
            {"$project": {"_id": 0, "email": 1, "name": 1, "phone_number": 1}},
        ]

        sales_representatives = list(self.user_collection.aggregate(sales_representatives_pipeline))

        return {"is_successful": True, "sales_representatives": sales_representatives}, HTTPStatus.OK

    # Comments APIs
    def add_comment(
        self, lead_code: str, comment_text: str, current_user_email: str, tenant_id: str
    ) -> tuple[dict, int]:
        # Ensure lead exists
        lead = self.collection.find_one({"lead_code": lead_code, "tenant_id": tenant_id})
        if not lead:
            return {"is_successful": False, "message": "Lead not found."}, HTTPStatus.NOT_FOUND

        comment_text = comment_text.strip()
        if len(comment_text) > 200:
            return {
                "is_successful": False,
                "message": "Comment exceeds maximum length of 200 characters.",
            }, HTTPStatus.BAD_REQUEST

        comment = {
            "comment_id": str(uuid.uuid4()),
            "lead_code": lead_code,
            "tenant_id": tenant_id,
            "comment": comment_text,
            "created_by": current_user_email,
            "created_at": datetime.now(timezone.utc),
        }

        result = self.comments_collection.insert_one(comment)
        if not result.acknowledged:
            return {"is_successful": False, "message": "Failed to add comment."}, HTTPStatus.INTERNAL_SERVER_ERROR

        LogManager.add_log(
            current_user_email=current_user_email,
            tenant_id=tenant_id,
            log_action_type=LogActionType.ADD,
            message=f"ADDED comment to lead: {lead_code}",
        )

        return {"is_successful": True, "message": "Comment added."}, HTTPStatus.OK
