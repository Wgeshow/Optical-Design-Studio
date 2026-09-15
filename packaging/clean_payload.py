"""Remove only this builder's previous generated payload before compiling."""
from pathlib import Path
import shutil
import stat

ROOT = Path(__file__).resolve().parent


def main():
    payload = ROOT / 'dist' / 'Optical Design Studio'
    if not payload.exists():
        return
    if payload.is_symlink() or payload.is_junction() or payload.resolve() != ROOT.resolve() / 'dist' / 'Optical Design Studio':
        raise ValueError('Generated payload must remain inside this packaging directory.')

    def remove_readonly(function, path, error):
        target = Path(path)
        if not isinstance(error, PermissionError) or not target.resolve().is_relative_to(payload.resolve()):
            raise error
        if not (target.stat().st_file_attributes & stat.FILE_ATTRIBUTE_READONLY):
            raise error
        target.chmod(stat.S_IWRITE | stat.S_IREAD)
        function(path)

    shutil.rmtree(payload, onexc=remove_readonly)


if __name__ == '__main__':
    main()
