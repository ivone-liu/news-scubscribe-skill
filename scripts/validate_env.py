#!/usr/bin/env python3
"""Validate NewsAPI and MySQL runtime prerequisites."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def load_dotenv_if_present() -> None:
    for candidate in [Path.cwd() / ".env", Path(__file__).resolve().parent.parent / ".env"]:
        if not candidate.exists():
            continue
        for raw_line in candidate.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)
        break


def main() -> int:
    load_dotenv_if_present()

    required = ["NEWSAPI_KEY", "MYSQL_URL"]
    missing = [key for key in required if not os.getenv(key)]

    driver_ok = False
    driver_names = []
    for name in ("pymysql", "mysql.connector"):
        try:
            __import__(name)
            driver_ok = True
            driver_names.append(name)
        except Exception:
            pass

    print("Environment check")
    print("-" * 60)
    print(f"NEWSAPI_KEY: {'OK' if os.getenv('NEWSAPI_KEY') else 'MISSING'}")
    print(f"MYSQL_URL : {'OK' if os.getenv('MYSQL_URL') else 'MISSING'}")
    print(f"Driver     : {'OK' if driver_ok else 'MISSING'}")
    if driver_names:
        print(f"Detected   : {', '.join(driver_names)}")

    if missing:
        print("\nMissing environment variables:")
        for item in missing:
            print(f"- {item}")

    if not driver_ok:
        print("\nMissing MySQL driver. Install one of:")
        print("- pip install pymysql")
        print("- pip install mysql-connector-python")

    return 0 if (not missing and driver_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
