import logging as logger
import threading
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from typing import Any

import requests
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from pydantic import ValidationError

from config import ProjectConfig
from src.cred import Credentials
from src.encryption_system import EncryptionSystem
from src.enums import MongoCollectionsNames, UserRoles
from src.mongodb.base import BaseDatabase
from src.schema import UpdateUserDetails, UserLoginRequest
from src.send_email import SendEmail
from src.utils import generate_randomised_numeric_string, hash_password, verify_password


class AuthorisationSystem:
    collection = BaseDatabase.get_collection(collection_name=MongoCollectionsNames.USER_MASTER)

    def fetch_user_by_email(self, email: str) -> dict | None:
        return self.collection.find_one({"email": email.lower()})

    def google_callback_login(self, code: str, redirect_uri: str) -> tuple[dict, int]:
        try:
            # Exchange code for tokens using client_secret (server-side only)
            token_response = requests.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": code,
                    "client_id": Credentials.smtp_oauth_client_id,
                    "client_secret": Credentials.smtp_oauth_client_secret,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
            )

            if token_response.status_code != 200:
                return {
                    "is_successful": False,
                    "message": "Failed to exchange authorization code for tokens",
                }, HTTPStatus.UNAUTHORIZED

            tokens = token_response.json()
            access_token = tokens.get("access_token")
            new_refresh_token = tokens.get("refresh_token")
            expires_in = int(tokens.get("expires_in", 3600))
            raw_id_token = tokens.get("id_token")

            if not access_token:
                return {
                    "is_successful": False,
                    "message": "No access token received from Google",
                }, HTTPStatus.UNAUTHORIZED

            # Verify id_token to securely extract user identity
            email = None
            picture = ""
            if raw_id_token:
                try:
                    id_token_claims = google_id_token.verify_oauth2_token(
                        raw_id_token,
                        google_requests.Request(),
                        Credentials.smtp_oauth_client_id,
                    )
                    email = id_token_claims.get("email")
                    picture = id_token_claims.get("picture", "")
                except Exception as e:
                    logger.warning(f"id_token verification failed, falling back to userinfo endpoint: {e}")

            # Fallback: fetch user info from userinfo endpoint
            if not email:
                userinfo_response = requests.get(
                    "https://www.googleapis.com/oauth2/v2/userinfo",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                if userinfo_response.status_code != 200:
                    return {
                        "is_successful": False,
                        "message": "Failed to fetch user info from Google",
                    }, HTTPStatus.UNAUTHORIZED
                user_info = userinfo_response.json()
                email = user_info.get("email")
                picture = user_info.get("picture", "")

            if not email:
                return {"is_successful": False, "message": "Email not found in Google token"}, HTTPStatus.UNAUTHORIZED

        except Exception as e:
            return {"is_successful": False, "message": f"Token exchange failed: {str(e)}"}, HTTPStatus.UNAUTHORIZED

        email = email.lower()
        user_db = self.fetch_user_by_email(email=email)
        if not user_db:
            return {
                "is_successful": False,
                "message": "You are not authorised to access this application. Please contact support for further assistance.",
            }, HTTPStatus.UNAUTHORIZED

        if user_db["is_disabled"]:
            return {
                "is_successful": False,
                "message": "Your account has been disabled. Please contact support for further assistance.",
            }, HTTPStatus.UNAUTHORIZED

        token_expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

        # TODO: Update the user record with the new access token, refresh token, and expiry time when other features are implemented. For now, we are not storing these tokens in the database. Also Encrypt the access token and refresh token before storing in the database. This will be implemented in the future.
        # update_data: dict = {
        #     "google_access_token": access_token,
        #     "google_token_expiry": token_expiry,
        #     "google_token_updated_at": datetime.now(timezone.utc),
        # }

        # # Only overwrite refresh token if Google returned a new one
        # if new_refresh_token:
        #     update_data["google_refresh_token"] = new_refresh_token

        # self.collection.update_one({"email": email}, {"$set": update_data})

        encryption_system = EncryptionSystem()
        encryption_dict = {
            "email": email,
            "role": user_db["role"],
        }

        auth_token = encryption_system.encrypt_dict(input_json=encryption_dict)
        return {
            "is_successful": True,
            "is_user_exists": True,
            "auth_token": auth_token,
            "message": "Sign-in successful!",
            "name": user_db["name"],
            "role": user_db["role"],
            "email": email,
        }, HTTPStatus.OK

    def user_login(self, login_data: dict) -> dict:
        """Authorises user data during login
        Args:
            login data (dict): User's login data
        Returns:
            dict: successful or not - user exists or not
            {"is_successful": True | False, "is_user_exists": True | False}
        """

        login_request = UserLoginRequest.model_validate(login_data)
        email_lower = login_request.email.lower()
        user_db = self.collection.find_one(
            {"email": email_lower, "is_disabled": False},
            {
                "password": 1,
                "role": 1,
                "name": 1,
                "lockout_time": 1,
                "login_attempts": 1,
                "tenant_id": 1,
                "permissions": 1,
            },
        )
        if not user_db:
            return {
                "is_successful": False,
                "is_user_exists": False,
                "message": f"Email ID: {login_request.email} is not permitted on the portal.",
            }

        # Check if the user is locked out
        if user_db.get("lockout_time"):
            lockout_time = user_db["lockout_time"]
            if lockout_time.tzinfo is None:
                lockout_time = lockout_time.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) < lockout_time:
                remaining_time = lockout_time - datetime.now(timezone.utc)
                hours, remainder = divmod(remaining_time.seconds, 3600)
                minutes, seconds = divmod(remainder, 60)
                return {
                    "is_successful": False,
                    "is_user_exists": True,
                    "message": f"Account is locked. Try again later. Lockout ends in {hours} hours, {minutes} minutes, and {seconds} seconds.",
                }

        user_db_pass = user_db.get("password", "")

        if not verify_password(login_request.password, user_db_pass):
            # Increment login attempts
            login_attempts = user_db.get("login_attempts", 0) + 1
            lockout_time = None

            # Set lockout time if necessary
            MAX_LOGIN_ATTEMPTS_PER_DAY = ProjectConfig.MAX_LOGIN_ATTEMPTS_PER_DAY
            LOCKOUT_COUNTER = ProjectConfig.LOCKOUT_COUNTER
            if login_attempts >= MAX_LOGIN_ATTEMPTS_PER_DAY:
                lockout_time = datetime.now(timezone.utc) + timedelta(days=1)
                login_attempts = 0  # Set login attempts as 0 after final penality

            elif login_attempts % LOCKOUT_COUNTER == 0:
                lockout_time = datetime.now(timezone.utc) + timedelta(minutes=5 * (login_attempts // LOCKOUT_COUNTER))

            self.collection.update_one(
                {"email": email_lower},
                {"$set": {"login_attempts": login_attempts, "lockout_time": lockout_time}},
            )

            return {"is_successful": False, "is_user_exists": True, "message": f"Email ID and Password doesn't match."}

        # Reset login attempts, update lockout time,  in a single query
        self.collection.update_one(
            {"email": email_lower},
            {
                "$set": {
                    "login_attempts": 0,
                    "lockout_time": None,
                }
            },
        )

        encryption_system = EncryptionSystem()
        encryption_dict = {
            "email": login_request.email.lower(),
            "role": user_db["role"],
        }

        if user_db["role"] in (UserRoles.COMPANY_ADMIN, UserRoles.EMPLOYEE):
            encryption_dict["tenant_id"] = user_db["tenant_id"]

        auth_token = encryption_system.encrypt_dict(input_json=encryption_dict)
        return {
            "is_successful": True,
            "is_user_exists": True,
            "auth_token": auth_token,
            "message": "Sign-in successful!",
            "name": user_db["name"],
            "role": user_db["role"],
            "permissions": user_db.get("permissions", {}),
            "email": email_lower,
        }

    def user_logout_db(self, email: str) -> dict:
        """Logs user out
        Args:
            email (dict): User's email id
        Returns:
            dict: successful or not - user exists or not
            {"is_successful": True | False, "is_user_exists": True | False}
        """
        email_lower = email.lower()
        user = self.collection.find_one({"email": email_lower}, {"_id": 1})

        if not user:
            return {"is_successful": False, "is_user_exists": False, "message": "User does not exist."}

        self.collection.update_one(
            {"email": email_lower},
            {"$unset": {"lockout_time": "", "login_attempts": 0, "update_password_permission": False}},
        )

        return {"is_successful": True, "is_user_exists": True, "message": "User logged out successfully."}

    def is_email_exists(self, email: str) -> bool:
        user_exists = self.collection.find_one({"email": email, "is_disabled": False}, {"_id": 1})
        return user_exists is not None

    def send_reset_password_otp(self, email: str) -> dict[str, Any]:
        email_lower = email.lower()
        user = self.collection.find_one({"email": email_lower, "is_disabled": False}, {"_id": 1, "last_otp_time": 1})
        if not user:
            return {
                "is_successful": False,
                "message": f"Either Email '{email_lower}' does not exist or is not permitted on the portal.",
            }

        # Check the last OTP request time
        last_otp_time = user.get("last_otp_time")
        if last_otp_time:
            # Convert last_otp_time to timezone-aware if it's not
            if last_otp_time.tzinfo is None:
                last_otp_time = last_otp_time.replace(tzinfo=timezone.utc)

            time_since_last_otp = datetime.now(timezone.utc) - last_otp_time
            if time_since_last_otp < timedelta(seconds=ProjectConfig.OTP_RESEND_COOLDOWN_SECONDS):
                return {
                    "is_successful": False,
                    "message": f"You can only request a new OTP every {ProjectConfig.OTP_RESEND_COOLDOWN_SECONDS} seconds.",
                }

        send_email = SendEmail()
        otp = generate_randomised_numeric_string(length=6)
        is_successful = send_email.send_forgot_password_otp_email(receiver_email=email_lower, otp=otp)

        if not is_successful:
            return {
                "is_successful": False,
                "message": "Error sending OTP in email. Please check your email and try again",
            }

        self.collection.update_one(
            {"email": email_lower}, {"$set": {"reset_password_otp": otp, "last_otp_time": datetime.now(timezone.utc)}}
        )

        OTP_VALIDITY = ProjectConfig.OTP_VALIDITY_MINUTES  # In minutes
        timer = threading.Timer(OTP_VALIDITY * 60, self.delete_reset_password_otp, [email_lower])
        timer.start()

        return {
            "is_successful": True,
            "message": "OTP has been sent to your email and it will be valid for 5 minutes only.",
        }

    def delete_reset_password_otp(self, email: str) -> None:
        """Deletes the reset_password_otp attribute from the database."""
        self.collection.update_one({"email": email}, {"$unset": {"reset_password_otp": "", "last_otp_time": ""}})

    def delete_update_password_permission(self, email: str) -> None:
        """Deletes the update_password_permission attribute from the database."""
        self.collection.update_one({"email": email}, {"$unset": {"update_password_permission": ""}})

    def verify_reset_password_otp(self, email: str, input_otp: str) -> dict[str, Any]:

        email_lower = email.lower()
        user = self.collection.find_one(
            {"email": email_lower, "is_disabled": False},
            {"_id": 1, "reset_password_otp": 1, "last_otp_time": 1, "otp_attempts": 1, "update_password_permission": 1},
        )
        if not user:
            return {
                "is_successful": False,
                "message": f"Either Email '{email_lower}' does not exist or is not permitted on the portal.",
            }

        # Get the current number of attempts
        otp_attempts = user.get("otp_attempts", 0)
        MAX_OTP_ATTEMPTS = 5

        if otp_attempts >= MAX_OTP_ATTEMPTS:
            self.collection.update_one(
                {"email": email_lower}, {"$unset": {"reset_password_otp": ""}, "$set": {"otp_attempts": 0}}
            )
            return {"is_successful": False, "message": "Maximum OTP attempts reached. Please request a new OTP."}

        if user.get("reset_password_otp") == input_otp:
            PASSWORD_RESET_VALIDITY = 5  # In minutes
            self.collection.update_one(
                {"email": email_lower},
                {
                    "$set": {"otp_attempts": 0, "update_password_permission": True},
                    "$unset": {"reset_password_otp": "", "last_otp_time": ""},
                },
            )
            timer = threading.Timer(PASSWORD_RESET_VALIDITY * 60, self.delete_update_password_permission, [email_lower])
            timer.start()

            return {"is_successful": True, "message": "OTP verified successfully!"}
        else:
            otp_attempts += 1
            self.collection.update_one({"email": email_lower}, {"$set": {"otp_attempts": otp_attempts}})
            attempts_left = MAX_OTP_ATTEMPTS - otp_attempts
            return {
                "is_successful": False,
                "message": f"Invalid OTP, please try again! You have {attempts_left} attempts left.",
            }

    def update_password(self, email: str, new_password: str) -> dict[str, Any]:

        email_lower = email.lower()
        user = self.collection.find_one(
            {"email": email_lower, "is_disabled": False}, {"_id": 1, "update_password_permission": 1}
        )
        if not user.get("update_password_permission", False):  # type: ignore
            return {"is_successful": False, "message": "You do not have permission to update the password"}

        hashed_password = hash_password(new_password)
        self.collection.update_one(
            {"email": email_lower},
            {
                "$set": {"password": hashed_password},
                "$unset": {
                    "lockout_time": "",
                    "login_attempts": 0,
                    "update_password_permission": False,
                    "reset_password_otp": "",
                    "last_otp_time": "",
                },
            },
        )

        return {"is_successful": True, "message": "Password updated successfully!"}

    def change_password(self, email: str, old_password: str, new_password: str) -> dict:
        """Updates user password if old password matches and new password is valid.

        Args:
            email (str): User's email address
            old_password (str): User's current password
            new_password (str): User's desired new password

        Returns:
            dict: {"is_successful": True/False, "message": str}
                - is_successful: True if password updated successfully, False otherwise
                - message: Descriptive message indicating the result
        """
        email_lower = email.lower()
        user_db = self.collection.find_one({"email": email_lower, "is_disabled": False}, {"_id": 1, "password": 1})

        if not user_db:
            return {"is_successful": False, "message": "User not found or account is disabled."}

        if not verify_password(old_password, user_db.get("password", "")):
            return {"is_successful": False, "message": "Old password is incorrect."}

        hashed_new_password = hash_password(new_password)
        self.collection.update_one({"email": email_lower}, {"$set": {"password": hashed_new_password}})

        return {"is_successful": True, "message": "Password updated successfully."}

    def update_user_profile(self, current_user_email: str, profile_data: dict) -> tuple[dict[str, Any], int]:

        try:
            validated_data = UpdateUserDetails.model_validate(profile_data)
        except ValidationError as e:
            logger.exception("Validation error while updating user profile", e)
            return {"is_successful": False, "message": "Invalid or incomplete request data."}, HTTPStatus.BAD_REQUEST

        existing_user = self.collection.find_one(
            {"email": current_user_email},
            {
                "_id": 1,
                "email": 1,
            },
        )
        if not existing_user:
            return {
                "is_successful": False,
                "message": f"User with email '{current_user_email}' not found.",
            }, HTTPStatus.NOT_FOUND

        updated_data = validated_data.model_dump(exclude_unset=True)
        # updated_data["email"] = current_user_email  # Prevent email update
        result = self.collection.update_one(
            {"email": current_user_email},
            {"$set": updated_data},
        )

        if result.matched_count == 0:
            return {
                "is_successful": False,
                "message": "Failed to find the user to update.",
            }, HTTPStatus.NOT_FOUND

        if result.modified_count == 0:
            return {
                "is_successful": True,
                "message": "No changes were made to the user details.",
            }, HTTPStatus.OK

        return {
            "is_successful": True,
            "message": f"User '{validated_data.name}' updated successfully.",
        }, HTTPStatus.OK
