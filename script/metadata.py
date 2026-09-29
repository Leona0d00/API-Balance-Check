"""Non-secret account labels stored separately from API credentials."""
import sqlite3
from contextlib import closing
from . import util


def _connect():
    util.CONFIG_ROOT.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(util.CONFIG_ROOT / 'metadata.sqlite3')
    db.execute('CREATE TABLE IF NOT EXISTS account (identifier TEXT PRIMARY KEY, note TEXT NOT NULL)')
    return db


def notes():
    with closing(_connect()) as db, db:
        return dict(db.execute('SELECT identifier, note FROM account'))


def set_note(identifier, note):
    util.find_api(identifier)
    with closing(_connect()) as db, db:
        db.execute('INSERT INTO account VALUES (?, ?) ON CONFLICT(identifier) DO UPDATE SET note=excluded.note', (identifier, note.strip()[:120]))


def delete_note(identifier):
    with closing(_connect()) as db, db:
        db.execute('DELETE FROM account WHERE identifier=?', (identifier,))
