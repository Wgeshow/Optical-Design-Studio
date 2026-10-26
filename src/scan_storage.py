"""Bounded-memory scan descriptions, ordered results, and field sample indexes."""
from collections.abc import Sequence
from contextlib import closing, nullcontext
import csv
import json
import math
from pathlib import Path
import sqlite3
import time
import uuid


class ScanPoints(Sequence):
    """Generate a regular scan on demand; slices allocate only their own batch."""
    def __init__(self, start, step, count, fixed, axis='wavelength'):
        if axis not in ('wavelength', 'angle') or count < 1:
            raise ValueError('Invalid regular scan')
        self.start, self.step, self.count, self.fixed, self.axis = start, step, count, fixed, axis

    def __len__(self):
        return self.count

    def __getitem__(self, index):
        if isinstance(index, slice):
            return [self[i] for i in range(*index.indices(self.count))]
        if index < 0:
            index += self.count
        if not 0 <= index < self.count:
            raise IndexError(index)
        value = self.start + index * self.step
        return [index, value, self.fixed] if self.axis == 'wavelength' else [index, self.fixed, value]

    def __deepcopy__(self, memo):
        return ScanPoints(self.start, self.step, self.count, self.fixed, self.axis)

    def as_json(self):
        return dict(_ods_scan_points=1, start=self.start, step=self.step, count=self.count, fixed=self.fixed, axis=self.axis)


def json_default(value):
    if isinstance(value, ScanPoints):
        return value.as_json()
    raise TypeError(f'{type(value).__name__} is not JSON serializable')


def json_object(value):
    if value.get('_ods_scan_points') == 1:
        return ScanPoints(value['start'], value['step'], value['count'], value['fixed'], value['axis'])
    return value


def read_connection(path):
    connection = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    connection.execute('PRAGMA cache_size=-2048')
    return connection


COLUMNS = ('wavelength_nm', 'angle_deg', 'R', 'T', 'A', 'R_plus_T_plus_A')


class SpectrumResults(Sequence):
    """Disk-backed, point-index-ordered rows. SQLite's integer key handles late batches."""
    def __init__(self, path, create=False):
        self.path = Path(path).resolve()
        self.connection = None
        if create:
            self.connection = sqlite3.connect(self.path)
            self.connection.execute('PRAGMA cache_size=-2048')
            self.connection.execute('PRAGMA journal_mode=DELETE')
            self.connection.execute('CREATE TABLE results (id INTEGER PRIMARY KEY, wave REAL, theta REAL, r REAL, t REAL, a REAL, rp REAL, tp REAL)')
            self.connection.execute('CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT)')
            self.connection.execute('CREATE TABLE preview (id INTEGER PRIMARY KEY)')
            self.connection.execute('CREATE TABLE failures (id INTEGER PRIMARY KEY, wave REAL, theta REAL, reason TEXT)')
            self.connection.commit()
        self._count = 0 if create else None
        self._mapped = False
        if not create:
            with closing(read_connection(self.path)) as connection:
                saved = connection.execute("SELECT value FROM metadata WHERE key='mapped_positions'").fetchone()
                self._mapped = bool(saved and saved[0] == '1')
        self._pending=0
        self._last_commit=time.monotonic()

    def _position_source(self):
        return ('results r JOIN positions p ON r.id=p.id', 'p.ordinal') if self._mapped else ('results r', 'r.id')

    def _finalize_positions(self):
        """Keep original scan ids while making interrupted results a sequence.

        A canceled parallel scan may contain only ids 0, 3 and 4. Store the
        positional mapping on disk; complete scans retain their direct key lookup.
        """
        count, minimum, maximum = self.connection.execute('SELECT COUNT(*),MIN(id),MAX(id) FROM results').fetchone()
        self._count = count
        self._mapped = bool(count and (minimum != 0 or maximum != count-1))
        self.connection.execute('DROP TABLE IF EXISTS positions')
        if self._mapped:
            self.connection.execute('CREATE TABLE positions (ordinal INTEGER PRIMARY KEY, id INTEGER UNIQUE NOT NULL)')
            self.connection.execute('INSERT INTO positions SELECT ROW_NUMBER() OVER (ORDER BY id)-1,id FROM results ORDER BY id')
        self.connection.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)', ('mapped_positions', '1' if self._mapped else '0'))

    def position_for_id(self, point_index):
        """Find the selector position for an original saved scan point id."""
        if not self._mapped:
            return int(point_index)
        with closing(read_connection(self.path)) as connection:
            row = connection.execute('SELECT ordinal FROM positions WHERE id=?', (point_index,)).fetchone()
        if row is None:
            raise IndexError(point_index)
        return row[0]

    def add_batch(self, rows, phases=()):
        phase_values = {r[0]: r[3:5] for r in phases}
        self.connection.executemany('INSERT INTO results VALUES (?,?,?,?,?,?,?,?)',
            (tuple(row) + tuple(phase_values.get(row[0], (None, None))) for row in rows))
        self._count += len(rows)
        self._pending+=len(rows)
        if self._pending>=1024 or time.monotonic()-self._last_commit>=1.:self.flush()

    def flush(self):
        if self.connection is not None:
            self.connection.commit();self._pending=0;self._last_commit=time.monotonic()

    def add_failures(self, failures):
        self.connection.executemany('INSERT INTO failures VALUES (?,?,?,?)',
            ((f['point_index'],f['wavelength_nm'],f['angle_deg'],f['reason']) for f in failures))

    def export_failures(self, path):
        self.flush()
        count=self.connection.execute('SELECT COUNT(*) FROM failures').fetchone()[0]
        if not count:return
        with Path(path).open('w',newline='',encoding='utf-8') as stream:
            writer=csv.writer(stream);writer.writerow(('point_index','wavelength_nm','angle_deg','reason'))
            writer.writerows(self.connection.execute('SELECT id,wave,theta,reason FROM failures ORDER BY id'))

    def __len__(self):
        if self._count is None:
            with closing(read_connection(self.path)) as connection:
                saved=connection.execute("SELECT value FROM metadata WHERE key='count'").fetchone()
                self._count = int(saved[0]) if saved else connection.execute('SELECT COUNT(*) FROM results').fetchone()[0]
        return self._count

    def __iter__(self):
        self.flush()
        with closing(read_connection(self.path)) as connection:
            for row in connection.execute('SELECT id,wave,theta,r,t,a FROM results ORDER BY id'):
                yield list(row)

    def __getitem__(self, index):
        self.flush()
        if isinstance(index, slice):
            return [self[i] for i in range(*index.indices(len(self)))]
        if index < 0:
            index += len(self)
        if not 0 <= index < len(self):
            raise IndexError(index)
        source, position = self._position_source()
        with closing(read_connection(self.path)) as connection:
            row = connection.execute(f'SELECT r.id,wave,theta,r,t,a FROM {source} WHERE {position}=?', (index,)).fetchone()
        if row is None:
            raise IndexError(index)
        return list(row)

    def phase_rows(self):
        self.flush()
        with closing(read_connection(self.path)) as connection:
            yield from connection.execute('SELECT id,wave,theta,rp,tp FROM results ORDER BY id')

    def export_csv(self, path=None, bins=2000):
        """One linear pass exports all rows and records extrema-preserving plot bins."""
        self._finalize_positions()
        count = len(self)
        width = max(1, math.ceil(count / bins))
        peaks, minima, selected, bucket, group = {}, {}, [], {}, -1
        with (Path(path).open('w', newline='', encoding='utf-8') if path is not None else nullcontext()) as stream:
            writer = csv.writer(stream) if stream is not None else None
            if writer is not None:writer.writerow(COLUMNS)
            for ordinal, row in enumerate(self):
                i, wave, theta, r, t, a = row
                finite=all(value is not None and math.isfinite(value) for value in row[1:])
                if writer is not None:writer.writerow((wave, theta, r, t, a, r+t+a if finite else None))
                for column, key in enumerate(('R', 'T', 'A'), 3):
                    if not finite:continue
                    if key not in peaks or row[column] > peaks[key][column]:
                        peaks[key] = row
                    if key not in minima or row[column] < minima[key][column]:
                        minima[key] = row
                if ordinal // width != group:
                    selected.extend({value[0] for value in bucket.values()})
                    bucket, group = {'first': row}, ordinal // width
                bucket['last'] = row
                if not finite:
                    # Preserve a gap and its neighbors even inside decimated
                    # plot bins; never draw a finite line across missing data.
                    selected.extend((row[0],))
                    previous=self.connection.execute('SELECT MAX(id) FROM results WHERE id<?',(row[0],)).fetchone()[0]
                    following=self.connection.execute('SELECT MIN(id) FROM results WHERE id>?',(row[0],)).fetchone()[0]
                    selected.extend(i for i in (previous,following) if i is not None)
                    continue
                for column in range(3, 6):
                    for name, less in (('min', True), ('max', False)):
                        key = (column, name)
                        if key not in bucket or bucket[key][column] is None or (row[column] < bucket[key][column] if less else row[column] > bucket[key][column]):
                            bucket[key] = row
            selected.extend({value[0] for value in bucket.values()})
        self.connection.execute('DELETE FROM preview')
        self.connection.executemany('INSERT OR IGNORE INTO preview VALUES (?)', ((i,) for i in selected))
        self.connection.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)', ('peaks', json.dumps(peaks)))
        self.connection.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)', ('minima', json.dumps(minima)))
        self.connection.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)', ('count', str(count)))
        self.connection.commit()

    def frame(self, preview=False, limit=10000):
        import pandas as pd
        source, position = self._position_source()
        if preview:
            source += ' JOIN preview v ON r.id=v.id'
        query = f'SELECT {position},wave,theta,r,t,a FROM {source} ORDER BY {position}' + ('' if preview else ' LIMIT ?')
        with closing(read_connection(self.path)) as connection:
            data = connection.execute(query, () if preview else (limit,)).fetchall()
        frame = pd.DataFrame(data, columns=('point_index', *COLUMNS[:5]))
        frame['R_plus_T_plus_A'] = frame[['R','T','A']].sum(axis=1,min_count=3)
        return frame

    def peak(self, key):
        with closing(read_connection(self.path)) as connection:
            value = connection.execute("SELECT value FROM metadata WHERE key='peaks'").fetchone()
        return json.loads(value[0]).get(key) if value else None

    def extremum(self, key, maximum=True):
        """Exact finite extrema, including old indexes; ties use scan order."""
        if key not in ('R', 'T', 'A'):raise ValueError('Choose R, T or A.')
        self.flush()
        column=key.lower();direction='DESC' if maximum else 'ASC'
        with closing(read_connection(self.path)) as connection:
            saved=connection.execute('SELECT value FROM metadata WHERE key=?',('peaks' if maximum else 'minima',)).fetchone()
            value=json.loads(saved[0]).get(key) if saved else None
            if value is not None and all(math.isfinite(item) for item in value[1:]):return value
            # NaNs are NULL in SQLite; infinities are excluded explicitly.
            finite=' AND '.join(f'{name} BETWEEN -1.7976931348623157e308 AND 1.7976931348623157e308' for name in ('wave','theta','r','t','a'))
            row=connection.execute(f'SELECT id,wave,theta,r,t,a FROM results WHERE {finite} AND wave>0 ORDER BY {column} {direction},id ASC LIMIT 1').fetchone()
        return list(row) if row is not None else None

    def _bound(self,value,axis,right=False):
        first,last=0,len(self)
        column=0 if axis=='wavelength_nm' else 1
        source, position = self._position_source()
        with closing(read_connection(self.path)) as connection:
            while first<last:
                middle=(first+last)//2
                row=connection.execute(f'SELECT wave,theta FROM {source} WHERE {position}=?',(middle,)).fetchone()
                if row[column]<value or right and row[column]==value:first=middle+1
                else:last=middle
        return first

    def nearest_index(self,value,axis='wavelength_nm'):
        if not len(self):return None
        position=self._bound(value,axis)
        if position==0:return 0
        if position==len(self):return position-1
        column=1 if axis=='wavelength_nm' else 2
        return position-1 if abs(self[position-1][column]-value)<=abs(self[position][column]-value) else position

    def view_frame(self,lo,hi,axis='wavelength_nm',limit=20000):
        """Zoom into exact rows without loading the rest of a monotone scan."""
        import pandas as pd
        count=len(self)
        start=max(0,self._bound(min(lo,hi),axis)-1);stop=min(count,self._bound(max(lo,hi),axis,True)+1)
        source, position = self._position_source()
        if stop-start > limit:
            source += ' JOIN preview v ON r.id=v.id'
        with closing(read_connection(self.path)) as connection:
            query=f'SELECT {position},wave,theta,r,t,a FROM {source} WHERE {position}>=? AND {position}<? ORDER BY {position}'
            rows=connection.execute(query,(start,stop)).fetchall()
        frame=pd.DataFrame(rows,columns=('point_index',*COLUMNS[:5]))
        frame['R_plus_T_plus_A']=frame[['R','T','A']].sum(axis=1,min_count=3)
        return frame

    def close(self):
        if self.connection is not None:
            self.flush()
            self.connection.close()
            self.connection = None


class FieldSampleIndex:
    def __init__(self, root, create=False):
        self.root = Path(root).resolve()
        self.path = self.root / 'samples.sqlite'
        self.connection = sqlite3.connect(self.path) if create else None
        if create:
            self.connection.execute('PRAGMA cache_size=-2048')
            self.connection.execute('CREATE TABLE samples (ordinal INTEGER PRIMARY KEY, point_index INTEGER, wave REAL, theta REAL, directory TEXT)')
            self.connection.commit()
        if create:self.count=0
        else:
            with closing(read_connection(self.path)) as connection:
                self.count=connection.execute('SELECT COALESCE(MAX(ordinal)+1,0) FROM samples').fetchone()[0]
        self._pending=0;self._last_commit=time.monotonic()

    def add(self, ordinal, index, wave, theta, directory):
        # Generated sample paths already descend from the resolved root. Avoid
        # filesystem canonicalization for every entry in a million-point scan.
        relative_path = Path(directory).absolute().relative_to(self.root)
        if '..' in relative_path.parts:raise ValueError('Field sample must stay inside its run')
        relative = relative_path.as_posix()
        self.connection.execute('INSERT INTO samples VALUES (?,?,?,?,?)', (ordinal, index, wave, theta, relative))
        self.count += 1
        self._pending+=1
        if self._pending>=128 or time.monotonic()-self._last_commit>=1.:self.flush()

    def flush(self):
        if self.connection is not None:
            self.connection.commit();self._pending=0;self._last_commit=time.monotonic()

    def __len__(self):
        return self.count

    def compact(self):
        """Retain every completed sample in scan order after interruption.

        Parallel workers can finish with gaps in the original ordinal sequence.
        Compact only at finalization so the saved selector remains contiguous.
        """
        maximum = self.connection.execute('SELECT COALESCE(MAX(ordinal)+1,0) FROM samples').fetchone()[0]
        if maximum != self.count:
            self.connection.execute('CREATE TEMP TABLE compact_samples AS SELECT ROW_NUMBER() OVER (ORDER BY ordinal)-1 AS ordinal, point_index, wave, theta, directory FROM samples')
            self.connection.execute('DELETE FROM samples')
            self.connection.execute('INSERT INTO samples SELECT * FROM compact_samples')
            self.connection.execute('DROP TABLE compact_samples')
        self.flush()

    def sample(self, ordinal):
        if self.connection is not None:
            row=self.connection.execute('SELECT point_index,wave,theta,directory FROM samples WHERE ordinal=?',(ordinal,)).fetchone()
        else:
            with closing(read_connection(self.path)) as connection:
                row=connection.execute('SELECT point_index,wave,theta,directory FROM samples WHERE ordinal=?',(ordinal,)).fetchone()
        if row is None:
            raise IndexError(ordinal)
        return dict(point_index=row[0], wavelength_nm=row[1], angle_deg=row[2], directory=str(self.root / row[3]))

    def close(self):
        if self.connection is not None:
            self.flush();self.connection.close();self.connection=None


def legacy_spectrum_index(path,minimum_bytes=8*1024*1024):
    """Index a large legacy CSV once, without changing it or loading it into RAM."""
    path=Path(path)
    if not path.is_file() or path.stat().st_size<minimum_bytes:return None
    signature=f'{path.stat().st_mtime_ns}:{path.stat().st_size}'
    cache=path.parent/'spectrum-view.sqlite'
    if cache.is_file():
        with closing(read_connection(cache)) as connection:
            saved=connection.execute("SELECT value FROM metadata WHERE key='source_csv'").fetchone()
        if saved and saved[0]==signature:return SpectrumResults(cache)
    temporary=cache.with_name(cache.name+'.'+uuid.uuid4().hex+'.tmp')
    results=SpectrumResults(temporary,create=True)
    try:
        batch=[]
        with path.open(newline='',encoding='utf-8-sig') as stream:
            for i,row in enumerate(csv.DictReader(stream)):
                values=[float(row[key]) for key in COLUMNS[:5]]
                if not all(math.isfinite(value) for value in values):
                    raise ValueError('Legacy spectrum contains nonfinite data')
                batch.append([i,*values])
                if len(batch)==1024:results.add_batch(batch);batch=[]
        if batch:results.add_batch(batch)
        results.export_csv()
        if signature!=f'{path.stat().st_mtime_ns}:{path.stat().st_size}':
            raise ValueError('Spectrum changed while it was being indexed; load it again')
        results.connection.execute('INSERT INTO metadata VALUES (?,?)',('source_csv',signature))
        results.close()
        temporary.replace(cache)
        return SpectrumResults(cache)
    finally:
        results.close()
        temporary.unlink(missing_ok=True)
