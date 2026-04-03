"""
Send refresh digest email to all subscribers in refresh_digest_emails.

Reads data/prizepicks_results.json and data/moneylines.json from repo data/.
Requires SMTP_HOST + SMTP_USER + SMTP_PASSWORD (see README).

Usage (e.g. from refresh.sh after fetch_data + update_model_stats):
  python scripts/send_refresh_digest.py

Exits 0 if email delivery not configured or no subscribers (no failure).
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.config import load_env  # noqa: E402

load_env()

from app import create_app  # noqa: E402
from app.models.models import RefreshDigestEmail  # noqa: E402
from app.services.refresh_digest import (  # noqa: E402
    email_delivery_configured,
    send_digest_to_recipients,
)


def main() -> int:
    if not email_delivery_configured():
        print("⏭️  Skipping refresh digest — SMTP not configured.")
        print("   Set SMTP_HOST, SMTP_USER, SMTP_PASSWORD in .env (see README).")
        return 0

    app = create_app()
    with app.app_context():
        rows = RefreshDigestEmail.query.order_by(RefreshDigestEmail.email).all()
        recipients = [r.email for r in rows]

    if not recipients:
        print("⏭️  No refresh digest subscribers; no email sent.")
        return 0

    print(f"📧 Sending refresh digest to {len(recipients)} subscriber(s)...")
    send_digest_to_recipients(recipients)
    print("✅ Refresh digest sent.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print(f"❌ Refresh digest failed: {e}")
        raise
