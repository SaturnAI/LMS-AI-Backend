"""
Project Configuration File
===========================
This file centralises every value that is likely to change between products /
deployments.  When starting a new project, edit ONLY this file to configure:
  - Branding (name, support email, colour theme)
  - Allowed CORS origins
  - Redis connection and key prefixes
  - Rate-limit thresholds
  - Auth-token lifetime
  - File-upload limits
  - Login-lockout policy
  - OTP settings

Secrets (API keys, passwords, DB URIs) still live in environment variables
loaded via src/cred.py.  Do NOT put secrets here.
"""

import os


class ProjectConfig:
    # Brand
    BRAND_NAME: str = "LMS-AI"
    SUPPORT_EMAIL: str = "info@saturnai.in"

    # CORS / Allowed Origins
    # Origins allowed in production
    PRODUCTION_ORIGINS: list[str] = [
        "https://lmsai.saturnai.in",
    ]
    # Extra origins added when NOT in production (UAT / LOCAL)
    NON_PRODUCTION_ORIGINS: list[str] = [
        "http://localhost:3000",
    ]

    # File Uploads
    MAX_LOGO_SIZE_MB: int = 2  # Company logo / profile picture hard limit
    MAX_UPLOAD_SIZE_MB: int = 5  # Middleware-level cap for any upload

    # Login Security (brute-force protection)
    MAX_LOGIN_ATTEMPTS_PER_DAY: int = 20  # Hard lock after this many failures
    LOCKOUT_COUNTER: int = 5  # Temporary lock every N failures

    # Auth Key Rotation
    KEY_ROTATION_CHECK_INTERVAL: int = 24 * 60 * 60  # Check for key rotation every 24 hours
    KEY_ROTATION_DAYS: int = 30  # Auto-rotate the Fernet auth key every N days

    # OTP / Password Reset
    OTP_RESEND_COOLDOWN_SECONDS: int = 30  # Minimum gap between OTP requests
    OTP_VALIDITY_MINUTES: int = 10  # OTP expires after this many minutes

    # Email Theme  (hex colours used in transactional email templates)
    EMAIL_THEME: dict = {
        "primary_color": "#1D71D4",
        "primary_dark": "#1e40af",
        "primary_darker": "#1e3a8a",
        "background_light": "#eff6ff",
        "background_box": "#dbeafe",
        "border_color": "#3b82f6",
        "text_primary": "#333333",
        "text_secondary": "#6b7280",
        "white": "#ffffff",
        "footer_bg": "#f9fafb",
    }
