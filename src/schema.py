from typing import Optional, Union

from pydantic import BaseModel, Field

from src.enums import (
    CompanyBillingPlan,
    EmployeePermissionType,
    LeadPriority,
    LeadSource,
    LeadStatus,
)


class UserLoginRequest(BaseModel):
    email: str
    password: str
    # refresh_token_info: Optional[dict] = None


class AddUpdateUserRequest(BaseModel):
    email: str
    name: str
    phone_number: int


# class GetAccessTokenRequest(BaseModel):
#     email: str
#     refresh_token: str


class UpdateUserDetails(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    phone_number: Optional[str] = Field(None, max_length=15)
    designation: Optional[str] = Field(None, max_length=100)


# Company Master
class CompanyDetails(BaseModel):
    legal_name: str = Field(..., max_length=80)
    phone_number: str = Field(..., max_length=30)
    address_1: str = Field(..., max_length=100)
    address_2: str = Field(default="", max_length=100)
    country: str = Field(..., max_length=50)
    state: str = Field(..., max_length=50)
    city: str = Field(..., max_length=30)
    pincode: str = Field(..., max_length=15)
    industry: str = Field(default="", max_length=100)
    company_size: str = Field(default="", max_length=50)
    gst_number: str = Field(default="", max_length=15)
    pan_number: str = Field(default="", max_length=10)
    billing_plan: CompanyBillingPlan = CompanyBillingPlan.FREE

    employee_limit: int = Field(..., ge=1)

    # Contact Info
    name: str = Field(..., max_length=80)
    email: str = Field(..., max_length=80)
    mobile_number: str = Field(default="", max_length=30)
    website: str = Field(default="", max_length=100)
    designation: str = Field(default="", max_length=100)


class CompanyProfile(BaseModel):
    legal_name: str = Field(..., max_length=80)
    phone_number: str = Field(..., max_length=30)
    address_1: str = Field(..., max_length=100)
    address_2: str = Field(default="", max_length=100)
    country: str = Field(..., max_length=50)
    state: str = Field(..., max_length=50)
    city: str = Field(..., max_length=30)
    pincode: str = Field(..., max_length=15)
    industry: str = Field(default="", max_length=100)
    company_size: str = Field(default="", max_length=50)
    gst_number: str = Field(default="", max_length=15)
    pan_number: str = Field(default="", max_length=10)

    # Contact Info
    name: str = Field(..., max_length=80)
    mobile_number: str = Field(default="", max_length=30)
    website: str = Field(default="", max_length=100)
    designation: str = Field(default="", max_length=100)


# Employee Master
class EmployeePermissions(BaseModel):
    employee_master: EmployeePermissionType = EmployeePermissionType.NOT_ALLOWED
    leads: EmployeePermissionType = EmployeePermissionType.NOT_ALLOWED
    log_manager: EmployeePermissionType = EmployeePermissionType.NOT_ALLOWED


class EmployeeDetails(BaseModel):
    name: str = Field(..., max_length=100)
    email: str = Field(..., max_length=300)
    phone_number: str = Field(..., max_length=20)
    permissions: EmployeePermissions


class CompanyAddress(BaseModel):
    address_1: Optional[str] = Field(default=None, max_length=100)
    address_2: Optional[str] = Field(default=None, max_length=100)
    country: Optional[str] = Field(default=None, max_length=50)
    state: Optional[str] = Field(default=None, max_length=50)
    city: Optional[str] = Field(default=None, max_length=30)
    pincode: Optional[str] = Field(default=None, max_length=15)


class LeadSpecificPersonOfContact(BaseModel):
    name: Optional[str] = Field(default=None, max_length=100)
    email: Optional[str] = Field(default=None, max_length=300)
    phone_number: Optional[str] = Field(default=None, max_length=20)
    designation: Optional[str] = Field(default=None, max_length=100)


class LeadDetails(BaseModel):
    name: str = Field(..., max_length=200)
    company_name: str = Field(..., max_length=100)
    sales_representative_emails: list[str] = Field(default_factory=list)

    email: Optional[str] = Field(default=None, max_length=300)
    alt_email: Optional[str] = Field(default=None, max_length=300)
    phone_number: Optional[str] = Field(default=None, max_length=20)
    alt_phone_number: Optional[str] = Field(default=None, max_length=20)
    designation: Optional[str] = Field(default=None, max_length=100)

    company_registered_address: Optional[CompanyAddress] = None
    company_operational_address: Optional[CompanyAddress] = None

    status: LeadStatus = LeadStatus.NEW
    source: LeadSource = LeadSource.OTHER
    priority: LeadPriority = LeadPriority.MEDIUM

    remarks: Optional[str] = Field(default=None, max_length=500)
    person_of_contact: Optional[LeadSpecificPersonOfContact] = None


# AI Analyser
class Examples(BaseModel):
    user_prompt: Union[str, list]
    completion: dict


class JSONSchema(BaseModel):
    role: str
    description: list[str]
    instructions: str
    examples: Optional[list[Examples]] = []
    important_notes: Optional[list] = []


class IndexTextRequest(BaseModel):
    lead_code: str = Field(..., min_length=1, max_length=100)
    title: str = Field(default="text-input", max_length=200)
    text: str = Field(..., min_length=1)
    source: str = Field(default="manual_input", max_length=100)


class AskQuestionRequest(BaseModel):
    lead_code: str = Field(..., min_length=1, max_length=100)
    question: str = Field(..., min_length=1)
    stream: bool = True
    top_k: int = 5
