import sqlite3
import datetime as dt
import dateutil.tz as dutz
from dateutil.relativedelta import *
import sys, typing
import csv
from collections import defaultdict

def group_by(iterable, f):
    results = defaultdict(list)
    for x in iterable:
        results[f(x)].append(x)
    return sorted(results.items())

def open_default_db():
    return Database('db.sqlite3')

def month_num_to_date(num, today):
    if num > 0:
        d = dt.date(today.year, num, 1)
    else:
        d = today.replace(day=1)
        d += relativedelta(months=num)
    return d

def week_num_to_date(num, today):
    if num > 0:
        d = dt.date(today.year, 1, 4)
        d += relativedelta(weekday=MO(-1), weeks=(num-1))
    else:
        d = today
        d += relativedelta(weekday=MO(-1), weeks=num)
    return d

_ENTRY_HEADER = 'Id,Start,End,Client,Project,Extra'.split(',')
_ENTRY_ALIGN  = 'right left left left left left'.split()

def print_entries(entries, file=sys.stderr):
    from tabulate import tabulate
    rows = [ [ e.id, e.start, e.end, e.client, e.project, e.extra ]
        for e in entries ]
    print(tabulate(rows, headers=_ENTRY_HEADER, colalign=_ENTRY_ALIGN))

_CSV_COLUMNS  = 'id client project start end extra'.split()

class Entry(typing.NamedTuple):
    client: str
    project: str
    start: dt.datetime
    end: dt.datetime
    extra: str = None
    id: int = None

    @classmethod
    def write_csv(cls, entries, file=sys.stdout):
        writer = csv.writer(file)
        writer.writerow(_CSV_COLUMNS)
        for e in entries:
            writer.writerow(e.to_row())

    def to_row(self):
        return [ self._asdict()[attr] for attr in _CSV_COLUMNS ]

class DayHours(typing.NamedTuple):
    client: str
    project: str
    date: dt.date
    hours: dt.timedelta

    @classmethod
    def from_entries(cls, entries):
        return dict([
            (d, [
                DayHours(c, p, d, sum(
                    [ e.end - e.start for e in proj_entries ],
                    dt.timedelta())
                )
                for (c, p), proj_entries in
                    group_by(date_entries, lambda e: (e.client, e.project))
            ])
            for d, date_entries in
                group_by(entries, lambda e: e.start.date())
        ])

class OverlappingEntryError(Exception):

    def __init__(self, new_entry, existing_entries):
        super().__init__('Overlapping entry')
        self.new_entry = new_entry
        self.existing_entries = existing_entries

    def is_duplicate(self):
        if len(self.existing_entries) != 1:
            return False
        e1 = self.new_entry
        e2 = self.existing_entries[0]
        return e1.start == e2.start and e1.end == e2.end

    def print_overlapping_entries(self, file=sys.stderr):
        rows = [self.new_entry] + self.existing_entries
        print_entries(rows, file=file)

class Database:

    _DB_VERSION = 1

    _PRAGMAS = '''
        pragma foreign_keys = on;
        pragma journal_mode = wal;
    '''

    _DDL = '''
        create table if not exists misc (
            key text primary key,
            n integer,
            s text,
            b blob
        );
        create table if not exists clients (
            id text primary key
        );
        create table if not exists projects (
            id text not null,
            client text not null references clients (id),
            primary key (id, client)
        );
        create table if not exists entries (
            id integer primary key,
            client text not null,
            project text not null,
            start text not null,
            end text not null check (end >= start),
            extra text,
            foreign key (project, client) references projects (id, client)
        );
    '''

    def __init__(self, db_path):
        self.db_path = db_path

    def __enter__(self):
        self.db = sqlite3.connect(self.db_path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(self._PRAGMAS)
        self.db.executescript(self._DDL)
        self.db.execute(
                "insert or ignore into misc (key, n) values ('version', ?)",
                [ self._DB_VERSION ])
        self.db.commit()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_val:
            self.db.rollback()
        else:
            self.db.commit()
        self.db.close()

    def _row_to_entry(self, row):
        return Entry(row['client'], row['project'],
                dt.datetime.fromisoformat(row['start']),
                dt.datetime.fromisoformat(row['end']),
                extra=row['extra'], id=row['id'])

    def _rows_to_entries(self, rows):
        return [ self._row_to_entry(r) for r in rows ]

    def get_entries_for_query(self, query, args=[]):
        return self._rows_to_entries(self.db.execute(query, args).fetchall())

    def get_entries(self, client=None, project=None, months=[], weeks=[]):
        conj_clauses = [['1=1']]
        args = []

        if client:
            conj_clauses += [['client like ?']]
            args += [client]
        if project:
            conj_clauses += [['project like ?']]
            args += [project]

        period_clauses = []
        for w in weeks:
            period_clauses += ["strftime('%Y %W', start) = ?"]
            args += [ w.strftime('%Y %V') ]
        for m in months:
            period_clauses += ["strftime('%Y %m', start) = ?"]
            args += [ m.strftime('%Y %m') ]
        if period_clauses:
            conj_clauses += [period_clauses]

        selection = ' and '.join(
                [ '(' + ' or '.join(disj) + ')' for disj in conj_clauses ])
        query = f'''
            select * from entries where {selection}
            order by start, client, project'''
        #print(query); print(args)
        return self.get_entries_for_query(query, args)

    def get_overlapping_entries(self, entry):
        return self.get_entries_for_query(
                '''select * from entries where
                   datetime(start) < datetime(?) and
                   datetime(end)   > datetime(?) and
                   client = ? and project = ?''',
                [ entry.end, entry.start, entry.client, entry.project ])

    def add_entry(self, entry, ignore_overlaps=False, add_project=False):
        if not ignore_overlaps:
            existing = self.get_overlapping_entries(entry)
            if existing:
                raise OverlappingEntryError(entry, existing)
        if add_project:
            self.db.execute(
                    'insert or ignore into clients (id) values (?)',
                    [entry.client])
            self.db.execute(
                    'insert or ignore into projects (id, client) values (?,?)',
                    [entry.project, entry.client])
        c = self.db.cursor()
        try:
            c.execute('''
                insert into entries (client, project, start, end, extra)
                values (:client, :project, :start, :end, :extra)''',
                entry._asdict())
            return entry._replace(id=c.lastrowid)
        finally:
            c.close()
