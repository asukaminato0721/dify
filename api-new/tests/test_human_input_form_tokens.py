from __future__ import annotations

from types import SimpleNamespace
from typing import cast

from sqlalchemy.orm import Session

from core.workflow.human_input_forms import load_form_tokens_by_form_id


class _SessionStub:
    def __init__(self, recipients: list[SimpleNamespace]) -> None:
        self._recipients = recipients

    def scalars(self, _stmt: object) -> list[SimpleNamespace]:
        return self._recipients


def test_load_form_tokens_by_form_id_prefers_highest_priority_recipient() -> None:
    session = _SessionStub(
        [
            SimpleNamespace(
                form_id="form-1",
                recipient_type="standalone_web_app",
                access_token="token-web",
            ),
            SimpleNamespace(
                form_id="form-1",
                recipient_type="console",
                access_token="token-console",
            ),
            SimpleNamespace(
                form_id="form-1",
                recipient_type="backstage",
                access_token="token-backstage",
            ),
        ]
    )

    result = load_form_tokens_by_form_id(["form-1"], session=cast(Session, session))

    assert result == {"form-1": "token-backstage"}
