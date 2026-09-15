"""Create a separate local test copy without bundled optional native packs."""
import argparse
from pathlib import Path
import shutil


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('payload', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    source, destination = args.payload.resolve(), args.destination.resolve()
    if not (source/'Optical Design Studio.exe').is_file() or not (source/'_internal').is_dir():
        raise ValueError('Select the completed local Windows test build.')
    if destination.exists() or destination.is_relative_to(source):
        raise ValueError('Destination must be a new separate directory.')
    excluded = {'cad_runtime', 'cublas64_11.dll', 'cublasLt64_11.dll', 'cudart64_110.dll'}
    def ignore(directory, names):
        if Path(directory).resolve() == source/'_internal':
            return set(names) & excluded
        return {'User Data'} & set(names)
    shutil.copytree(source, destination, ignore=ignore)
    (destination/'ADDON-INSTALL-TEST.txt').write_text(
        'Separate add-on installation test copy.\n'
        'GPU and CAD native libraries were omitted from THIS COPY ONLY.\n'
        'Use Settings > Add-ons > Install to download verified GitHub packages.\n'
        'Installed add-ons are shared by application version; no existing add-ons\n'
        'or research files were removed to make this test copy.\n', encoding='utf-8')
    print(destination)


if __name__ == '__main__':
    main()
