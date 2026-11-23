#!/usr/bin/env python3
"""Detect when generated GRUB menu does not (likely) reflect /etc/default/grub."""

import os
import time
from collections.abc import Callable
from types import SimpleNamespace

DEFAULT_GENERATED_NEWER_HOURS = 4.0

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


def _mtime(path) -> float | None:
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

    Returns:
     * None when either file is missing or unreadable.
     * Otherwise returns a record with:
       * config_path, generated_path  display strings
       * config_mtime, generated_mtime  float seconds
       * delta_seconds  config minus generated (positive = config newer)
       * state          STATUS_* constant
       * blocking       True only for STATUS_CONFIG_NEWER
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


def report_lines(status) -> list[str]:
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
    """``input()`` that survives a closed or non-interactive stdin."""
    try:
        return input(prompt)
    except EOFError:
        return ''


def run_sync_check(config_path, generated_path,
                   generated_newer_hours: float = DEFAULT_GENERATED_NEWER_HOURS,
                   grace_seconds: float = DEFAULT_GRACE_SECONDS,
                   ask: Callable[[str], str] | None = None,
                   out: Callable[[str], None] | None = None) -> bool:
    """Print the status and decide whether the caller should continue.

    Returns: True when the run may continue and False only when the defaults
        file is newer and the user answers ``n``/``no`` (anything else,
        including Enter and EOF, continues).
        A generated config that is much newer is reported as a note and does not
        gate: it is the normal result of an unrelated kernel or GRUB package update.
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

    ask('Press ENTER to continue: ')
    return True
