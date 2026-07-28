"""Register (or print) the daily scheduled task that runs run_daily.py.

Detects the OS:
  - Windows: uses schtasks.exe to create a Task Scheduler entry.
  - macOS/Linux: prints the crontab line to add (does not touch your
    crontab automatically, so an existing crontab is never clobbered).

Usage:
  python setup_scheduler.py --time 07:00            # print what would run
  python setup_scheduler.py --time 07:00 --apply     # actually register it (Windows only)
"""

import argparse
import platform
import subprocess
import sys
from pathlib import Path

TASK_NAME = "MoneyPrinterDailyBrief"
RUN_DAILY = Path(__file__).resolve().parent / "run_daily.py"


def windows_command(time_str: str) -> list[str]:
    return [
        "schtasks", "/Create",
        "/TN", TASK_NAME,
        "/TR", f'"{sys.executable}" "{RUN_DAILY}"',
        "/SC", "DAILY",
        "/ST", time_str,
        "/F",
    ]


def posix_crontab_line(time_str: str) -> str:
    hour, minute = time_str.split(":")
    log_path = RUN_DAILY.parent / "logs" / "cron.log"
    return f"{int(minute)} {int(hour)} * * * {sys.executable} {RUN_DAILY} >> {log_path} 2>&1"


def main() -> int:
    parser = argparse.ArgumentParser(description="Set up the daily scheduled run.")
    parser.add_argument("--time", default="07:00", help="24h HH:MM, local time (default 07:00).")
    parser.add_argument(
        "--apply", action="store_true",
        help="Actually register the task (Windows). Without this flag, only prints the command.",
    )
    args = parser.parse_args()

    system = platform.system()

    if system == "Windows":
        cmd = windows_command(args.time)
        # cmd is built for subprocess (one argv element each -- correct as-is
        # for --apply below). For a human to paste into a terminal, the /TR
        # value itself must be re-quoted as a single token since it contains
        # a space (the repo path) and embedded quotes.
        printable_parts = []
        skip_next_requote = False
        for i, part in enumerate(cmd):
            if skip_next_requote:
                printable_parts.append('"' + part.replace('"', '\\"') + '"')
                skip_next_requote = False
            else:
                printable_parts.append(part)
            if part == "/TR":
                skip_next_requote = True
        printable = " ".join(printable_parts)
        print("Windows Task Scheduler command:\n")
        print(f"  {printable}\n")
        if args.apply:
            print("Registering scheduled task...")
            result = subprocess.run(cmd, capture_output=True, text=True)
            print(result.stdout)
            if result.returncode != 0:
                print(result.stderr, file=sys.stderr)
                return result.returncode
            print(f"Done. View/edit it in Task Scheduler under 'Task Scheduler Library' as '{TASK_NAME}'.")
        else:
            print("Re-run with --apply to actually register this task (recommended -- it")
            print("invokes schtasks directly, avoiding quoting issues). The line above is")
            print("for reference if you'd rather paste it into a `cmd.exe` prompt yourself")
            print("(note: PowerShell quotes nested arguments differently than cmd.exe).")
        return 0

    # macOS / Linux
    line = posix_crontab_line(args.time)
    print("Add this line to your crontab (run `crontab -e`):\n")
    print(f"  {line}\n")
    print("This script does not modify your crontab automatically, so it can't")
    print("clobber any existing entries.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
