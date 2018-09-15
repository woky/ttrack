import sqlite3
import datetime as dt
import dateutil.tz as dutz
import sys, typing
import csv
from tabulate import tabulate

def open_default_db():
    return Database('db.sqlite3')

_ENTRY_SHOW_FIELDS  = 'id client project start end extra'.split()
_ENTRY_SHOW_HEADERS = [ s.capitalize() for s in _ENTRY_SHOW_FIELDS ]

def print_entries(entries, file=sys.stdout):
    def entry_to_row(e):
        d = dict(e._asdict())
        d['start'] = e.start.astimezone().replace(tzinfo=None)
        d['end'] = e.end.astimezone().replace(tzinfo=None)
        return [ d[attr] for attr in _ENTRY_SHOW_FIELDS ]
    rows = [ entry_to_row(e) for e in entries ]
    print(tabulate(rows, headers=_ENTRY_SHOW_HEADERS), file=file)

def print_entries_csv(entries, file=sys.stdout):
    writer = csv.writer(file)
    writer.writerow(_ENTRY_SHOW_FIELDS)
    for e in entries:
        writer.writerow(e.to_row())

class Entry(typing.NamedTuple):

    client: str
    project: str
    start: dt.datetime
    end: dt.datetime
    extra: str = None
    id: int = None

    def to_row(self):
        return [ self._asdict()[attr] for attr in _ENTRY_SHOW_FIELDS ]

class OverlappingEntriesError(Exception):

    def __init__(self, new_entry, existing):
        super().__init__('Overlapping entries')
        self.new_entry = new_entry
        self.existing = existing

    def print_error(self, file=sys.stderr):
        print('ERROR: New entry overlaps with existing entries.', file=file)
        print('New entry:', file=file)
        print_entries([self.new_entry])
        print('Existing entries:', file=file)
        print_entries(self.existing)

class Database:

    _DB_VERSION = 1

    def __init__(self, db_path):
        self.db_path = db_path

    def __enter__(self):
        self.db = sqlite3.connect(self.db_path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            create table if not exists misc (
                key text primary key,
                n integer,
                s text,
                b blob
            );
            create table if not exists entries (
                id integer primary key,
                client text not null,
                project text not null,
                start text not null,
                end text not null check (end >= start),
                extra text
            );
        ''')
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

    def _select_entries(self, query, args = []):
        return self._rows_to_entries(self.db.execute(query, args).fetchall())

    def get_entries(self, select=None, order=None, limit=None, query=None,
            reverse=False):
        if not query:
            query = 'select * from entries'
            if select:
                query += ' where ' + select
            if order:
                query += ' order by ' + order
            else:
                query += ' order by start'
                if reverse:
                    query += ' desc'
            if limit:
                query += ' limit ' + limit
        #print(query)
        return self._select_entries(query)

    def get_overlapping_entries(self, start, end):
        return self._select_entries(
                '''select * from entries where
                   datetime(start) < datetime(?) and
                   datetime(end)   > datetime(?)''',
                [ end, start ])

    def add_entry(self, entry):
        existing = self.get_overlapping_entries(entry.start, entry.end)
        if existing:
            raise OverlappingEntriesError(entry, existing)
        self.db.execute(
                '''insert into entries (client, project, start, end, extra)
                   values (:client, :project, :start, :end, :extra)''',
                entry._asdict())
