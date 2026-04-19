---
name: shaping-gh
description: Shape a feature milestone into a dependency graph of GitHub Issues. Input: a GitHub Discussion thread or a local markdown brief. Output: an epic issue plus story issues linked by "## Blocked by" tasklists, with the first root issue labeled `agent` to kick off the engine.
---

# Shaping (GitHub mode)

## When to use

- The user has a rough feature idea (in a GH Discussion thread, a markdown file,
  or verbally) and wants to break it into a sequence of tickets the a2sdlc
  engine can process.
- The target repo already has `a2sdlc-run.yml` and `a2sdlc-unblock.yml`
  installed (see `docs/mode2/README.md`).

## Flow

1. Read the input source (Discussion thread via `gh api graphql` or local file).
2. Ask the user clarifying questions one at a time — scope, non-goals, success
   criteria. Keep it short; this is not full brainstorming.
3. Draft a pitch list as markdown (see `templates/pitch.md`). Each pitch has
   - a story title
   - a problem statement (2–3 sentences)
   - acceptance criteria (bulleted)
   - a `## Blocked by` tasklist referencing earlier pitches by their eventual
     issue numbers (use placeholders `#?` until issues exist).
4. Present the full draft back to the user. Iterate on feedback.
5. On approval:
   - Create the epic issue (`gh issue create`) with a summary + a tasklist
     pointing at the stories.
   - Run `scripts/create-issues.sh <pitches-dir> <owner/repo>` — creates each
     story, writes `<pitches-dir>/pitches.json` mapping slug → issue_number.
   - Back-patch `#?` placeholders in each created issue:
     ```bash
     # Example for one story body that had "- [ ] #?auth-slug":
     NUM=$(jq -r '."auth-slug"' pitches.json)
     gh issue edit <STORY_NUM> --repo <owner/repo> \
       --body "$(gh issue view <STORY_NUM> --repo <owner/repo> --json body --jq .body \
         | sed "s/#?auth-slug/#${NUM}/g")"
     ```
     (The skill iterates this for every `#?slug` placeholder in every story.)
   - Apply the `agent` label to the root issue(s) (those with no blockers).

## Scripts

`scripts/create-issues.sh` expects a bundle of pitch markdown files and
creates issues in order, writing the mapping back to `pitches.json`.

## Anti-patterns

- Do not create issues before the user approves the draft.
- Do not start engine runs directly — only label the first issue `agent`;
  the GH Actions workflow fires from there.
- Do not rewrite the user's language into agent-speak. Preserve their framing.
