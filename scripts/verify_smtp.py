"""
Verify SMTP env vars for the refresh digest.

  python scripts/verify_smtp.py              # show what's configured
  python scripts/verify_smtp.py --test-smtp  # connect + login only (no email)

Run send_refresh_digest.py with subscribers to test a real send.
"""

from __future__ import annotations

import argparse
import os
import smtplib
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.config import load_env  # noqa: E402

load_env()

from app.services.refresh_digest import (  # noqa: E402
    email_delivery_configured,
    smtp_configured,
    smtp_missing_env_keys,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--test-smtp",
        action="store_true",
        help="Connect to SMTP, STARTTLS, and login (does not send mail).",
    )
    args = parser.parse_args()

    print("Project .env should live at repo root (same folder as run.py).\n")

    if smtp_configured():
        print("✅ SMTP is configured for the refresh digest.")
        for k in ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM", "SMTP_USE_TLS"):
            v = os.environ.get(k, "")
            if k == "SMTP_PASSWORD":
                print(f"  {k}=*** ({len(v.strip())} chars)")
            else:
                print(f"  {k}={v!r}")
    else:
        missing = smtp_missing_env_keys()
        print("SMTP not fully configured. Missing:", ", ".join(missing))

    if not email_delivery_configured():
        print(
            "\n❌ Digest email disabled until you set:\n"
            "   SMTP_HOST, SMTP_USER, SMTP_PASSWORD\n"
            "   (optional: SMTP_PORT, SMTP_FROM, SMTP_USE_TLS — see README)"
        )
        return 1

    if not args.test_smtp:
        print("\nRun with --test-smtp to verify SMTP login, or run send_refresh_digest.py to send.")
        return 0

    host = os.environ["SMTP_HOST"].strip()
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ["SMTP_USER"].strip()
    password = os.environ["SMTP_PASSWORD"].strip()
    use_tls = os.environ.get("SMTP_USE_TLS", "1").strip().lower() not in (
        "0",
        "false",
        "no",
    )

    print(f"\nConnecting to {host}:{port} ...")
    try:
        with smtplib.SMTP(host, port, timeout=30) as server:
            if use_tls:
                server.starttls()
            server.login(user, password)
        print("✅ SMTP login succeeded (no email was sent).")
        return 0
    except Exception as e:
        print(f"❌ SMTP test failed: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
