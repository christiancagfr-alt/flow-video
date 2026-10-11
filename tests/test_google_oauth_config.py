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

if __name__=='__main__':unittest.main()
