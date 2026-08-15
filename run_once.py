"""Run the full WorldPulse pipeline ONCE (manual trigger, no scheduler).

This is the entry point cron and Task Scheduler call. It exits 1 on failure so
a scheduled run records a real result instead of a permanent green light.
"""
import html
import sys
import traceback

from scheduler import run_pipeline


def _alert(message: str) -> None:
    """Best-effort Telegram failure alert. Never masks the original error."""
    try:
        from telegram_bot import send_message
        # Escape: an exception message containing < or & would otherwise make
        # Telegram reject the whole alert with a 400 under parse_mode=HTML.
        safe = html.escape(message)[:1500]
        send_message(f"🚨 <b>WorldPulse run FAILED</b>\n\n<code>{safe}</code>")
    except Exception:
        print(f"(could not send Telegram alert: {message})", file=sys.stderr)


def main() -> int:
    print("=== WorldPulse — One-shot pipeline ===\n")
    try:
        generated = run_pipeline()
    except Exception as exc:
        traceback.print_exc()
        _alert(f"{type(exc).__name__}: {exc}")
        print("\n=== FAILED ===", file=sys.stderr)
        return 1

    if generated == 0:
        print("\n=== Done — no content: every topic was filtered as duplicate ===")
    else:
        print(f"\n=== Done — {generated} topic(s) generated ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
