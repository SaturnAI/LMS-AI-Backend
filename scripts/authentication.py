import datetime
import secrets
import urllib.parse
from http import HTTPStatus
from io import BytesIO

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    StreamingResponse,
)

# from scripts.rate_limiter import limiter
from src.constants import MAX_AGE_AUTH_TOKEN_SECONDS
from src.cred import Credentials
from src.enums import Environments, MongoCollectionsNames
from src.exceptions import FileTypeNotSupported
from src.mongodb.authorisation_system import AuthorisationSystem
from src.mongodb.base import BaseDatabase
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

STATE_TTL_SECONDS = 600  # 10 minutes

GOOGLE_OAUTH_SCOPES = " ".join(
    [
        "openid",
        "email",
        "profile",
        # "https://www.googleapis.com/auth/spreadsheets",
        # "https://www.googleapis.com/auth/documents",
        # "https://www.googleapis.com/auth/presentations",
    ]
)


@router.get("/google/start")
# @limiter.limit("10/minute")
async def google_oauth_start(request: Request):

    if not Credentials.smtp_oauth_client_id:
        return JSONResponse(
            {"is_successful": False, "message": "Google OAuth is not configured on this server."},
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,
        )

    redirect_uri = Credentials.redirect_url + "/api/google/callback"
    if not redirect_uri:
        return JSONResponse(
            {"is_successful": False, "message": "SMTP_OAUTH_REDIRECT_URI is not configured on this server."},
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,
        )

    state = secrets.token_urlsafe(32)
    expires_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=STATE_TTL_SECONDS)
    oauth_states_col = BaseDatabase.get_collection(MongoCollectionsNames.OAUTH_STATES)
    oauth_states_col.insert_one({"state": state, "expires_at": expires_at})

    params = {
        "client_id": Credentials.smtp_oauth_client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": GOOGLE_OAUTH_SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)
    return RedirectResponse(url=auth_url, status_code=302)


@router.get("/google/callback")
# @limiter.limit("10/minute")
async def google_oauth_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    website_redirect_uri = Credentials.redirect_url

    if error:
        return RedirectResponse(url=f"{website_redirect_uri}/login?error={urllib.parse.quote(error)}", status_code=302)

    # Validate CSRF state
    if not state:
        return JSONResponse(
            {"is_successful": False, "message": "Invalid or expired state parameter. Please try logging in again."},
            status_code=HTTPStatus.BAD_REQUEST,
        )

    oauth_states_col = BaseDatabase.get_collection(MongoCollectionsNames.OAUTH_STATES)

    state_doc = oauth_states_col.find_one({"state": state})

    if not state_doc:
        return JSONResponse(
            {
                "is_successful": False,
                "message": "Invalid state parameter. This login link has already been used or is invalid. Please try logging in again.",
            },
            status_code=HTTPStatus.BAD_REQUEST,
        )

    now = datetime.datetime.now(datetime.timezone.utc)
    expires_at = state_doc.get("expires_at")
    if expires_at:
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=datetime.timezone.utc)
        if expires_at < now:
            oauth_states_col.delete_one({"state": state})
            return JSONResponse(
                {"is_successful": False, "message": "Login session expired. Please try logging in again."},
                status_code=HTTPStatus.BAD_REQUEST,
            )

    oauth_states_col.delete_one({"state": state})

    if not code:
        return JSONResponse(
            {"is_successful": False, "message": "Authorization code is missing."},
            status_code=HTTPStatus.BAD_REQUEST,
        )

    redirect_uri = Credentials.redirect_url + "/api/google/callback"
    response_data, status_code = authorisation_system.google_callback_login(code=code, redirect_uri=redirect_uri)

    if not response_data["is_successful"]:
        return JSONResponse(content=response_data, status_code=status_code)

    auth_token = response_data.pop("auth_token", "")

    redirect_response = RedirectResponse(url=website_redirect_uri + "/", status_code=302)

    samesite_setting = "lax"
    if Credentials.environment != Environments.PRODUCTION:
        samesite_setting = "none"

    redirect_response.set_cookie(
        key="auth_token",
        value=auth_token,
        secure=True,
        httponly=True,
        samesite=samesite_setting,
        max_age=MAX_AGE_AUTH_TOKEN_SECONDS,
    )
    return redirect_response


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
        return logout_user(is_successful=True, message="User successfully logged out!", status_code=200)

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


@router.post("/update_user_profile")
@requires_verification
async def update_user_profile(request: Request, decoded_data: dict = {}):
    request_data = await request.json()

    response_data, status_code = authorisation_system.update_user_profile(
        current_user_email=decoded_data["email"], profile_data=request_data
    )

    return JSONResponse(response_data, status_code=status_code)


@router.get("/", response_class=HTMLResponse)
async def login_html():
    return HTMLResponse(content=HTML_TEMPLATE)


HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Login Test</title>

    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }

        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #0f766e 0%, #0ea5e9 100%);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 20px;
        }

        .container {
            background: white;
            padding: 32px 28px;
            border-radius: 14px;
            box-shadow: 0 10px 25px rgba(0, 0, 0, 0.18);
            text-align: center;
            max-width: 440px;
            width: 90%;
        }

        h1 { color: #0f172a; margin-bottom: 10px; }
        p { color: #475569; margin-bottom: 18px; }

        .profile-img {
            width: 80px;
            height: 80px;
            border-radius: 50%;
            margin: 14px auto;
            object-fit: cover;
            display: block;
            border: 2px solid #e2e8f0;
        }

        .btn {
            border: none;
            padding: 10px 18px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 14px;
            margin: 6px;
            font-weight: 600;
        }

        .btn-primary { background: #0284c7; color: white; }
        .btn-danger { background: #dc2626; color: white; }

        .btn:hover { opacity: 0.9; }
        .muted { color: #64748b; font-size: 13px; }

        #user-info { display: none; }
    </style>
</head>
<body>
    <div class="container">
        <div id="login-section">
            <h1>Google Login Test</h1>
            <p>Click login to test OAuth and fetch profile.</p>
            <button class="btn btn-primary" onclick="startGoogleLogin()">Login with Google</button>
            <p class="muted">You will be redirected to Google and back to this page.</p>
        </div>

        <div id="user-info">
            <h2>Welcome</h2>
            <br><br>
            <p><strong id="user-name"></strong></p>
            <p id="user-email"></p>
            <button class="btn btn-danger" onclick="logout()">Logout</button>
        </div>
    </div>

    <script>
        window.onload = function () {
            fetchProfile();
        };

        function fetchProfile() {
            fetch("/api/get_profile", {
                method: "GET",
                credentials: "include"
            })
            .then(async (res) => {
                if (!res.ok) {
                    throw new Error("Not logged in");
                }
                return res.json();
            })
            .then((data) => {
                if (!data.is_successful) {
                    throw new Error("Profile fetch failed");
                }
                showUser(data);
            })
            .catch(() => {
                document.getElementById("login-section").style.display = "block";
                document.getElementById("user-info").style.display = "none";
            });
        }

        function startGoogleLogin() {
            window.location.href = "/api/google/start";
        }

        function showUser(user) {
            document.getElementById("login-section").style.display = "none";
            document.getElementById("user-info").style.display = "block";

            document.getElementById("user-name").textContent = user.name;
            document.getElementById("user-email").textContent = user.email;
        }

        function logout() {
            fetch("/api/logout", {
                method: "GET",
                credentials: "include"
            })
            .then(() => fetchProfile());
        }
    </script>
</body>
</html>
"""
