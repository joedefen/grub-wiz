#!/usr/bin/env python3
"""Build an automatic backup tag from a set of parameter differences."""
try:
    from .GrubFile import GrubFile
except ImportError:
    from GrubFile import GrubFile

ADDED = '+'
REMOVED = '-'
CHANGED = '~'

PRIORITY = (ADDED, REMOVED, CHANGED)
MAX_PARAM_LEN = 12
_PREFIX = 'GRUB_'
_WIDTHS = {
    1: (12,),
    2: (6, 6),
    3: (4, 4, 4),
    4: (3, 3, 3, 3),
    5: (3, 3, 2, 2, 2),
    6: (2, 2, 2, 2, 2, 2),
}


def words_of(param_name: str) -> list:
    """Split a parameter name into the chunks used for abbreviation."""
    name = param_name[len(_PREFIX):] if param_name.startswith(_PREFIX) else param_name
    return [chunk for chunk in name.split('_') if chunk]


def abbreviate(param_name: str) -> str:
    """Return the <=12 character CamelCase abbreviation of *param_name*."""
    chunks = words_of(param_name)[:6]
    if not chunks:
        return ''
    parts = []
    for chunk, width in zip(chunks, _WIDTHS[len(chunks)], strict=False):
        part = chunk[:width]
        parts.append(part[:1].upper() + part[1:].lower())
    return ''.join(parts)[:MAX_PARAM_LEN]


def _is_active(value) -> bool:
    """True when *value* is a parameter that is in effect in the file."""
    return value is not None and value not in (GrubFile.COMMENT, GrubFile.ABSENT)


def classify(old_value, new_value):
    """Return ``ADDED``/``REMOVED``/``CHANGED`` for a pair, or ``None``."""
    was = _is_active(old_value)
    now = _is_active(new_value)
    if now and not was:
        return ADDED
    if was and not now:
        return REMOVED
    if was and now and str(old_value) != str(new_value):
        return CHANGED
    return None


def change_tag(diffs):
    """Return the automatic tag for *diffs*, or ``None`` when unknowable.

    *diffs* maps a parameter name to ``(old_value, new_value)``
    in the order the parameters are presented,
    so the chosen parameter is the first of its category as the user sees them.
    """
    if not diffs:
        return None

    buckets = {ADDED: [], REMOVED: [], CHANGED: []}
    for param_name, pair in diffs.items():
        old_value, new_value = pair
        kind = classify(old_value, new_value)
        if kind is not None:
            buckets[kind].append(param_name)

    total = sum(len(names) for names in buckets.values())
    if not total:
        return None

    kind = next(candidate for candidate in PRIORITY if buckets[candidate])
    param = abbreviate(buckets[kind][0]) or 'Unknown'
    count = f'+{total - 1}' if total > 1 else ''
    return f'{kind}{param}{count}'
