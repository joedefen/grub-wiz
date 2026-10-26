#!/usr/bin/env python3
"""Build an automatic backup tag from a set of parameter differences.

The tag is a hint, not a record: the timestamp in the filename is what a
restore is chosen by.  A tag is therefore only produced where the parameter
diff is actually known (the REVIEW screen, at commit time); everywhere else
the snapshot is untagged.

Shape: ``{type}{param}[+{cnt}]`` where

* ``type`` is ``+`` (something was added), ``-`` (something was removed) or
  ``~`` (only values changed).  Priority follows that order, so a commit that
  both adds and modifies is labelled by its addition.
* ``param`` is the first parameter of the winning category, in the order the
  parameters are presented.  The leading ``GRUB_`` is dropped, the rest is
  split on ``_`` and each chunk is truncated and CamelCased, to at most 12
  characters: ``DISABLE_SUBMENU`` becomes ``DisablSubmen``.
* ``cnt`` is the number of parameters touched minus one, omitted at one, so
  ``~Timeout+2`` means three parameters changed.

``COMMENT`` and ``ABSENT`` both mean "not in effect".  Deleting a line and
commenting it out are therefore the same removal, and un-commenting a
parameter is an addition.
"""
# pylint: disable=invalid-name
try:
    from .GrubFile import GrubFile
except ImportError:
    from GrubFile import GrubFile

ADDED = '+'
REMOVED = '-'
CHANGED = '~'

#: Priority order: an addition outranks a removal, which outranks a change.
PRIORITY = (ADDED, REMOVED, CHANGED)

#: Longest abbreviation kept in a filename.
MAX_PARAM_LEN = 12

#: Prefix stripped before abbreviating; only this one, so a vendor prefix
#: stays visible.
_PREFIX = 'GRUB_'

#: Chunk widths by number of meaningful words.  Six or more words use the
#: six-word row and drop the rest.
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
    for chunk, width in zip(chunks, _WIDTHS[len(chunks)]):
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

    *diffs* maps a parameter name to ``(old_value, new_value)`` in the order
    the parameters are presented, so the chosen parameter is the first of its
    category as the user sees them.
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
