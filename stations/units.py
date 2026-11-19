"""Canonical unit labels are stored and compared exactly."""


def validate_unit(unit: str) -> str:
    if not isinstance(unit, str) or not unit or unit != unit.strip() or '\x00' in unit:
        raise ValueError('unit must be a nonempty label without surrounding whitespace')
    return unit


def require_matching_unit(registered: str, submitted: str) -> None:
    validate_unit(submitted)
    if submitted != registered:
        raise ValueError(f'unit mismatch: station uses {registered!r}, batch uses {submitted!r}')
