import json
import tempfile
import unittest
from pathlib import Path
from app.services.google_oauth_config import load_desktop_config

class OAuthConfigTests(unittest.TestCase):
    def test_types_and_bom(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'credentials.json'
            path.write_text(json.dumps({'type':'service_account','private_key':'must-not-appear'}))
            with self.assertRaisesRegex(ValueError,'服务账号') as error:load_desktop_config(path)
            self.assertNotIn('must-not-appear',str(error.exception))
            for value in ([],{'token':'secret'},{'installed':{}},{'web':{}}):
                path.write_text(json.dumps(value))
                with self.assertRaises(ValueError):load_desktop_config(path)
            good={'installed':dict(client_id='test',client_secret='test',auth_uri='https://accounts.google.com/o/oauth2/auth',token_uri='https://oauth2.googleapis.com/token',redirect_uris=['http://localhost'])}
            path.write_text(json.dumps(good),encoding='utf-8-sig')
            self.assertEqual(load_desktop_config(path),good)

    def test_rejects_non_google_authentication_endpoints(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'client.json'
            for key in ('auth_uri','token_uri'):
                for url in ('http://accounts.google.com/token','https://accounts.google.com.evil.test/token','https://user@accounts.google.com/token','https://127.0.0.1/token'):
                    config=dict(client_id='test',client_secret='private',auth_uri='https://accounts.google.com/o/oauth2/auth',token_uri='https://oauth2.googleapis.com/token',redirect_uris=['http://localhost'])
                    config[key]=url;path.write_text(json.dumps({'installed':config}))
                    with self.assertRaises(ValueError) as error:load_desktop_config(path)
                    self.assertNotIn('private',str(error.exception))

if __name__=='__main__':unittest.main()
