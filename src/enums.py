from enum import Enum


class ApiReponseStatus(str, Enum):
    FAILED = "failed"
    PROCESSING = "processing"
    SUCCESS = "success"


# class AuthTokenType(str, Enum):
#     JWT_TOKEN = "jwt"
#     REFRESH_TOKEN = "refresh"


class MongoCollectionsNames(str, Enum):
    USER_MASTER = "user_master"
    COMPANY_MASTER = "company_master"
    LEADS = "leads"
    LEAD_COMMENTS = "lead_comments"
    LOG_MANAGER = "log_manager"
    AUTH_KEY_STORE = "auth_key_store"
    OAUTH_STATES = "oauth_states"
    AI_LEAD_FILES = "ai_lead_files"
    AI_LEAD_CHUNKS = "ai_lead_chunks"
    AI_LEAD_QUERY_CACHE = "ai_lead_query_cache"
    AI_LEAD_INDEX_JOBS = "ai_lead_index_jobs"

    # Just for Permissions
    EMPLOYEE_MASTER = "employee_master"


class UserRoles(str, Enum):
    SUPER_ADMIN = "super_admin"
    COMPANY_ADMIN = "company_admin"
    EMPLOYEE = "employee"


class Environments(str, Enum):
    LOCAL = "LOCAL"
    UAT = "UAT"
    PRODUCTION = "PRODUCTION"


class LogActionType(str, Enum):
    ADD = "add"
    EDIT = "edit"
    DELETE = "delete"
    DISABLE = "disable"
    ENABLE = "enable"
    UPLOADED = "uploaded"


class EmployeePermissionType(str, Enum):
    VIEW = "view"
    EDIT = "edit"
    NOT_ALLOWED = "not_allowed"


class PromptFileName(str, Enum):
    ...


class GptModel(str, Enum):
    GPT_5_MINI = "gpt-5-mini"
    GPT_5_4_MINI = "gpt-5.4-mini"
    GPT_5_4_NANO = "gpt-5.4-nano"


class GPTModels(str, Enum):
    GPT_5_4 = "gpt-5.4"
    GPT_5_4_MINI = "gpt-5.4-mini"
    GPT_5_4_NANO = "gpt-5.4-nano"


class CompanyBillingPlan(str, Enum):
    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"


class LeadStatus(str, Enum):
    NEW = "new"
    CONTACTED = "contacted"
    NURTURE = "nurture"
    QUALIFIED = "qualified"
    WON = "won"
    LOST = "lost"


class LeadSource(str, Enum):
    WEBSITE = "website"
    REFERRAL = "referral"
    COLD_CALL = "cold_call"
    SOCIAL_MEDIA = "social_media"
    EMAIL_CAMPAIGN = "email_campaign"
    TRADE_SHOW = "trade_show"
    OTHER = "other"


class LeadPriority(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
