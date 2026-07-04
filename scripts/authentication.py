from http import HTTPStatus
from io import BytesIO

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

# from scripts.rate_limiter import limiter
from src.constants import MAX_AGE_AUTH_TOKEN_SECONDS
from src.cred import Credentials
from src.enums import Environments
from src.exceptions import FileTypeNotSupported
from src.mongodb.authorisation_system import AuthorisationSystem
from src.utils import (
    delete_profile_picture,
    fetch_profile,
    fetch_profile_picture,
    logout_user,
    requires_verification,
    update_profile_picture,
)

router = APIRouter()
authorisation_system = AuthorisationSystem()


@router.post("/login")
# @limiter.limit("5/minute")
async def login(request: Request):
    login_request_data = await request.json()
    email = login_request_data.get("email")
    password = login_request_data.get("password")
    login_data = {"email": email, "password": password}
    response_data = authorisation_system.user_login(login_data=login_data)

    samesite_setting = "lax"
    if Credentials.environment != Environments.PRODUCTION:
        samesite_setting = "none"

    if response_data.get("is_successful"):
        auth_token = response_data.pop("auth_token", None)
        response = JSONResponse(response_data, status_code=HTTPStatus.OK)
        if auth_token:
            response.set_cookie(
                key="auth_token",
                value=auth_token,
                secure=True,
                httponly=True,
                samesite=samesite_setting,
                max_age=MAX_AGE_AUTH_TOKEN_SECONDS,
            )
        return response

    return JSONResponse(response_data, status_code=HTTPStatus.UNAUTHORIZED)


@router.get("/logout")
@requires_verification
async def logout(request: Request, decoded_data: dict = {}):
    email = decoded_data["email"]
    result = authorisation_system.user_logout_db(email=email)
    if result.get("is_successful"):
        logout_user(is_successful=True, message="User successfully logged out!", status_code=200)
        return JSONResponse(
            {"is_successful": True, "message": "User successfully logged out!"}, status_code=HTTPStatus.OK
        )

    return JSONResponse({"is_successful": False, "message": "User not found."}, status_code=HTTPStatus.NOT_FOUND)


@router.post("/forgot_password")
# @limiter.limit("5/minute")
async def forgot_password(request: Request):
    request_data = await request.json()
    response_data = authorisation_system.send_reset_password_otp(email=request_data["email"])
    status_code = HTTPStatus.OK if response_data.get("is_successful") else HTTPStatus.BAD_REQUEST
    return JSONResponse(response_data, status_code=status_code)


@router.post("/verify_forgot_password_otp")
# @limiter.limit("5/minute")
async def verify_forgot_password_otp(request: Request):
    request_data = await request.json()
    response_data = authorisation_system.verify_reset_password_otp(
        email=request_data["email"], input_otp=request_data["input_otp"]
    )
    status_code = HTTPStatus.OK if response_data.get("is_successful") else HTTPStatus.BAD_REQUEST
    return JSONResponse(response_data, status_code=status_code)


@router.post("/update_password")
# @limiter.limit("5/minute")
async def update_password(request: Request):
    request_data = await request.json()
    response_data = authorisation_system.update_password(
        email=request_data["email"], new_password=request_data["new_password"]
    )
    status_code = HTTPStatus.OK if response_data.get("is_successful") else HTTPStatus.FORBIDDEN
    return JSONResponse(response_data, status_code=status_code)


@router.get("/get_profile")
@requires_verification
async def get_profile(request: Request, decoded_data: dict = {}):
    response_data = fetch_profile(email=decoded_data["email"])
    status_code = HTTPStatus.OK if response_data.get("is_successful") else HTTPStatus.NOT_FOUND
    return JSONResponse(response_data, status_code=status_code)


@router.post("/update_profile_picture")
@requires_verification
async def update_profile_picture_endpoint(
    request: Request, decoded_data: dict = {}, profile_picture: UploadFile = File(...)
):

    if not profile_picture:
        return JSONResponse(
            {
                "is_successful": False,
                "message": "Profile picture file is required.",
            },
            status_code=HTTPStatus.BAD_REQUEST,
        )
    file_bytes = await profile_picture.read()
    profile_picture_file = BytesIO(file_bytes)

    try:
        response_data, status_code = update_profile_picture(
            email=decoded_data["email"], profile_picture=profile_picture_file
        )

    except FileTypeNotSupported as e:
        return JSONResponse(
            {
                "is_successful": False,
                "message": str(e),
            },
            status_code=HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
        )

    return JSONResponse(response_data, status_code=status_code)


@router.delete("/delete_profile_picture")
@requires_verification
async def delete_profile_picture_endpoint(request: Request, decoded_data: dict = {}):
    response_data, status_code = delete_profile_picture(email=decoded_data["email"])
    return JSONResponse(response_data, status_code=status_code)


@router.get("/fetch_profile_picture")
@requires_verification
async def fetch_profile_picture_endpoint(request: Request, decoded_data: dict = {}):
    response_data, status_code = fetch_profile_picture(email=decoded_data["email"])
    if status_code != HTTPStatus.OK:
        return JSONResponse(response_data, status_code=status_code)

    profile_picture_bytes = response_data["profile_picture"]
    return StreamingResponse(BytesIO(profile_picture_bytes))


@router.post("/change_password")
@requires_verification
async def change_password(request: Request, decoded_data: dict = {}):
    request_data = await request.json()
    response_data = authorisation_system.change_password(
        email=decoded_data["email"],
        old_password=request_data["old_password"],
        new_password=request_data["new_password"],
    )
    status_code = HTTPStatus.OK if response_data.get("is_successful") else HTTPStatus.BAD_REQUEST
    return JSONResponse(response_data, status_code=status_code)


@router.put("/update_user_profile")
@requires_verification
async def update_user_profile(request: Request, decoded_data: dict = {}):
    request_data = await request.json()

    response_data, status_code = authorisation_system.update_user_profile(
        current_user_email=decoded_data["email"], profile_data=request_data
    )

    return JSONResponse(response_data, status_code=status_code)
