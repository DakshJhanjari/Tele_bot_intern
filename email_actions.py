"""Private JSON-RPC extensions for explicitly reviewed email writes.

The discovery bot persists the send claim in its EC2 database before calling us.
This additional process lock coalesces repeats; it is not a durable send ledger.
"""
import hashlib
import hmac
import json
import os
import threading
import time
from email_validation import validate_email
from gmail_integration import get_gmail_service
from email.message import EmailMessage
import base64

_lock = threading.Lock()
_requests = {}


def perform(action, params):
    expected = os.environ.get('A2A_EMAIL_ACTION_TOKEN', '')
    supplied = params.get('token', '')
    if not expected or not isinstance(supplied, str) or not hmac.compare_digest(expected, supplied):
        raise ValueError('Email actions are not authorized.')
    if action not in ('save', 'send'):
        raise ValueError('Unknown email action.')
    subject, body, recipient = (params.get(k, '') for k in ('subject', 'body', 'recipient'))
    validate_email(subject, body, recipient, action == 'send')
    key = params.get('request_id')
    if not isinstance(key, str) or not key or len(key) > 120:
        raise ValueError('A unique request_id is required.')
    digest = hashlib.sha256(json.dumps([action, subject, body, recipient, params.get('draft_id')]).encode()).hexdigest()
    with _lock:
        previous = _requests.get(key)
        if previous:
            if previous['digest'] != digest:
                raise ValueError('A request_id cannot be reused with changed content.')
            return previous['result']
        # Retain one day. The caller keeps a durable claim even across our restarts.
        for old in [k for k,v in _requests.items() if v['time'] < time.time()-86400]:
            del _requests[old]
        _requests[key] = {'digest': digest, 'time': time.time(),
                          'result': {'success': False, 'state': 'in_progress_or_uncertain'}}
    # Never automatically retry a write whose result may already have reached Gmail.
    try:
        message = EmailMessage()
        message['Subject'] = subject
        if recipient:
            message['To'] = recipient
        message.set_content(body)
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        gmail = get_gmail_service()
        draft_id = params.get('draft_id')
        if draft_id:
            gmail.users().drafts().update(userId='me', id=draft_id,
                body={'message': {'raw': raw}}).execute()
        else:
            draft = gmail.users().drafts().create(userId='me', body={'message': {'raw': raw}}).execute()
            draft_id = draft['id']
        if action == 'send':
            result = gmail.users().drafts().send(userId='me', body={'id': draft_id}).execute()
            outcome = {'success': True, 'id': result['id'], 'state': 'sent'}
        else:
            outcome = {'success': True, 'id': draft_id, 'state': 'saved'}
    except Exception:
        # Do not leak provider credentials or draft content in a JSON-RPC error.
        outcome = {'success': False, 'state': 'uncertain'}
    with _lock:
        _requests[key]['result'] = outcome
    return outcome
