import base64
import os
import unittest
from email import message_from_bytes
from unittest.mock import Mock, patch
import test_timeouts  # installs offline SDK transports before importing Gmail
import email_actions
import a2a_protocol
from ai_agent import DraftResponse


class EmailActionsTests(unittest.TestCase):
    def setUp(self):
        email_actions._requests.clear()
        self.env = patch.dict(os.environ, {'A2A_EMAIL_ACTION_TOKEN':'offline-secret'})
        self.env.start()
        self.params = dict(token='offline-secret',request_id='review-1:1:send',
            subject='Founder office at Example',body='Exact reviewed body\nSecond paragraph.',recipient='founder@example.com')
        self.gmail = Mock()
        self.gmail.users.return_value.drafts.return_value.create.return_value.execute.return_value = {'id':'draft-1'}
        self.gmail.users.return_value.drafts.return_value.send.return_value.execute.return_value = {'id':'message-1'}
        self.transport = patch.object(email_actions,'get_gmail_service',return_value=self.gmail)
        self.transport.start()

    def tearDown(self):
        self.transport.stop();self.env.stop()

    def test_preview_does_not_save_draft(self):
        with patch.object(a2a_protocol,'generate_email_draft',return_value=DraftResponse(subject='Test',body='Preview',recruiter_email='')),patch.object(a2a_protocol,'create_draft') as save:
            task = a2a_protocol.A2AHandler().handle_send({'save_draft':False,'message':{'parts':[{'type':'text','text':'Example startup'}]}})
            save.assert_not_called()
            data = task.artifacts[0].parts[1].data
            self.assertFalse(data['gmail_draft_saved'])
            self.assertEqual(data['body'],'Preview')

    def test_legacy_default_still_saves(self):
        with patch.object(a2a_protocol,'generate_email_draft',return_value=DraftResponse(subject='Test',body='Preview',recruiter_email='')),patch.object(a2a_protocol,'create_draft') as save:
            a2a_protocol.A2AHandler().handle_send({'message':{'parts':[{'type':'text','text':'Example startup'}]}})
            save.assert_called_once()

    def test_unauthorized_request_does_not_touch_gmail(self):
        self.params['token']='wrong'
        with self.assertRaises(ValueError):email_actions.perform('send',self.params)
        self.gmail.users.assert_not_called()

    def test_missing_recipient_does_not_touch_gmail(self):
        self.params['recipient']=''
        with self.assertRaises(ValueError):email_actions.perform('send',self.params)
        self.gmail.users.assert_not_called()

    def test_send_uses_exact_reviewed_content_and_duplicate_is_coalesced(self):
        first=email_actions.perform('send',self.params)
        second=email_actions.perform('send',self.params)
        self.assertEqual(first,second)
        drafts=self.gmail.users.return_value.drafts.return_value
        drafts.send.assert_called_once_with(userId='me',body={'id':'draft-1'})
        raw=drafts.create.call_args.kwargs['body']['message']['raw']
        message=message_from_bytes(base64.urlsafe_b64decode(raw))
        self.assertEqual(message['To'],self.params['recipient'])
        self.assertEqual(message['Subject'],self.params['subject'])
        self.assertEqual(message.get_payload(decode=True).decode().rstrip('\n'),self.params['body'])

    def test_timeout_is_not_retried(self):
        drafts=self.gmail.users.return_value.drafts.return_value
        drafts.send.return_value.execute.side_effect=TimeoutError()
        self.assertFalse(email_actions.perform('send',self.params)['success'])
        self.assertFalse(email_actions.perform('send',self.params)['success'])
        self.assertEqual(drafts.send.call_count,1)

    def test_existing_gmail_draft_is_updated_before_sending(self):
        self.params['draft_id']='saved-draft'
        email_actions.perform('send',self.params)
        drafts=self.gmail.users.return_value.drafts.return_value
        drafts.create.assert_not_called()
        drafts.update.assert_called_once()
        drafts.send.assert_called_once_with(userId='me',body={'id':'saved-draft'})

    def test_save_does_not_send(self):
        self.assertTrue(email_actions.perform('save',self.params)['success'])
        self.gmail.users.return_value.drafts.return_value.send.assert_not_called()

    def test_changed_content_cannot_reuse_request_id(self):
        email_actions.perform('send',self.params)
        self.params['body']='Changed after confirmation'
        with self.assertRaises(ValueError):email_actions.perform('send',self.params)

if __name__=='__main__':unittest.main()
