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
    LOG_MANAGER = "log_manager"
    AUTH_KEY_STORE = "auth_key_store"
    OAUTH_STATES = "oauth_states"

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


class CompanyBillingPlan(str, Enum):
    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"
