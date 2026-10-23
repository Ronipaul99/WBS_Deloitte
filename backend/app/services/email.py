import asyncio
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from functools import lru_cache
from typing import Protocol
from urllib.parse import urlencode
from uuid import UUID

from app.core.config import Settings, get_settings
from app.db.session import SessionLocal
from app.models.auth import PasswordResetToken, TenantInvitation
from app.services.auth import add_auth_event, utc_now


class TransactionalEmailProvider(Protocol):
    async def send_password_reset(self, recipient: str, reset_url: str) -> None: ...

    async def send_tenant_invitation(
        self, recipient: str, invitation_url: str, tenant_name: str
    ) -> None: ...


class EmailDeliveryError(RuntimeError):
    pass


@dataclass(frozen=True)
class PasswordResetDelivery:
    recipient: str
    reset_url: str


@dataclass(frozen=True)
class TenantInvitationDelivery:
    recipient: str
    invitation_url: str
    tenant_name: str


class InMemoryEmailProvider:
    def __init__(self) -> None:
        self.deliveries: list[PasswordResetDelivery] = []
        self.invitation_deliveries: list[TenantInvitationDelivery] = []
        self.should_fail = False

    async def send_password_reset(self, recipient: str, reset_url: str) -> None:
        if self.should_fail:
            raise EmailDeliveryError("Password reset email delivery failed")
        self.deliveries.append(PasswordResetDelivery(recipient=recipient, reset_url=reset_url))

    async def send_tenant_invitation(
        self, recipient: str, invitation_url: str, tenant_name: str
    ) -> None:
        if self.should_fail:
            raise EmailDeliveryError("Tenant invitation email delivery failed")
        self.invitation_deliveries.append(
            TenantInvitationDelivery(
                recipient=recipient,
                invitation_url=invitation_url,
                tenant_name=tenant_name,
            )
        )

    def clear(self) -> None:
        self.deliveries.clear()
        self.invitation_deliveries.clear()
        self.should_fail = False


class SmtpEmailProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _send(self, recipient: str, reset_url: str) -> None:
        message = EmailMessage()
        message["From"] = self.settings.email_from
        message["To"] = recipient
        message["Subject"] = "Reset your WBS Genie password"
        message.set_content(
            "A password reset was requested for your WBS Genie account.\n\n"
            f"Reset your password: {reset_url}\n\n"
            f"This link expires in {self.settings.password_reset_minutes} minutes. "
            "If you did not request this, you can ignore this email."
        )

        context = ssl.create_default_context()
        if self.settings.smtp_security == "tls":
            smtp = smtplib.SMTP_SSL(
                self.settings.smtp_host,
                self.settings.smtp_port,
                timeout=self.settings.email_delivery_timeout_seconds,
                context=context,
            )
        else:
            smtp = smtplib.SMTP(
                self.settings.smtp_host,
                self.settings.smtp_port,
                timeout=self.settings.email_delivery_timeout_seconds,
            )
        with smtp:
            if self.settings.smtp_security == "starttls":
                smtp.starttls(context=context)
            if self.settings.smtp_username and self.settings.smtp_password:
                smtp.login(self.settings.smtp_username, self.settings.smtp_password)
            smtp.send_message(message)

    async def send_password_reset(self, recipient: str, reset_url: str) -> None:
        attempts = self.settings.email_delivery_retries + 1
        for attempt in range(attempts):
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(self._send, recipient, reset_url),
                    timeout=self.settings.email_delivery_timeout_seconds + 1,
                )
                return
            except Exception:
                if attempt + 1 == attempts:
                    raise EmailDeliveryError("Password reset email delivery failed") from None
                await asyncio.sleep(min(2**attempt, 2))

    def _send_invitation(self, recipient: str, invitation_url: str, tenant_name: str) -> None:
        message = EmailMessage()
        message["From"] = self.settings.email_from
        message["To"] = recipient
        message["Subject"] = f"Join {tenant_name} in WBS Genie"
        message.set_content(
            f"You have been invited to join {tenant_name} in WBS Genie.\n\n"
            f"Accept the invitation: {invitation_url}\n\n"
            f"This link expires in {self.settings.tenant_invitation_hours} hours. "
            "If you were not expecting this invitation, you can ignore this email."
        )

        context = ssl.create_default_context()
        if self.settings.smtp_security == "tls":
            smtp = smtplib.SMTP_SSL(
                self.settings.smtp_host,
                self.settings.smtp_port,
                timeout=self.settings.email_delivery_timeout_seconds,
                context=context,
            )
        else:
            smtp = smtplib.SMTP(
                self.settings.smtp_host,
                self.settings.smtp_port,
                timeout=self.settings.email_delivery_timeout_seconds,
            )
        with smtp:
            if self.settings.smtp_security == "starttls":
                smtp.starttls(context=context)
            if self.settings.smtp_username and self.settings.smtp_password:
                smtp.login(self.settings.smtp_username, self.settings.smtp_password)
            smtp.send_message(message)

    async def send_tenant_invitation(
        self, recipient: str, invitation_url: str, tenant_name: str
    ) -> None:
        attempts = self.settings.email_delivery_retries + 1
        for attempt in range(attempts):
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(
                        self._send_invitation, recipient, invitation_url, tenant_name
                    ),
                    timeout=self.settings.email_delivery_timeout_seconds + 1,
                )
                return
            except Exception:
                if attempt + 1 == attempts:
                    raise EmailDeliveryError("Tenant invitation email delivery failed") from None
                await asyncio.sleep(min(2**attempt, 2))


def build_password_reset_url(settings: Settings, token: str) -> str:
    base_url = (settings.public_ui_url or "").rstrip("/")
    return f"{base_url}/reset-password#{urlencode({'token': token})}"


def build_tenant_invitation_url(settings: Settings, token: str) -> str:
    base_url = (settings.public_ui_url or "").rstrip("/")
    return f"{base_url}/accept-invitation#{urlencode({'token': token})}"


@lru_cache
def get_email_provider() -> TransactionalEmailProvider:
    settings = get_settings()
    if settings.email_provider == "test":
        return InMemoryEmailProvider()
    return SmtpEmailProvider(settings)


async def deliver_password_reset_email(
    provider: TransactionalEmailProvider,
    *,
    recipient: str,
    reset_url: str,
    token_id: UUID,
    user_id: UUID,
    subject_hash: str,
    ip_hash: str,
    user_agent_hash: str,
) -> None:
    delivered = True
    try:
        await provider.send_password_reset(recipient, reset_url)
    except Exception:
        delivered = False

    async with SessionLocal() as db:
        if not delivered:
            token = await db.get(PasswordResetToken, token_id)
            if token is not None and token.used_at is None:
                token.used_at = utc_now()
        add_auth_event(
            db,
            event_type="password_reset_delivery",
            success=delivered,
            user_id=user_id,
            subject_hash=subject_hash,
            ip_hash=ip_hash,
            user_agent_hash=user_agent_hash,
        )
        await db.commit()


async def deliver_tenant_invitation_email(
    provider: TransactionalEmailProvider,
    *,
    recipient: str,
    invitation_url: str,
    tenant_name: str,
    invitation_id: UUID,
    actor_id: UUID,
    subject_hash: str,
    ip_hash: str,
    user_agent_hash: str,
) -> None:
    delivered = True
    try:
        await provider.send_tenant_invitation(recipient, invitation_url, tenant_name)
    except Exception:
        delivered = False

    async with SessionLocal() as db:
        invitation = await db.get(TenantInvitation, invitation_id)
        if not delivered and invitation is not None and invitation.accepted_at is None:
            invitation.revoked_at = utc_now()
        add_auth_event(
            db,
            event_type="tenant_invitation_delivery",
            success=delivered,
            user_id=actor_id,
            subject_hash=subject_hash,
            ip_hash=ip_hash,
            user_agent_hash=user_agent_hash,
            details={"invitation_id": str(invitation_id)},
        )
        await db.commit()
