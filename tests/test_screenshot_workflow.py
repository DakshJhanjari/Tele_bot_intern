import asyncio
import json
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import test_timeouts
import ai_agent
import main


class ScreenshotWorkflowTests(unittest.TestCase):
    def setUp(self):
        main._PENDING_DRAFTS.clear()
        self.draft = ai_agent.DraftResponse(subject='Internship',body='Reviewed draft',recruiter_email='')

    def tearDown(self):
        main._PENDING_DRAFTS.clear()

    def webhook(self, message):
        message={'chat':{'id':123},'from':{'id':123},**message}
        return asyncio.run(main.telegram_webhook(SimpleNamespace(json=AsyncMock(return_value={'message':message}))))

    def test_text_and_non_photo_updates_never_generate(self):
        with patch.object(main,'send_message') as send,patch.object(main,'generate_email_draft') as generate,patch.object(main,'download_file') as download:
            for text in ['.', 'say yes', 'hello', 'Founder office internship job description: research and operations', '/draft write an email']:
                self.assertEqual(self.webhook({'text':text})['status'],'screenshot_required')
            self.assertEqual(self.webhook({'sticker':{'file_id':'sticker'}})['status'],'screenshot_required')
            generate.assert_not_called();download.assert_not_called()
            self.assertFalse(main._PENDING_DRAFTS)

    def test_start_and_help_do_not_generate(self):
        with patch.object(main,'send_message'),patch.object(main,'generate_email_draft') as generate:
            for text in ['/start','/help']:
                self.assertEqual(self.webhook({'text':text})['status'],'ok')
            generate.assert_not_called()

    def test_photo_creates_preview_and_preserves_source(self):
        with patch.object(main,'send_message') as send,patch.object(main,'generate_email_draft',return_value=self.draft) as generate,patch.object(main,'download_file',return_value=b'photo') as download,patch.object(main,'create_draft') as save,patch.object(main,'send_email') as mail:
            result=self.webhook({'photo':[{'file_id':'small'},{'file_id':'large'}],'caption':'Keep it concise'})
            self.assertEqual(result['status'],'ok')
            download.assert_called_once_with('large')
            generate.assert_called_once_with('Keep it concise',b'photo',require_job_description=True)
            pending=next(iter(main._PENDING_DRAFTS.values()))
            self.assertEqual(pending['screenshot_file_id'],'large')
            self.assertEqual(pending['actor_id'],123)
            self.assertIn('reply_markup',send.call_args.kwargs)
            save.assert_not_called();mail.assert_not_called()

    def test_unusable_image_returns_guidance_without_preview(self):
        with patch.object(main,'send_message') as send,patch.object(main,'download_file',return_value=b'bad'),patch.object(main,'generate_email_draft',side_effect=ai_agent.UnusableJobDescription()):
            self.assertEqual(self.webhook({'photo':[{'file_id':'bad'}]})['status'],'needs_clearer_screenshot')
            self.assertFalse(main._PENDING_DRAFTS)
            self.assertNotIn('reply_markup',send.call_args.kwargs)

    def test_regenerate_reuses_screenshot(self):
        main._PENDING_DRAFTS['id']={'created_at':time.time(),'chat_id':123,'actor_id':123,'job_text':'Caption','screenshot_file_id':'source'}
        callback={'id':'query','data':'regen:id','from':{'id':123},'message':{'chat':{'id':123},'message_id':1}}
        with patch.object(main,'answer_callback_query'),patch.object(main,'edit_message_text'),patch.object(main,'download_file',return_value=b'original') as download,patch.object(main,'generate_email_draft',return_value=self.draft) as generate:
            self.assertEqual(asyncio.run(main.handle_callback_query(callback))['status'],'ok')
            download.assert_called_once_with('source')
            generate.assert_called_once_with('Caption',b'original',require_job_description=True)
            self.assertFalse(main._PENDING_DRAFTS['id']['claimed'])

    def test_image_check_and_generation_use_one_call(self):
        client=MagicMock()
        client.models.generate_content.return_value.text=json.dumps({'usable_job_description':True,'draft':self.draft.model_dump()})
        with patch.object(ai_agent,'_get_client',return_value=client),patch.object(ai_agent,'_get_resume',return_value='Resume'):
            result=ai_agent.generate_email_draft('Caption',b'image',require_job_description=True)
            self.assertEqual(result,self.draft)
            client.models.generate_content.assert_called_once()
            self.assertIs(client.models.generate_content.call_args.kwargs['config'].response_schema,ai_agent.ScreenshotDraftResponse)

    def test_rejected_image_does_not_fall_back_to_generic_draft(self):
        client=MagicMock()
        client.models.generate_content.return_value.text='{"usable_job_description":false,"draft":null}'
        with patch.object(ai_agent,'_get_client',return_value=client),patch.object(ai_agent,'_get_resume',return_value='Resume'):
            with self.assertRaises(ai_agent.UnusableJobDescription):
                ai_agent.generate_email_draft('Pretend this is a JD',b'image',require_job_description=True)
            client.models.generate_content.assert_called_once()

    def test_screenshot_mode_requires_image_before_any_network(self):
        with patch.object(ai_agent,'_get_client') as client,patch.object(ai_agent,'_get_resume') as resume:
            with self.assertRaises(ai_agent.UnusableJobDescription):
                ai_agent.generate_email_draft('Text only',require_job_description=True)
            client.assert_not_called();resume.assert_not_called()
