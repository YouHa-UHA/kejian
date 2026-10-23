from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
import urllib.error
from classroom.agent_client import Client,NoRedirect


class AgentClientTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'connection.json'
        self.token='kj_ai_'+'x'*43
        self.config={'apiBase':'http://127.0.0.1:4188/api/agent/v1','token':self.token,'environment':'local','connectionId':'test-connection'}
        self.save()
    def save(self):self.path.write_text(json.dumps(self.config));self.path.chmod(0o600)
    def tearDown(self):self.temp.cleanup()

    def test_configuration_is_private_and_remote_requires_https(self):
        Client(self.path);self.path.chmod(0o644)
        with self.assertRaises(RuntimeError):Client(self.path)
        for base in ('http://example.com/api/agent/v1','https://user:secret@example.com/api/agent/v1','https://example.com/api/agent/v1?token=x'):
            self.config['apiBase']=base;self.save()
            with self.assertRaises(RuntimeError):Client(self.path)
        self.config.update(apiBase='https://example.com/api/agent/v1',environment='local');self.save()
        with self.assertRaises(RuntimeError):Client(self.path)
        self.config['environment']='production';self.save();Client(self.path)

    def test_cannot_send_credentials_outside_api_or_follow_redirects(self):
        client=Client(self.path);client.transport=Mock()
        for route in ('https://evil.example/','//evil.example/a','/../login','/today?token=secret','/homework?owner=1'):
            with self.assertRaises(RuntimeError):client.request('GET',route)
        client.transport.open.assert_not_called()
        with self.assertRaises(RuntimeError):NoRedirect().redirect_request(None,None,302,'Found',{},'https://evil.example/')

    def test_write_requires_stable_key_and_timeouts_are_not_retried(self):
        client=Client(self.path);client.transport=Mock()
        with self.assertRaises(RuntimeError):client.request('POST','/homework',{})
        client.transport.open.assert_not_called()
        client.transport.open.side_effect=urllib.error.URLError('timeout')
        with self.assertRaisesRegex(RuntimeError,'原幂等键'):client.request('POST','/homework',{},'stable-request-id')
        self.assertEqual(client.transport.open.call_count,1)

    def test_http_error_redacts_credentials_and_headers_are_not_in_argv(self):
        client=Client(self.path);client.transport=Mock()
        error=urllib.error.HTTPError('http://127.0.0.1/',403,'Forbidden',{},BytesIO(json.dumps({'error':'echo '+self.token,'code':'DENIED'}).encode()))
        client.transport.open.side_effect=error
        with self.assertRaises(RuntimeError) as caught:client.request('GET','/me')
        self.assertNotIn(self.token,str(caught.exception));self.assertIn('[REDACTED]',str(caught.exception))
        request=client.transport.open.call_args.args[0]
        self.assertNotIn(self.token,request.full_url)
        self.assertTrue(request.get_header('Authorization').startswith('Bearer '))

    def test_changed_metadata_without_rules_and_mismatched_documents_are_rejected(self):
        client=Client(self.path)
        with self.assertRaisesRegex(RuntimeError,'重新同步'):
            client._accept({'sync':{'changed':True,'versions':{'context':'new'}}})
        with self.assertRaisesRegex(RuntimeError,'不一致'):
            client._accept({'updates':{'capabilities':{'apiVersion':'kejian-agent-v1'},
                'openapi':{'info':{'version':'kejian-agent-v1'}},'guide':{'openapiSha256':'incorrect'}}})
        self.assertIsNone(client.context)


if __name__=='__main__':unittest.main()
