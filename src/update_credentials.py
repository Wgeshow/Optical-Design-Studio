"""Optional per-user OS credential storage, never a project file or export.

Windows uses Credential Manager directly. On Linux/macOS an installed supported
system keyring can be used; otherwise users connect for the current session.
There is deliberately no plaintext or home-grown encrypted-file fallback.
"""
import os

SERVICE = 'OpticalDesignStudio/GitHub/Wgeshow/optical-design-studio-updates'
ACCOUNT = 'private-updates'


class CredentialError(RuntimeError):
    pass


def validate_token(token):
    if not isinstance(token, str):
        raise CredentialError('Enter your GitHub access token.')
    token = token.strip()
    if not token or len(token) > 2048 or any(ord(c) < 33 or ord(c) > 126 for c in token):
        raise CredentialError('Enter a valid GitHub access token without spaces or line breaks.')
    return token


class _WindowsVault:
    label = 'Windows Credential Manager'

    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.ctypes = ctypes

        class Credential(ctypes.Structure):
            _fields_ = [('Flags', wintypes.DWORD), ('Type', wintypes.DWORD),
                        ('TargetName', wintypes.LPWSTR), ('Comment', wintypes.LPWSTR),
                        ('LastWritten', wintypes.FILETIME), ('CredentialBlobSize', wintypes.DWORD),
                        ('CredentialBlob', ctypes.POINTER(wintypes.BYTE)), ('Persist', wintypes.DWORD),
                        ('AttributeCount', wintypes.DWORD), ('Attributes', ctypes.c_void_p),
                        ('TargetAlias', wintypes.LPWSTR), ('UserName', wintypes.LPWSTR)]

        self.Credential = Credential
        self.api = ctypes.WinDLL('Advapi32.dll', use_last_error=True)
        self.api.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                      ctypes.POINTER(ctypes.POINTER(Credential))]
        self.api.CredReadW.restype = wintypes.BOOL
        self.api.CredWriteW.argtypes = [ctypes.POINTER(Credential), wintypes.DWORD]
        self.api.CredWriteW.restype = wintypes.BOOL
        self.api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        self.api.CredDeleteW.restype = wintypes.BOOL
        self.api.CredFree.argtypes = [ctypes.c_void_p]
        self.api.CredFree.restype = None

    def load(self):
        ct = self.ctypes
        pointer = ct.POINTER(self.Credential)()
        if not self.api.CredReadW(SERVICE, 1, 0, ct.byref(pointer)):
            if ct.get_last_error() == 1168:  # ERROR_NOT_FOUND
                return None
            raise CredentialError('Windows could not read the saved GitHub connection. Connect again for this session.')
        try:
            item = pointer.contents
            if item.CredentialBlobSize > 2048:
                raise CredentialError('The saved GitHub connection is invalid. Remove it and connect again.')
            return validate_token(ct.string_at(item.CredentialBlob, item.CredentialBlobSize).decode('utf-8'))
        except UnicodeError:
            raise CredentialError('The saved GitHub connection is invalid. Remove it and connect again.') from None
        finally:
            self.api.CredFree(pointer)

    def save(self, token):
        ct = self.ctypes
        blob = ct.create_string_buffer(token.encode('ascii'))
        item = self.Credential()
        item.Type = 1  # Generic credential, scoped to the signed-in Windows user.
        item.TargetName = SERVICE
        item.UserName = ACCOUNT
        item.Comment = 'Optical Design Studio private release downloads'
        item.Persist = 2  # CRED_PERSIST_LOCAL_MACHINE; not enterprise roaming.
        item.CredentialBlobSize = len(token)
        item.CredentialBlob = ct.cast(blob, type(item.CredentialBlob))
        try:
            if not self.api.CredWriteW(ct.byref(item), 0):
                raise CredentialError('Windows could not remember this connection. Use it for this session instead.')
        finally:
            ct.memset(ct.addressof(blob), 0, len(blob))

    def delete(self):
        if not self.api.CredDeleteW(SERVICE, 1, 0) and self.ctypes.get_last_error() != 1168:
            raise CredentialError('Windows could not remove the saved GitHub connection. Try again.')


class _SystemKeyring:
    label = 'System credential store'

    def __init__(self, backend):
        self.backend = backend

    def load(self):
        return self.backend.get_password(SERVICE, ACCOUNT)

    def save(self, token):
        self.backend.set_password(SERVICE, ACCOUNT, token)

    def delete(self):
        if self.backend.get_password(SERVICE, ACCOUNT) is not None:
            self.backend.delete_password(SERVICE, ACCOUNT)


def _backend():
    if os.name == 'nt':
        try:
            return _WindowsVault()
        except (OSError, AttributeError):
            return None
    try:
        import keyring
        backend = keyring.get_keyring()
        module = type(backend).__module__
        if module in {'keyring.backends.SecretService', 'keyring.backends.kwallet',
                      'keyring.backends.macOS'}:
            return _SystemKeyring(backend)
    except Exception:
        pass
    return None


class CredentialStore:
    def __init__(self, backend_factory=None):
        self._backend = (backend_factory or _backend)()

    @property
    def can_persist(self):
        return self._backend is not None

    @property
    def storage_label(self):
        return self._backend.label if self.can_persist else 'Session only'

    def load(self):
        if not self.can_persist:
            return None
        try:
            token = self._backend.load()
            return validate_token(token) if token is not None else None
        except CredentialError:
            raise
        except Exception:
            raise CredentialError('The saved GitHub connection could not be read. Connect again for this session.') from None

    def save(self, token):
        token = validate_token(token)
        if not self.can_persist:
            raise CredentialError('A system credential store is unavailable. Use this connection for the current session.')
        try:
            self._backend.save(token)
        except CredentialError:
            raise
        except Exception:
            raise CredentialError('The connection could not be remembered. Use it for this session instead.') from None

    def delete(self):
        if self.can_persist:
            try:
                self._backend.delete()
            except CredentialError:
                raise
            except Exception:
                raise CredentialError('The saved GitHub connection could not be removed. Try again.') from None
