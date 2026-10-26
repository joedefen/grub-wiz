"""Tests for the startup config/menu sync check.

The check compares the mtime of the defaults file (an input) with the
generated ``grub.cfg`` (the installed result).  It must block only when the
defaults file is newer, and treat a much-newer generated file as a note.
"""

import os

import pytest

import grub_wiz.SyncCheck as sync


def _pair(tmp_path, config_age, generated_age, base=1_800_000_000):
    """Create both files with mtimes *ages* seconds before *base*."""
    config = tmp_path / 'grub'
    generated = tmp_path / 'grub.cfg'
    config.write_text('GRUB_TIMEOUT=5\n', encoding='utf-8')
    generated.write_text('# generated\n', encoding='utf-8')
    os.utime(config, (base - config_age, base - config_age))
    os.utime(generated, (base - generated_age, base - generated_age))
    return config, generated


def test_small_difference_is_in_sync(tmp_path):
    """A generated file a few seconds newer is normal write/update noise."""
    config, generated = _pair(tmp_path, config_age=20, generated_age=10)

    status = sync.compare_mtimes(config, generated)

    assert status.state == sync.STATUS_IN_SYNC
    assert status.blocking is False


def test_config_newer_blocks(tmp_path):
    """Nothing regenerated the menu after the defaults file changed."""
    config, generated = _pair(tmp_path, config_age=0, generated_age=7200)

    status = sync.compare_mtimes(config, generated)

    assert status.state == sync.STATUS_CONFIG_NEWER
    assert status.blocking is True
    assert status.delta_seconds == pytest.approx(7200)


def test_config_newer_within_grace_does_not_block(tmp_path):
    """Sub-second skew from the same write/update sequence is tolerated."""
    config, generated = _pair(tmp_path, config_age=0, generated_age=0.5)

    assert sync.compare_mtimes(config, generated).state == sync.STATUS_IN_SYNC


def test_generated_newer_below_threshold_is_in_sync(tmp_path):
    config, generated = _pair(tmp_path, config_age=3 * 3600, generated_age=0)

    assert sync.compare_mtimes(config, generated).state == sync.STATUS_IN_SYNC


def test_generated_far_newer_is_a_note(tmp_path):
    """A large gap is reported, but it must not gate the run."""
    config, generated = _pair(tmp_path, config_age=5 * 3600, generated_age=0)

    status = sync.compare_mtimes(config, generated)

    assert status.state == sync.STATUS_GENERATED_NEWER
    assert status.blocking is False


def test_missing_generated_config_is_skipped(tmp_path):
    """Crippled mode has no grub.cfg to compare; DistroVars reports it."""
    config, _generated = _pair(tmp_path, config_age=0, generated_age=0)

    assert sync.compare_mtimes(config, tmp_path / 'missing.cfg') is None
    assert sync.compare_mtimes(config, None) is None


def test_missing_config_is_skipped(tmp_path):
    _, generated = _pair(tmp_path, config_age=0, generated_age=0)

    assert sync.compare_mtimes(tmp_path / 'missing', generated) is None


def test_in_sync_prints_nothing(tmp_path, capsys):
    config, generated = _pair(tmp_path, config_age=20, generated_age=10)

    assert sync.run_sync_check(config, generated) is True
    assert capsys.readouterr().out == ''


def test_config_newer_eof_continues(tmp_path, capsys):
    """EOF (no usable stdin) must not abort the run."""
    config, generated = _pair(tmp_path, config_age=0, generated_age=7200)

    def input_that_eofs(_prompt):
        raise EOFError

    original = input
    import builtins
    builtins.input = input_that_eofs
    try:
        # ask=None exercises the module's own EOF-safe prompt.
        assert sync.run_sync_check(config, generated) is True
    finally:
        builtins.input = original

    output = capsys.readouterr().out
    assert 'sync check' in output
    assert 'does not reflect it yet' in output


def test_config_newer_enter_continues(tmp_path, capsys):
    config, generated = _pair(tmp_path, config_age=0, generated_age=7200)
    prompts = []

    def ask(prompt):
        prompts.append(prompt)
        return ''

    assert sync.run_sync_check(config, generated, ask=ask) is True
    assert prompts == ['Continue? [Y/n]: ']
    assert 'sync check' in capsys.readouterr().out


@pytest.mark.parametrize('answer, expected', [('n', False), ('no', False),
                                              ('N', False), ('yes', True),
                                              ('y', True)])
def test_config_newer_answer_gates(tmp_path, answer, expected):
    config, generated = _pair(tmp_path, config_age=0, generated_age=7200)

    assert sync.run_sync_check(
        config, generated, ask=lambda _prompt: answer) is expected


def test_generated_newer_note_does_not_gate(tmp_path, capsys):
    """Only one acknowledgement is asked for, and the run continues."""
    config, generated = _pair(tmp_path, config_age=5 * 3600, generated_age=0)
    prompts = []

    def ask(prompt):
        prompts.append(prompt)
        return ''

    assert sync.run_sync_check(config, generated, ask=ask) is True

    output = capsys.readouterr().out
    assert 'normal after a kernel' in output
    assert prompts == ['Press ENTER to continue: ']


@pytest.mark.parametrize('seconds, expected', [
    (7200, '2h'),
    (9000, '2h 30m'),
    (90000, '1d 1h'),
    (86400, '1d'),
    (90, '1m 30s'),
    (120, '2m'),
    (5, '5s'),
])
def test_human_seconds(seconds, expected):
    assert sync.human_seconds(seconds) == expected
