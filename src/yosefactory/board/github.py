"""GitHub Issues as a `BoardAdapter`, via `gh api` subprocess calls (design.md D1).

Every call names `self.repo` explicitly (spec: "no call omits `--repo` or relies on the current
directory's git remote") -- this repo's own git remote is `yoselabs/yosefactory`, the public repo
the whole design exists to keep work items off of, so an adapter that ever fell back to "current
directory" would be the exact disclosure risk architecture.md §7 and the dispatch both name.

Ref resolution (`open()`) has no cache: every call searches issues for the marker line
`<!-- yosefactory:item=<id> -->` in the body (design.md D2). That is what makes the re-projection
acid test meaningful rather than assumed -- deleting every issue and calling `open()` again finds
nothing, by construction, and creates fresh ones.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence

from yosefactory.board.event import Event, parse_command
from yosefactory.protocol.backlog import frame
from yosefactory.protocol.eventlog import FoldedLog

MARKER = "yosefactory:item="


class BoardError(RuntimeError):
    """A `gh` call the adapter needed did not succeed."""


def _marker_line(item_id: str) -> str:
    return f"<!-- {MARKER}{item_id} -->"


def _extract_item_id(body: str) -> str | None:
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("<!--") and MARKER in stripped:
            return stripped.split(MARKER, 1)[1].split("-->", 1)[0].strip()
    return None


class GitHubIssuesAdapter:
    """One instance per repository. `gh` supplies auth (the operator's session, or `GH_TOKEN` in
    a container) -- this class never reads, prints, or stores a credential itself.

    S242: identity is not, however, silent. `self.identity` names which `gh` login answered --
    resolved once, on first read, from `gh api user` -- so a call that failed or returned less
    than expected is diagnosable after the fact without a second manual `gh auth status`."""

    def __init__(self, repo: str) -> None:
        if "/" not in repo:
            raise ValueError(f"repo must be 'owner/name', got {repo!r}")
        self.repo = repo
        self.identity: str | None = None  # resolved on first read; see `_ensure_identity`

    # -- gh plumbing -----------------------------------------------------------------------

    def _ensure_identity(self) -> None:
        """S242: identity was ambient -- whichever `gh` account is active answers every call, and
        a second account's 404 was the only sign anything had changed. Resolve+cache the
        authenticated login (`gh api user`'s `.login`) once, so every `BoardError` this instance
        raises from here on names who made the call, not only which repo it named.

        Login only, never a token -- `gh api user` returns profile data, the same shape `gh auth
        status` already prints. Best-effort: a failure here must not block the read that
        triggered it, so it degrades to `identity` staying `None` rather than raising.
        """
        if self.identity is not None:
            return
        try:
            self.identity = json.loads(self._api(["user"]))["login"]
        except (BoardError, KeyError, ValueError):
            pass

    def _api(self, args: Sequence[str], *, input_text: str | None = None) -> str:
        argv = ["gh", "api", *args]
        completed = subprocess.run(  # noqa: S603
            argv, input=input_text, capture_output=True, text=True, check=False
        )
        if completed.returncode != 0:
            who = f" as {self.identity!r}" if self.identity else ""
            raise BoardError(
                f"gh api {' '.join(args)} failed{who}: {(completed.stderr or completed.stdout).strip()}"
            )
        return completed.stdout

    def _paginated_json_array(self, args: Sequence[str]) -> list[dict]:
        """`gh api --paginate` concatenates one JSON array per page in the output stream --
        one `json.loads` on the whole thing breaks past a single page. Used by every list call."""
        out = self._api(args).strip()
        items: list[dict] = []
        decoder = json.JSONDecoder()
        pos = 0
        while pos < len(out):
            chunk, end = decoder.raw_decode(out, pos)
            items.extend(chunk)
            pos = end
            while pos < len(out) and out[pos] in " \n\t":
                pos += 1
        return items

    def _issues(self, *, state: str = "all") -> list[dict]:
        self._ensure_identity()
        args = [f"repos/{self.repo}/issues", "--paginate", "-X", "GET", "-f", f"state={state}", "-f", "per_page=100"]
        return [issue for issue in self._paginated_json_array(args) if "pull_request" not in issue]

    def _find_ref(self, item_id: str) -> str | None:
        marker = _marker_line(item_id)
        for issue in self._issues():
            if marker in (issue.get("body") or ""):
                return str(issue["number"])
        return None

    # -- BoardAdapter ------------------------------------------------------------------------

    def open(self, item: FoldedLog) -> str:
        existing = self._find_ref(item.id)
        if existing is not None:
            return existing
        title, body = self._render(item)
        out = self._api([f"repos/{self.repo}/issues", "-f", f"title={title}", "-F", "body=@-"], input_text=body)
        return str(json.loads(out)["number"])

    def project(self, item: FoldedLog, ref: str) -> None:
        title, body = self._render(item)
        self._api([f"repos/{self.repo}/issues/{ref}", "-X", "PATCH", "-f", f"title={title}", "-F", "body=@-"], input_text=body)

    def comment(self, ref: str, body: str) -> None:
        self._api([f"repos/{self.repo}/issues/{ref}/comments", "-F", "body=@-"], input_text=body)

    def close(self, ref: str, resolution: str) -> None:
        current = json.loads(self._api([f"repos/{self.repo}/issues/{ref}"]))
        if current.get("state") == "closed":
            return
        self.comment(ref, f"closed: {resolution}")
        self._api([f"repos/{self.repo}/issues/{ref}", "-X", "PATCH", "-f", "state=closed"])

    def list_events(self, since: str | None) -> Sequence[Event]:
        """No login-based actor guard, deliberately -- see the module docstring's own correction.

        A comment is a command only if it parses as one (`parse_command`), and every comment this
        adapter itself posts (`comment()`'s rejections, `close()`'s resolution note) is free text
        that never starts with `/`, so `parse_command` already excludes them regardless of who
        posted them. A login check would be redundant *and* wrong on any single-account setup --
        Denis's own operator session and the adapter's credential can be the same GitHub identity,
        which is exactly this change's own live-test setup and a realistic early-deployment shape
        before a separate bot account exists. Found live: an earlier version filtered by login and
        silently ate every test command because the test posted as the same account the adapter
        reads as.
        """
        events: list[Event] = []
        for issue in self._issues():
            item_id = _extract_item_id(issue.get("body") or "")
            number = str(issue["number"])
            if item_id is None:
                # design.md ("the property create doesn't share with the other three"): a
                # markerless issue has no item to dispatch comments against yet, so this pass reads
                # only its title/body -- fresh, never cached -- and offers it as intake. Once
                # `ingest()`'s create branch calls `project()` on this same issue, the next call
                # here finds the marker and this issue never reaches this branch again.
                events.append(
                    Event(
                        event_id=f"gh-issue-create-{number}",
                        ts=issue["created_at"],
                        actor=(issue.get("user") or {}).get("login", "unknown"),
                        type="create",
                        payload={"title": issue.get("title") or "", "body": issue.get("body") or "", "ref": number},
                    )
                )
                continue

            comments_args = [f"repos/{self.repo}/issues/{number}/comments", "--paginate", "-X", "GET", "-f", "per_page=100"]
            comments = self._paginated_json_array(comments_args)
            for comment in comments:
                if since is not None and comment["created_at"] <= since:
                    continue
                parsed = parse_command(comment["body"])
                if parsed is None:
                    continue
                command_type, payload = parsed
                events.append(
                    Event(
                        event_id=f"gh-comment-{comment['id']}",
                        ts=comment["created_at"],
                        actor=comment["user"]["login"],
                        type=command_type,
                        payload={**payload, "item_id": item_id, "ref": number},
                    )
                )
        events.sort(key=lambda event: event.ts)
        return events

    # -- rendering -----------------------------------------------------------------------------

    def _render(self, item: FoldedLog) -> tuple[str, str]:
        goal = str(frame(item).get("goal", ""))
        title = f"[{item.state}] {goal[:80]}" if goal else f"[{item.state}] {item.id}"
        body = f"{_marker_line(item.id)}\nState: {item.state}\n\n{goal}\n"
        return title, body
