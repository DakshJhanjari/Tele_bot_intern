# Telegram email review

From a startup's leads card choose **Draft Cold Email**. The bot generates a
Founder's Office pitch and shows the recipient, subject, and full plain-text body.
No Gmail draft is created at this stage.

- **Edit recipient / subject / body**: reply directly to the bot's edit prompt.
  `/cancel` cancels that edit. The updated preview replaces older buttons.
- **Regenerate**: generate a new pitch while keeping the selected recipient.
- **Save to Gmail**: save/update a Gmail draft and continue reviewing in Telegram.
- **Send**: show the exact email again, then require **Confirm send**.
- **Discard**: disable this preview; previously saved Gmail drafts are retained.

Previews expire after 24 hours. Sending requires one complete email address.
The recipient is taken from the selected lead, never guessed by the language model.
New pitches prioritize strategy, operations, customer research, growth experiments,
and execution alongside founders. Candidate claims, including Grabit details, must
be supported by the résumé fetched by the email agent from its configured Gist.

## Reliability and configuration

`services/telegram_email.py` creates only its own `telegram_email_reviews` table in
the application's database. Existing database tables are preserved. The send claim
is committed before the network call and survives EC2/container restarts. Repeated
taps and outdated confirmation buttons cannot reuse it. If Gmail or the network
returns an ambiguous result, the preview is locked; inspect Gmail Sent/Drafts before
starting another attempt. A crash can leave a preview in `sending`/`saving`; it is
deliberately not automatically retried.

The email agent implements private JSON-RPC extensions `email/save` and `email/send`.
Both require the same `A2A_EMAIL_ACTION_TOKEN` on EC2 and Render. Existing A2A
`tasks/send` callers still save Gmail drafts by default. The Telegram preview caller
sets `save_draft: false`. These extensions do not change the A2A standard.

Saved drafts are updated to the exact Telegram-reviewed content before sending.
Edits made independently in Gmail are therefore replaced when sending from Telegram.
The email agent also coalesces identical request IDs in memory; the durable source
of duplicate prevention remains the EC2 database. No extra services or subscriptions
are required.

## Offline checks

Discovery repository: `python -B -m unittest discover -s tests -v`

Email-agent repository: `python -B -W ignore::DeprecationWarning -m unittest discover -s tests -v`

Workflow cases include initial preview without Gmail writes, missing recipient,
exact reviewed content, two-stage confirmation, duplicate claims/taps, old buttons
after edits, force-reply routing, regeneration, saving then sending the same Gmail
draft, expiry, actor/chat mismatch, discard, persistence, long Unicode messages,
header validation, and ambiguous provider timeouts. Provider calls are mocked;
verification must never send a real email automatically.
