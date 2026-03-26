#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import random
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

NEWSAPI_ENDPOINT = "https://newsapi.org/v2/everything"
DEFAULT_FROM_HOURS = 24
DEFAULT_PAGE_SIZE = 100
DEFAULT_MAX_PAGES = 3
FETCH_OVERLAP_MINUTES = 10
TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "igshid",
    "mc_cid",
    "mc_eid",
    "ref",
    "spm",
    "utm_campaign",
    "utm_content",
    "utm_id",
    "utm_medium",
    "utm_name",
    "utm_source",
    "utm_term",
}


@dataclass
class Subscription:
    id: int
    keyword: str
    normalized_keyword: str
    language: Optional[str]
    search_in: Optional[str]
    sort_by: str
    active: int
    last_fetched_at: Optional[dt.datetime]


DRIVER_KIND: Optional[str] = None


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


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def parse_mysql_url(mysql_url: str) -> Dict[str, Any]:
    parsed = urlparse(mysql_url)
    if parsed.scheme not in {"mysql", "mysql+pymysql", "mysql+mysqlconnector"}:
        raise ValueError("MYSQL_URL must start with mysql://, mysql+pymysql://, or mysql+mysqlconnector://")

    database = (parsed.path or "").lstrip("/")
    if not database:
        raise ValueError("MYSQL_URL must include a database name")

    return {
        "host": parsed.hostname or "127.0.0.1",
        "port": parsed.port or 3306,
        "user": parsed.username or "root",
        "password": parsed.password or "",
        "database": database,
        "charset": "utf8mb4",
    }


def get_connection():
    global DRIVER_KIND
    cfg = parse_mysql_url(require_env("MYSQL_URL"))

    try:
        import pymysql  # type: ignore

        DRIVER_KIND = "pymysql"
        return pymysql.connect(
            host=cfg["host"],
            port=cfg["port"],
            user=cfg["user"],
            password=cfg["password"],
            database=cfg["database"],
            charset=cfg["charset"],
            autocommit=False,
            cursorclass=pymysql.cursors.DictCursor,
        )
    except ImportError:
        pass

    try:
        import mysql.connector  # type: ignore

        DRIVER_KIND = "mysql.connector"
        return mysql.connector.connect(
            host=cfg["host"],
            port=cfg["port"],
            user=cfg["user"],
            password=cfg["password"],
            database=cfg["database"],
            charset=cfg["charset"],
            autocommit=False,
        )
    except ImportError as exc:
        raise RuntimeError(
            "No supported MySQL driver found. Install one of: pymysql, mysql-connector-python"
        ) from exc


def dict_cursor(conn):
    if DRIVER_KIND == "mysql.connector":
        return conn.cursor(dictionary=True)
    return conn.cursor()


def normalize_keyword(keyword: str) -> str:
    return " ".join(keyword.strip().lower().split())


def canonicalize_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url.strip())
    scheme = (parsed.scheme or "https").lower()
    host = (parsed.hostname or "").lower()
    port = parsed.port
    netloc = host
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc = f"{host}:{port}"

    filtered_params = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        key_lower = key.lower()
        if key_lower.startswith("utm_") or key_lower in TRACKING_QUERY_KEYS:
            continue
        filtered_params.append((key, value))
    filtered_params.sort()

    cleaned = parsed._replace(
        scheme=scheme,
        netloc=netloc,
        fragment="",
        query=urlencode(filtered_params, doseq=True),
    )
    return urlunparse(cleaned)


def hash_article(url: str, title: str, source_name: str, published_at: Optional[str]) -> str:
    canonical_url = canonicalize_url(url)
    if canonical_url:
        basis = canonical_url
    else:
        basis = "|".join([(title or "").strip(), (source_name or "").strip(), (published_at or "").strip()])
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def to_mysql_datetime(value: Optional[str]) -> Optional[dt.datetime]:
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = dt.datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc).replace(tzinfo=None)


def format_iso8601_utc(value: dt.datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_schema_sql() -> str:
    path = Path(__file__).resolve().parent.parent / "assets" / "mysql_schema.sql"
    return path.read_text(encoding="utf-8")


def run_statements(conn, sql_blob: str) -> None:
    with dict_cursor(conn) as cur:
        statement = []
        for line in sql_blob.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("--"):
                continue
            statement.append(line)
            if stripped.endswith(";"):
                cur.execute("\n".join(statement))
                statement = []
        if statement:
            cur.execute("\n".join(statement))
    conn.commit()


def init_db(conn) -> None:
    run_statements(conn, read_schema_sql())


def upsert_subscription(conn, keyword: str, language: Optional[str], search_in: Optional[str], sort_by: str) -> int:
    normalized = normalize_keyword(keyword)
    sql = """
    INSERT INTO subscriptions (keyword, normalized_keyword, language, search_in, sort_by, active)
    VALUES (%s, %s, %s, %s, %s, 1)
    ON DUPLICATE KEY UPDATE
        keyword = VALUES(keyword),
        language = VALUES(language),
        search_in = VALUES(search_in),
        sort_by = VALUES(sort_by),
        active = 1,
        id = LAST_INSERT_ID(id)
    """
    with dict_cursor(conn) as cur:
        cur.execute(sql, (keyword.strip(), normalized, language, search_in, sort_by))
        conn.commit()
        return cur.lastrowid


def update_subscription_active(conn, keyword: str, active: int) -> int:
    sql = "UPDATE subscriptions SET active = %s WHERE normalized_keyword = %s"
    with dict_cursor(conn) as cur:
        cur.execute(sql, (active, normalize_keyword(keyword)))
        conn.commit()
        return cur.rowcount


def remove_subscription(conn, keyword: str) -> int:
    sql = "DELETE FROM subscriptions WHERE normalized_keyword = %s"
    with dict_cursor(conn) as cur:
        cur.execute(sql, (normalize_keyword(keyword),))
        conn.commit()
        return cur.rowcount


def list_subscriptions(conn) -> List[Dict[str, Any]]:
    sql = """
    SELECT id, keyword, normalized_keyword, language, search_in, sort_by, active, last_fetched_at, updated_at
    FROM subscriptions
    ORDER BY active DESC, keyword ASC
    """
    with dict_cursor(conn) as cur:
        cur.execute(sql)
        return list(cur.fetchall())


def get_subscription_by_keyword(conn, keyword: str) -> Optional[Subscription]:
    sql = """
    SELECT id, keyword, normalized_keyword, language, search_in, sort_by, active, last_fetched_at
    FROM subscriptions
    WHERE normalized_keyword = %s
    LIMIT 1
    """
    with dict_cursor(conn) as cur:
        cur.execute(sql, (normalize_keyword(keyword),))
        row = cur.fetchone()
    return row_to_subscription(row) if row else None


def get_active_subscriptions(conn) -> List[Subscription]:
    sql = """
    SELECT id, keyword, normalized_keyword, language, search_in, sort_by, active, last_fetched_at
    FROM subscriptions
    WHERE active = 1
    ORDER BY id ASC
    """
    with dict_cursor(conn) as cur:
        cur.execute(sql)
        return [row_to_subscription(row) for row in cur.fetchall()]


def row_to_subscription(row: Dict[str, Any]) -> Subscription:
    return Subscription(
        id=int(row["id"]),
        keyword=row["keyword"],
        normalized_keyword=row["normalized_keyword"],
        language=row.get("language"),
        search_in=row.get("search_in"),
        sort_by=row.get("sort_by") or "publishedAt",
        active=int(row.get("active") or 0),
        last_fetched_at=row.get("last_fetched_at"),
    )


def request_newsapi(params: Dict[str, Any], api_key: str, retries: int = 3) -> Dict[str, Any]:
    query = urlencode({k: v for k, v in params.items() if v is not None})
    url = f"{NEWSAPI_ENDPOINT}?{query}"
    headers = {
        "X-Api-Key": api_key,
        "User-Agent": "news-keyword-ingest/1.0",
        "Accept": "application/json",
    }

    attempt = 0
    while True:
        attempt += 1
        request = Request(url, headers=headers, method="GET")
        try:
            with urlopen(request, timeout=30) as response:
                payload = response.read().decode("utf-8")
                return json.loads(payload)
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            retryable = exc.code == 429 or 500 <= exc.code < 600
            if retryable and attempt <= retries:
                sleep_seconds = min(8, (2 ** (attempt - 1)) + random.random())
                time.sleep(sleep_seconds)
                continue
            raise RuntimeError(f"NewsAPI HTTP {exc.code}: {body}") from exc
        except URLError as exc:
            if attempt <= retries:
                sleep_seconds = min(8, (2 ** (attempt - 1)) + random.random())
                time.sleep(sleep_seconds)
                continue
            raise RuntimeError(f"NewsAPI network error: {exc}") from exc


def compute_from_time(subscription: Subscription, from_hours: Optional[int]) -> dt.datetime:
    now = utc_now()
    if from_hours is not None:
        return now - dt.timedelta(hours=from_hours)
    if subscription.last_fetched_at:
        last = subscription.last_fetched_at
        if last.tzinfo is None:
            last = last.replace(tzinfo=dt.timezone.utc)
        return last.astimezone(dt.timezone.utc) - dt.timedelta(minutes=FETCH_OVERLAP_MINUTES)
    return now - dt.timedelta(hours=DEFAULT_FROM_HOURS)


def store_article(conn, article: Dict[str, Any]) -> Tuple[int, bool]:
    source = article.get("source") or {}
    source_name = (source.get("name") or "").strip()
    source_id = source.get("id")
    url = article.get("url") or ""
    canonical_url = canonicalize_url(url)
    article_hash = hash_article(url, article.get("title") or "", source_name, article.get("publishedAt"))

    sql = """
    INSERT INTO articles (
        article_hash, source_id, source_name, author, title, description, url,
        canonical_url, url_to_image, published_at, content, raw_json
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
        source_id = VALUES(source_id),
        source_name = VALUES(source_name),
        author = VALUES(author),
        title = VALUES(title),
        description = VALUES(description),
        url = VALUES(url),
        canonical_url = VALUES(canonical_url),
        url_to_image = VALUES(url_to_image),
        published_at = VALUES(published_at),
        content = VALUES(content),
        raw_json = VALUES(raw_json),
        id = LAST_INSERT_ID(id)
    """

    with dict_cursor(conn) as cur:
        cur.execute(
            sql,
            (
                article_hash,
                source_id,
                source_name or None,
                article.get("author"),
                article.get("title") or "",
                article.get("description"),
                url,
                canonical_url,
                article.get("urlToImage"),
                to_mysql_datetime(article.get("publishedAt")),
                article.get("content"),
                json.dumps(article, ensure_ascii=False),
            ),
        )
        article_id = int(cur.lastrowid)
        inserted = getattr(cur, "rowcount", 0) == 1
    return article_id, inserted


def link_article_to_subscription(conn, article_id: int, subscription: Subscription) -> bool:
    sql = """
    INSERT INTO article_subscriptions (article_id, subscription_id, matched_keyword)
    VALUES (%s, %s, %s)
    ON DUPLICATE KEY UPDATE matched_keyword = VALUES(matched_keyword)
    """
    with dict_cursor(conn) as cur:
        cur.execute(sql, (article_id, subscription.id, subscription.keyword))
        return getattr(cur, "rowcount", 0) == 1


def update_fetch_status(conn, subscription_id: int, status: str, error: Optional[str]) -> None:
    sql = """
    UPDATE subscriptions
    SET last_fetched_at = %s,
        last_fetch_status = %s,
        last_fetch_error = %s
    WHERE id = %s
    """
    with dict_cursor(conn) as cur:
        cur.execute(sql, (utc_now().replace(tzinfo=None), status, error, subscription_id))
    conn.commit()


def fetch_subscription(conn, subscription: Subscription, from_hours: Optional[int], page_size: int, max_pages: int) -> Dict[str, Any]:
    api_key = require_env("NEWSAPI_KEY")
    from_time = compute_from_time(subscription, from_hours)
    overall = {
        "subscription_id": subscription.id,
        "keyword": subscription.keyword,
        "from": format_iso8601_utc(from_time),
        "pages_requested": 0,
        "total_results": 0,
        "new_articles": 0,
        "existing_articles": 0,
        "new_links": 0,
        "errors": [],
    }

    try:
        for page in range(1, max_pages + 1):
            params = {
                "q": subscription.keyword,
                "language": subscription.language,
                "searchIn": subscription.search_in,
                "sortBy": subscription.sort_by or "publishedAt",
                "from": format_iso8601_utc(from_time),
                "pageSize": page_size,
                "page": page,
            }
            payload = request_newsapi(params=params, api_key=api_key)
            status = payload.get("status")
            if status != "ok":
                raise RuntimeError(f"NewsAPI returned non-ok status: {json.dumps(payload, ensure_ascii=False)}")

            articles = payload.get("articles") or []
            overall["pages_requested"] += 1
            overall["total_results"] = int(payload.get("totalResults") or 0)

            if not articles:
                break

            for article in articles:
                article_id, inserted = store_article(conn, article)
                if inserted:
                    overall["new_articles"] += 1
                else:
                    overall["existing_articles"] += 1

                linked = link_article_to_subscription(conn, article_id, subscription)
                if linked:
                    overall["new_links"] += 1

            conn.commit()

            if len(articles) < page_size:
                break

        update_fetch_status(conn, subscription.id, "success", None)
        return overall
    except Exception as exc:
        conn.rollback()
        error_message = str(exc)
        overall["errors"].append(error_message)
        update_fetch_status(conn, subscription.id, "failed", error_message)
        return overall


def command_init_db(args) -> int:
    conn = get_connection()
    try:
        init_db(conn)
        print(json.dumps({"status": "ok", "message": "database initialized"}, ensure_ascii=False, indent=2))
        return 0
    finally:
        conn.close()


def command_add_subscription(args) -> int:
    conn = get_connection()
    try:
        subscription_id = upsert_subscription(conn, args.keyword, args.language, args.search_in, args.sort_by)
        print(json.dumps({
            "status": "ok",
            "message": "subscription upserted",
            "subscription_id": subscription_id,
            "keyword": args.keyword,
        }, ensure_ascii=False, indent=2))
        return 0
    finally:
        conn.close()


def command_list_subscriptions(args) -> int:
    conn = get_connection()
    try:
        rows = list_subscriptions(conn)
        print(json.dumps({"status": "ok", "count": len(rows), "subscriptions": rows}, ensure_ascii=False, indent=2, default=str))
        return 0
    finally:
        conn.close()


def command_activate(args, active: int) -> int:
    conn = get_connection()
    try:
        affected = update_subscription_active(conn, args.keyword, active)
        print(json.dumps({
            "status": "ok",
            "keyword": args.keyword,
            "affected_rows": affected,
            "active": bool(active),
        }, ensure_ascii=False, indent=2))
        return 0
    finally:
        conn.close()


def command_remove_subscription(args) -> int:
    conn = get_connection()
    try:
        affected = remove_subscription(conn, args.keyword)
        print(json.dumps({
            "status": "ok",
            "keyword": args.keyword,
            "affected_rows": affected,
        }, ensure_ascii=False, indent=2))
        return 0
    finally:
        conn.close()


def command_fetch_keyword(args) -> int:
    conn = get_connection()
    try:
        subscription = get_subscription_by_keyword(conn, args.keyword)
        if not subscription:
            print(json.dumps({"status": "error", "message": f"subscription not found: {args.keyword}"}, ensure_ascii=False, indent=2))
            return 1
        result = fetch_subscription(conn, subscription, args.from_hours, args.page_size, args.max_pages)
        print(json.dumps({"status": "ok", "result": result}, ensure_ascii=False, indent=2))
        return 0 if not result["errors"] else 2
    finally:
        conn.close()


def command_fetch_all(args) -> int:
    conn = get_connection()
    try:
        subscriptions = get_active_subscriptions(conn)
        results = []
        for subscription in subscriptions:
            results.append(fetch_subscription(conn, subscription, args.from_hours, args.page_size, args.max_pages))

        summary = {
            "status": "ok",
            "subscription_count": len(subscriptions),
            "results": results,
            "totals": {
                "pages_requested": sum(item["pages_requested"] for item in results),
                "new_articles": sum(item["new_articles"] for item in results),
                "existing_articles": sum(item["existing_articles"] for item in results),
                "new_links": sum(item["new_links"] for item in results),
                "error_count": sum(len(item["errors"]) for item in results),
            },
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if summary["totals"]["error_count"] == 0 else 2
    finally:
        conn.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Keyword-based NewsAPI ingestion into MySQL with deduplication.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init-db", help="Initialize MySQL tables")
    p_init.set_defaults(func=command_init_db)

    p_add = sub.add_parser("add-subscription", help="Add or update a keyword subscription")
    p_add.add_argument("--keyword", required=True)
    p_add.add_argument("--language", default=None)
    p_add.add_argument("--search-in", default=None, dest="search_in")
    p_add.add_argument("--sort-by", default="publishedAt", choices=["relevancy", "popularity", "publishedAt"], dest="sort_by")
    p_add.set_defaults(func=command_add_subscription)

    p_list = sub.add_parser("list-subscriptions", help="List all subscriptions")
    p_list.set_defaults(func=command_list_subscriptions)

    p_deactivate = sub.add_parser("deactivate-subscription", help="Deactivate a subscription")
    p_deactivate.add_argument("--keyword", required=True)
    p_deactivate.set_defaults(func=lambda args: command_activate(args, 0))

    p_activate = sub.add_parser("activate-subscription", help="Activate a subscription")
    p_activate.add_argument("--keyword", required=True)
    p_activate.set_defaults(func=lambda args: command_activate(args, 1))

    p_remove = sub.add_parser("remove-subscription", help="Delete a subscription")
    p_remove.add_argument("--keyword", required=True)
    p_remove.set_defaults(func=command_remove_subscription)

    def add_fetch_args(p):
        p.add_argument("--from-hours", type=int, default=None)
        p.add_argument("--page-size", type=int, default=DEFAULT_PAGE_SIZE)
        p.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES)

    p_fetch_all = sub.add_parser("fetch-all", help="Fetch news for all active subscriptions")
    add_fetch_args(p_fetch_all)
    p_fetch_all.set_defaults(func=command_fetch_all)

    p_fetch_kw = sub.add_parser("fetch-keyword", help="Fetch news for one subscription keyword")
    p_fetch_kw.add_argument("--keyword", required=True)
    add_fetch_args(p_fetch_kw)
    p_fetch_kw.set_defaults(func=command_fetch_keyword)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    load_dotenv_if_present()
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
