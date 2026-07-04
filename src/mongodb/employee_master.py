from datetime import datetime, timezone
from http import HTTPStatus

from pydantic import ValidationError
from pymongo import ReturnDocument

from src.enums import MongoCollectionsNames, UserRoles
from src.mongodb.base import BaseDatabase
from src.mongodb.log_manager import LogActionType, LogManager
from src.schema import EmployeeDetails
from src.utils import create_user_and_send_email


class EmployeeMaster:

    collection = BaseDatabase.get_collection(collection_name=MongoCollectionsNames.USER_MASTER)
    company_collection = BaseDatabase.get_collection(collection_name=MongoCollectionsNames.COMPANY_MASTER)

    def is_user_exists(self, email: str) -> bool:
        user_exists = self.collection.find_one({"email": email.lower()})
        return user_exists is not None

    def add_employee(self, request_data: dict, current_user_email: str, tenant_id: str) -> tuple[dict, int]:
        try:
            validated_request_data = EmployeeDetails.model_validate(request_data)
        except ValidationError:
            return {"is_successful": False, "message": "Invalid or incomplete request data."}, HTTPStatus.BAD_REQUEST

        company = self.company_collection.find_one({"company_code": tenant_id})
        if not company:
            return {"is_successful": False, "message": "Company not found."}, HTTPStatus.NOT_FOUND

        employee_limit = int(company.get("employee_limit", 0))  # 0 means 0 not unlimited

        # Count active employees for this company (exclude disabled)
        active_count = self.collection.count_documents(
            {"tenant_id": tenant_id, "role": UserRoles.EMPLOYEE.value, "is_disabled": False}
        )

        if active_count >= employee_limit:
            return {
                "is_successful": False,
                "message": f"Employee limit reached. Allowed: {employee_limit}, Active: {active_count}. Disable an employee or buy more license to add more employees.",
            }, HTTPStatus.BAD_REQUEST

        if self.is_user_exists(validated_request_data.email):
            return {
                "is_successful": False,
                "message": f"User with email '{validated_request_data.email}' already exists",
            }, HTTPStatus.BAD_REQUEST

        employee_data = validated_request_data.model_dump()

        extra_data = {
            "permissions": employee_data["permissions"],
            "tenant_id": tenant_id,
        }

        user_creation = create_user_and_send_email(
            email=validated_request_data.email,
            name=validated_request_data.name,
            role=UserRoles.EMPLOYEE,
            created_by=current_user_email,
            phone_number=validated_request_data.phone_number,
            extra_data=extra_data,
        )

        if not user_creation["is_successful"]:
            self.collection.delete_one({"email": validated_request_data.email})  # Rollback if needed
            return {
                "is_successful": True,
                "message": f"Employee '{validated_request_data.name}' added. BUT: {user_creation['message']}",
            }, HTTPStatus.OK

        LogManager.add_log(
            current_user_email=current_user_email,
            tenant_id=tenant_id,
            log_action_type=LogActionType.ADD,
            message=f"ADDED a new employee: {validated_request_data.name}({validated_request_data.email})",
        )

        return {"is_successful": True, "message": "Employee added successfully"}, HTTPStatus.OK

    def update_employee(self, request_data: dict, current_user_email: str, tenant_id: str) -> tuple[dict, int]:

        try:
            validated_request_data = EmployeeDetails.model_validate(request_data)
        except ValidationError:
            return {"is_successful": False, "message": "Invalid or incomplete request data."}, HTTPStatus.BAD_REQUEST

        update_data = validated_request_data.model_dump()
        employee_email = update_data.pop("email")

        update_data["updated_by"] = current_user_email
        update_data["updated_at"] = datetime.now(timezone.utc)

        result = self.collection.find_one_and_update(
            {"email": employee_email.lower(), "tenant_id": tenant_id},
            {"$set": update_data},
            return_document=ReturnDocument.AFTER,
        )

        if result:
            LogManager.add_log(
                current_user_email=current_user_email,
                tenant_id=tenant_id,
                log_action_type=LogActionType.EDIT,
                message=f"UPDATED employee details: {result['name']}({result['email']})",
            )
            return {"is_successful": True, "message": "Employee updated successfully"}, HTTPStatus.OK

        return {"is_successful": False, "message": "Employee not found"}, HTTPStatus.NOT_FOUND

    def fetch_enabled_employees(self, tenant_id: str) -> tuple[dict, int]:
        user_data = []

        users = list(
            self.collection.find({"is_disabled": False, "role": UserRoles.EMPLOYEE.value, "tenant_id": tenant_id})
        )
        for user in users:
            single_user = {
                "code": user["code"],
                "email": user["email"],
                "name": user["name"],
                "phone_number": user["phone_number"],
                "permissions": user.get("permissions", {}),
            }
            user_data.append(single_user)
        return {
            "is_successful": True,
            "user_data": user_data,
            "message": "Successfully Fetched the Data!",
        }, HTTPStatus.OK

    def fetch_disabled_employees(self, tenant_id: str) -> tuple[dict, int]:
        user_data = []

        users = list(
            self.collection.find({"is_disabled": True, "role": UserRoles.EMPLOYEE.value, "tenant_id": tenant_id})
        )
        for user in users:
            single_user = {
                "code": user["code"],
                "email": user["email"],
                "name": user["name"],
                "phone_number": user["phone_number"],
                "permissions": user.get("permissions", {}),
            }
            user_data.append(single_user)
        return {
            "is_successful": True,
            "user_data": user_data,
            "message": "Successfully Fetched the Data!",
        }, HTTPStatus.OK

    def disable_employee(self, disable_user_email: str, current_user_email: str, tenant_id: str) -> tuple[dict, int]:
        if disable_user_email.lower() == current_user_email.lower():
            return {
                "is_successful": False,
                "message": "You can't disable yourself.",
            }, HTTPStatus.FORBIDDEN

        user_to_disable = self.collection.find_one({"email": disable_user_email.lower(), "is_disabled": False})

        if not user_to_disable:
            return {
                "is_successful": False,
                "message": f"Employee with email '{disable_user_email}' not found or is already disabled.",
            }, HTTPStatus.NOT_FOUND

        result = self.collection.update_one(
            {
                "email": disable_user_email.lower(),
                "role": UserRoles.EMPLOYEE.value,
                "tenant_id": tenant_id,
            },
            {"$set": {"is_disabled": True}},
        )

        if result.matched_count == 0:
            return {
                "is_successful": False,
                "message": "Failed to disable the employee. Invalid email.",
            }, HTTPStatus.BAD_REQUEST

        LogManager.add_log(
            current_user_email=current_user_email,
            tenant_id=tenant_id,
            log_action_type=LogActionType.DISABLE,
            message=f"DISABLED employee: {user_to_disable['name']}({user_to_disable['email']})",
        )

        return {
            "is_successful": True,
            "message": f"Employee with '{disable_user_email}' has been disabled.",
        }, HTTPStatus.OK

    def enable_employee(self, enable_user_email: str, tenant_id: str, current_user_email: str) -> tuple[dict, int]:
        user_to_enable = self.collection.find_one({"email": enable_user_email.lower(), "is_disabled": True})

        if not user_to_enable:
            return {
                "is_successful": False,
                "message": f"Either Employee with email '{enable_user_email}' not found or is already enabled/active.",
            }, HTTPStatus.NOT_FOUND

        company = self.company_collection.find_one({"company_code": tenant_id})
        if not company:
            return {"is_successful": False, "message": "Company not found."}, HTTPStatus.NOT_FOUND

        employee_limit = int(company.get("employee_limit", 0))

        active_count = self.collection.count_documents(
            {"tenant_id": tenant_id, "role": UserRoles.EMPLOYEE.value, "is_disabled": False}
        )
        # If enabling this user would exceed limit, deny
        if active_count >= employee_limit:
            return {
                "is_successful": False,
                "message": f"Cannot enable employee. Employee limit reached ({employee_limit}). Active: {active_count}.",
            }, HTTPStatus.BAD_REQUEST

        result = self.collection.update_one(
            {
                "email": enable_user_email.lower(),
                "role": UserRoles.EMPLOYEE.value,
                "tenant_id": tenant_id,
            },
            {"$set": {"is_disabled": False}},
        )

        if result.matched_count == 0:
            return {
                "is_successful": False,
                "message": "Failed to enable the employee.",
            }, HTTPStatus.BAD_REQUEST

        LogManager.add_log(
            current_user_email=current_user_email,
            tenant_id=tenant_id,
            log_action_type=LogActionType.ENABLE,
            message=f"ENABLED employee: {user_to_enable['name']}({user_to_enable['email']})",
        )

        return {
            "is_successful": True,
            "message": f"Employee with email '{enable_user_email}' has been enabled.",
        }, HTTPStatus.OK
