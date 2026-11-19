"""Business fixtures for the threshold amendment handoff."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory

import check_project
from tests import CommitFault
from warehouse import ObservationInput, ThresholdInterval, Warehouse

STATION = "cape"


def seed(db):
    db.register_station(STATION, "mV", -50, 50)
    db.publish_schedule("A", STATION, [ThresholdInterval(0, 10, 10)])
    db.ingest_batch("raw", STATION, "mV", [ObservationInput(h, 11) for h in (1, 3, 4, 8)])
    old_page = db.issue_rows("plain", STATION, db.latest_cutoff(), "A", 0, 24)
    old_day = db.close_day("original-day", old_page.page_id)
    assert asdict(old_day.totals) == {"normal": 0, "exceeded": 4, "unruled": 0, "missing": 0}
    return old_page, old_day


def rule_value(db, revision, hour):
    rule = db.threshold_at(STATION, revision, hour)
    if rule is None:
        return None
    return (rule.interval.threshold, rule.source.publication_id, rule.source.position)


def coverage_by_hour(page):
    cursor = page.binding.start
    values = {}
    for start, end, threshold, source in page.coverage:
        assert start == cursor and start < end <= page.binding.end
        assert (threshold is None) == (source is None)
        value = None if source is None else (threshold, source.publication_id, source.position)
        values.update((hour, value) for hour in range(start, end))
        cursor = end
    assert cursor == page.binding.end
    return values


def reject(error_type, call, *args):
    try:
        call(*args)
    except error_type as error:
        return error
    raise AssertionError(f"{call.__name__} unexpectedly accepted {args!r}")


def check_stale(db, request, page_id, edits, expected_hour):
    head = db.get_head(STATION)
    error = reject(ValueError, db.amend_review, request, page_id, edits)
    assert error.conflict_hour == expected_hour
    reject(KeyError, db.get_revision, STATION, request)
    assert db.get_head(STATION) == head
    return error.conflict_hour


def baseline(path):
    with Warehouse(path) as db:
        original_page, original_day = seed(db)
        assert [row.observation.hour for row in original_page.rows] == [1, 3, 4, 8]
        assert rule_value(db, "A", 5) == (10, "A", 0)
        db.publish_schedule("whole", STATION, [ThresholdInterval(0, 10, 10)])
    with Warehouse(path) as db:
        assert rule_value(db, "whole", 2) == (10, "whole", 0)
        assert rule_value(db, "A", 2) == (10, "A", 0)
        assert db.get_review("plain") == original_page
        assert db.get_day("original-day") == original_day
    return {"no_sample_hour": 5, "whole_replacement_at_2": [10, "whole", 0],
            "original_day": asdict(original_day.totals)}


def joint(path):
    fault = CommitFault()
    edits_b = [(2, 8, 12), (10, 11, 7)]
    with Warehouse(path, before_commit=fault) as db:
        old_page, old_day = seed(db)
        a = db.issue_review("a", STATION, "A", 0, 10)
        assert a.rows == old_page.rows
        assert coverage_by_hour(a) == dict.fromkeys(range(10), (10, "A", 0))
        reject(ValueError, db.amend_review, "v1-denied", "plain", [(5, 6, 10)])
        assert db.get_head(STATION) == "A"
        db.amend_review("W", "a", [(5, 6, 10)])
        same_value = check_stale(db, "stale", "a", [(2, 8, 12)], 5)
        w = db.issue_review("w", STATION, "W", 0, 12)
        expected_w = dict.fromkeys(range(10), (10, "A", 0))
        expected_w.update({5: (10, "W", 0), 10: None, 11: None})
        assert coverage_by_hour(w) == expected_w
        fault.arm()
        reject(sqlite3.DatabaseError, db.amend_review, "B", "w", edits_b)
        assert fault.denials == 1

    with Warehouse(path) as db:
        assert db.get_head(STATION) == "W"
        assert coverage_by_hour(db.get_review("w")) == expected_w
        assert {h: rule_value(db, "W", h) for h in expected_w} == expected_w
        reject(KeyError, db.get_revision, STATION, "B")
        b_receipt = db.amend_review("B", "w", edits_b)
        assert b_receipt.revision.publication_id == b_receipt.current_head == "B"
        filled_gap = check_stale(db, "gap-stale", "w", [(10, 11, 9)], 10)
        b = db.issue_review("b", STATION, "B", 0, 10)
        db.amend_review("C", "b", [(4, 5, None)])
        expected_c = dict.fromkeys(range(10), (10, "A", 0))
        expected_c.update(dict.fromkeys(range(2, 8), (12, "B", 0)))
        expected_c.update({4: None, 10: (7, "B", 1), 11: None})
        db.ingest_batch("late", STATION, "mV", [ObservationInput(5, 11)])
        assert db.issue_review("a", STATION, "A", 0, 10) == a
        current = db.issue_rows("checked", STATION, db.latest_cutoff(), "C", 0, 24)
        assert [row.classification.value for row in current.rows] == ["exceeded", "normal", "unruled", "normal", "exceeded"]
        day = db.close_day("checked-day", "checked")
        assert asdict(day.totals) == {"normal": 2, "exceeded": 2, "unruled": 1, "missing": 0}
        db.amend_review("D", "a", [(8, 9, 11)])
        assert rule_value(db, "D", 8) == (11, "D", 0)
        db.publish_schedule("R", STATION, [ThresholdInterval(0, 12, 10)])
        whole = check_stale(db, "whole-stale", "a", [(2, 8, 12)], 2)

    with Warehouse(path) as db:
        assert db.get_head(STATION) == "R"
        assert rule_value(db, "R", 4) == (10, "R", 0)
        assert {h: rule_value(db, "C", h) for h in expected_c} == expected_c
        assert db.get_review("a") == a and db.get_review("plain") == old_page
        assert db.get_day("original-day") == old_day and db.get_day("checked-day") == day
        assert db.amend_review("B", "w", edits_b) == b_receipt
        reject(ValueError, db.amend_review, "B", "w", [(2, 8, 13)])
        reject(ValueError, db.publish_schedule, "B", STATION, [])
        assert db.get_head(STATION) == "R"
    return {"same_value_conflict_hour": same_value, "filled_gap_conflict_hour": filled_gap,
            "whole_replacement_conflict_hour": whole, "day_revision": "C",
            "reopened_day": asdict(day.totals), "current_head": "R"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("baseline", "verify", "demo"))
    mode = parser.parse_args().mode
    if mode == "verify":
        status = check_project.main()
        if status:
            return status
    if mode == "demo":
        subprocess.run([sys.executable, "-B", "warehouse.py", "demo"], check=True)
    with TemporaryDirectory(prefix="rivercape-amendment-") as directory:
        run = baseline if mode == "baseline" else joint
        result = run(Path(directory) / "warehouse.sqlite")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
