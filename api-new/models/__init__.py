from __future__ import annotations

from importlib import import_module
from typing import Any

_MODULE_EXPORTS: dict[str, tuple[str, ...]] = {
    "account": (
        "Account",
        "AccountIntegrate",
        "AccountStatus",
        "InvitationCode",
        "Tenant",
        "TenantAccountJoin",
        "TenantAccountRole",
        "TenantStatus",
    ),
    "api_based_extension": (
        "APIBasedExtension",
        "APIBasedExtensionPoint",
    ),
    "comment": (
        "WorkflowComment",
        "WorkflowCommentMention",
        "WorkflowCommentReply",
    ),
    "dataset": (
        "AppDatasetJoin",
        "Dataset",
        "DatasetCollectionBinding",
        "DatasetKeywordTable",
        "DatasetPermission",
        "DatasetPermissionEnum",
        "DatasetProcessRule",
        "DatasetQuery",
        "Document",
        "DocumentSegment",
        "Embedding",
        "ExternalKnowledgeApis",
        "ExternalKnowledgeBindings",
        "TidbAuthBinding",
        "Whitelist",
    ),
    "enums": (
        "AppTriggerStatus",
        "AppTriggerType",
        "CreatorUserRole",
        "WorkflowRunTriggeredFrom",
        "WorkflowTriggerStatus",
    ),
    "execution_extra_content": (
        "ExecutionExtraContent",
        "HumanInputContent",
    ),
    "human_input": ("HumanInputForm",),
    "model": (
        "AccountTrialAppRecord",
        "ApiRequest",
        "ApiToken",
        "App",
        "AppAnnotationHitHistory",
        "AppAnnotationSetting",
        "AppMCPServer",
        "AppMode",
        "AppModelConfig",
        "Conversation",
        "DatasetRetrieverResource",
        "DifySetup",
        "EndUser",
        "ExporleBanner",
        "IconType",
        "InstalledApp",
        "Message",
        "MessageAgentThought",
        "MessageAnnotation",
        "MessageChain",
        "MessageFeedback",
        "MessageFile",
        "OperationLog",
        "RecommendedApp",
        "Site",
        "Tag",
        "TagBinding",
        "TenantCreditPool",
        "TraceAppConfig",
        "TrialApp",
        "UploadFile",
    ),
    "oauth": (
        "DatasourceOauthParamConfig",
        "DatasourceProvider",
    ),
    "provider": (
        "LoadBalancingModelConfig",
        "Provider",
        "ProviderModel",
        "ProviderModelSetting",
        "ProviderOrder",
        "ProviderQuotaType",
        "ProviderType",
        "TenantDefaultModel",
        "TenantPreferredModelProvider",
    ),
    "source": (
        "DataSourceApiKeyAuthBinding",
        "DataSourceOauthBinding",
    ),
    "task": (
        "CeleryTask",
        "CeleryTaskSet",
    ),
    "tools": (
        "ApiToolProvider",
        "BuiltinToolProvider",
        "ToolConversationVariables",
        "ToolFile",
        "ToolLabelBinding",
        "ToolModelInvoke",
        "WorkflowToolProvider",
    ),
    "trigger": (
        "AppTrigger",
        "TriggerOAuthSystemClient",
        "TriggerOAuthTenantClient",
        "TriggerSubscription",
        "WorkflowSchedulePlan",
    ),
    "web": (
        "PinnedConversation",
        "SavedMessage",
    ),
    "workflow": (
        "ConversationVariable",
        "Workflow",
        "WorkflowAppLog",
        "WorkflowAppLogCreatedFrom",
        "WorkflowArchiveLog",
        "WorkflowNodeExecutionModel",
        "WorkflowNodeExecutionOffload",
        "WorkflowNodeExecutionTriggeredFrom",
        "WorkflowPause",
        "WorkflowRun",
        "WorkflowType",
    ),
}

_SYMBOL_TO_MODULE = {
    symbol: module_name
    for module_name, symbols in _MODULE_EXPORTS.items()
    for symbol in symbols
}

__all__ = sorted(_SYMBOL_TO_MODULE)


def __getattr__(name: str) -> Any:
    module_name = _SYMBOL_TO_MODULE.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module(f".{module_name}", __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value

