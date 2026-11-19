"""Select a half-open window from a fixed prefix of the instrument journal."""

from .journal import BatchJournal
from .records import Observation


def select_observations(journal: BatchJournal, station: str, cutoff: int,
                        start: int, end: int) -> tuple[Observation, ...]:
    if type(cutoff) is not int or cutoff < 0 or cutoff > journal.latest_cutoff():
        raise ValueError('cutoff must be 0 or an already admitted batch sequence')
    selected = (
        observation for observation in journal.iter_station_observations(station, cutoff)
        if start <= observation.hour < end
    )
    return tuple(sorted(selected, key=lambda observation: (
        observation.hour, observation.source.cutoff, observation.source.position
    )))
