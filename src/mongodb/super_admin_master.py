import logging as logger
from datetime import datetime, timezone
from email.mime.image import MIMEImage
from http import HTTPStatus
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from src.enums import MongoCollectionsNames, UserRoles
from src.mongodb.base import BaseDatabase
from src.schema import AddUpdateUserRequest
from src.send_email import SendEmail
from src.utils import generate_randomised_alphanumeric_string, hash_password


class SuperAdminMaster:
    collection = BaseDatabase.get_collection(collection_name=MongoCollectionsNames.USER_MASTER)

    def is_user_exists(self, email: str) -> bool:
        user_exists = self.collection.find_one({"email": email.lower()})
        return user_exists is not None

    def add_super_admin(self, request_data: dict, current_user_email: str) -> tuple[dict[str, Any], int]:
        try:
            request_data_schema = AddUpdateUserRequest.model_validate(request_data)
        except ValidationError as e:
            logger.exception("Validation error", e)
            return {
                "is_successful": False,
                "message": "Incomplete or Invalid request data.",
            }, HTTPStatus.BAD_REQUEST

        if self.is_user_exists(request_data_schema.email):
            return {
                "is_successful": False,
                "message": f"User with email '{request_data_schema.email}' already exists",
            }, HTTPStatus.BAD_REQUEST

        password = generate_randomised_alphanumeric_string()
        user_data = {
            "code": str(uuid4()),
            "email": request_data_schema.email.lower(),
            "password": hash_password(password),
            "name": request_data_schema.name,
            "phone_number": request_data_schema.phone_number,
            "role": UserRoles.SUPER_ADMIN.value,
            "token_validity": None,
            "jwt_secret": None,
            "is_disabled": False,
            "created_at": datetime.now(timezone.utc),
            "created_by": current_user_email,
        }

        result = self.collection.insert_one(user_data)

        if not result.acknowledged:
            return {
                "is_successful": False,
                "message": "Failed to add the User into Database. Please try again.",
            }, HTTPStatus.INTERNAL_SERVER_ERROR

        send_email = SendEmail()
        is_successful = send_email.send_add_user_email(
            receiver_email=request_data_schema.email.lower(), password=password
        )
        if not is_successful:
            self.collection.delete_one({"email": request_data_schema.email.lower()})
            return {
                "is_successful": False,
                "message": "Error sending password in email. Please check your email and try again.",
            }, HTTPStatus.INTERNAL_SERVER_ERROR

        return {"is_successful": True, "message": "Super Admin Successfully Added."}, HTTPStatus.CREATED

    def update_super_admin(self, request_data: dict, current_user_email: str) -> tuple[dict[str, Any], int]:
        try:
            request_data_schema = AddUpdateUserRequest.model_validate(request_data)
        except ValidationError as e:
            logger.exception("Validation error", e)
            return {
                "is_successful": False,
                "message": "Incomplete or Invalid request data.",
            }, HTTPStatus.BAD_REQUEST

        update_fields = {
            "name": request_data_schema.name.strip(),
            "phone_number": request_data_schema.phone_number,
            "updated_at": datetime.now(timezone.utc),
            "updated_by": current_user_email,
        }

        result = self.collection.update_one({"email": request_data_schema.email}, {"$set": update_fields})

        if result.matched_count == 0:
            return {
                "is_successful": False,
                "message": "No super admin found with the provided email.",
            }, HTTPStatus.NOT_FOUND

        if result.modified_count == 0:
            return {
                "is_successful": True,
                "message": "No changes were made to the super admin details.",
            }, HTTPStatus.OK

        return {
            "is_successful": True,
            "message": "Super Admin details updated successfully.",
        }, HTTPStatus.OK

    def fetch_all_super_admins(self) -> tuple[dict[str, Any], int]:

        users = list(
            self.collection.find(
                {"role": UserRoles.SUPER_ADMIN.value},
                {"_id": 0, "code": 1, "email": 1, "name": 1, "phone_number": 1, "is_disabled": 1},
            )
        )

        return {
            "is_successful": True,
            "user_data": users,
            "message": "Successfully Fetched the Data!",
        }, HTTPStatus.OK

    def disable_super_admin(
        self, disable_user_email: str, current_super_admin_email: str
    ) -> tuple[dict[str, Any], int]:
        if disable_user_email.lower() == current_super_admin_email.lower():
            return {
                "is_successful": False,
                "message": "You can't disable yourself.",
            }, HTTPStatus.FORBIDDEN

        user_to_disable = self.collection.find_one({"email": disable_user_email.lower(), "is_disabled": False})

        if not user_to_disable:
            return {
                "is_successful": False,
                "message": f"Super Admin with email '{disable_user_email}' not found or is already disabled.",
            }, HTTPStatus.NOT_FOUND

        result = self.collection.update_one(
            {"email": disable_user_email.lower(), "role": UserRoles.SUPER_ADMIN.value}, {"$set": {"is_disabled": True}}
        )

        if result.matched_count == 0:
            return {
                "is_successful": False,
                "message": "Failed to disable the super admin. Invalid email.",
            }, HTTPStatus.BAD_REQUEST
        return {
            "is_successful": True,
            "message": f"Super Admin with '{disable_user_email}' has been disabled.",
        }, HTTPStatus.OK

    def enable_super_admin(self, enable_user_email: str) -> tuple[dict[str, Any], int]:
        user_to_enable = self.collection.find_one({"email": enable_user_email.lower(), "is_disabled": True})

        if not user_to_enable:
            return {
                "is_successful": False,
                "message": f"Either Super Admin with email '{enable_user_email}' not found or is already enabled/active.",
            }, HTTPStatus.NOT_FOUND

        result = self.collection.update_one(
            {"email": enable_user_email.lower(), "role": UserRoles.SUPER_ADMIN.value}, {"$set": {"is_disabled": False}}
        )

        if result.matched_count == 0:
            return {
                "is_successful": False,
                "message": "Failed to enable the Super Admin.",
            }, HTTPStatus.BAD_REQUEST

        return {
            "is_successful": True,
            "message": f"Super Admin with email '{enable_user_email}' has been enabled.",
        }, HTTPStatus.OK
