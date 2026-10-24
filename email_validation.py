"""Shared, dependency-free validation for a single reviewed email."""
import re


def validate_email(subject, body, recipient, require_recipient=True):
    if not isinstance(subject, str) or not subject.strip() or len(subject) > 200 or any(c in subject for c in '\r\n'):
        raise ValueError('Use a subject on one line (1–200 characters).')
    if not isinstance(body, str) or not body.strip() or len(body) > 12000:
        raise ValueError('Use an email body of 1–12000 characters.')
    if not isinstance(recipient, str) or (recipient and not re.fullmatch(r'[^\s@<>,;\r\n]+@[^\s@<>,;\r\n]+\.[^\s@<>,;\r\n]+', recipient)):
        raise ValueError('Enter one recipient email address, without a display name.')
    if require_recipient and not recipient:
        raise ValueError('Add the recipient using Edit recipient before sending.')
