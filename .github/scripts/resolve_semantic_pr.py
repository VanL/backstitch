#!/usr/bin/env python3
"""Resolve and revalidate the exact hostile PR revision used as analysis data.

Spec: docs/specs/06-semantic-gates.md [SEM-9]
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping, Sequence
from pathlib import Path

_POSITIVE_DECIMAL = re.compile(r"[1-9][0-9]*")
_LOWER_HEX_SHA = re.compile(r"[0-9a-f]{40}")
_REPOSITORY = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}")


def parse_pr_number(value: str) -> int:
    """Return a canonical positive pull-request number."""

    if _POSITIVE_DECIMAL.fullmatch(value) is None:
        raise ValueError("pull request number must be a positive decimal")
    return int(value)


def parse_head_sha(value: str) -> str:
    """Return a lowercase full commit SHA."""

    if _LOWER_HEX_SHA.fullmatch(value) is None:
        raise ValueError("expected head SHA must be lowercase 40-hex")
    return value


def parse_repository(value: object, *, label: str) -> str:
    """Return a closed GitHub owner/repository identity."""

    if not isinstance(value, str) or _REPOSITORY.fullmatch(value) is None:
        raise ValueError(f"{label} is missing or invalid")
    return value


def _mapping(value: object, *, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} is missing or invalid")
    return value


def validate_pull_request(
    payload: Mapping[str, object],
    *,
    expected_number: int,
    repository: str,
    expected_head_sha: str,
    confirmed_head_repo: str | None = None,
    confirmed_head_sha: str | None = None,
) -> tuple[str, str]:
    """Validate the complete PR identity and return its exact head."""

    parse_repository(repository, label="base repository")
    parse_head_sha(expected_head_sha)
    if payload.get("number") != expected_number:
        raise ValueError("GitHub API returned a different pull request number")
    if payload.get("state") != "open":
        raise ValueError("pull request must remain open")

    base = _mapping(payload.get("base"), label="base")
    if base.get("ref") != "main":
        raise ValueError("pull request base must be main")
    base_repo = _mapping(base.get("repo"), label="base repository")
    if base_repo.get("full_name") != repository:
        raise ValueError("pull request base repository changed")

    head = _mapping(payload.get("head"), label="head")
    head_repo_value = head.get("repo")
    if head_repo_value is None:
        raise ValueError("pull request head repository is missing or unreadable")
    head_repo = _mapping(head_repo_value, label="head repository")
    head_repo_name = parse_repository(
        head_repo.get("full_name"),
        label="head repository",
    )
    head_sha = head.get("sha")
    if head_sha != expected_head_sha:
        raise ValueError("pull request does not match expected head SHA")
    assert isinstance(head_sha, str)
    parse_head_sha(head_sha)

    if confirmed_head_repo is not None and head_repo_name != confirmed_head_repo:
        raise ValueError("pull request changed head repository")
    if confirmed_head_sha is not None and head_sha != confirmed_head_sha:
        raise ValueError("pull request changed head SHA")
    return head_repo_name, head_sha


def github_api_get(
    *,
    api_url: str,
    repository: str,
    number: int,
    token: str,
) -> dict[str, object]:
    """Fetch one pull request without exposing the token in command arguments."""

    repository_path = urllib.parse.quote(repository, safe="/")
    url = f"{api_url.rstrip('/')}/repos/{repository_path}/pulls/{number}"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "backstitch-semantic-pr-report",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"GitHub API request failed with HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError("GitHub API request failed") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("GitHub API response was not a JSON object")
    return payload


def _required_env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise ValueError(f"{name} is required")
    return value


def _write_github_output(path: Path, *, head_repo: str, head_sha: str) -> None:
    with path.open("a", encoding="utf-8") as output:
        output.write(f"head_repo={head_repo}\n")
        output.write(f"head_sha={head_sha}\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("resolve", "revalidate"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        repository = parse_repository(
            _required_env("GITHUB_REPOSITORY"),
            label="base repository",
        )
        number = parse_pr_number(_required_env("BACKSTITCH_PR_NUMBER"))
        expected_sha = parse_head_sha(_required_env("BACKSTITCH_EXPECTED_HEAD_SHA"))
        token = _required_env("GITHUB_TOKEN")
        payload = github_api_get(
            api_url=os.environ.get("GITHUB_API_URL", "https://api.github.com"),
            repository=repository,
            number=number,
            token=token,
        )
        confirmed_repo = None
        confirmed_sha = None
        if args.operation == "revalidate":
            confirmed_repo = parse_repository(
                _required_env("BACKSTITCH_CONFIRMED_HEAD_REPO"),
                label="confirmed head repository",
            )
            confirmed_sha = parse_head_sha(
                _required_env("BACKSTITCH_CONFIRMED_HEAD_SHA")
            )
        head_repo, head_sha = validate_pull_request(
            payload,
            expected_number=number,
            repository=repository,
            expected_head_sha=expected_sha,
            confirmed_head_repo=confirmed_repo,
            confirmed_head_sha=confirmed_sha,
        )
        if args.operation == "resolve":
            _write_github_output(
                Path(_required_env("GITHUB_OUTPUT")),
                head_repo=head_repo,
                head_sha=head_sha,
            )
    except (http.client.HTTPException, OSError, RuntimeError, ValueError) as exc:
        print(f"semantic PR identity error: {exc}", file=sys.stderr)
        return 2

    print(f"validated pull request {number} at {head_repo}@{head_sha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
