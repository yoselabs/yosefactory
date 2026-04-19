# a2sdlc dispatcher — Dokploy deploy

## Prereqs

- Dokploy installed on the host, Traefik running with an external network
  named `traefik-public`.
- Cloudflare wildcard DNS record for the chosen domain (`dispatcher.yose.tld`).
- GitHub App registered in the yoselabs org, installed on target repos.
- Jira Cloud bot user + API token.
- Self-hosted MLflow reachable from GitHub Actions (optional).

## Env (set in Dokploy UI)

| Var | Meaning |
|---|---|
| `JIRA_BASE_URL` | e.g. `https://acme.atlassian.net` |
| `JIRA_USER` | bot account email |
| `JIRA_TOKEN` | API token |
| `GH_APP_ID` | numeric App id |
| `GH_APP_PRIVATE_KEY` | PEM contents, newlines preserved |
| `GH_APP_INSTALLATION_ID` | numeric installation id (per target-repo-owning org). Dispatcher mints JWT + exchanges for installation tokens on demand; no long-lived token to rotate. |
| `HMAC_SIGNING_KEY` | random 32 bytes, base64 or hex |
| `JIRA_WEBHOOK_SECRET` | shared secret for webhook sig verification |
| `GH_WEBHOOK_SECRET` | shared secret for GH webhook sig verification |
| `SELF_URL` | public HTTPS URL of this dispatcher, e.g. `https://dispatcher.yose.tld`. Used as `dispatcher_url` workflow input. |
| `PROJECTS_JSON` | JSON array, one entry per Jira project (see spec §"Config") |

## Deploy

1. Point Dokploy at this compose (repo + path).
2. Set env vars.
3. Deploy. Traefik will serve HTTPS on `https://dispatcher.yose.tld/healthz`.

## Configure Jira webhook

Jira → Project settings → Automation → System webhook.
- URL: `https://dispatcher.yose.tld/jira/events`
- Secret: `JIRA_WEBHOOK_SECRET`
- Events: Issue updated (scoped to the project)
- Payload: default JSON

## Configure GitHub webhook

Each target repo's GitHub App installation auto-sends PR events to a shared
URL. If using a webhook directly instead of the App:
- URL: `https://dispatcher.yose.tld/gh/events`
- Secret: `GH_WEBHOOK_SECRET`
- Content-Type: `application/json`
- Events: Pull request (closed)
