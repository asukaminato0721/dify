"""FastAPI wrappers for dataset-token hit-testing endpoints."""

from __future__ import annotations

import asyncio
from typing import Any, TypedDict

import services
from api_server.errors import bad_request, forbidden, not_found
from api_server.services.service_api_legacy import load_legacy_owner_account
from services.dataset_service import DatasetService
from services.hit_testing_service import HitTestingService, QueryDict
from core.errors.error import (
    LLMBadRequestError,
    ModelCurrentlyNotSupportError,
    ProviderTokenNotInitError,
    QuotaExceededError,
)
from graphon.model_runtime.errors.invoke import InvokeError


class ServiceApiHitTestingResponseDict(TypedDict):
    query: QueryDict
    records: list[dict[str, Any]]


class ServiceApiHitTestingService:
    @classmethod
    async def hit_test(
        cls,
        *,
        tenant_id: str,
        dataset_id: str,
        payload: dict[str, Any],
    ) -> ServiceApiHitTestingResponseDict:
        def _run() -> ServiceApiHitTestingResponseDict:
            owner_account = load_legacy_owner_account(tenant_id)
            dataset = DatasetService.get_dataset(dataset_id)
            if dataset is None:
                raise not_found("dataset_not_found", "Dataset not found.")
            try:
                DatasetService.check_dataset_permission(dataset, owner_account)
            except services.errors.account.NoPermissionError as exc:
                raise forbidden("forbidden", str(exc)) from exc

            try:
                HitTestingService.hit_testing_args_check(payload)
                return HitTestingService.retrieve(
                    dataset=dataset,
                    query=payload.get("query", ""),
                    account=owner_account,
                    retrieval_model=payload.get("retrieval_model"),
                    external_retrieval_model=payload.get("external_retrieval_model") or {},
                    attachment_ids=payload.get("attachment_ids"),
                    limit=10,
                )
            except services.errors.index.IndexNotInitializedError as exc:
                raise bad_request("dataset_not_initialized", str(exc)) from exc
            except ProviderTokenNotInitError as exc:
                raise bad_request("provider_not_initialize", exc.description) from exc
            except QuotaExceededError as exc:
                raise bad_request("provider_quota_exceeded", str(exc)) from exc
            except ModelCurrentlyNotSupportError as exc:
                raise bad_request("provider_model_currently_not_support", str(exc)) from exc
            except LLMBadRequestError as exc:
                raise bad_request(
                    "provider_not_initialize",
                    "No Embedding Model or Reranking Model available. Please configure a valid provider in the Settings -> Model Provider.",
                ) from exc
            except InvokeError as exc:
                raise bad_request("completion_request_error", str(exc.description or exc)) from exc
            except ValueError as exc:
                raise bad_request("invalid_argument", str(exc)) from exc

        return await asyncio.to_thread(_run)
