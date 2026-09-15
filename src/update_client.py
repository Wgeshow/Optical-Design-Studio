"""Anonymous, read-only GitHub release checks and verified package downloads.

This module never installs or executes a downloaded package and never reads or
sends account credentials. Production requests use system TLS verification and
an opener that disables automatic redirects, so every download address is checked
before the next request.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from http.client import HTTPException
import json
import math
import os
from pathlib import Path
import re
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


REPOSITORY = "Wgeshow/Optical-Design-Studio"
REPOSITORY_URL = f"https://github.com/{REPOSITORY}"
_API_ROOT = "https://api.github.com"
_REPO_PATH = f"/repos/{REPOSITORY}"
_ASSET_HOSTS = frozenset({
    "release-assets.githubusercontent.com", "objects.githubusercontent.com",
    "github-releases.githubusercontent.com",
})
_PACKAGE_TEMPLATES = {
    "windows-x64": "OpticalDesignStudio-Setup-{version}-Windows-x64.exe",
    "linux-x64": "OpticalDesignStudio-{version}-Linux-x64.tar.gz",
    "linux-arm64": "OpticalDesignStudio-{version}-Linux-arm64.tar.gz",
}
_WINDOWS_PORTABLE = 'OpticalDesignStudio-Portable-{version}-Windows-x64.zip'
_VERSION_RE = re.compile(r"v?(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})\Z")
_DIGEST_RE = re.compile(r"sha256:([0-9a-fA-F]{64})\Z")
_HASH_RE = re.compile(r"[0-9a-f]{64}\Z")
_MAX_PACKAGE_BYTES = 8 * 1024**3
_MAX_JSON_BYTES = 8 * 1024**2
_MAX_PAGES = 100
_PAGE_SIZE = 100
_CHUNK_SIZE = 1024**2


class UpdateError(Exception):
    """An error whose message is safe to display without exposing credentials."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class UpdateCancelled(UpdateError):
    def __init__(self):
        super().__init__("cancelled", "Update operation cancelled.")


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    tag: str
    published_at: str
    notes: str
    html_url: str
    asset_id: int
    asset_name: str
    asset_size: int
    sha256: str


@dataclass(frozen=True)
class CheckResult:
    status: str
    # Kept for compatibility with saved results; anonymous checks leave it empty.
    username: str
    release: ReleaseInfo | None
    checked_at: str


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _version(value):
    match = _VERSION_RE.fullmatch(value) if isinstance(value, str) else None
    return tuple(map(int, match.groups())) if match else None


def _cancelled(cancel):
    if cancel is not None and cancel.is_set():
        raise UpdateCancelled()


def _positive_int(value):
    return type(value) is int and value > 0


def _read_available(response, size):
    # HTTPResponse.read(size) can wait for the entire size on a continuously
    # trickling connection. read1 returns after at most one underlying read,
    # allowing cancellation checks between arrivals. Simple test transports
    # and compatible file-like responses may only implement read.
    read1 = getattr(response, "read1", None)
    return read1(size) if callable(read1) else response.read(size)


class GitHubUpdateClient:
    """Read this application's public downloads repository without signing in.

    An optional test opener implements ``open(request, timeout=seconds)`` and
    must return redirects without following them, as the production opener does.
    ``progress(done, total)`` is called on the caller's thread.
    """

    def __init__(self, timeout=15, opener=None):
        try:
            self.timeout = float(timeout)
        except (TypeError, ValueError):
            raise UpdateError("configuration", "The update request timeout is invalid.") from None
        if not math.isfinite(self.timeout) or not 0 < self.timeout <= 120:
            raise UpdateError("configuration", "The update request timeout is invalid.")
        self._opener = opener if opener is not None else build_opener(_NoRedirect())

    def _request(self, url, *, api_request, accept):
        parts = urlsplit(url)
        if (parts.scheme != "https" or parts.username or parts.password
                or parts.fragment or parts.port not in (None, 443)):
            raise UpdateError("unsafe_url", "The update service returned an unsafe download address.")
        if api_request:
            allowed = (parts.hostname == "api.github.com" and (
                parts.path == _REPO_PATH
                or parts.path == f"{_REPO_PATH}/releases"
                or re.fullmatch(re.escape(_REPO_PATH) + r"/releases/assets/[1-9][0-9]*", parts.path)
            ))
            if not allowed:
                raise UpdateError("unsafe_url", "The update request is outside the approved repository.")
        elif parts.hostname not in _ASSET_HOSTS:
            raise UpdateError("unsafe_redirect", "The update service returned an unapproved download host.")
        headers = {"Accept": accept, "User-Agent": "Optical-Design-Studio-Updater",
                   "Accept-Encoding": "identity"}
        if api_request:
            headers["X-GitHub-Api-Version"] = "2022-11-28"
        return Request(url, headers=headers, method="GET")

    def _open(self, request):
        try:
            return self._opener.open(request, timeout=self.timeout)
        except HTTPError as exc:
            # Redirects are deliberately surfaced rather than followed by urllib.
            return exc
        except (URLError, OSError, ValueError, HTTPException):
            raise UpdateError("network", "Cannot reach GitHub. Check your connection and try again.") from None

    @staticmethod
    def _status(response):
        status = getattr(response, "status", None)
        return status if status is not None else response.getcode()

    @staticmethod
    def _http_error(status, headers):
        retry_after = headers.get("Retry-After", "")
        secondary_limit = isinstance(retry_after, str) and retry_after.strip().isascii() and retry_after.strip().isdigit()
        if status == 429 or (status == 403 and (headers.get("X-RateLimit-Remaining") == "0" or secondary_limit)):
            return UpdateError("rate_limit", "GitHub's anonymous request limit was reached. Wait before checking again; no access key is required.")
        if status in (401, 403, 404):
            return UpdateError("access_denied", "The public update repository or package is unavailable. Try again later or contact the application publisher.")
        return UpdateError("service", "GitHub could not complete the update request. Try again later.")

    def _json(self, path, cancel=None):
        _cancelled(cancel)
        request = self._request(_API_ROOT + path, api_request=True,
                                accept="application/vnd.github+json")
        response = self._open(request)
        try:
            status = self._status(response)
            if status != 200:
                raise self._http_error(status, response.headers)
            try:
                chunks = []
                total = 0
                while True:
                    _cancelled(cancel)
                    chunk = _read_available(response, min(65536, _MAX_JSON_BYTES - total + 1))
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > _MAX_JSON_BYTES:
                        raise UpdateError("invalid_response", "The update response exceeds the supported size.")
                    chunks.append(chunk)
                data = b"".join(chunks)
            except (OSError, ValueError, HTTPException):
                raise UpdateError("network", "The update response was interrupted. Try again.") from None
            _cancelled(cancel)
            try:
                return json.loads(data.decode("utf-8"))
            except (UnicodeError, ValueError, RecursionError):
                raise UpdateError("invalid_response", "GitHub returned an unreadable update response.") from None
        finally:
            response.close()

    def check(self, installed_version, platform_id="windows-x64", cancel=None):
        installed = _version(installed_version)
        if installed is None:
            raise UpdateError("configuration", "The installed application version is invalid.")
        if platform_id not in _PACKAGE_TEMPLATES:
            raise UpdateError("unsupported_platform", "Update downloads are not available for this platform.")
        repository = self._json(_REPO_PATH, cancel)
        if not isinstance(repository, dict) or str(repository.get("full_name", "")).lower() != REPOSITORY.lower():
            raise UpdateError("invalid_response", "GitHub did not return the configured update repository.")
        if repository.get("private") is not False:
            raise UpdateError("repository_not_public", "The update repository is not confirmed public. Contact the application publisher.")
        candidates = []
        stable_found = False
        for page in range(1, _MAX_PAGES + 1):
            releases = self._json(f"{_REPO_PATH}/releases?per_page={_PAGE_SIZE}&page={page}", cancel)
            if not isinstance(releases, list):
                raise UpdateError("invalid_response", "GitHub returned an invalid release list.")
            for release in releases:
                if not isinstance(release, dict) or release.get("draft") is not False or release.get("prerelease") is not False:
                    continue
                parsed = _version(release.get("tag_name"))
                if parsed is None or not release.get("published_at"):
                    continue
                stable_found = True
                version = ".".join(map(str, parsed))
                expected = [_PACKAGE_TEMPLATES[platform_id].format(version=version)]
                if platform_id == 'windows-x64':
                    expected.insert(0, _WINDOWS_PORTABLE.format(version=version))
                assets = release.get("assets")
                if not isinstance(assets, list):
                    raise UpdateError("invalid_response", "GitHub returned invalid release assets.")
                matches = []
                for name in expected:
                    same_name = [asset for asset in assets if isinstance(asset, dict) and asset.get('name') == name]
                    if len(same_name) > 1:
                        raise UpdateError('invalid_response', 'The release contains ambiguous update packages.')
                    if same_name and not matches:
                        matches = same_name
                if matches:
                    candidates.append((parsed, release, matches[0]))
            if len(releases) < _PAGE_SIZE:
                break
        else:
            raise UpdateError("listing_limit", "There are too many releases to complete a reliable update check.")
        _cancelled(cancel)
        if not candidates:
            return CheckResult("no_compatible" if stable_found else "no_releases", "", None, _utc_now())
        parsed, release, asset = max(candidates, key=lambda candidate: candidate[0])
        digest = _DIGEST_RE.fullmatch(asset.get("digest", "")) if isinstance(asset.get("digest"), str) else None
        if (asset.get("state") != "uploaded" or not _positive_int(asset.get("id"))
                or not _positive_int(asset.get("size")) or asset["size"] > _MAX_PACKAGE_BYTES):
            raise UpdateError("invalid_asset", "The update package is incomplete or has invalid file metadata.")
        if digest is None:
            raise UpdateError("integrity_metadata", "This release has no valid GitHub SHA256 digest. The publisher must upload a verifiable update package.")
        version = ".".join(map(str, parsed))
        info = ReleaseInfo(version, release["tag_name"], str(release["published_at"]),
                           release.get("body") if isinstance(release.get("body"), str) else "",
                           f"{REPOSITORY_URL}/releases/tag/{release['tag_name']}",
                           asset["id"], asset["name"], asset["size"], digest.group(1).lower())
        return CheckResult("available" if parsed > installed else "current", "", info, _utc_now())

    def _download_response(self, asset_id, cancel):
        asset_path = f"{_REPO_PATH}/releases/assets/{asset_id}"
        url = _API_ROOT + asset_path
        for _ in range(6):
            _cancelled(cancel)
            parts = urlsplit(url)
            api_request = parts.hostname == "api.github.com" and parts.path == asset_path
            request = self._request(url, api_request=api_request, accept="application/octet-stream")
            response = self._open(request)
            status = self._status(response)
            if status == 200:
                return response
            if status not in (302, 303, 307, 308):
                try:
                    raise self._http_error(status, response.headers)
                finally:
                    response.close()
            location = response.headers.get("Location")
            response.close()
            if not isinstance(location, str) or not location:
                raise UpdateError("unsafe_redirect", "The update service returned an invalid redirect.")
            try:
                url = urljoin(url, location)
                # Validate before the next request, including the final redirect.
                next_parts = urlsplit(url)
                api_asset = next_parts.hostname == "api.github.com" and next_parts.path == asset_path
                self._request(url, api_request=api_asset, accept="application/octet-stream")
            except ValueError:
                raise UpdateError("unsafe_redirect", "The update service returned an invalid redirect.") from None
        raise UpdateError("redirect_limit", "The update download redirected too many times.")

    @staticmethod
    def _validate_release(release):
        if not isinstance(release, ReleaseInfo) or _version(release.version) is None:
            raise UpdateError("invalid_asset", "Select a valid update release first.")
        if release.version != ".".join(map(str, _version(release.version))) or _version(release.tag) != _version(release.version):
            raise UpdateError("invalid_asset", "The update package version does not match its release tag.")
        allowed_names = {template.format(version=release.version) for template in _PACKAGE_TEMPLATES.values()}
        allowed_names.add(_WINDOWS_PORTABLE.format(version=release.version))
        if (release.asset_name not in allowed_names or not _positive_int(release.asset_id)
                or not _positive_int(release.asset_size) or release.asset_size > _MAX_PACKAGE_BYTES
                or not isinstance(release.sha256, str) or not _HASH_RE.fullmatch(release.sha256)):
            raise UpdateError("invalid_asset", "The update package has invalid file or integrity metadata.")

    @staticmethod
    def _publish_file(temporary, directory, name):
        # An exclusive hard link publishes the verified file atomically on both
        # operating systems. Existing files are never replaced, even in a race.
        original = Path(name)
        for number in range(1, 10001):
            suffix = "" if number == 1 else f" ({number})"
            candidate = directory / f"{original.stem}{suffix}{original.suffix}"
            try:
                os.link(temporary, candidate)
                return candidate
            except FileExistsError:
                continue
            except OSError:
                # Windows rename is also exclusive and supports FAT/exFAT where
                # hard links are unavailable. POSIX rename would overwrite.
                if os.name == "nt":
                    try:
                        os.rename(temporary, candidate)
                        return candidate
                    except FileExistsError:
                        continue
                raise UpdateError("save_failed", "Cannot save this update atomically in the selected folder. Choose another writable local folder.") from None
        raise UpdateError("save_failed", "Too many files already use this update filename. Choose another folder.")

    def download(self, release, destination_directory, progress=None, cancel=None):
        self._validate_release(release)
        _cancelled(cancel)
        temporary = None
        response = None
        try:
            directory = Path(destination_directory).expanduser().resolve()
            directory.mkdir(parents=True, exist_ok=True)
            response = self._download_response(release.asset_id, cancel)
            length = response.headers.get("Content-Length")
            if length is not None:
                if not str(length).isdigit() or int(length) != release.asset_size:
                    raise UpdateError("size_mismatch", "The download size does not match the published update package.")
            encoding = response.headers.get("Content-Encoding", "identity")
            if encoding.lower() not in ("identity", ""):
                raise UpdateError("invalid_response", "The update package has an unsupported transfer encoding.")
            digest = hashlib.sha256()
            completed = 0
            with tempfile.NamedTemporaryFile(mode="wb", prefix=".optical-update-", suffix=".part", dir=directory, delete=False) as output:
                temporary = Path(output.name)
                if progress is not None:
                    progress(0, release.asset_size)
                while True:
                    _cancelled(cancel)
                    chunk = _read_available(response, min(_CHUNK_SIZE, release.asset_size - completed + 1))
                    if not chunk:
                        break
                    completed += len(chunk)
                    if completed > release.asset_size:
                        raise UpdateError("size_mismatch", "The download exceeds the published update package size.")
                    digest.update(chunk)
                    output.write(chunk)
                    if progress is not None:
                        progress(completed, release.asset_size)
                _cancelled(cancel)
                if completed != release.asset_size:
                    raise UpdateError("size_mismatch", "The update download was incomplete. Download it again.")
                if digest.hexdigest() != release.sha256:
                    raise UpdateError("hash_mismatch", "The downloaded update failed its SHA256 integrity check. The file was discarded.")
                output.flush()
                os.fsync(output.fileno())
            _cancelled(cancel)
            return self._publish_file(temporary, directory, release.asset_name)
        except UpdateError:
            raise
        except (OSError, ValueError, TypeError, HTTPException):
            raise UpdateError("download_failed", "The update could not be downloaded or saved. Check your connection, disk space, and destination folder.") from None
        finally:
            if response is not None:
                response.close()
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    # A locked temporary file can remain; it is never reported
                    # as a verified package or used to replace a user's file.
                    pass
