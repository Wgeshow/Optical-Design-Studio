import unittest
from unittest.mock import Mock
from update_credentials import CredentialStore, CredentialError, validate_token


class CredentialTests(unittest.TestCase):
    def test_no_plaintext_fallback_when_vault_missing(self):
        store = CredentialStore(backend_factory=lambda: None)
        self.assertFalse(store.can_persist)
        self.assertIsNone(store.load())
        with self.assertRaises(CredentialError):
            store.save('test_token')
        store.delete()

    def test_retrieval_remember_and_forget_use_only_selected_backend(self):
        backend = Mock(label='Test OS vault')
        backend.load.return_value = 'test_token'
        store = CredentialStore(backend_factory=lambda: backend)
        self.assertEqual(store.load(), 'test_token')
        store.save('test_token')
        backend.save.assert_called_once_with('test_token')
        store.delete()
        backend.delete.assert_called_once_with()

    def test_failure_messages_do_not_expose_credentials(self):
        backend = Mock(label='Test OS vault')
        for operation in ('load', 'save', 'delete'):
            getattr(backend, operation).side_effect = RuntimeError('sensitive_test_token')
        store = CredentialStore(backend_factory=lambda: backend)
        for operation, args in (('load', ()), ('save', ('sensitive_test_token',)), ('delete', ())):
            with self.subTest(operation=operation), self.assertRaises(CredentialError) as result:
                getattr(store, operation)(*args)
            self.assertNotIn('sensitive_test_token', str(result.exception))

    def test_invalid_tokens_never_reach_store(self):
        backend = Mock(label='Test OS vault')
        store = CredentialStore(backend_factory=lambda: backend)
        for token in ('', 'abc\ndef', 'abc def', 'x' * 2049, 'é', None):
            with self.subTest(token=repr(token)[:25]), self.assertRaises(CredentialError):
                store.save(token)
        backend.save.assert_not_called()


if __name__ == '__main__':
    unittest.main()
