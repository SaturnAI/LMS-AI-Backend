import os


class Credentials:
    openai_api_key = os.getenv("OPENAI_API_KEY", "")
    directory = os.getenv("DIRECTORY", "")

    mongo_url = os.getenv("MONGO_URL", "")
    db_name = os.getenv("DB_NAME", "")

    redirect_url = os.getenv("REDIRECT_URL", "")
    environment = os.getenv("ENVIRONMENT", "LOCAL")

    smtp_email = os.getenv("SMTP_EMAIL", "")
    smtp_provider = os.getenv("SMTP_PROVIDER", "")
    smtp_host = os.getenv("SMTP_HOST", "")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_use_ssl = os.getenv("SMTP_USE_SSL", "false").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    # Gmail OAuth2 (XOAUTH2) credentials
    smtp_oauth_client_id = os.getenv("SMTP_OAUTH_CLIENT_ID", "")
    smtp_oauth_client_secret = os.getenv("SMTP_OAUTH_CLIENT_SECRET", "")
    smtp_oauth_refresh_token = os.getenv("SMTP_OAUTH_REFRESH_TOKEN", "")
