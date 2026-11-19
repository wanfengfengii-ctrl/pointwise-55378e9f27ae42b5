"""Apply an ordinary whole-schedule publication as one business write."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from stations.registry import StationRegistry

from .amendment import AmendmentArchive
from .catalog import ScheduleCatalog
from .intervals import ThresholdInterval
from .revisions import PublicationReceipt, build_revision, same_publication

if TYPE_CHECKING:
    from warehouse import Store


def publish_schedule(store: Store, publication_id: str, station: str,
                     intervals: Iterable[ThresholdInterval]) -> PublicationReceipt:
    store.require_key(publication_id, 'publication id')
    requested = build_revision(publication_id, station, intervals)
    catalog = ScheduleCatalog(store.connection)
    with store.write():
        StationRegistry(store).get_station(station)
        if AmendmentArchive(store.connection).occupies(publication_id):
            raise ValueError(f'publication {publication_id!r} already names a review amendment')
        original = catalog.find_revision(publication_id)
        if original is not None:
            if not same_publication(original, requested):
                raise ValueError(f'publication {publication_id!r} already has different content')
            head = catalog.get_head(station)
            if head is None:
                raise RuntimeError(f'published station {station!r} has no current head')
            return PublicationReceipt(original, head)
        catalog.store_revision(requested)
        catalog.move_head(station, publication_id)
        return PublicationReceipt(requested, publication_id)
