import logging as logger
import uuid
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

from pydantic import ValidationError

from src.enums import MongoCollectionsNames, UserRoles
from src.exceptions import FileSizeExceeded, FileTypeNotSupported
from src.mongodb.base import BaseDatabase
from src.schema import CompanyDetails, CompanyProfile
from src.utils import check_file_type_size, create_user_and_send_email


class CompanyMaster:

    collection = BaseDatabase.get_collection(collection_name=MongoCollectionsNames.COMPANY_MASTER)
    user_collection = BaseDatabase.get_collection(collection_name=MongoCollectionsNames.USER_MASTER)

    def get_company_from_company_code(self, company_code: str) -> dict[str, Any] | None:
        """Fetch company admin details using company_code."""
        return self.user_collection.find_one(
            {"company_code": company_code, "role": UserRoles.COMPANY_ADMIN, "is_disabled": False}
        )

    def add_company(self, request_data: dict, current_user_email: str, company_logo=None) -> tuple[dict[str, Any], int]:
        """Add a new company record to the database."""
        try:
            validated_data = CompanyDetails.model_validate(request_data)
        except ValidationError as e:
            logger.exception("Validation error while adding company", e)
            return {"is_successful": False, "message": "Invalid or incomplete request data."}, HTTPStatus.BAD_REQUEST

        if not validated_data.email:
            return {
                "is_successful": False,
                "message": "Email is required for company creation.",
            }, HTTPStatus.BAD_REQUEST

        validated_data.email = validated_data.email.lower()

        if self.user_collection.find_one({"email": validated_data.email}):
            return {
                "is_successful": False,
                "message": f"User with email '{validated_data.email}' already exists.",
            }, HTTPStatus.CONFLICT

        if company_logo:
            try:
                check_file_type_size(file=company_logo, size=2)
            except FileTypeNotSupported as e:
                return {
                    "is_successful": False,
                    "message": str(e),
                }, HTTPStatus.BAD_REQUEST
            except FileSizeExceeded as e:
                return {
                    "is_successful": False,
                    "message": str(e),
                }, HTTPStatus.BAD_REQUEST

            company_logo.seek(0)

        company_code = str(uuid.uuid4())
        company_data = validated_data.model_dump()

        company_data.update(
            {
                "company_code": company_code,
                "company_logo": company_logo.read() if company_logo else None,
                "created_at": datetime.now(timezone.utc),
                "created_by": current_user_email,
            }
        )

        result = self.collection.insert_one(company_data)
        if not result.acknowledged:
            return {
                "is_successful": False,
                "message": "Failed to add company to the database. Please try again.",
            }, HTTPStatus.INTERNAL_SERVER_ERROR

        user_creation = create_user_and_send_email(
            email=validated_data.email,
            name=validated_data.name,
            role=UserRoles.COMPANY_ADMIN,
            created_by=current_user_email,
            phone_number=validated_data.mobile_number,
            extra_data={"company_code": company_code, "tenant_id": company_code},
        )

        if not user_creation["is_successful"]:
            self.collection.delete_one({"company_code": company_code})  # Rollback company creation

            return {
                "is_successful": True,
                "message": user_creation["message"],
            }, HTTPStatus.OK

        return {
            "is_successful": True,
            "message": f"Company '{validated_data.legal_name}' added successfully.",
        }, HTTPStatus.OK

    def update_company(
        self, request_data: dict, current_user_email: str, company_logo=None
    ) -> tuple[dict[str, Any], int]:
        """Update existing company details."""

        try:
            validated_data = CompanyDetails.model_validate(request_data)
        except ValidationError as e:
            logger.exception("Validation error while updating company", e)
            return {"is_successful": False, "message": "Invalid or incomplete request data."}, HTTPStatus.BAD_REQUEST

        company_code = request_data.get("company_code")
        if not company_code:
            return {"is_successful": False, "message": "Missing required field: company_code"}, HTTPStatus.BAD_REQUEST

        existing_company = self.collection.find_one({"company_code": company_code})
        if not existing_company:
            return {
                "is_successful": False,
                "message": f"Company with code '{company_code}' not found.",
            }, HTTPStatus.NOT_FOUND

        updated_data = validated_data.model_dump()
        updated_data.pop("company_code", None)
        updated_data["email"] = existing_company["email"]  # Prevent email update

        updated_data["company_logo"] = None
        if company_logo:
            try:
                check_file_type_size(file=company_logo, size=2)
            except FileTypeNotSupported as e:
                return {
                    "is_successful": False,
                    "message": str(e),
                }, HTTPStatus.BAD_REQUEST
            except FileSizeExceeded as e:
                return {
                    "is_successful": False,
                    "message": str(e),
                }, HTTPStatus.BAD_REQUEST

            company_logo.seek(0)
            updated_data["company_logo"] = company_logo.read()

        updated_data.update(
            {
                "updated_at": datetime.now(timezone.utc),
                "updated_by": current_user_email,
            }
        )

        result = self.collection.update_one(
            {"company_code": company_code},
            {"$set": updated_data},
        )

        if result.matched_count == 0:
            return {
                "is_successful": False,
                "message": "Failed to find the company to update.",
            }, HTTPStatus.NOT_FOUND

        if result.modified_count == 0:
            return {
                "is_successful": True,
                "message": "No changes were made to the company details.",
            }, HTTPStatus.OK

        return {
            "is_successful": True,
            "message": f"Company '{validated_data.legal_name}' updated successfully.",
        }, HTTPStatus.OK

    def update_company_profile(
        self, current_user_email: str, profile_data: dict, company_logo=None
    ) -> tuple[dict[str, Any], int]:

        try:
            validated_data = CompanyProfile.model_validate(profile_data)
        except ValidationError as e:
            logger.exception("Validation error while updating company", e)
            return {"is_successful": False, "message": "Invalid or incomplete request data."}, HTTPStatus.BAD_REQUEST

        existing_company = self.collection.find_one({"email": current_user_email})
        if not existing_company:
            return {
                "is_successful": False,
                "message": f"Company with email '{current_user_email}' not found.",
            }, HTTPStatus.NOT_FOUND

        updated_data = validated_data.model_dump()
        updated_data.pop("company_code", None)
        updated_data["email"] = current_user_email  # Prevent email update

        updated_data["company_logo"] = None
        if company_logo:
            try:
                check_file_type_size(file=company_logo, size=2)
            except FileTypeNotSupported as e:
                return {
                    "is_successful": False,
                    "message": str(e),
                }, HTTPStatus.BAD_REQUEST
            except FileSizeExceeded as e:
                return {
                    "is_successful": False,
                    "message": str(e),
                }, HTTPStatus.BAD_REQUEST
            company_logo.seek(0)
            updated_data["company_logo"] = company_logo.read()

        updated_data.update({"updated_at": datetime.now(timezone.utc), "updated_by": current_user_email})
        result = self.collection.update_one(
            {"email": current_user_email},
            {"$set": updated_data},
        )

        if result.matched_count == 0:
            return {
                "is_successful": False,
                "message": "Failed to find the company to update.",
            }, HTTPStatus.NOT_FOUND

        if result.modified_count == 0:
            return {
                "is_successful": True,
                "message": "No changes were made to the company details.",
            }, HTTPStatus.OK

        return {
            "is_successful": True,
            "message": f"Company '{validated_data.legal_name}' updated successfully.",
        }, HTTPStatus.OK

    def fetch_company_logo(self, tenant_id: str) -> tuple[dict[str, Any], int]:
        """Fetch company logo using company code."""
        company = self.collection.find_one({"company_code": tenant_id}, {"_id": 0, "company_logo": 1})
        if not company or "company_logo" not in company or not company["company_logo"]:
            return {
                "is_successful": False,
                "message": f"No logo found for company code: {tenant_id}",
            }, HTTPStatus.NOT_FOUND

        return {
            "is_successful": True,
            "company_logo": company["company_logo"],
            "message": f"Company logo fetched successfully.",
        }, HTTPStatus.OK

    def disable_company_admin_and_employees(
        self, company_code: str, current_user_email: str
    ) -> tuple[dict[str, Any], int]:
        """Disable company admin and all users associated with a company."""

        company_admin = self.user_collection.find_one({"company_code": company_code, "role": UserRoles.COMPANY_ADMIN})

        if not company_admin:
            return {
                "is_successful": False,
                "message": f"No company admin found for company code: {company_code}",
            }, HTTPStatus.NOT_FOUND

        update_result = self.user_collection.update_many(
            {
                "$or": [
                    {"company_code": company_code, "role": UserRoles.COMPANY_ADMIN},  # company admin
                    {"tenant_id": company_code},  # employees
                ]
            },
            {
                "$set": {
                    "is_disabled": True,
                    "updated_at": datetime.now(timezone.utc),
                    "updated_by": current_user_email,
                }
            },
        )

        if update_result.modified_count == 0:
            return {
                "is_successful": True,
                "message": "No changes were made. Company admin and associated users were already disabled.",
            }, HTTPStatus.OK

        return {
            "is_successful": True,
            "message": "Company admin and all associated users have been disabled.",
            "modified_count": update_result.modified_count,
        }, HTTPStatus.OK

    def enable_company_admin(self, company_code: str, current_user_email: str) -> tuple[dict[str, Any], int]:
        """Enable company admin associated with a company."""

        company_admin = self.user_collection.find_one({"company_code": company_code, "role": UserRoles.COMPANY_ADMIN})

        if not company_admin:
            return {
                "is_successful": False,
                "message": f"No company admin found for company code: {company_code}",
            }, HTTPStatus.NOT_FOUND

        update_result = self.user_collection.update_one(
            {"email": company_admin["email"]},
            {
                "$set": {
                    "is_disabled": False,
                    "updated_at": datetime.now(timezone.utc),
                    "updated_by": current_user_email,
                }
            },
        )

        if update_result.modified_count == 0:
            return {
                "is_successful": True,
                "message": "No changes were made. Company admin was already enabled.",
            }, HTTPStatus.OK

        return {
            "is_successful": True,
            "message": "Company admin has been enabled.",
        }, HTTPStatus.OK

    def fetch_all_companies(self) -> tuple[dict[str, Any], int]:
        """Fetch all companies with company admin disabled status."""

        pipeline = [
            {
                "$lookup": {
                    "from": MongoCollectionsNames.USER_MASTER.value,
                    "let": {"company_code": "$company_code"},
                    "pipeline": [
                        {
                            "$match": {
                                "$expr": {
                                    "$and": [
                                        {"$eq": ["$company_code", "$$company_code"]},
                                        {"$eq": ["$role", UserRoles.COMPANY_ADMIN]},
                                    ]
                                }
                            }
                        },
                        {
                            "$project": {
                                "_id": 0,
                                "is_disabled": 1,
                            }
                        },
                    ],
                    "as": "company_admin",
                }
            },
            {
                "$addFields": {
                    "is_disabled": {
                        "$ifNull": [
                            {"$arrayElemAt": ["$company_admin.is_disabled", 0]},
                            False,
                        ]
                    }
                }
            },
            {
                "$project": {
                    "_id": 0,
                    "company_admin": 0,
                    "created_at": 0,
                    "updated_at": 0,
                    "company_logo": 0,
                }
            },
        ]

        companies = list(self.collection.aggregate(pipeline))
        return {
            "is_successful": True,
            "companies": companies,
            "message": f"Fetched {len(companies)} companies successfully.",
        }, HTTPStatus.OK
