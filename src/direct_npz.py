"""Write interleaved array blocks directly into one lossless ZIP64 NPZ.

Member shapes are known up front. Each member has a reserved byte range and
accepts blocks in row order, even when callers alternate between members.
CRCs are accumulated during writes, so finalization never rereads the payload.
Only the destination archive is staged; publication is an atomic rename.
"""
import io
import math
import os
from pathlib import Path
import struct
import tempfile
import zlib

import numpy as np


class DirectNPZWriter:
    def __init__(self, destination, specifications):
        self.destination = Path(destination)
        self.destination.parent.mkdir(parents=True, exist_ok=True)
        self.members = {}
        self.stream = None
        self.temporary = None
        self.finished = False
        self.sparse_enabled = False
        # Build headers before opening a file, so invalid declarations leave no
        # temporary output behind. Restrict names to simple NPZ array keys.
        offset = 0
        for name, (shape, dtype) in specifications.items():
            if not isinstance(name, str) or not name.isascii() or not name.isidentifier():
                raise ValueError('NPZ array names must be ASCII identifiers')
            shape = tuple(shape)
            if any(not isinstance(n, int) or isinstance(n, bool) or n < 0 for n in shape):
                raise ValueError('Invalid NPZ array shape')
            dtype = np.dtype(dtype)
            if dtype.hasobject or dtype.fields is not None:
                raise ValueError('Object and structured arrays are unsupported')
            header = io.BytesIO()
            np.lib.format.write_array_header_2_0(header, dict(
                descr=dtype.str, fortran_order=False, shape=shape))
            npy_header = header.getvalue()
            size = len(npy_header) + math.prod(shape) * dtype.itemsize
            filename = (name + '.npy').encode('ascii')
            extra = struct.pack('<HHQQ', 1, 16, size, size)
            # ZIP64 local header: stored, no data descriptor, fixed 1980-01-01.
            local = struct.pack('<IHHHHHIIIHH', 0x04034b50, 45, 0, 0, 0, 33,
                                0, 0xffffffff, 0xffffffff, len(filename), len(extra))
            local += filename + extra
            self.members[name] = dict(shape=shape, dtype=dtype, size=size,
                offset=offset, data_offset=offset+len(local), filename=filename,
                local=local, header=npy_header, written=0, crc=zlib.crc32(npy_header))
            offset += len(local) + size
        if not self.members:
            raise ValueError('An NPZ archive needs at least one array')
        self.central_offset = offset
        fd, self.temporary = tempfile.mkstemp(prefix='.fields-', suffix='.npz',
                                              dir=self.destination.parent)
        try:
            self.stream = os.fdopen(fd, 'w+b')
            # NTFS otherwise zero-fills the gaps as member headers are reserved.
            # Sparse reservation avoids that extra disk traffic. Every declared
            # payload byte must still be supplied before publication.
            if os.name == 'nt' and offset > 32 * 1024 * 1024:
                import ctypes
                from ctypes import wintypes
                import msvcrt
                control = ctypes.windll.kernel32.DeviceIoControl
                control.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p,
                    wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                    ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
                control.restype = wintypes.BOOL
                returned = wintypes.DWORD()
                self.sparse_enabled = bool(control(msvcrt.get_osfhandle(fd), 0x900c4,
                    None, 0, None, 0, ctypes.byref(returned), None))
            for member in self.members.values():
                self.stream.seek(member['offset'])
                self.stream.write(member['local'])
                self.stream.write(member['header'])
        except BaseException:
            self.abort()
            raise

    def append(self, name, block):
        if self.finished or self.stream is None:
            raise ValueError('NPZ writer is closed')
        member = self.members[name]
        block = np.asarray(block)
        if block.dtype != member['dtype']:
            raise ValueError(f'Wrong dtype for {name}')
        shape = member['shape']
        if shape and (block.ndim != len(shape) or block.shape[1:] != shape[1:]):
            raise ValueError(f'Wrong block shape for {name}')
        if not shape and block.shape != ():
            raise ValueError(f'Wrong scalar shape for {name}')
        if block.nbytes == 0:
            return
        payload = memoryview(np.ascontiguousarray(block)).cast('B')
        remaining = member['size'] - len(member['header']) - member['written']
        if len(payload) > remaining:
            raise ValueError(f'Too many values for {name}')
        self.stream.seek(member['data_offset'] + len(member['header']) + member['written'])
        self.stream.write(payload)
        member['crc'] = zlib.crc32(payload, member['crc'])
        member['written'] += len(payload)

    def finish(self):
        if self.finished or self.stream is None:
            raise ValueError('NPZ writer is closed')
        for name, member in self.members.items():
            if member['written'] != member['size'] - len(member['header']):
                raise ValueError(f'Incomplete NPZ array: {name}')
        stream = self.stream
        for member in self.members.values():
            stream.seek(member['offset'] + 14)
            stream.write(struct.pack('<I', member['crc']))
        stream.seek(self.central_offset)
        for member in self.members.values():
            extra = struct.pack('<HHQQQ', 1, 24, member['size'], member['size'], member['offset'])
            central = struct.pack('<IHHHHHHIIIHHHHHII', 0x02014b50, 45, 45,
                0, 0, 0, 33, member['crc'], 0xffffffff, 0xffffffff,
                len(member['filename']), len(extra), 0, 0, 0, 0, 0xffffffff)
            stream.write(central + member['filename'] + extra)
        end_offset = stream.tell()
        count = len(self.members)
        central_size = end_offset - self.central_offset
        stream.write(struct.pack('<IQHHIIQQQQ', 0x06064b50, 44, 45, 45, 0, 0,
                                 count, count, central_size, self.central_offset))
        stream.write(struct.pack('<IIQI', 0x07064b50, 0, end_offset, 1))
        stream.write(struct.pack('<IHHHHIIH', 0x06054b50, 0, 0,
                                 min(count, 65535), min(count, 65535),
                                 min(central_size, 0xffffffff),
                                 min(self.central_offset, 0xffffffff), 0))
        stream.truncate()
        stream.flush()
        os.fsync(stream.fileno())
        stream.close()
        self.stream = None
        os.replace(self.temporary, self.destination)
        self.temporary = None
        self.finished = True
        return self.destination

    def abort(self):
        if self.stream is not None:
            self.stream.close()
            self.stream = None
        if self.temporary is not None:
            Path(self.temporary).unlink(missing_ok=True)
            self.temporary = None

    def __enter__(self):
        return self

    def __exit__(self, kind, value, traceback):
        try:
            if kind is None and not self.finished:
                self.finish()
        finally:
            self.abort()
