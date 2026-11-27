# Telegram job screenshot workflow

Send the bot a LinkedIn job description screenshot as a Telegram photo. An optional
caption can request a tone or focus. `/start` and `/help` explain the workflow.
Text-only messages, pasted JDs, punctuation, stickers and unsupported attachments
receive screenshot guidance without fetching the resume or calling Gemini.
Images sent as documents should be resent as photos.

For photos, the agent fetches the current Gist resume and uses one Gemini request
to check the image and draft a tailored email. The screenshot itself must contain a
readable role and responsibilities or requirements. Captions cannot substitute for
missing JD content. Unrelated or unreadable images return a request for a clearer
screenshot and create no pending email. The image check is model-based and can
misclassify inputs; it is not a guarantee of OCR accuracy.

Successful images produce the existing Telegram preview and action buttons.
Nothing is written to Gmail until Save as Draft or Send Email is selected.
Regenerate downloads the original Telegram photo again, retains the caption, and
checks/drafts against the image again. Only the file ID is retained, not image bytes.

The A2A discovery card and authenticated endpoints continue accepting text-based
job descriptions/company profiles. Their response format and save_draft behavior
are unchanged. No separate A2A capability notification is sent to another agent.

Validation: python -B -W ignore::DeprecationWarning -m unittest discover -s tests -v
