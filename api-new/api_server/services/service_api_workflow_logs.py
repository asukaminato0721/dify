"""FastAPI-native workflow log listing for `/v1` service API routes."""

from __future__ import annotations

from datetime import datetime
from typing import TypedDict

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import aliased

from api_server.models.app import Account, EndUser
from api_server.models.workflow import WorkflowAppLog, WorkflowRun
from extensions.ext_database import db


class ServiceApiSimpleAccountDict(TypedDict):
    id: str
    name: str
    email: str


class ServiceApiSimpleEndUserDict(TypedDict):
    id: str
    type: str
    is_anonymous: bool
    session_id: str | None


class ServiceApiWorkflowRunForLogDict(TypedDict):
    id: str
    version: str | None
    status: str | None
    triggered_from: str | None
    error: str | None
    elapsed_time: float
    total_tokens: int
    total_steps: int | None
    created_at: int
    finished_at: int | None
    exceptions_count: int | None


class ServiceApiWorkflowLogItemDict(TypedDict):
    id: str
    workflow_run: ServiceApiWorkflowRunForLogDict | None
    details: None
    created_from: str
    created_by_role: str
    created_by_account: ServiceApiSimpleAccountDict | None
    created_by_end_user: ServiceApiSimpleEndUserDict | None
    created_at: int


class ServiceApiWorkflowLogPaginationDict(TypedDict):
    page: int
    limit: int
    total: int
    has_more: bool
    data: list[ServiceApiWorkflowLogItemDict]


class ServiceApiWorkflowLogService:
    """Query workflow app logs through local async ORM mappings."""

    @staticmethod
    def _timestamp(value: datetime | None) -> int | None:
        if value is None:
            return None
        return int(value.timestamp())

    @classmethod
    def _serialize_workflow_run(cls, workflow_run: WorkflowRun | None) -> ServiceApiWorkflowRunForLogDict | None:
        if workflow_run is None:
            return None
        return {
            "id": workflow_run.id,
            "version": workflow_run.version,
            "status": workflow_run.status.value,
            "triggered_from": workflow_run.triggered_from,
            "error": workflow_run.error,
            "elapsed_time": float(workflow_run.elapsed_time or 0.0),
            "total_tokens": int(workflow_run.total_tokens or 0),
            "total_steps": workflow_run.total_steps,
            "created_at": cls._timestamp(workflow_run.created_at) or 0,
            "finished_at": cls._timestamp(workflow_run.finished_at),
            "exceptions_count": workflow_run.exceptions_count,
        }

    @staticmethod
    def _serialize_account(account: Account | None) -> ServiceApiSimpleAccountDict | None:
        if account is None:
            return None
        return {"id": account.id, "name": account.name, "email": account.email}

    @staticmethod
    def _serialize_end_user(end_user: EndUser | None) -> ServiceApiSimpleEndUserDict | None:
        if end_user is None:
            return None
        return {
            "id": end_user.id,
            "type": end_user.type,
            "is_anonymous": end_user.is_anonymous,
            "session_id": end_user.session_id,
        }

    @classmethod
    async def list_logs(
        cls,
        *,
        tenant_id: str,
        app_id: str,
        keyword: str | None,
        status: str | None,
        created_at_before: datetime | None,
        created_at_after: datetime | None,
        page: int,
        limit: int,
        created_by_end_user_session_id: str | None,
        created_by_account: str | None,
    ) -> ServiceApiWorkflowLogPaginationDict:
        stmt = (
            select(WorkflowAppLog, WorkflowRun)
            .outerjoin(WorkflowRun, WorkflowRun.id == WorkflowAppLog.workflow_run_id)
            .where(
                WorkflowAppLog.tenant_id == tenant_id,
                WorkflowAppLog.app_id == app_id,
            )
        )
        keyword_end_user = aliased(EndUser)
        created_end_user = aliased(EndUser)

        if keyword:
            keyword_like = f"%{keyword[:30]}%"
            stmt = stmt.outerjoin(
                keyword_end_user,
                and_(
                    WorkflowRun.created_by == keyword_end_user.id,
                    WorkflowRun.created_by_role == "end_user",
                ),
            ).where(
                or_(
                    WorkflowRun.inputs.ilike(keyword_like),
                    WorkflowRun.outputs.ilike(keyword_like),
                    keyword_end_user.session_id.ilike(keyword_like),
                    WorkflowRun.id == keyword,
                )
            )

        if status:
            stmt = stmt.where(WorkflowRun.status == status)
        if created_at_before is not None:
            stmt = stmt.where(WorkflowAppLog.created_at <= created_at_before)
        if created_at_after is not None:
            stmt = stmt.where(WorkflowAppLog.created_at >= created_at_after)

        if created_by_end_user_session_id:
            stmt = stmt.join(
                created_end_user,
                and_(
                    WorkflowAppLog.created_by == created_end_user.id,
                    WorkflowAppLog.created_by_role == "end_user",
                    created_end_user.session_id == created_by_end_user_session_id,
                ),
            )

        if created_by_account:
            stmt = stmt.join(
                Account,
                and_(
                    WorkflowAppLog.created_by == Account.id,
                    WorkflowAppLog.created_by_role == "account",
                    Account.email == created_by_account,
                ),
            )

        stmt = stmt.order_by(WorkflowAppLog.created_at.desc())

        async with db.session_context() as session:
            rows = (await session.execute(stmt.offset((page - 1) * limit).limit(limit))).all()
            total = len((await session.execute(stmt)).all())

            account_ids = {row[0].created_by for row in rows if row[0].created_by_role.value == "account"}
            end_user_ids = {row[0].created_by for row in rows if row[0].created_by_role.value == "end_user"}

            accounts_by_id: dict[str, Account] = {}
            if account_ids:
                accounts = (await session.scalars(select(Account).where(Account.id.in_(account_ids)))).all()
                accounts_by_id = {account.id: account for account in accounts}

            end_users_by_id: dict[str, EndUser] = {}
            if end_user_ids:
                end_users = (await session.scalars(select(EndUser).where(EndUser.id.in_(end_user_ids)))).all()
                end_users_by_id = {end_user.id: end_user for end_user in end_users}

        return {
            "page": page,
            "limit": limit,
            "total": total,
            "has_more": total > page * limit,
            "data": [
                {
                    "id": log.id,
                    "workflow_run": cls._serialize_workflow_run(workflow_run),
                    "details": None,
                    "created_from": log.created_from.value,
                    "created_by_role": log.created_by_role.value,
                    "created_by_account": cls._serialize_account(accounts_by_id.get(log.created_by)),
                    "created_by_end_user": cls._serialize_end_user(end_users_by_id.get(log.created_by)),
                    "created_at": cls._timestamp(log.created_at) or 0,
                }
                for log, workflow_run in rows
            ],
        }
