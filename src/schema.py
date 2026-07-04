from typing import Optional, Union

from pydantic import BaseModel, Field

from src.enums import CompanyBillingPlan, EmployeePermissionType


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
    log_manager: EmployeePermissionType = EmployeePermissionType.NOT_ALLOWED


class EmployeeDetails(BaseModel):
    name: str = Field(..., max_length=100)
    email: str = Field(..., max_length=300)
    phone_number: str = Field(..., max_length=20)
    permissions: EmployeePermissions


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
