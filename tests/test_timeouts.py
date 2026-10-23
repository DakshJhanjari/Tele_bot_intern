import asyncio
import importlib.util
import logging
import os
import sys
import threading
import types
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock,patch

# Gmail SDK transports are mocked. No credentials or network calls are used.
for name in ("googleapiclient", "googleapiclient.discovery", "google_auth_httplib2", "httplib2"):
    if name not in sys.modules:
        module=types.ModuleType(name)
        module.build=MagicMock()
        module.AuthorizedHttp=MagicMock()
        module.Http=MagicMock()
        sys.modules[name]=module
import ai_agent
import gmail_integration
import a2a_router

class TimeoutTests(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)
    def tearDown(self):
        logging.disable(logging.NOTSET)
    def test_gemini_client_has_bounded_timeout(self):
        with patch.object(ai_agent,"_client",None),patch.dict(os.environ,{"GEMINI_API_KEY":"offline-test"}),patch.object(ai_agent.genai,"Client") as client:
            ai_agent._get_client()
            self.assertEqual(client.call_args.kwargs["http_options"].timeout,20000)
    def test_stable_default_models(self):
        self.assertIn("gemini-2.5-flash-lite",ai_agent.FALLBACK_MODELS)
        self.assertIn("gemini-2.5-flash",ai_agent.FALLBACK_MODELS)
        self.assertNotIn("gemini-3.8-flash",ai_agent.FALLBACK_MODELS)
    def test_gmail_transport_has_timeout(self):
        with patch.object(gmail_integration,"_get_credentials",return_value=object()),patch.object(gmail_integration,"AuthorizedHttp") as auth,patch.object(gmail_integration.httplib2,"Http") as http,patch.object(gmail_integration,"build") as build:
            gmail_integration.get_gmail_service()
            http.assert_called_once_with(timeout=20.0)
            self.assertIs(build.call_args.kwargs["http"],auth.return_value)
            self.assertFalse(build.call_args.kwargs["cache_discovery"])
    def test_generation_falls_back_on_model_failure(self):
        client=MagicMock()
        client.models.generate_content.side_effect=[RuntimeError("404 NOT_FOUND"),SimpleNamespace(text='{"subject":"Hello","body":"Draft","recruiter_email":""}')]
        with patch.object(ai_agent,"_get_client",return_value=client),patch.object(ai_agent,"_get_resume",return_value="Offline resume"),patch.object(ai_agent.time,"sleep"):
            result=ai_agent.generate_email_draft("Offline startup profile")
        self.assertEqual(result.body,"Draft")
        self.assertEqual(client.models.generate_content.call_count,2)
    def test_status_lookup_stays_responsive_during_generation(self):
        async def check():
            started=threading.Event();release=threading.Event()
            task=SimpleNamespace(model_dump=lambda:{"id":"task-1","status":{"state":"working"}})
            def slow_send(params):
                started.set();release.wait(2);return task
            with patch.object(a2a_router._handler,"handle_send",side_effect=slow_send),patch.object(a2a_router._handler,"handle_get",return_value=task):
                send=asyncio.create_task(a2a_router._handle_tasks_send("rpc-send",{}))
                try:
                    self.assertTrue(await asyncio.to_thread(started.wait,1))
                    self.assertFalse(send.done(),"Generation blocked the event loop")
                    response=await asyncio.wait_for(a2a_router.a2a_endpoint({"jsonrpc":"2.0","id":"rpc-get","method":"tasks/get","params":{"id":"task-1"}}),timeout=0.5)
                    self.assertEqual(response.status_code,200)
                finally:
                    release.set()
                    await send
        asyncio.run(check())

if __name__=="__main__":unittest.main()
