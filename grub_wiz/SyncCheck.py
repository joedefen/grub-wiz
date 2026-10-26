#!/usr/bin/env python3
"""Detect when the generated GRUB menu does not reflect /etc/default/grub.

``/etc/default/grub`` is an input file: the distro's scripts source it and
``update-grub`` (``grub-mkconfig``) turns it into ``grub.cfg``, which is what
the bootloader actually reads.  The two are in sync only while ``grub.cfg``
was generated after the defaults file last changed.

The comparison is asymmetric on purpose:

* Defaults newer than ``grub.cfg``: nothing has regenerated the menu since the
  file was written.  This covers hand edits and restores (restoring a backup
  deliberately does not run update-grub), so it is a real pending-change
  state and the caller may block on it.
* ``grub.cfg`` newer than defaults: normally a kernel or GRUB package update
  regenerating the menu without touching the defaults file.  Timestamps
  cannot distinguish that from a defaults file that was replaced from a
  backup, so only a large gap is reported, and only as a note.

Timestamps are a heuristic, not proof.  File times can be preserved by
``cp -p``, ``tar`` or a restored config directory, and a clock change can
reorder them.  This module only reads metadata; it never opens either file.
"""
# pylint: disable=invalid-name

import os
import time
from types import SimpleNamespace
from typing import Callable, List, Optional

#: A generated config this much newer than the defaults file is reported as a
#: note.  Below it the difference is normal update noise.
DEFAULT_GENERATED_NEWER_HOURS = 4.0

#: A defaults file is not called "newer" for sub-second differences: a write
#: and the update that follows it can land in the same timestamp tick.
DEFAULT_GRACE_SECONDS = 1.0

STATUS_IN_SYNC = 'in_sync'
STATUS_CONFIG_NEWER = 'config_newer'
STATUS_GENERATED_NEWER = 'generated_newer'


def human_seconds(seconds: float) -> str:
    """Render a duration (absolute value) as a compact human string."""
    seconds = int(round(abs(seconds)))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    mins, secs = divmod(rem, 60)
    if days and not hours:
        return f'{days}d'
    if days:
        return f'{days}d {hours}h'
    if hours and not mins:
        return f'{hours}h'
    if hours:
        return f'{hours}h {mins}m'
    if mins and secs:
        return f'{mins}m {secs}s'
    if mins:
        return f'{mins}m'
    return f'{secs}s'


def _mtime(path) -> Optional[float]:
    """Return *path*'s mtime, or None when it cannot be stat'ed."""
    if path is None:
        return None
    try:
        return os.stat(str(path)).st_mtime
    except OSError:
        return None


def _stamp(mtime: float) -> str:
    return time.strftime('%Y-%m-%d %H:%M:%S %Z', time.localtime(mtime))


def compare_mtimes(config_path, generated_path,
                   generated_newer_hours: float = DEFAULT_GENERATED_NEWER_HOURS,
                   grace_seconds: float = DEFAULT_GRACE_SECONDS):
    """Compare the defaults file with the generated config.

    Returns None when either file is missing or unreadable: the check cannot
    say anything then, and a missing ``grub.cfg`` is already reported by
    ``DistroVars`` as crippled mode.  Otherwise returns a record with:

        config_path, generated_path  display strings
        config_mtime, generated_mtime  float seconds
        delta_seconds  config minus generated (positive = config newer)
        state          STATUS_* constant
        blocking       True only for STATUS_CONFIG_NEWER
    """
    config_mtime = _mtime(config_path)
    generated_mtime = _mtime(generated_path)
    if config_mtime is None or generated_mtime is None:
        return None

    delta = config_mtime - generated_mtime
    if delta > grace_seconds:
        state = STATUS_CONFIG_NEWER
    elif delta < 0 and -delta >= generated_newer_hours * 3600:
        state = STATUS_GENERATED_NEWER
    else:
        state = STATUS_IN_SYNC

    return SimpleNamespace(
        config_path=str(config_path),
        generated_path=str(generated_path),
        config_mtime=config_mtime,
        generated_mtime=generated_mtime,
        delta_seconds=delta,
        state=state,
        blocking=state == STATUS_CONFIG_NEWER,
    )


def report_lines(status) -> List[str]:
    """Return the printable status block for a non-IN_SYNC result."""
    lines = [
        'grub-wiz: config/menu sync check',
        f'  config:    {status.config_path}  ({_stamp(status.config_mtime)})',
        f'  generated: {status.generated_path}  ({_stamp(status.generated_mtime)})',
    ]
    if status.state == STATUS_CONFIG_NEWER:
        lines += [
            f'  >> the config is {human_seconds(status.delta_seconds)} newer than '
            'the generated menu.',
            '     The menu does not reflect it yet: update-grub has not run since',
            '     the config changed (restoring a backup does not regenerate it).',
        ]
    else:
        lines += [
            '  >> note: the generated menu is '
            f'{human_seconds(-status.delta_seconds)} newer than the config.',
            '     This is normal after a kernel or GRUB package update.  If the',
            '     config was replaced from a backup (old timestamp preserved), the',
            '     menu may not match it.',
        ]
    return lines


def _ask(prompt: str) -> str:
    """``input()`` that survives a closed or non-interactive stdin.

    EOF is treated as an empty answer, which the callers map to "continue":
    this check must never abort a run just because stdin went away.
    """
    try:
        return input(prompt)
    except EOFError:
        return ''


def run_sync_check(config_path, generated_path,
                   generated_newer_hours: float = DEFAULT_GENERATED_NEWER_HOURS,
                   grace_seconds: float = DEFAULT_GRACE_SECONDS,
                   ask: Optional[Callable[[str], str]] = None,
                   out: Optional[Callable[[str], None]] = None) -> bool:
    """Print the status and decide whether the caller should continue.

    Returns True when the run may continue and False only when the defaults
    file is newer and the user answers ``n``/``no`` (anything else, including
    Enter and EOF, continues).  A generated config that is much newer is
    reported as a note and does not gate: it is the normal result of an
    unrelated kernel or GRUB package update.

    ``ask`` and ``out`` are injectable for tests; by default they use the
    built-in ``input()`` and ``print()``.
    """
    ask = ask or _ask
    out = out or print

    status = compare_mtimes(config_path, generated_path,
                            generated_newer_hours=generated_newer_hours,
                            grace_seconds=grace_seconds)
    if status is None or status.state == STATUS_IN_SYNC:
        return True

    for line in report_lines(status):
        out(line)

    if status.state == STATUS_CONFIG_NEWER:
        answer = ask('Continue? [Y/n]: ')
        return answer.strip().lower() not in ('n', 'no')

    # The TUI clears the screen as soon as it starts, so a bare print would
    # scroll away unread.  This is an acknowledgement, not a decision.
    ask('Press ENTER to continue: ')
    return True
