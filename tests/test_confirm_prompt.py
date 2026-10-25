"""Destructive confirmations must default to "no" (AUDIT.md H8).

``GrubWiz.really_wanna()`` guards restore, delete and commit.  Pressing Enter
on an empty, pre-seeded prompt must never confirm: only the whole word
``yes`` may proceed, so a stray keypress or a habitual "y" cannot restore a
backup, delete one, or rewrite the boot configuration.
"""

import grub_wiz.main as main_mod
from grub_wiz.main import GrubWiz


def _confirm(monkeypatch, reply):
    """Run really_wanna() against a fake window that returns ``reply``.

    Returns ``(result, kwargs_seen_by_answer)``.
    """
    monkeypatch.setattr(main_mod.cs, 'flushinp', lambda: None)
    seen = {}

    def fake_answer(**kwargs):
        seen.update(kwargs)
        return reply

    gw = main_mod.SimpleNamespace(
        win=main_mod.SimpleNamespace(passthrough_mode=True, answer=fake_answer)
    )
    return GrubWiz.really_wanna(gw, 'remove a backup'), seen


def test_prompt_seed_is_empty_so_enter_cancels(monkeypatch):
    """The prompt must not be pre-filled with a confirming answer."""
    _result, seen = _confirm(monkeypatch, '')

    assert seen['seed'] == '', 'a pre-seeded answer would let Enter confirm'
    assert seen['prompt'] == "Enter 'yes' to remove a backup"
    assert seen['height'] == 1


def test_abort_is_cancelled(monkeypatch):
    """Esc (``answer()`` returns None) must not confirm."""
    result, _seen = _confirm(monkeypatch, None)

    assert result is False


def test_bare_enter_is_cancelled(monkeypatch):
    """A bare Enter submits an empty string, which must be a refusal."""
    result, _seen = _confirm(monkeypatch, '')

    assert result is False


def test_prefixes_are_refused(monkeypatch):
    """Only the complete word ``yes`` may confirm; prefixes are typos."""
    for reply in ('y', 'ye', 'YEP', 'yeah', 'yess', 'yes!', 'affirmative'):
        result, _seen = _confirm(monkeypatch, reply)
        assert result is False, f'{reply!r} must not confirm'


def test_exact_yes_confirms(monkeypatch):
    """The explicit word ``yes`` still works, ignoring case and padding."""
    for reply in ('yes', 'YES', 'Yes', '  yes\n', '\tyes '):
        result, _seen = _confirm(monkeypatch, reply)
        assert result is True, f'{reply!r} must confirm'


def test_passthrough_mode_disengaged(monkeypatch):
    """Typed-ahead search keystrokes must not leak into the dialog."""
    monkeypatch.setattr(main_mod.cs, 'flushinp', lambda: None)
    win = main_mod.SimpleNamespace(passthrough_mode=True, answer=lambda **_k: '')
    gw = main_mod.SimpleNamespace(win=win)

    GrubWiz.really_wanna(gw, 'commit')

    assert win.passthrough_mode is False
