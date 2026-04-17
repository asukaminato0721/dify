from __future__ import annotations

import uvicorn

from app_factory import create_app

app = create_app()


def main() -> None:
    uvicorn.run("main:app", host="0.0.0.0", port=5001, reload=False)


if __name__ == "__main__":
    main()
