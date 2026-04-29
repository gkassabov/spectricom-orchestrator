#!/usr/bin/env python3
"""
SPECTRICOM SLACK NOTIFIER
==========================
Sends batch completion/failure notifications to Slack via webhook.

Setup:
  1. Create Slack Incoming Webhook at https://api.slack.com/messaging/webhooks
  2. Save webhook URL:
     python3 slack_notify.py set-webhook "https://hooks.slack.com/services/T.../B.../xxx"
  3. Test:
     python3 slack_notify.py test

Usage (imported):
  from slack_notify import notify_batch
  notify_batch("batch-32.md", "passed", briefs=3, duration_s=420, migrations=["056_foo.sql"])
"""

import json, sys, argparse
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError

ORCH_DIR = Path.home() / "spectricom-orchestrator"
WEBHOOK_FILE = ORCH_DIR / "slack-webhook.json"

# ═══════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════
def load_webhook() -> str:
    if WEBHOOK_FILE.exists():
        data = json.loads(WEBHOOK_FILE.read_text())
        return data.get("url", "")
    return ""

def save_webhook(url: str):
    WEBHOOK_FILE.write_text(json.dumps({"url": url}))

# ═══════════════════════════════════════════════════════
# SEND
# ═══════════════════════════════════════════════════════
def send_slack(text: str, blocks: list = None) -> bool:
    """Send a message to Slack. Returns True on success."""
    url = load_webhook()
    if not url:
        return False

    payload = {"text": text}
    if blocks:
        payload["blocks"] = blocks

    try:
        req = Request(url, data=json.dumps(payload).encode("utf-8"),
                      headers={"Content-Type": "application/json"})
        resp = urlopen(req, timeout=10)
        return resp.status == 200
    except (URLError, Exception) as e:
        print(f"Slack error: {e}")
        return False

# ═══════════════════════════════════════════════════════
# BATCH NOTIFICATION
# ═══════════════════════════════════════════════════════
def notify_batch(batch_name: str, status: str, briefs: int = 0,
                 duration_s: float = 0, migrations: list = None,
                 exit_code: int = 0):
    """Send a batch completion notification to Slack."""
    is_pass = status == "passed"
    emoji = "white_check_mark" if is_pass else "x"
    status_text = "PASSED" if is_pass else "FAILED"
    dur = f"{duration_s/60:.1f}m" if duration_s >= 60 else f"{duration_s:.0f}s"

    text = f":{emoji}: *{batch_name}* — {status_text} | {briefs} briefs | {dur}"

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":{emoji}: *{batch_name}*\n"
                        f"Status: *{status_text}*  |  Briefs: *{briefs}*  |  Duration: *{dur}*"
                        + (f"  |  Exit: *{exit_code}*" if exit_code != 0 else "")
            }
        }
    ]

    if migrations:
        mig_text = "\n".join(
            f"`npx supabase db query --linked -f supabase/migrations/{m}`"
            for m in migrations
        )
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":warning: *{len(migrations)} migrations to apply:*\n{mig_text}"
            }
        })

    if not is_pass:
        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"Check logs: `tail -f ~/spectricom-orchestrator/logs/`"}]
        })

    return send_slack(text, blocks)

def notify_rate_warning(batches_used: int, batch_cap: int, briefs_used: int, brief_cap: int):
    """Alert when approaching rate limits."""
    text = (f":warning: *Rate limit warning*\n"
            f"Batches: {batches_used}/{batch_cap} | Briefs: {briefs_used}/{brief_cap}")
    return send_slack(text)

def notify_cascade(unblocked_batch: str, completed_dep: str):
    """Notify when a batch is unblocked by dependency completion."""
    text = f":arrows_counterclockwise: *{unblocked_batch}* unblocked — dependency *{completed_dep}* completed"
    return send_slack(text)

# ═══════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════
def main():
    ap = argparse.ArgumentParser(description="Spectricom Slack Notifier")
    sp = ap.add_subparsers(dest="cmd")

    sw = sp.add_parser("set-webhook", help="Save Slack webhook URL")
    sw.add_argument("url", help="Slack Incoming Webhook URL")

    sp.add_parser("test", help="Send a test notification")
    sp.add_parser("status", help="Show webhook config status")

    a = ap.parse_args()

    if a.cmd == "set-webhook":
        save_webhook(a.url)
        print(f"✅ Webhook saved to {WEBHOOK_FILE}")
    elif a.cmd == "test":
        url = load_webhook()
        if not url:
            print("❌ No webhook configured. Run: python3 slack_notify.py set-webhook <url>")
            return
        ok = notify_batch("test-batch.md", "passed", briefs=3, duration_s=180)
        print(f"{'✅ Test sent' if ok else '❌ Test failed'}")
    elif a.cmd == "status":
        url = load_webhook()
        if url:
            masked = url[:40] + "..." + url[-10:] if len(url) > 50 else url
            print(f"✅ Webhook configured: {masked}")
        else:
            print("❌ No webhook configured")
    else:
        ap.print_help()

if __name__ == "__main__":
    main()
