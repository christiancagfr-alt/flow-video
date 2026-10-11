import hashlib,io,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from app.services import updater
class UpdateTests(unittest.TestCase):
    def release(self):
        name='FlowStudio-99.1.2-Windows-x64-Setup.exe'
        return {'tag_name':'v99.1.2','assets':[{'name':name,'state':'uploaded','size':4,'digest':'sha256:'+hashlib.sha256(b'test').hexdigest(),'browser_download_url':f'https://github.com/{updater.REPOSITORY}/releases/download/v99.1.2/{name}'}]}
    def test_platform_assets_and_numeric_versions(self):
        self.assertIn('arm64.dmg',updater.asset_name('1.2.3','darwin','arm64'))
        self.assertIn('x86_64.dmg',updater.asset_name('1.2.3','darwin','x86_64'))
        self.assertIn('amd64.deb',updater.asset_name('1.2.3','linux','x86_64'))
        self.assertGreater(updater.version_tuple('1.2.10'),updater.version_tuple('1.2.9'))
        with self.assertRaises(ValueError):updater.asset_name('1.2.3','linux','arm64')
        with self.assertRaises(ValueError):updater.version_tuple('../../bad')
    def test_requires_same_repo_exact_name_and_digest(self):
        data=self.release();self.assertIsNotNone(updater.select_release(data,'win32','AMD64'))
        data['assets'][0]['browser_download_url']='https://evil.example/installer.exe'
        with self.assertRaises(ValueError):updater.select_release(data,'win32','AMD64')
        data=self.release();data['assets'][0]['digest']=''
        with self.assertRaises(ValueError):updater.select_release(data,'win32','AMD64')
        data=self.release();data['prerelease']=True;self.assertIsNone(updater.select_release(data,'win32','AMD64'))
    def test_download_integrity_and_cleanup(self):
        release=updater.select_release(self.release(),'win32','AMD64')
        with tempfile.TemporaryDirectory() as folder,patch.object(updater,'data_dir',return_value=Path(folder)):
            response=io.BytesIO(b'evil');response.url='https://release-assets.githubusercontent.com/file'
            with patch.object(updater.urllib.request,'urlopen',return_value=response),self.assertRaises(ValueError):updater.download(release)
            self.assertEqual(list((Path(folder)/'updates').iterdir()),[])
            response=io.BytesIO(b'test');response.url='https://release-assets.githubusercontent.com/file'
            with patch.object(updater.urllib.request,'urlopen',return_value=response):path=updater.download(release)
            self.assertEqual(path.read_bytes(),b'test')
            path.write_bytes(b'evil')
            with self.assertRaises(ValueError):updater.verify(path,release)
    def test_cancel_never_installs_partial_download(self):
        release=updater.select_release(self.release(),'win32','AMD64')
        with tempfile.TemporaryDirectory() as folder,patch.object(updater,'data_dir',return_value=Path(folder)):
            response=io.BytesIO(b'test');response.url='https://release-assets.githubusercontent.com/file'
            with patch.object(updater.urllib.request,'urlopen',return_value=response),self.assertRaises(InterruptedError):updater.download(release,cancelled=lambda:True)
            self.assertEqual(list((Path(folder)/'updates').iterdir()),[])
