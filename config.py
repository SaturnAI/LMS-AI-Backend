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

    MAX_AUTH_DAYS = 7

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
        "primary_color": "#111111",
        "primary_dark": "#000000",
        "primary_darker": "#000000",
        "background_light": "#f5f5f5",
        "background_box": "#fafafa",
        "border_color": "#d4d4d4",
        "text_primary": "#111111",
        "text_secondary": "#525252",
        "white": "#ffffff",
        "footer_bg": "#f3f3f3",
    }

    # AI Query Cache
    # Set to False to disable semantic query caching entirely.
    QUERY_CACHE_ENABLED: bool = True
    # Cosine-similarity threshold (0-1) for semantic cache hit.
    QUERY_CACHE_SIMILARITY_THRESHOLD: float = 0.90

    # Code Indexing (Repo/Lead Q&A)
    CODE_INDEX_MAX_FILE_SIZE_MB: int = 2
    CODE_INDEX_MAX_FILES: int = 5000
    # Logical chunking budget in characters per chunk.
    CODE_INDEX_UNIT_MAX_CHARS: int = 3000
    # Backward-compat alias used by older code paths.
    CODE_INDEX_CHUNK_SIZE_CHARS: int = CODE_INDEX_UNIT_MAX_CHARS
    CODE_INDEX_CHUNK_OVERLAP_LINES: int = 3
    CODE_INDEX_STRATEGY: str = "ast_logical"

    # Embeddings for Q&A
    CODE_EMBEDDING_MODEL: str = "text-embedding-3-small"

    # Retrieval
    CODE_QA_TOP_K: int = 5
    # In-memory embedding cache guardrails (per app process)
    CODE_QA_EMBED_CACHE_TTL_SECONDS: int = 600
    CODE_QA_EMBED_CACHE_MAX_PROJECTS: int = 5

    # AI Chat Context
    CHAT_CONTEXT_LAST_N: int = 7
    CHAT_SUMMARY_BATCH_SIZE: int = 7
    CHAT_SUMMARY_MAX_CHARS: int = 1200
