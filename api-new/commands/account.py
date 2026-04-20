"""Account CLI commands for the FastAPI port.

The legacy Flask commands are not fully ported yet. Keep the command names
registered so extension bootstrap and CLI wiring stay intact while the command
logic moves over incrementally.
"""

from __future__ import annotations

from commands._common import unsupported_with_options

create_tenant = unsupported_with_options("create-tenant")
reset_email = unsupported_with_options("reset-email")
reset_password = unsupported_with_options("reset-password")
