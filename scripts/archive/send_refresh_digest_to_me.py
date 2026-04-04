"""
Send the same refresh digest as send_refresh_digest.py, but always to one address
(does not read refresh_digest_emails). For testing / personal copies.

  python scripts/archive/send_refresh_digest_to_me.py

Requires SMTP_* env vars like the main sender.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from app.config import load_env  # noqa: E402

load_env()

from app.services.refresh_digest import (  # noqa: E402
    email_delivery_configured,
    send_digest_to_recipients,
)

DIGEST_TO = "davisb7@me.com"


def main() -> int:
    if not email_delivery_configured():
        print("⏭️  Skipping — SMTP not configured.")
        print("   Set SMTP_HOST, SMTP_USER, SMTP_PASSWORD in .env (see README).")
        return 0

    print(f"📧 Sending refresh digest (test copy) to {DIGEST_TO!r} only...")
    send_digest_to_recipients([DIGEST_TO])
    print("✅ Refresh digest sent.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print(f"❌ Refresh digest failed: {e}")
        raise
