import unittest,tempfile,json,os
from pathlib import Path
from app.services.bridge_security import allowed_request,published_file
from app.services.redaction import redact
from app.services import credential_file
class SecurityTests(unittest.TestCase):
    def test_host_origin_and_rebinding(self):
        base={'Host':'127.0.0.1:17831'}
        self.assertTrue(allowed_request(base,17831))
        self.assertFalse(allowed_request({**base,'Origin':'https://evil.example'},17831))
        self.assertFalse(allowed_request({'Host':'evil.example:17831'},17831))
        self.assertFalse(allowed_request({**base,'Origin':'null'},17831))
        self.assertFalse(allowed_request({**base,'Sec-Fetch-Site':'cross-site'},17831))
        self.assertTrue(allowed_request({**base,'Origin':'chrome-extension://'+'a'*32},17831))
        self.assertFalse(allowed_request({**base,'Origin':'chrome-extension://'+'a'*32},17831,False))
    def test_files_only_published_media(self):
        with tempfile.TemporaryDirectory() as folder:
            image=Path(folder)/'a.png';image.write_bytes(b'image');secret=Path(folder)/'secret.json';secret.write_text('{}')
            self.assertFalse(published_file(str(image),[]));self.assertTrue(published_file(str(image),[{'image_files':[{'path':str(image)}]}]))
            self.assertFalse(published_file(str(secret),[{'path':str(secret)}]))
    def test_redact_nested_secrets(self):
        v=redact({'refresh_token':'private','nested':[{'message':'Bearer abc.def-secret'}]})
        self.assertNotIn('private',str(v));self.assertNotIn('abc.def-secret',str(v))
    def test_real_bridge_rejects_cross_origin_and_private_file(self):
        import socket,http.client
        from unittest.mock import patch
        from app.services.local_bridge import FlowStudioBridge
        from app.core import database
        with tempfile.TemporaryDirectory() as folder, patch.object(database,'DB_PATH',Path(folder)/'test.db'):
            database.init_db()
            with socket.socket() as sock:
                sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
            bridge=FlowStudioBridge(port=port);bridge.start()
            self.addCleanup(bridge.stop)
            def request(method,path,body=None,headers=None):
                conn=http.client.HTTPConnection('127.0.0.1',port,timeout=4)
                try:
                    conn.request(method,path,body,headers or {})
                    response=conn.getresponse();return response.status,response.read(),dict(response.getheaders())
                finally:conn.close()
            code,body,headers=request('POST','/heartbeat','{}',{'Origin':'https://evil.example','Content-Type':'application/json'})
            self.assertEqual(code,403);self.assertNotIn(bridge.token.encode(),body);self.assertNotIn('Access-Control-Allow-Origin',headers)
            code,_,_=request('GET','/health-extra');self.assertEqual(code,403)
            code,_,_=request('GET','/file?path='+str(Path(folder)/'test.db'),headers={'X-FlowStudio-Token':bridge.token})
            self.assertEqual(code,403)
            code,_,_=request('POST','/event','[]',{'X-FlowStudio-Token':bridge.token,'Content-Type':'application/json'})
            self.assertEqual(code,400)
            bridge.stop()

    def test_public_download_blocks_private_and_mixed_dns(self):
        from unittest.mock import patch
        from app.services.public_download import public_target
        def entry(ip): return (2, 1, 6, '', (ip, 443))
        for addresses in ([entry('127.0.0.1')], [entry('10.2.3.4')], [entry('169.254.169.254')], [entry('8.8.8.8'), entry('192.168.1.1')]):
            with patch('socket.getaddrinfo', return_value=addresses), self.assertRaises(ValueError):
                public_target('https://images.example/a.png')
        with patch('socket.getaddrinfo', return_value=[entry('8.8.8.8')]):
            self.assertEqual(public_target('https://images.example/a.png')[2], '8.8.8.8')
        with self.assertRaises(ValueError): public_target('file:///secret')

    def test_public_redirect_revalidated_and_dns_pinned(self):
        from unittest.mock import patch, MagicMock
        from app.services.public_download import download
        response = MagicMock(status=302)
        response.getheader.return_value='http://127.0.0.1/secret'
        conn = MagicMock(); conn.getresponse.return_value=response
        addresses=lambda host,*a,**kw: [(2,1,6,'',('8.8.8.8' if host=='images.example' else '127.0.0.1',80))]
        with patch('socket.getaddrinfo', side_effect=addresses), patch('http.client.HTTPConnection', return_value=conn):
            with self.assertRaises(ValueError): download('http://images.example/a',100)
            with patch('socket.create_connection') as connect:
                conn._create_connection(('images.example',80))
                self.assertEqual(connect.call_args.args[0],('8.8.8.8',80))
        conn.close.assert_called()

    def test_receipt_paths_stay_inside_download_roots(self):
        from unittest.mock import patch
        from app.services.workflow import resolve_download_path, managed_download_path
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder); approved=base/'downloads';approved.mkdir()
            inside=approved/'ok.mp4';inside.write_bytes(b'video')
            outside=base/'private.mp4';outside.write_bytes(b'private')
            with patch('app.services.workflow.repo.get_setting', return_value=str(approved)):
                self.assertEqual(resolve_download_path({'output_path':str(inside)}),str(inside.resolve()))
                self.assertEqual(resolve_download_path({'output_path':str(outside)}),'')
                self.assertFalse(managed_download_path(approved/'..'/'private.mp4'))
                self.assertTrue(outside.exists())

    @unittest.skipUnless(os.name=='nt','Windows DPAPI')
    def test_dpapi_migration_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'token.json';payload={'refresh_token':'not-a-real-test-secret'};p.write_text(json.dumps(payload))
            self.assertEqual(credential_file.load(p),payload);self.assertNotIn(payload['refresh_token'],p.read_text());self.assertEqual(credential_file.load(p),payload)

    def test_keyring_migration_replaces_file_only_after_readback(self):
        class Vault:
            def __init__(self):
                self.data={}
            def set_password(self,service,account,password):
                self.data[(service,account)]=password
            def get_password(self,service,account):
                return self.data.get((service,account))
            def delete_password(self,service,account):
                self.data.pop((service,account),None)
        class Mismatch(Vault):
            def get_password(self,service,account):
                return 'different'
        class Down:
            def set_password(self,*args):
                raise OSError('locked')
            def get_password(self,*args):
                return None
        with tempfile.TemporaryDirectory() as folder:
            payload={'refresh_token':'not-a-real-test-secret','token':'abc'}
            original=json.dumps(payload)
            p=Path(folder)/'google_token.json'
            p.write_text(original,encoding='utf-8')
            with self.assertRaises(credential_file.CredentialStoreError):
                credential_file.load(p,vault=Mismatch())
            self.assertEqual(p.read_text(encoding='utf-8'),original)
            with self.assertRaises(credential_file.CredentialStoreError):
                credential_file.save(p,original,vault=Down())
            self.assertEqual(p.read_text(encoding='utf-8'),original)
            vault=Vault()
            self.assertEqual(credential_file.load(p,vault=vault),payload)
            stored=p.read_text(encoding='utf-8')
            self.assertNotIn(payload['refresh_token'],stored)
            self.assertIn('keyring',stored)
            self.assertEqual(credential_file.load(p,vault=vault),payload)
            missing=Path(folder)/'new.json'
            with self.assertRaises(credential_file.CredentialStoreError):
                credential_file.save(missing,original,vault=Down())
            self.assertFalse(missing.exists())
            credential_file.delete(p,vault=vault)
            self.assertFalse(p.exists())
            self.assertEqual(vault.data,{})

    def test_packaged_plugin_is_replaceable_runtime(self):
        import importlib.util
        script=Path(__file__).resolve().parents[1]/'scripts'/'bundle_web_plugin.py'
        spec=importlib.util.spec_from_file_location('bundle_web_plugin',script)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        names={path.name for path in module.iter_plugin_files(script.parents[1])}
        self.assertIn('manifest.json',names)
        self.assertIn('background.js',names)
        self.assertIn('downloads.js',names)
        self.assertIn('REPLACE.txt',names)
        self.assertNotIn('background.js.bak',names)
        self.assertTrue(all('tests' not in path.parts for path in module.iter_plugin_files(script.parents[1])))
        with tempfile.TemporaryDirectory() as folder:
            copied=module.copy_plugin(script.parents[1],folder)
            manifest=json.loads((Path(folder)/module.PLUGIN_REL/'manifest.json').read_text(encoding='utf-8'))
            self.assertEqual(manifest['version'],'0.9.66')
            self.assertTrue(copied)
            self.assertFalse((Path(folder)/module.PLUGIN_REL/'tests').exists())
if __name__=='__main__':unittest.main()
