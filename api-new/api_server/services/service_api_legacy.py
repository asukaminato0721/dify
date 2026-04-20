"""Helpers for calling legacy sync dataset/pipeline services from FastAPI routes."""

from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import select

from api_server.errors import forbidden
from core.db.session_factory import create_sync_session
from models.account import Account as LegacyAccount
from models.account import Tenant as LegacyTenant
from models.account import TenantAccountJoin, TenantAccountRole


def load_legacy_owner_account(tenant_id: str) -> LegacyAccount:
    """Load the legacy owner account model with current-tenant context populated."""

    with create_sync_session() as session:
        row = session.execute(
            select(LegacyAccount, LegacyTenant)
            .join(TenantAccountJoin, TenantAccountJoin.account_id == LegacyAccount.id)
            .where(
                TenantAccountJoin.tenant_id == tenant_id,
                TenantAccountJoin.role == TenantAccountRole.OWNER,
                LegacyTenant.id == tenant_id,
            )
            .limit(1)
        ).first()

    if row is None:
        raise forbidden("owner_not_found", "Tenant owner account not found.")

    account, tenant = row
    account.current_tenant = tenant
    return account


@contextmanager
def dataset_service_current_user(account: LegacyAccount):
    """Temporarily bind the legacy dataset-service `current_user` proxy to an account."""

    import services.dataset_service as dataset_service_module

    original_current_user = dataset_service_module.current_user
    dataset_service_module.current_user = account
    try:
        yield
    finally:
        dataset_service_module.current_user = original_current_user
