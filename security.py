"""Fail-closed authentication and bounded bodies for account-backed endpoints."""
import hmac
import json
import os


def matches(expected, supplied):
    return bool(expected) and isinstance(supplied, str) and hmac.compare_digest(
        expected.encode(), supplied.encode())


class SecurityMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope['path'] not in ('/a2a', '/webhook'):
            return await self.app(scope, receive, send)
        async def reject(status, message):
            await send({'type': 'http.response.start', 'status': status,
                        'headers': [(b'content-type', b'application/json')]})
            await send({'type': 'http.response.body', 'body': json.dumps({'detail': message}).encode()})
        headers = dict(scope['headers'])
        if scope['path'] == '/webhook':
            expected = os.environ.get('TELEGRAM_WEBHOOK_SECRET', '')
            supplied = headers.get(b'x-telegram-bot-api-secret-token', b'').decode('latin1')
            if not matches(expected, supplied):
                return await reject(401, 'Unauthorized')
        else:
            expected = os.environ.get('A2A_EMAIL_ACTION_TOKEN', '')
            supplied = headers.get(b'authorization', b'').decode('latin1')
            # The existing email extension body token is accepted after bounded parsing.
            header_authenticated = matches('Bearer ' + expected if expected else '', supplied)
        body = bytearray()
        while True:
            event = await receive()
            if event['type'] == 'http.disconnect':
                return
            body.extend(event.get('body', b''))
            if len(body) > 128 * 1024:
                return await reject(413, 'Request too large')
            if not event.get('more_body', False):
                break
        try:
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise ValueError()
        except (ValueError, UnicodeDecodeError):
            return await reject(400, 'Expected a JSON object')
        if scope['path'] == '/a2a':
            params = payload.get('params')
            body_authenticated = (payload.get('method') in ('email/save', 'email/send')
                and isinstance(params, dict) and matches(expected, params.get('token')))
            if not header_authenticated and not body_authenticated:
                return await reject(401, 'Unauthorized')
        else:
            update = payload.get('callback_query', payload.get('message', {}))
            actor = update.get('from', {}) if isinstance(update, dict) else {}
            allowed = os.environ.get('TELEGRAM_ALLOWED_USER_IDS', '').split(',')
            if str(actor.get('id', '')) not in {x.strip() for x in allowed if x.strip()}:
                return await reject(403, 'User is not authorized')
        delivered = False
        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {'type': 'http.request', 'body': bytes(body), 'more_body': False}
            return await receive()
        await self.app(scope, replay, send)
