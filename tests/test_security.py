import asyncio
import os
import unittest
from unittest.mock import patch, Mock
import httpx
import test_timeouts
import main
import ai_agent
from security import matches


class SecurityTests(unittest.TestCase):
    def request(self, path, payload, headers=None):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test') as client:
                return await client.post(path, json=payload, headers=headers or {})
        return asyncio.run(run())

    def test_a2a_fails_closed(self):
        with patch.dict(os.environ, {'A2A_EMAIL_ACTION_TOKEN': ''}):
            self.assertEqual(self.request('/a2a', {}).status_code, 401)

    def test_authorized_a2a_and_body_limit(self):
        with patch.dict(os.environ, {'A2A_EMAIL_ACTION_TOKEN': 'test-secret'}):
            headers={'Authorization':'Bearer test-secret'}
            r=self.request('/a2a', {'jsonrpc':'2.0','method':'unknown'}, headers)
            self.assertEqual(r.json()['error']['code'], -32601)
            self.assertEqual(self.request('/a2a', {'x':'x'*140000}, headers).status_code, 413)

    def test_webhook_requires_secret_and_allowed_actor(self):
        with patch.dict(os.environ, {'TELEGRAM_WEBHOOK_SECRET':'hook-secret','TELEGRAM_ALLOWED_USER_IDS':'123'}):
            payload={'message':{'from':{'id':456}}}
            self.assertEqual(self.request('/webhook',payload).status_code,401)
            headers={'X-Telegram-Bot-Api-Secret-Token':'hook-secret'}
            self.assertEqual(self.request('/webhook',payload,headers).status_code,403)
            payload['message']['from']['id']=123
            self.assertEqual(self.request('/webhook',payload,headers).json()['status'],'ignored')

    def test_callback_cannot_access_another_users_draft(self):
        import time
        main._PENDING_DRAFTS['private']={'created_at':time.time(),'chat_id':1,'actor_id':1}
        try:
            result=asyncio.run(main.handle_callback_query({'id':'cb','data':'send:private','from':{'id':2},'message':{'chat':{'id':1},'message_id':3}}))
            self.assertEqual(result['status'],'forbidden')
        finally:
            main._PENDING_DRAFTS.clear()

    def test_expired_drafts_removed_even_for_small_store(self):
        main._PENDING_DRAFTS['old']={'created_at':0}
        main._cleanup_old_drafts()
        self.assertNotIn('old',main._PENDING_DRAFTS)

    def test_unicode_token_is_rejected_without_error(self):
        self.assertFalse(matches('secret','💥'))

    def test_resume_refreshes_and_rejects_redirects_and_non_gist_urls(self):
        def response(text,status=200):
            r=Mock(status_code=status)
            r.__enter__=Mock(return_value=r);r.__exit__=Mock(return_value=False)
            r.iter_content.return_value=[text.encode()]
            return r
        url='https://gist.githubusercontent.com/DakshJhanjari/6700e1da879449ad083d486f004d5248/raw'
        with patch.dict(os.environ, {'RESUME_GIST_URL':url}),patch.object(ai_agent.requests,'get',side_effect=[response('First'),response('Updated'),response('',302)]) as get:
            self.assertEqual(ai_agent._get_resume(),'First')
            self.assertEqual(ai_agent._get_resume(),'Updated')
            with self.assertRaises(ValueError):ai_agent._get_resume()
            self.assertFalse(get.call_args.kwargs['allow_redirects'])
        for bad in ['http://127.0.0.1/resume','https://gist.githubusercontent.com.evil.test/a/b/raw','https://gist.githubusercontent.com/a/123/raw/abc/resume.txt']:
            with patch.dict(os.environ,{'RESUME_GIST_URL':bad}),patch.object(ai_agent.requests,'get') as get:
                with self.assertRaises(ValueError):ai_agent._get_resume()
                get.assert_not_called()

    def test_streaming_preview_does_not_save(self):
        from a2a_protocol import A2AHandler
        from ai_agent import DraftResponse
        with patch('a2a_protocol.generate_email_draft',return_value=DraftResponse(subject='Test',body='Body',recruiter_email='')),patch('a2a_protocol.create_draft') as save:
            list(A2AHandler().handle_send_subscribe({'save_draft':False,'message':{'parts':[{'type':'text','text':'Job'}]}}))
            save.assert_not_called()
