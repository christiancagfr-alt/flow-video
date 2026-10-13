import tempfile
import unittest
from pathlib import Path

from app.services.chrome_profiles import chrome_open_command, classify_session, profile_avatar_file, valid_profile_directory


class ChromeProfileTests(unittest.TestCase):
    def test_flow_cookie_counts_as_logged_in(self):
        self.assertEqual(classify_session('a@example.com', True, True), '已登录 Flow')

    def test_google_account_without_flow_cookie_can_open(self):
        self.assertEqual(classify_session('a@example.com', False, False), '可打开 Flow')
        self.assertEqual(classify_session('', False, True), '可打开 Flow')

    def test_profile_without_google_is_logged_out(self):
        self.assertEqual(classify_session('', False, False), '未登录')

    def test_profile_directory_rejects_paths(self):
        self.assertTrue(valid_profile_directory('Default'))
        self.assertTrue(valid_profile_directory('Profile 9'))
        self.assertFalse(valid_profile_directory(r'..\Default'))
        self.assertFalse(valid_profile_directory('Profile/1'))

    def test_avatar_uses_a_local_picture_and_rejects_a_path(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'Google Profile.ico').write_bytes(b'ico')
            self.assertTrue(profile_avatar_file(str(root)).endswith('Google Profile.ico'))
            (root / 'Google Profile Picture.png').write_bytes(b'png')
            self.assertTrue(profile_avatar_file(str(root)).endswith('.png'))
        self.assertEqual(profile_avatar_file(r'..\Default'), '')

    def test_open_command_uses_the_existing_profile(self):
        command = chrome_open_command(r'C:\Chrome\chrome.exe', 'Profile 3')
        self.assertEqual(command[1], '--profile-directory=Profile 3')
        self.assertTrue(command[2].startswith('https://flow.google.com/'))


if __name__ == '__main__':
    unittest.main()
