#!/usr/bin/env python3
"""Fetch accurate public GitHub profile statistics using only Python's stdlib.

By default, reads ``username`` from the repository's profile.json and writes
assets/stats.json. GITHUB_TOKEN is optional and never leaves api.github.com.
Commit counts, lines of code, email addresses, and private repositories are not
collected or written.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener


ROOT = Path(__file__).resolve().parents[1]
API_BASE = "https://api.github.com"
USERNAME_PATTERN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?\Z")
TIMEOUT_SECONDS = 20
MAX_ATTEMPTS = 3


class NoRedirect(HTTPRedirectHandler):
    """Refuse redirects so credentials cannot be forwarded to another host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class GitHubClient:
    def __init__(self, username: str):
        self.username = username
        self.opener = build_opener(NoRedirect())
        self.headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "public-profile-card/1.0",
        }
        token = os.environ.get("GITHUB_TOKEN", "").strip()
        if token:
            self.headers["Authorization"] = f"Bearer {token}"

    def get(self, resource: str, page: int | None = None):
        # Callers can choose only these fixed public endpoints, never a URL from
        # profile data, a response, or a pagination Link header.
        if resource == "user":
            path = f"/users/{self.username}"
        elif resource == "repos" and isinstance(page, int) and page >= 1:
            path = f"/users/{self.username}/repos?" + urlencode({
                "type": "owner", "sort": "pushed", "direction": "desc",
                "per_page": 100, "page": page,
            })
        else:
            raise ValueError("Unsupported GitHub endpoint")

        request = Request(API_BASE + path, headers=self.headers)
        for attempt in range(MAX_ATTEMPTS):
            try:
                with self.opener.open(request, timeout=TIMEOUT_SECONDS) as response:
                    return json.load(response)
            except HTTPError as exc:
                retryable = exc.code in {429, 500, 502, 503, 504}
                if retryable and attempt < MAX_ATTEMPTS - 1:
                    retry_after = exc.headers.get("Retry-After", "")
                    delay = min(int(retry_after), 10) if retry_after.isdigit() else 2 ** attempt
                    exc.close()
                    time.sleep(max(delay, 1))
                    continue
                status = exc.code
                exc.close()
                if status in {403, 429}:
                    raise RuntimeError(
                        "GitHub API access was denied or rate-limited. Retry later; "
                        "an optional GITHUB_TOKEN can increase the rate limit."
                    ) from None
                if status == 404:
                    raise RuntimeError("GitHub user or endpoint was not found.") from None
                raise RuntimeError(f"GitHub API request failed (HTTP {status}).") from None
            except (URLError, TimeoutError, ConnectionError, OSError):
                if attempt < MAX_ATTEMPTS - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise RuntimeError("GitHub API could not be reached after three attempts.") from None
            except (json.JSONDecodeError, UnicodeError):
                raise RuntimeError("GitHub API returned an invalid JSON response.") from None
        raise RuntimeError("GitHub API request did not complete.")


def collect_stats(username: str) -> dict:
    client = GitHubClient(username)
    user = client.get("user")
    if not isinstance(user, dict) or not user.get("login") or not user.get("created_at"):
        raise RuntimeError("GitHub API returned an unexpected user response.")

    login = user["login"]
    repos = []
    page = 1
    while True:
        batch = client.get("repos", page)
        if not isinstance(batch, list):
            raise RuntimeError("GitHub API returned an unexpected repository response.")
        for repo in batch:
            if (
                isinstance(repo, dict)
                and repo.get("private") is False
                and repo.get("visibility", "public") == "public"
                and repo.get("owner", {}).get("login", "").casefold() == login.casefold()
            ):
                repos.append(repo)
        if len(batch) < 100:
            break
        page += 1

    # Forks remain included in the explicitly owned public repository totals.
    # Language and project highlights use original, non-fork repositories.
    originals = [repo for repo in repos if not repo.get("fork")]
    language_counts = Counter(repo["language"] for repo in originals if repo.get("language"))
    languages = dict(sorted(language_counts.items(), key=lambda pair: (-pair[1], pair[0].casefold())))
    highlights = sorted(
        (repo for repo in originals if not repo.get("archived")),
        key=lambda repo: repo.get("pushed_at") or "", reverse=True,
    )[:6]
    now = datetime.now(timezone.utc)
    try:
        created = datetime.fromisoformat(user["created_at"].replace("Z", "+00:00"))
    except (ValueError, TypeError):
        raise RuntimeError("GitHub API returned an invalid account creation date.") from None

    # Whitelist fields rather than serializing API objects: this deliberately
    # omits user.email and every private repository field.
    return {
        "login": login,
        "name": user.get("name") or login,
        "bio": user.get("bio") or "",
        "blog": user.get("blog") or "",
        "avatar_url": user.get("avatar_url") or "",
        "created_at": user["created_at"],
        "account_age_days": max((now - created).days, 0),
        "followers": user.get("followers", 0),
        "following": user.get("following", 0),
        "public_repos": len(repos),
        "owned_stars": sum(repo.get("stargazers_count", 0) for repo in repos),
        "owned_forks": sum(repo.get("forks_count", 0) for repo in repos),
        "languages": languages,
        "recent_projects": [
            {
                "name": repo["name"],
                "url": repo["html_url"],
                "description": repo.get("description") or "",
                "language": repo.get("language") or "",
                "stars": repo.get("stargazers_count", 0),
                "forks": repo.get("forks_count", 0),
                "pushed_at": repo.get("pushed_at"),
            }
            for repo in highlights
        ],
        "fetched_at": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
    }


def write_json_atomic(output: Path, data: dict) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", delete=False,
            dir=output.parent, prefix=f".{output.name}.", suffix=".tmp",
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        temporary_path.replace(output)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=ROOT / "profile.json", help="Profile JSON containing username")
    parser.add_argument("--username", help="Override the username in profile.json")
    parser.add_argument("--output", type=Path, default=ROOT / "assets" / "stats.json", help="Output JSON path")
    args = parser.parse_args()
    try:
        if args.username:
            username = args.username.strip()
        else:
            with args.profile.open(encoding="utf-8-sig") as handle:
                profile = json.load(handle)
            if not isinstance(profile, dict):
                raise ValueError("profile.json must contain a JSON object.")
            username = str(profile.get("username") or "").strip()
        if not USERNAME_PATTERN.fullmatch(username):
            raise ValueError("Provide a valid GitHub username in profile.json or --username.")
        stats = collect_stats(username)
        write_json_atomic(args.output, stats)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Could not refresh public GitHub statistics: {exc}", file=sys.stderr)
        return 1
    print(f"Updated public statistics for {stats['login']}: {stats['public_repos']} repositories.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
