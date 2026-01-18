"""GitHub Code adapter — branches, PRs, reviews, merge via gh CLI."""

from __future__ import annotations

import json
import logging
import re
import subprocess

from a2sdlc.adapters._gh import gh
from a2sdlc.adapters.base import CodeAdapter

_EVENT_FLAGS = {
    "APPROVE": "--approve",
    "REQUEST_CHANGES": "--request-changes",
    "COMMENT": "--comment",
}


class GitHubCode(CodeAdapter):
    """CodeAdapter backed by GitHub PRs via the ``gh`` CLI."""

    def __init__(self, repo: str) -> None:
        self.repo = repo
        self.logger = logging.getLogger("a2sdlc.adapters.github_code")

    # ── public interface ────────────────────────────────────────────

    def create_branch(self, name: str) -> None:
        self.logger.info("create_branch %s", name)
        subprocess.run(
            ["git", "checkout", "-b", name],
            check=True,
            capture_output=True,
            text=True,
        )

    def create_pr(self, title: str, body: str, head: str) -> int:
        self.logger.info("create_pr '%s' head=%s in %s", title, head, self.repo)
        url = gh(
            [
                "pr",
                "create",
                "--repo",
                self.repo,
                "--title",
                title,
                "--body",
                body,
                "--base",
                "main",
                "--head",
                head,
            ]
        )
        match = re.search(r"/pull/(\d+)", url)
        if not match:
            msg = f"Could not extract PR number from: {url}"
            raise ValueError(msg)
        pr_number = int(match.group(1))
        self.logger.debug("created PR #%d", pr_number)
        return pr_number

    def get_pr_context(self, pr: int) -> str:
        self.logger.info("get_pr_context PR #%d in %s", pr, self.repo)
        raw = gh(
            [
                "pr",
                "view",
                str(pr),
                "--repo",
                self.repo,
                "--json",
                "title,body,files,comments",
            ]
        )
        data = json.loads(raw)

        parts: list[str] = [
            f"# {data['title']}",
            "",
            data.get("body") or "",
            "",
            "## Changed files",
            "",
        ]
        for f in data.get("files", []):
            parts.append(
                f"- `{f['path']}` (+{f.get('additions', 0)} -{f.get('deletions', 0)})"
            )

        comments = data.get("comments", [])
        if comments:
            parts.append("")
            parts.append("## Comments")
            for c in comments:
                author = c.get("author", {}).get("login", "unknown")
                parts.append("")
                parts.append(f"**{author}**: {c['body']}")

        md = "\n".join(parts)
        self.logger.debug("get_pr_context result length: %d chars", len(md))
        return md

    def post_review(self, pr: int, body: str, event: str) -> None:
        self.logger.info("post_review PR #%d event=%s in %s", pr, event, self.repo)
        flag = _EVENT_FLAGS[event]
        gh(
            [
                "pr",
                "review",
                str(pr),
                "--repo",
                self.repo,
                flag,
                "--body",
                body,
            ]
        )
        self.logger.debug("posted review on PR #%d", pr)

    def comment_on_pr(self, pr: int, body: str) -> str:
        self.logger.info("comment_on_pr PR #%d in %s", pr, self.repo)
        raw = gh(
            [
                "api",
                f"repos/{self.repo}/issues/{pr}/comments",
                "-X",
                "POST",
                "-f",
                f"body={body}",
            ]
        )
        data = json.loads(raw)
        comment_id = str(data["id"])
        self.logger.debug("created comment %s on PR #%d", comment_id, pr)
        return comment_id

    def update_pr_comment(self, pr: int, comment_id: str, body: str) -> None:
        self.logger.info(
            "update_pr_comment %s on PR #%d in %s", comment_id, pr, self.repo
        )
        gh(
            [
                "api",
                f"repos/{self.repo}/issues/comments/{comment_id}",
                "-X",
                "PATCH",
                "-f",
                f"body={body}",
            ]
        )
        self.logger.debug("updated comment %s", comment_id)

    def merge_pr(self, pr: int) -> None:
        self.logger.info("merge_pr PR #%d in %s", pr, self.repo)
        gh(
            [
                "pr",
                "merge",
                str(pr),
                "--repo",
                self.repo,
                "--squash",
            ]
        )
        self.logger.debug("merged PR #%d", pr)
