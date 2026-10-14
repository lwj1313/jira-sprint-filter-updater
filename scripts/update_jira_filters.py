#!/usr/bin/env python3
"""Move configured Jira saved filters to the next sprint every other Thursday."""

import base64
import json
import os
import re
import sys
from datetime import date, datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

FILTER_IDS = [x.strip() for x in os.environ.get("JIRA_FILTER_IDS", "").split(",") if x.strip()]
BOARD_ID = os.environ.get("JIRA_BOARD_ID", "").strip()
BASE_URL = os.environ.get("JIRA_BASE_URL", "").rstrip("/")
EMAIL = os.environ.get("JIRA_EMAIL", "").strip()
API_TOKEN = os.environ.get("JIRA_API_TOKEN", "").strip()
ANCHOR_DATE = date.fromisoformat(os.environ.get("SPRINT_ANCHOR_DATE", "2026-10-15"))
TIMEZONE = os.environ.get("RUN_TIMEZONE", "America/New_York")
RUN_LOCAL_HOUR = int(os.environ.get("RUN_LOCAL_HOUR", "9"))
DRY_RUN = os.environ.get("DRY_RUN", "true").strip().lower() not in {"0", "false", "no", "off"}

# Replaces sprint = "Sprint 42", sprint = 123, or sprint in (...).
# It intentionally leaves sprint in openSprints() unchanged.
SPRINT_CLAUSE = re.compile(
    r"(?P<field>\b sprint \b\s*(?:=|in)\s*)"
    r"(?P<value>\([^)]*\)|\"(?:\\.|[^\"])*\"|'(?:\\.|[^'])*'|\d+)",
    re.IGNORECASE | re.VERBOSE,
)


def fail(message):
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def jira_request(method, path, query=None, body=None):
    if not BASE_URL or not EMAIL or not API_TOKEN:
        fail("Set JIRA_BASE_URL, JIRA_EMAIL, and JIRA_API_TOKEN.")

    url = f"{BASE_URL}{path}"
    if query:
        url += "?" + urlencode(query, doseq=True)

    credentials = base64.b64encode(f"{EMAIL}:{API_TOKEN}".encode()).decode()
    payload = json.dumps(body).encode() if body is not None else None
    request = Request(
        url,
        data=payload,
        method=method,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Basic {credentials}",
            "User-Agent": "github-actions-jira-filter-updater/1.0",
        },
    )

    try:
        with urlopen(request, timeout=30) as response:
            raw = response.read()
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        fail(f"Jira API {method} {path} returned HTTP {exc.code}: {detail[:1000]}")
    except URLError as exc:
        fail(f"Could not reach Jira: {exc.reason}")

    if not raw:
        return {}
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        fail(f"Jira returned non-JSON data for {method} {path}.")


def get_sprints(state):
    values = []
    start_at = 0
    while True:
        response = jira_request(
            "GET",
            f"/rest/agile/1.0/board/{BOARD_ID}/sprint",
            {"state": state, "startAt": start_at, "maxResults": 50},
        )
        page = response.get("values", [])
        values.extend(page)
        if response.get("isLast", True) or not page:
            return values
        start_at += len(page)


def sprint_start(sprint):
    value = sprint.get("startDate") or sprint.get("endDate") or "9999-12-31T23:59:59+00:00"
    value = value.replace("Z", "+00:00")
    if value.endswith("+0000"):
        value = value[:-5] + "+00:00"
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return datetime.max


def choose_next_sprint():
    active = get_sprints("active")
    future = get_sprints("future")
    if active:
        return sorted(active, key=sprint_start, reverse=True)[0]
    if future:
        return sorted(future, key=sprint_start)[0]
    fail(f"No active or future sprint found for board {BOARD_ID}.")


def replace_sprint_clause(jql, sprint_id):
    return SPRINT_CLAUSE.subn(f"sprint = {sprint_id}", jql)


def local_run_is_due():
    if os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch":
        print("Manual workflow run; bypassing the Thursday/time gate.")
        return True

    now = datetime.now(ZoneInfo(TIMEZONE))
    if now.weekday() != 3 or now.hour != RUN_LOCAL_HOUR:
        print(f"Not the configured local run time ({now.isoformat()}); exiting.")
        return False

    days_since_anchor = (now.date() - ANCHOR_DATE).days
    if days_since_anchor < 0 or days_since_anchor % 14 != 0:
        print(f"Not an update Thursday for anchor {ANCHOR_DATE}; exiting.")
        return False
    return True


def main():
    if not BOARD_ID:
        fail("JIRA_BOARD_ID is required.")
    if not FILTER_IDS:
        fail("JIRA_FILTER_IDS is required.")
    if not local_run_is_due():
        return

    next_sprint = choose_next_sprint()
    sprint_id = int(next_sprint["id"])
    sprint_name = next_sprint.get("name", f"Sprint {sprint_id}")
    print(f"Selected next sprint: {sprint_name} (id={sprint_id})")
    print(f"Mode: {'DRY RUN' if DRY_RUN else 'LIVE UPDATE'}")

    failures = 0
    changes = 0
    for filter_id in FILTER_IDS:
        try:
            current = jira_request("GET", f"/rest/api/3/filter/{filter_id}")
            old_jql = current.get("jql", "")
            if not old_jql:
                print(f"SKIP filter {filter_id}: Jira returned no JQL.")
                failures += 1
                continue

            new_jql, replacements = replace_sprint_clause(old_jql, sprint_id)
            if replacements == 0:
                print(f"SKIP filter {filter_id}: no hard-coded sprint clause found.")
                continue
            if new_jql == old_jql:
                print(f"SKIP filter {filter_id}: already targets sprint {sprint_id}.")
                continue

            print(f"FILTER {filter_id}: {old_jql} -> {new_jql}")
            changes += 1
            if not DRY_RUN:
                jira_request("PUT", f"/rest/api/3/filter/{filter_id}", body={"jql": new_jql})
                print(f"UPDATED filter {filter_id}")
        except SystemExit:
            failures += 1
        except Exception as exc:
            failures += 1
            print(f"ERROR filter {filter_id}: {exc}", file=sys.stderr)

    print(f"Processed {len(FILTER_IDS)} filters; proposed changes: {changes}; failures: {failures}.")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
