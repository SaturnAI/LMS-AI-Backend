from config import ProjectConfig

MAX_AUTH_DAYS = ProjectConfig.MAX_AUTH_DAYS
MAX_AGE_AUTH_TOKEN_SECONDS = MAX_AUTH_DAYS * 24 * 60 * 60

MAX_FILE_SIZE = ProjectConfig.MAX_LOGO_SIZE_MB * 1024 * 1024
