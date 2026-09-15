"""Release identity and installation metadata, independent of the project library."""
from datetime import datetime
import json
import platform
import struct

from desktop_runtime import application_root

APP_VERSION = '1.1.4'
BUILD_DATE = '2026-09-14'


def installation_info():
    """Use an installation receipt, never a guessed file or first-launch date."""
    machine = platform.machine().lower()
    bits = struct.calcsize('P') * 8
    architecture = ('arm64' if machine in {'arm64', 'aarch64'} and bits == 64 else
                    'x64' if machine in {'amd64', 'x86_64', 'x64'} and bits == 64 else
                    'x86' if bits == 32 else machine)
    system = platform.system()
    platform_id = f'{system.lower()}-{architecture}'
    updated_at = None
    receipt = application_root() / 'installation.json'
    try:
        if receipt.is_file() and receipt.stat().st_size <= 4096:
            data = json.loads(receipt.read_text(encoding='utf-8-sig'))
            if isinstance(data, dict) and data.get('version') == APP_VERSION:
                value = data.get('updated_at')
                if isinstance(value, str) and len(value) < 80:
                    updated_at = datetime.fromisoformat(value.replace('Z', '+00:00'))
                    if updated_at.tzinfo is not None:
                        updated_at = updated_at.astimezone()
    except (OSError, ValueError, TypeError):
        pass
    date = (f'{updated_at.strftime("%B")} {updated_at.day}, {updated_at.year}'
            if updated_at is not None else 'Not recorded')
    return dict(version=APP_VERSION, last_updated=date, platform=f'{system} · {bits}-bit',
                platform_id=platform_id, build_date=BUILD_DATE)
