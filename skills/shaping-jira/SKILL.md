---
name: shaping-jira
description: Shape a feature milestone into a Jira epic + dependency-linked stories. Input: a Confluence page (via a2atlassian MCP) or a local markdown brief. Output: an epic issue plus stories linked by 'is blocked by', with the first root story transitioned to Ready so the a2sdlc dispatcher kicks off the engine.
---

# Shaping (Jira mode)

## When to use

- User has requirements in Confluence or a brief and wants Jira tickets
  ordered by dependency, ready for the a2sdlc engine to pick up.
- Target Jira project is already configured in the dispatcher's PROJECTS_JSON.
- a2atlassian MCP is connected with a Jira user that can create issues,
  link them, and transition them.

## Flow

1. Read the input source:
   - Confluence: `mcp__a2atlassian__confluence_get_page` (or equivalent from
     the a2atlassian server's Confluence tool list) with the page id/slug.
   - Local markdown: use Read tool.
2. Ask the user clarifying questions one at a time — scope, non-goals,
   success criteria. Short, targeted. Don't restart full brainstorming.
3. Draft a pitch list as markdown (see `templates/pitch.md`). Each pitch has
   - title
   - description (2–3 sentences)
   - acceptance criteria (bulleted)
   - an ordered dependency list referring to earlier pitch slugs.
4. Present draft back to user. Iterate.
5. On approval:
   a. Create epic via `mcp__a2atlassian__jira_create_issue` with
      issue_type=Epic, record its key.
   b. For each pitch, create a Story issue linked to the epic
      (fields: customfield_10014 or `Epic Link` depending on instance —
      consult a2atlassian MCP docs; fall back to issue link type "Relates to
      epic" if the custom field is unavailable).
   c. After all stories exist and slug→key mapping is known, for each story
      with dependencies, create `is blocked by` links via
      `mcp__a2atlassian__jira_create_issue_link`.
   d. Transition the root stories (no blockers) to the project's
      `status_ready` value via `mcp__a2atlassian__jira_transition_issue`.

## Anti-patterns

- Do not create Jira issues before the user approves the draft.
- Do not manually trigger the dispatcher — transitioning to Ready fires the
  Jira webhook automatically.
- Do not invent status names — use what's configured in dispatcher's
  PROJECTS_JSON for this project. When unsure, ask.

## Observability

Every ticket's life is visible in three places after shaping:
- Jira ticket: comments from the engine via the dispatcher.
- GH Actions run page linked from the Jira comment.
- MLflow run tagged with `ticket_key` (if MLflow is configured).
