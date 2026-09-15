from __future__ import annotations

import argparse
import sys

from .commands import govzakup_diagnose, mitwork_diagnose, run, samruk_diagnose, telegram_chat_id, telegram_test


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="icportal_bot")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("run", help="Search ICPortal and send new matches.")
    samruk_parser = subparsers.add_parser("samruk-diagnose", help="Show latest Samruk adverts parsed from public search.")
    samruk_parser.add_argument("--id", help="Check Samruk detail API for a known advert id.")
    samruk_parser.add_argument("--keyword", help="Check Samruk advert search API for a keyword.")
    govzakup_parser = subparsers.add_parser("govzakup-diagnose", help="Show actual GovZakup lots for a keyword.")
    govzakup_parser.add_argument("--keyword", required=True, help="Check GovZakup public lots search for a keyword.")
    mitwork_parser = subparsers.add_parser("mitwork-diagnose", help="Show actual Mitwork buys for a keyword.")
    mitwork_parser.add_argument("--keyword", required=True, help="Check Mitwork public buys search for a keyword.")
    subparsers.add_parser("telegram-chat-id", help="Show chat ids from recent Telegram bot messages.")
    subparsers.add_parser("telegram-test", help="Send a test Telegram message.")

    args = parser.parse_args()
    if args.command == "run":
        run()
    elif args.command == "samruk-diagnose":
        samruk_diagnose(args.id, args.keyword)
    elif args.command == "govzakup-diagnose":
        govzakup_diagnose(args.keyword)
    elif args.command == "mitwork-diagnose":
        mitwork_diagnose(args.keyword)
    elif args.command == "telegram-chat-id":
        telegram_chat_id()
    elif args.command == "telegram-test":
        telegram_test()


if __name__ == "__main__":
    main()
