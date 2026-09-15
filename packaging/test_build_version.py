"""Release metadata must stay consistent without executing application code."""
from pathlib import Path
import tempfile
import unittest

from build_version import release_info, update_info, write_build_metadata


class BuildVersionTests(unittest.TestCase):
    def test_generates_all_versions_without_importing_application(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            (path / 'app_version.py').write_text(
                "APP_VERSION = '1.0.2'\nBUILD_DATE: str = '2026-09-13'\n"
                "raise RuntimeError('The packager must not import me')\n", encoding='utf-8')
            self.assertEqual(write_build_metadata(path, path),
                             {'version': '1.0.2', 'build_date': '2026-09-13'})
            self.assertIn('#define Version "1.0.2"', (path / 'version.iss').read_text())
            self.assertIn('filevers=(1,0,2,0)', (path / 'version_info.txt').read_text())
            self.assertIn("StringStruct('ProductVersion', '1.0.2')",
                          (path / 'version_info.txt').read_text())

    def test_rejects_invalid_or_executable_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            for version, build_date in [("'1.0.2-beta'", "'2026-09-13'"),
                                        ("'65536.0.0'", "'2026-09-13'"),
                                        ("'1.0.2'", "'2026-02-30'"),
                                        ("str(1)", "'2026-09-13'")]:
                with self.subTest(version=version, build_date=build_date):
                    (path / 'app_version.py').write_text(
                        f'APP_VERSION = {version}\nBUILD_DATE = {build_date}\n', encoding='utf-8')
                    with self.assertRaises(ValueError):
                        release_info(path)

    def test_updater_authentication_follows_code_repository_not_data_profile(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            for repo, private in [('optical-design-studio-downloads', False),
                                  ('Optical-Design-Studio', False),
                                  ('optical-design-studio-updates', True)]:
                (path/'update_client.py').write_text(f'REPOSITORY = "Wgeshow/{repo}"\n', encoding='utf-8')
                info = update_info(path)
                self.assertEqual(info['authenticated_check'], private)
                self.assertEqual(info['authenticated_download'], private)
            (path/'update_client.py').write_text('REPOSITORY = "unreviewed/repository"\n', encoding='utf-8')
            with self.assertRaises(ValueError):
                update_info(path)


if __name__ == '__main__':
    unittest.main()
