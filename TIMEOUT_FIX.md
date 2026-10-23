# Draft timeout repair — 24 October 2026

The async A2A endpoint called synchronous AI/Gmail work directly, blocking health and task-status requests while generation was running. Draft generation also had no configured Gemini request timeout.

- Run synchronous task execution in Starlette's thread pool.
- Use a 20-second Gemini request timeout, configurable through GEMINI_REQUEST_TIMEOUT_MS.
- Prefer GEMINI_MODEL when configured, then stable gemini-2.5-flash-lite and gemini-2.5-flash fallbacks. Verify free-tier eligibility in the Google project.
- Bound Gmail discovery, OAuth refresh, and API calls with an authenticated httplib2 transport, default timeout 20 seconds (GMAIL_REQUEST_TIMEOUT_SECONDS).
- No email sending behavior or paid infrastructure was added.

Run the five offline regression tests from the repository root:

    python -B -m unittest discover -s tests -v

Tests mock Gmail and generation calls; the concurrency test uses a worker thread and verifies tasks/get can respond before generation completes.
