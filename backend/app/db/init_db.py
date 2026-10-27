from sqlalchemy import select

from app.core.config import get_settings
from app.core.passwords import hash_password
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models.auth import AuthIdentity
from app.models.domain import MembershipRole, Tenant, TenantMembership, User


async def initialize_database() -> None:
    settings = get_settings()
    if settings.auto_create_tables:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    if settings.app_env not in {"development", "test"} or not settings.bootstrap_development_data:
        return

    async with SessionLocal() as session:
        tenant = await session.get(Tenant, settings.dev_tenant_id)
        if tenant is None:
            tenant = Tenant(
                id=settings.dev_tenant_id,
                name="Development Tenant",
                slug="development",
            )
            session.add(tenant)

        user = await session.get(User, settings.dev_user_id)
        if user is None:
            user = User(
                id=settings.dev_user_id,
                external_subject="development-user",
                email="developer@example.com",
                display_name="Development User",
            )
            session.add(user)

        membership = await session.scalar(
            select(TenantMembership).where(
                TenantMembership.tenant_id == settings.dev_tenant_id,
                TenantMembership.user_id == settings.dev_user_id,
            )
        )
        if membership is None:
            session.add(
                TenantMembership(
                    tenant_id=settings.dev_tenant_id,
                    user_id=settings.dev_user_id,
                    role=MembershipRole.ADMIN,
                )
            )

        if settings.dev_user_password:
            identity = await session.scalar(
                select(AuthIdentity).where(
                    AuthIdentity.provider == "local",
                    AuthIdentity.subject == user.email.casefold(),
                )
            )
            if identity is None:
                session.add(
                    AuthIdentity(
                        user_id=user.id,
                        provider="local",
                        subject=user.email.casefold(),
                        password_hash=hash_password(settings.dev_user_password),
                    )
                )

        await session.commit()
