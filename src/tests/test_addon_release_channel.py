"""Exact-version add-on channels do not enable general prerelease updates."""
import unittest
from unittest.mock import patch

import addon_runtime as addon
import meep_managed as meep
from app_version import APP_VERSION
from update_client import UpdateError


class AddonChannelTests(unittest.TestCase):
    def clients(self):
        client = addon.AddonClient()
        yield client, lambda: client.check_addon('gpu'), addon.asset_name('gpu')
        client = meep.ManagedMeepClient()
        yield client, client.check_pack, meep.asset_name()

    def release(self, name, tag=None, **changes):
        value = dict(tag_name=tag or 'addons-v'+APP_VERSION, prerelease=True,
                     assets=[dict(name=name, state='uploaded', id=123, size=123,
                                  digest='sha256:'+'a'*64)])
        value.update(changes)
        return value

    def test_dedicated_prerelease_and_stable_preserve_actual_tag(self):
        for client, check, name in self.clients():
            for tag, prerelease in [('addons-v'+APP_VERSION, True), ('v'+APP_VERSION, False)]:
                with self.subTest(client=type(client).__name__, tag=tag), patch.object(
                        client, '_json', return_value=[self.release(name, tag, prerelease=prerelease)]):
                    result = check()
                    self.assertEqual(result.tag, tag)
                    self.assertTrue(result.html_url.endswith('/releases/tag/'+tag))
                    self.assertEqual(result.sha256, 'a'*64)

    def test_unrelated_prereleases_versions_and_drafts_are_ignored(self):
        for client, check, name in self.clients():
            releases = [self.release(name, 'v'+APP_VERSION),
                        self.release(name, 'addons-v0.0.0'),
                        self.release(name, 'addons-v'+APP_VERSION+'-rc1'),
                        self.release(name, draft=True)]
            with self.subTest(client=type(client).__name__), patch.object(client, '_json', return_value=releases):
                self.assertIsNone(check())

    def test_missing_asset_does_not_hide_other_channel(self):
        for client, check, name in self.clients():
            for first, second in [('v'+APP_VERSION, 'addons-v'+APP_VERSION),
                                  ('addons-v'+APP_VERSION, 'v'+APP_VERSION)]:
                releases = [self.release(name, first, prerelease=False, assets=[]),
                            self.release(name, second, prerelease=False)]
                with self.subTest(client=type(client).__name__, first=first), patch.object(client, '_json', return_value=releases):
                    self.assertEqual(check().tag, second)

    def test_dedicated_channel_requires_digest_and_matching_platform(self):
        for client, check, name in self.clients():
            release = self.release(name)
            release['assets'][0]['digest'] = ''
            with self.subTest(client=type(client).__name__), patch.object(client, '_json', return_value=[release]):
                with self.assertRaises(UpdateError):
                    check()
            with patch.object(client, '_json', return_value=[self.release('wrong-platform.zip')]):
                self.assertIsNone(check())
