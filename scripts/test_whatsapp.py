"""
Merchant alert channel check.

Answers one question: if Munim raised a restock alert right now, would the
merchant's phone actually buzz?

    python scripts/test_whatsapp.py               # check config, then send
    python scripts/test_whatsapp.py --status      # check config only, send nothing
    python scripts/test_whatsapp.py --to +9198... # send somewhere else once
    python scripts/test_whatsapp.py --watch       # retry every 10s until it works
    python scripts/test_whatsapp.py --template hello_world

Works with either provider, picked the same way the backend picks it:
MESSAGING_PROVIDER, or whichever one is actually configured.

Reads .env directly, so the backend does NOT need to be running. Standard
library only, same as smoke_test.py. Exit code 0 means a message went out.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

META_HINTS = {
    131047: (
        "Outside the 24-hour window, so free text is refused.\n"
        "     Send any WhatsApp message FROM that phone TO your test sender,\n"
        "     then run this again. Or use --template hello_world, which works\n"
        "     at any time."
    ),
    131030: (
        "That number is not in the test sender's allow-list.\n"
        "     Add it under WhatsApp > API Setup > To, and confirm the OTP."
    ),
    131026: "That number cannot receive WhatsApp messages (not registered, or not allow-listed).",
    190: "Access token invalid or expired. The temporary one on API Setup lasts 24 hours.",
    100: "A parameter was rejected: usually the phone number id, or the recipient format.",
}

TWILIO_HINTS = {
    21654: "Twilio trial refuses free text on WhatsApp; it wants a ContentSid template.",
    572006: "Twilio trial refuses free text on SMS; Body must be a predefined template name.",
    63007: "That phone has not joined the Twilio WhatsApp sandbox.",
    21608: "Trial account: the recipient must be a verified number.",
}


def load_env() -> dict[str, str]:
    """Read .env without importing anything: this may run outside the venv."""
    values: dict[str, str] = {}
    for candidate in (ROOT / ".env", ROOT / "backend" / ".env"):
        if not candidate.exists():
            continue
        for line in candidate.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values.setdefault(key.strip(), value.strip())
    return values


def real(value: str) -> str:
    """A placeholder counts as absent, exactly as the backend treats it."""
    return "" if value.upper().startswith("YOUR_") else value


def digits(number: str) -> str:
    out = number.strip()
    for prefix in ("whatsapp:", "sms:", "tel:"):
        if out.lower().startswith(prefix):
            out = out[len(prefix):]
    return out.lstrip("+").replace(" ", "").replace("-", "")


# ------------------------------------------------------------------- senders

def send_meta(env, recipient, template=None):
    """Returns (ok, code, detail)."""
    version = real(env.get("WHATSAPP_API_VERSION", "")) or "v21.0"
    number_id = real(env.get("WHATSAPP_PHONE_NUMBER_ID", ""))
    token = real(env.get("WHATSAPP_ACCESS_TOKEN", ""))

    if template:
        payload = {
            "messaging_product": "whatsapp",
            "to": digits(recipient),
            "type": "template",
            "template": {"name": template, "language": {"code": "en_US"}},
        }
    else:
        payload = {
            "messaging_product": "whatsapp",
            "to": digits(recipient),
            "type": "text",
            "text": {"body": "Munim AI: test message. Your alert channel is working."},
        }

    request = urllib.request.Request(
        f"https://graph.facebook.com/{version}/{number_id}/messages",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.loads(response.read().decode())
        return True, 0, (body.get("messages") or [{}])[0].get("id", "")
    except urllib.error.HTTPError as exc:
        try:
            err = json.loads(exc.read().decode()).get("error", {})
            return False, err.get("code"), err.get("message", "")
        except (ValueError, OSError):
            return False, exc.code, ""
    except urllib.error.URLError as exc:
        return False, -1, str(exc.reason)


def send_twilio(env, recipient):
    account = real(env.get("TWILIO_ACCOUNT_SID", ""))
    key_sid = real(env.get("TWILIO_API_KEY_SID", ""))
    secret = real(env.get("TWILIO_API_KEY_SECRET", ""))
    if not (key_sid and secret):
        key_sid, secret = account, real(env.get("TWILIO_AUTH_TOKEN", ""))

    body = urllib.parse.urlencode({
        "To": recipient,
        "From": real(env.get("TWILIO_FROM_NUMBER", "")),
        "Body": "Munim AI: test message. Your alert channel is working.",
    }).encode()
    token = base64.b64encode(f"{key_sid}:{secret}".encode()).decode()
    request = urllib.request.Request(
        f"https://api.twilio.com/2010-04-01/Accounts/{account}/Messages.json",
        data=body,
        headers={
            "Authorization": f"Basic {token}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return True, 0, json.loads(response.read().decode()).get("sid", "")
    except urllib.error.HTTPError as exc:
        try:
            problem = json.loads(exc.read().decode())
            return False, problem.get("code"), problem.get("message", "")
        except (ValueError, OSError):
            return False, exc.code, ""
    except urllib.error.URLError as exc:
        return False, -1, str(exc.reason)


# ---------------------------------------------------------------------- main

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--status", action="store_true", help="check config, send nothing")
    parser.add_argument("--to", help="override the recipient for this run")
    parser.add_argument("--watch", action="store_true", help="retry every 10s until it works")
    parser.add_argument("--template", help="send an approved template instead of free text")
    args = parser.parse_args()

    env = load_env()
    provider = (env.get("MESSAGING_PROVIDER", "") or "").strip().lower()
    if provider not in {"whatsapp_cloud", "twilio", "none"}:
        provider = "whatsapp_cloud" if real(env.get("WHATSAPP_PHONE_NUMBER_ID", "")) else "twilio"

    recipient = args.to or env.get("MERCHANT_ALERT_NUMBER", "")

    print(f"PROVIDER  {provider}")
    print("CONFIG (.env)")

    if provider == "whatsapp_cloud":
        required = [
            ("WHATSAPP_PHONE_NUMBER_ID", real(env.get("WHATSAPP_PHONE_NUMBER_ID", ""))),
            ("WHATSAPP_ACCESS_TOKEN", real(env.get("WHATSAPP_ACCESS_TOKEN", ""))),
            ("MERCHANT_ALERT_NUMBER", recipient),
        ]
    else:
        creds = real(env.get("TWILIO_API_KEY_SID", "")) or real(env.get("TWILIO_AUTH_TOKEN", ""))
        required = [
            ("TWILIO_ACCOUNT_SID", real(env.get("TWILIO_ACCOUNT_SID", ""))),
            ("credentials", creds),
            ("TWILIO_FROM_NUMBER", real(env.get("TWILIO_FROM_NUMBER", ""))),
            ("MERCHANT_ALERT_NUMBER", recipient),
        ]

    for name, value in required:
        shown = value if name.endswith("NUMBER") or name.endswith("ID") else ""
        print(f"  {'ok  ' if value else 'MISSING'}  {name:<26} {shown}")

    missing = [n for n, v in required if not v]
    if missing:
        print(f"\nStill needed: {', '.join(missing)}")
        return 1

    if args.status:
        return 0

    def attempt():
        if provider == "whatsapp_cloud":
            return send_meta(env, recipient, template=args.template)
        return send_twilio(env, recipient)

    hints = META_HINTS if provider == "whatsapp_cloud" else TWILIO_HINTS

    if args.watch:
        print("\nWATCHING. Retrying every 10 seconds. Ctrl+C to stop.\n")
        attempts = 0
        try:
            while True:
                attempts += 1
                ok, code, detail = attempt()
                if ok:
                    print(f"  [{attempts:>3}] SENT. Check that phone now.")
                    return 0
                print(f"  [{attempts:>3}] not yet (code {code}) ...")
                time.sleep(10)
        except KeyboardInterrupt:
            print("\nStopped.")
            return 1

    what = f"template '{args.template}'" if args.template else "a free-text message"
    print(f"\nSENDING {what} to {recipient} ...")
    ok, code, detail = attempt()

    if ok:
        print(f"\n  SENT. id={detail}")
        print("  Check that phone: it should arrive within a few seconds.")
        return 0

    print(f"\n  NOT SENT. [{code}] {detail}")
    if code in hints:
        print(f"\n  -> {hints[code]}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
