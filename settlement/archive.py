"""Persist and retrieve a day close without recomputing its counts."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from .receipt import DayClose
from .totals import DayTotals

if TYPE_CHECKING:
    from warehouse import Store


class DayArchive:
    def __init__(self, connection: sqlite3.Connection):
        self._connection = connection

    def initialize(self) -> None:
        self._connection.execute('''
            CREATE TABLE IF NOT EXISTS day_closes (
                close_id TEXT PRIMARY KEY NOT NULL,
                page_id TEXT NOT NULL REFERENCES review_pages (page_id),
                station TEXT NOT NULL REFERENCES stations (code),
                day_number TEXT NOT NULL,
                normal INTEGER NOT NULL CHECK (normal >= 0),
                exceeded INTEGER NOT NULL CHECK (exceeded >= 0),
                unruled INTEGER NOT NULL CHECK (unruled >= 0),
                missing INTEGER NOT NULL CHECK (missing >= 0)
            )
        ''')

    def find_day(self, close_id: str) -> DayClose | None:
        row = self._connection.execute('''
            SELECT page_id, station, day_number, normal, exceeded, unruled, missing
            FROM day_closes WHERE close_id = ?
        ''', (close_id,)).fetchone()
        if row is None:
            return None
        totals = DayTotals(row['normal'], row['exceeded'], row['unruled'], row['missing'])
        return DayClose(close_id, row['page_id'], row['station'], int(row['day_number'], 16), totals)

    def store_day(self, close: DayClose) -> None:
        totals = close.totals
        self._connection.execute('''
            INSERT INTO day_closes (close_id, page_id, station, day_number, normal, exceeded, unruled, missing)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (close.close_id, close.page_id, close.station, hex(close.day),
              totals.normal, totals.exceeded, totals.unruled, totals.missing))


def get_day(store: Store, close_id: str) -> DayClose:
    store.require_key(close_id, 'day close id')
    close = DayArchive(store.connection).find_day(close_id)
    if close is None:
        raise KeyError(f'unknown day close {close_id!r}')
    return close
