from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, SecretStr, model_validator

from app.models.domain import MembershipRole


class MemberResponse(BaseModel):
    user_id: UUID
    email: EmailStr
    display_name: str
    role: MembershipRole
    status: str
    joined_at: datetime


class InvitationResponse(BaseModel):
    id: UUID
    email: EmailStr
    role: MembershipRole
    status: str
    expires_at: datetime
    created_at: datetime
    invited_by_user_id: UUID


class MemberListResponse(BaseModel):
    members: list[MemberResponse]
    invitations: list[InvitationResponse]
    total_members: int
    total_invitations: int
    offset: int
    limit: int


class InvitationCreateRequest(BaseModel):
    email: EmailStr
    role: MembershipRole


class MembershipRoleUpdateRequest(BaseModel):
    role: MembershipRole


class InvitationAcceptanceRequest(BaseModel):
    token: SecretStr = Field(min_length=1, max_length=512)
    display_name: str | None = Field(default=None, min_length=1, max_length=160)
    password: SecretStr | None = Field(default=None, min_length=12, max_length=128)

    @model_validator(mode="after")
    def setup_fields_are_paired(self) -> "InvitationAcceptanceRequest":
        if (self.display_name is None) != (self.password is None):
            raise ValueError("Display name and password must be provided together.")
        return self


class InvitationAcceptanceResponse(BaseModel):
    message: str
    account_created: bool
    tenant_id: UUID
    tenant_name: str
    role: MembershipRole
