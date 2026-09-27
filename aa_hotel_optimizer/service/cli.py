import argparse
from urllib.parse import urlparse

import uvicorn

from .config import settings


def main():
    parser = argparse.ArgumentParser(description="Run LP Optimizer")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()
    config = settings()
    if not config.production and args.host not in ("127.0.0.1", "::1", "localhost"):
        parser.error(
            "The local preview must bind to loopback; configure production before exposing it."
        )
    uvicorn.run(
        "aa_hotel_optimizer.service.app:create_app",
        factory=True,
        host=args.host,
        port=args.port or urlparse(config.public_url).port or 8787,
        reload=args.reload,
        forwarded_allow_ips="127.0.0.1",
    )


if __name__ == "__main__":
    main()
