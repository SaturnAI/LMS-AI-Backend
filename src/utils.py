import inspect
import io
import logging as logger
import random
import string
from datetime import datetime, timezone
from functools import wraps
from http import HTTPStatus
from typing import Any, Optional
from uuid import uuid4

import bcrypt
import magic
from fastapi import Cookie, Request
from fastapi.responses import JSONResponse
from PIL import Image

from src.encryption_system import EncryptionSystem
from src.enums import EmployeePermissionType, MongoCollectionsNames, UserRoles
from src.exceptions import FileSizeExceeded, FileTypeNotSupported
from src.mongodb.base import BaseDatabase
from src.schema import CompanyDetails
from src.send_email import SendEmail


def handle_exception(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except Exception as e:
            logger.error(f"Exception: {e}")
            return logout_user(message="Something Went Wrong!!", status_code=500)

    return decorated_function


def requires_verification(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        request = kwargs.get("request")
        if not request:
            raise ValueError("Missing Request object — ensure your route includes `request: Request`")

        decoded_data = await verify_user(request)

        if isinstance(decoded_data, JSONResponse):
            return decoded_data

        kwargs["decoded_data"] = decoded_data

        if inspect.iscoroutinefunction(func):
            return await func(*args, **kwargs)
        else:
            return func(*args, **kwargs)

    return wrapper


async def verify_user(request: Request, auth_token: Optional[str] = Cookie(default=None)):

    try:
        encryption_system = EncryptionSystem()
        auth_token = request.cookies.get("auth_token", "")
        decoded_data = encryption_system.decrypt_string(encrypted_string=auth_token)
    except Exception:
        return logout_user(message="Unverified User, please login again.", status_code=401)

    return decoded_data


def hash_password(password: str) -> str:
    """Hashes a password using bcrypt with a random salt.
    Each call produces a different hash — use verify_password() to check.
    """
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Checks a plain-text password against a stored bcrypt hash."""
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def logout_user(message: str, is_successful: bool = False, status_code: int = 401):
    resp = JSONResponse(status_code=status_code, content={"is_successful": is_successful, "message": message})

    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"

    resp.delete_cookie("auth_token")
    return resp


def super_admin_only(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        decoded_data = kwargs.get("decoded_data", {})
        if decoded_data.get("role") != UserRoles.SUPER_ADMIN:
            return logout_user(message="Only Super Admins can access this.", status_code=403)

        if inspect.iscoroutinefunction(func):
            return await func(*args, **kwargs)
        else:
            return func(*args, **kwargs)

    return wrapper


def employee_page_permission(page_name):
    """Checks if the company admin or employee can access a page."""

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            decoded_data = kwargs.get("decoded_data", {})
            profile = fetch_profile(email=decoded_data.get("email"))

            if profile["role"] not in list(UserRoles):
                return logout_user(
                    message="You are not authorized to edit on this page.",
                    status_code=403,
                )

            if profile["role"] in [UserRoles.SUPER_ADMIN, UserRoles.COMPANY_ADMIN]:
                return await func(*args, **kwargs) if inspect.iscoroutinefunction(func) else func(*args, **kwargs)

            if (
                profile["role"] == UserRoles.EMPLOYEE
                and profile["permissions"].get(page_name) == EmployeePermissionType.NOT_ALLOWED
            ):
                return logout_user(
                    message=f"You don't have access to the page '{page_name.value.replace('_', ' ').capitalize()}'.",
                    status_code=403,
                )

            return await func(*args, **kwargs) if inspect.iscoroutinefunction(func) else func(*args, **kwargs)

        return wrapper

    return decorator


def employee_edit_permission(page_name):
    """Checks if the company admin or employee can edit a page."""

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            decoded_data = kwargs.get("decoded_data", {})
            profile = fetch_profile(email=decoded_data.get("email"))

            if profile["role"] not in list(UserRoles):
                return logout_user(
                    message="You are not authorized to edit on this page.",
                    status_code=403,
                )

            if profile["role"] in [UserRoles.SUPER_ADMIN, UserRoles.COMPANY_ADMIN]:
                return await func(*args, **kwargs) if inspect.iscoroutinefunction(func) else func(*args, **kwargs)

            if (
                profile["role"] == UserRoles.EMPLOYEE
                and profile["permissions"].get(page_name) != EmployeePermissionType.EDIT
            ):
                return logout_user(
                    message=f"You don't have access to edit the page '{page_name.value.replace('_', ' ').capitalize()}'.",
                    status_code=403,
                )

            return await func(*args, **kwargs) if inspect.iscoroutinefunction(func) else func(*args, **kwargs)

        return wrapper

    return decorator


def generate_randomised_alphanumeric_string(length=8):
    characters = string.ascii_letters + string.digits
    return "".join(random.choice(characters) for _ in range(length))


def generate_randomised_numeric_string(length=6):
    characters = string.digits
    return "".join(random.choice(characters) for _ in range(length))


def generate_randomised_uppercase_alpha_string(length=8):
    characters = string.ascii_uppercase
    return "".join(random.choice(characters) for _ in range(length))


def fetch_profile(email: str) -> dict[str, Any]:
    collection = BaseDatabase.get_collection(collection_name=MongoCollectionsNames.USER_MASTER)
    # resume_master = BaseDatabase.get_collection(collection_name=MongoCollectionsNames.RESUME_MASTER)
    email_lower = email.lower()
    user = collection.find_one({"email": email_lower, "is_disabled": False})

    if not user:
        return {"is_successful": False, "message": "User not found"}

    profile = {
        "email": user["email"],
        "is_successful": True,
        "message": "Profile fetched successfully",
        "role": user["role"],
        "name": user["name"],
        "phone_number": user["phone_number"],
        "permissions": user.get("permissions", {}),
        "designation": user.get("designation", ""),
        "created_at": user["created_at"].strftime("%d-%m-%Y"),
    }

    tenant_id = None
    if user["role"] == UserRoles.EMPLOYEE:
        tenant_id = user["tenant_id"]
        profile["tenant_id"] = tenant_id

    if user["role"] == UserRoles.COMPANY_ADMIN:
        tenant_id = user["company_code"]

    if tenant_id:
        company_collection = BaseDatabase.get_collection(collection_name=MongoCollectionsNames.COMPANY_MASTER)

        fields = {}
        for field in CompanyDetails.model_fields.keys():
            if field not in ["billing_plan", "company_logo", "employee_limit"]:
                fields[field] = 1  # Include this field in the query result

        company_data = company_collection.find_one(
            {"company_code": tenant_id},
            {
                "_id": 0,
                **fields,
            },
        )
        if company_data:
            profile["company_data"] = company_data

    return profile


def check_file_type_size(file, size: int = 2, pdf_allowed: bool = False) -> str:
    mime = magic.Magic(mime=True)
    mime_type = mime.from_buffer(file.read(1024))

    mime_to_extension = {
        "image/jpeg": "jpg",
        "image/png": "png",
    }
    if pdf_allowed:
        mime_to_extension["application/pdf"] = "pdf"

    # Determine the file extension based on MIME type
    file_extension = mime_to_extension.get(mime_type)
    if not file_extension:
        raise FileTypeNotSupported("Unsupported file type.")

    # Check file size (less than {size} MB)
    file.seek(0, 2)
    file_size = file.tell()
    file.seek(0)
    if file_size > size * 1024 * 1024:  # size MB in bytes
        raise FileSizeExceeded(f"Maximum file size exceeded. Please upload a file smaller than {size} MB.")
    return file_extension


def update_profile_picture(email: str, profile_picture) -> tuple[dict[str, Any], int]:
    collection = BaseDatabase.get_collection(collection_name=MongoCollectionsNames.USER_MASTER)
    email_lower = email.lower()

    check_file_type_size(profile_picture)

    profile_picture.seek(0)
    result = collection.update_one({"email": email_lower}, {"$set": {"profile_picture": profile_picture.read()}})

    if result.matched_count == 0:
        return {"is_successful": False, "message": "User not found"}, HTTPStatus.NOT_FOUND

    return {"is_successful": True, "message": "Profile picture updated successfully"}, HTTPStatus.OK


def delete_profile_picture(email: str) -> tuple[dict[str, Any], int]:
    collection = BaseDatabase.get_collection(collection_name=MongoCollectionsNames.USER_MASTER)
    email_lower = email.lower()

    result = collection.update_one({"email": email_lower}, {"$unset": {"profile_picture": ""}})

    if result.matched_count == 0:
        return {"is_successful": False, "message": "User not found"}, HTTPStatus.NOT_FOUND

    return {"is_successful": True, "message": "Profile picture deleted successfully"}, HTTPStatus.OK


def fetch_profile_picture(email: str) -> tuple[dict[str, Any], int]:
    collection = BaseDatabase.get_collection(collection_name=MongoCollectionsNames.USER_MASTER)
    email_lower = email.lower()

    user = collection.find_one({"email": email_lower}, {"profile_picture": 1})

    if not user or "profile_picture" not in user:
        return {"is_successful": False, "message": "Profile picture not found"}, HTTPStatus.NOT_FOUND

    return {
        "is_successful": True,
        "message": "Profile picture fetched successfully",
        "profile_picture": user["profile_picture"],
    }, HTTPStatus.OK


def create_user_and_send_email(
    email: str, name: str, role: str, created_by: str, phone_number: str = "", extra_data: dict = {}
) -> dict[str, Any]:

    user_collection = BaseDatabase.get_collection(collection_name=MongoCollectionsNames.USER_MASTER)

    email_lower = email.lower()
    if user_collection.find_one({"email": email_lower}):
        return {"is_successful": False, "message": "User already exists"}

    password = generate_randomised_alphanumeric_string(10)
    hashed_password = hash_password(password)

    user_details = {
        "code": str(uuid4()),
        "email": email_lower,
        "password": hashed_password,
        "name": name,
        "phone_number": phone_number,
        "role": role,
        "token_validity": None,
        "jwt_secret": None,
        "is_disabled": False,
        "created_at": datetime.now(timezone.utc),
        "created_by": created_by,
        **extra_data,
    }

    user_collection.insert_one(user_details)

    send_email = SendEmail()
    is_successful = send_email.send_add_user_email(receiver_email=email_lower, password=password)
    if not is_successful:
        user_collection.delete_one({"email": email_lower})
        return {
            "is_successful": False,
            "message": "Error sending password in email. Please check your email and try again.",
        }

    return {"is_successful": True, "message": "User created & email sent successfully!"}


def compress_image(image_bytes: bytes, max_size=(768, 768), quality=70):
    img = Image.open(io.BytesIO(image_bytes))
    img.thumbnail(max_size)

    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=quality, optimize=True)
    return buffer.getvalue()
