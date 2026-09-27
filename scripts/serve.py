"""Hosted entrypoint. The host supplies PORT, proxy trust, and its HTTPS origin."""

import os

import uvicorn

if __name__ == "__main__":
    if not os.environ.get("LP_PUBLIC_URL") and os.environ.get("RENDER_EXTERNAL_URL"):
        os.environ["LP_PUBLIC_URL"] = os.environ["RENDER_EXTERNAL_URL"]
    # Validate before binding a public listener; never expose development login.
    from aa_hotel_optimizer.service.config import Settings

    config = Settings()
    config.validate_deployment()
    if not config.production:
        raise SystemExit("Hosted startup requires staging or production settings.")
    uvicorn.run(
        "aa_hotel_optimizer.service.app:create_app",
        factory=True,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        forwarded_allow_ips=os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1"),
        limit_concurrency=50,
    )
