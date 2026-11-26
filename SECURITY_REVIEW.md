# Security review and local verification

Reviewed Python entry points, Telegram/Gmail/Gemini integrations, A2A handlers,
OAuth helper, deployment configuration, and dependency declarations.

## Changes

- `/a2a` requires `Authorization: Bearer <A2A_EMAIL_ACTION_TOKEN>` for generation,
  streaming, and task retrieval. The existing body token remains accepted only for
  the private `email/save` and `email/send` extensions. Unconfigured access fails closed.
- `/webhook` requires Telegram's secret-token header and an actor ID listed in
  `TELEGRAM_ALLOWED_USER_IDS`. Configure `TELEGRAM_WEBHOOK_SECRET` before webhook
  registration. These settings are intentionally required even for local webhook tests.
- Telegram callbacks are tied to the original chat and actor, expire after two
  hours, and claim actions before provider writes. Ambiguous failures remain locked;
  check Gmail before submitting a new operation. Pending drafts/tasks have capacity limits.
- Request bodies, downloaded images, and resume downloads have size limits.
  Gmail writes validate recipient/header/content fields. Error responses and application
  logs avoid raw provider exceptions, which can include credentials or email content.
- Streaming respects `save_draft: false`; OAuth credentials are written to a private,
  ignored `token.json` rather than printed to terminal logs.

## Resume updates

Default source: https://gist.githubusercontent.com/DakshJhanjari/6700e1da879449ad083d486f004d5248/raw

Edit the Gist to update future generated drafts. Each generation fetches it anew
with no application cache. GitHub's own caching can delay visibility; existing drafts
are unchanged. If the Gist has multiple files, set `RESUME_GIST_URL` to the same URL
with `/resume-filename.txt` appended. Use an unpinned raw URL, without a revision SHA.
An existing `RESUME_GIST_URL` environment setting overrides the new default: replace
an old setting or remove it. Fetches reject non-Gist URLs, redirects, empty/oversized
content and failures instead of silently using an outdated resume.

The current cloud network rejected access to this Gist, so its actual contents
have not been verified. Tests mock sequential Gist versions to verify refresh behavior.

## Checks and operating limits

Run from this repository:

```sh
/workspace/tele-bot-venv/bin/python -B -W ignore::DeprecationWarning -m unittest discover -s tests -v
```

Tests use mocked providers and never send real email. The service is a single-owner,
single-process application: all A2A callers sharing its token can read its tasks.
Run one worker. In-memory callback claims/tasks do not provide durable, cross-process
idempotency; a durable caller claim is still required for private email actions.
Deploy behind HTTPS with ingress rate limits and restricted access. No review can
guarantee the absence of vulnerabilities. Live provider verification requires credentials.

Validation: all 22 offline tests passed after dependency upgrades; pip check passed.
A follow-up pip-audit of requirements.txt reported no known vulnerabilities.
A real Uvicorn process passed health/discovery and rejected unauthenticated A2A
and webhook requests. This does not establish live provider behavior.
