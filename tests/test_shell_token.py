"""Regression tests for shell-value validation of edited parameters (H9).

``/etc/default/grub`` is *sourced* by the distro's GRUB scripts, so an edited
value must remain a single shell word.  The previous validator was both too
strict (it rejected plain GRUB values such as ``1024x768,auto``) and too
permissive (it accepted ``$(reboot)``, including inside double quotes).

The tests below pin the two sides of the fix:

* plain values keep working unquoted, and a space only requires quoting;
* command substitution is rejected unless the parameter's ``_re_specs_``
  entry opts in (``GRUB_DISTRIBUTOR``) or the user chooses expert edit, and
  is never accepted inside double quotes.
"""

import re
from importlib.resources import files

import pytest
from ruamel.yaml import YAML

from grub_wiz.CannedConfig import CannedConfig
from grub_wiz.main import GrubWiz, check_shell_value


# --- The value grammar ----------------------------------------------------

@pytest.mark.parametrize('value', [
    '',
    '0',
    '-1',
    'auto',
    'saved',
    '640x480',
    '1024x768,auto',
    'intel-ucode.img',
    'console=serial,115200n8',
    'net.ifnames=0',
    'modprobe.blacklist=nouveau',
    'a+b:c=d',
    '/boot/grub/themes/starfield/theme.txt',
    'root=UUID=1234-5678',
    '"quiet splash"',
    "'quiet splash'",
    '"Ubuntu, with Linux 6.8"',
    '"intel-ucode.img amd-ucode.img"',
    "''",
    '""',
    # Single quotes make shell syntax literal, which is safe.
    "'$(reboot)'",
    "'`reboot`'",
])
def test_plain_values_are_accepted(value):
    ok, reason = check_shell_value(value)
    assert ok, reason


@pytest.mark.parametrize('value', [
    'quiet splash',          # word splitting turns the second word into a command
    'x; reboot',
    'x && reboot',
    'x || reboot',
    'x | reboot',
    'x > /etc/passwd',
    'x < /etc/shadow',
    'x & reboot',
    'foo#bar',               # unquoted '#' starts a comment in the GRUB file
    'foo\\bar',
    '~/boot',
    '"unterminated',
    "'unterminated",
    '"$(reboot)"',           # expansion inside double quotes
    '"`reboot`"',
    'prefix$(reboot)',
    'x\ny',
    'x\x00y',
])
def test_unsafe_values_are_rejected(value):
    ok, reason = check_shell_value(value)
    assert not ok
    assert reason


def test_whitespace_error_asks_for_quotes():
    ok, reason = check_shell_value('intel-ucode.img amd-ucode.img')
    assert not ok
    assert 'quote' in reason


# --- Command substitution and the trust boundary --------------------------

@pytest.mark.parametrize('value', [
    '$(lsb_release -i -s)',
    '$(lsb_release -i -s 2>/dev/null || echo Debian)',
    '$(echo ")")',
    '`lsb_release -i -s`',
])
def test_command_substitution_is_accepted_when_opted_in(value):
    ok, reason = check_shell_value(value, allow_command_sub=True)
    assert ok, reason


@pytest.mark.parametrize('value', [
    '$(reboot)',
    '`reboot`',
    '"$(reboot)"',
])
def test_command_substitution_is_rejected_by_default(value):
    ok, reason = check_shell_value(value)
    assert not ok
    assert 'command substitution' in reason


@pytest.mark.parametrize('value', [
    '$(reboot',
    '$(reboot) extra',
    '$(reboot); reboot',
    '"$(reboot)"',
])
def test_opted_in_command_substitution_must_be_the_whole_value(value):
    ok, _reason = check_shell_value(value, allow_command_sub=True)
    assert not ok


def test_backtick_substitution_cannot_nest():
    ok, _reason = check_shell_value('`echo `reboot``', allow_command_sub=True)
    assert not ok


# --- edit_param / expert_edit_param wiring --------------------------------

class FakeWin:
    """Minimal ConsoleWindow stand-in that replays answers and records flashes."""

    def __init__(self, answers):
        self._answers = list(answers)
        self.flashes = []

    def answer(self, prompt=None, seed=None, height=1):
        if not self._answers:
            return None
        return self._answers.pop(0)

    def flash(self, message, duration=1.5):
        self.flashes.append(message)


def _bare_grubwiz(cfg):
    """A GrubWiz instance with only the attributes the edit paths touch."""
    gw = object.__new__(GrubWiz)
    gw.param_values = {name: '' for name in cfg}
    gw.param_cfg = cfg
    return gw


def test_edit_param_accepts_comma_separated_gfxmode():
    gw = _bare_grubwiz({'GRUB_GFXMODE': {'allow_command_sub': False}})
    win = FakeWin(['1024x768,auto'])

    gw.edit_param(win, 'GRUB_GFXMODE', re.compile(r'^[0-9a-z,]+$'))

    assert gw.param_values['GRUB_GFXMODE'] == '1024x768,auto'
    assert win.flashes == []


def test_edit_param_retries_until_a_multi_word_value_is_quoted():
    gw = _bare_grubwiz({'GRUB_EARLY_INITRD_LINUX_STOCK': {}})
    win = FakeWin(['intel-ucode.img amd-ucode.img',
                   '"intel-ucode.img amd-ucode.img"'])

    gw.edit_param(win, 'GRUB_EARLY_INITRD_LINUX_STOCK', re.compile(r'^.*$'))

    assert gw.param_values['GRUB_EARLY_INITRD_LINUX_STOCK'] == \
        '"intel-ucode.img amd-ucode.img"'
    assert any('Unsafe value' in message for message in win.flashes)


def test_edit_param_rejects_command_substitution_unless_opted_in():
    gw = _bare_grubwiz({'GRUB_CMDLINE_LINUX': {'allow_command_sub': False}})
    win = FakeWin(['$(reboot)', '"quiet"'])

    gw.edit_param(win, 'GRUB_CMDLINE_LINUX', re.compile(r'^.*$'))

    assert gw.param_values['GRUB_CMDLINE_LINUX'] == '"quiet"'
    assert any('command substitution' in message for message in win.flashes)


def test_edit_param_allows_opted_in_command_substitution():
    gw = _bare_grubwiz({'GRUB_DISTRIBUTOR': {'allow_command_sub': True}})
    win = FakeWin(['$(lsb_release -i -s)'])

    gw.edit_param(win, 'GRUB_DISTRIBUTOR', re.compile(r'^.*$'))

    assert gw.param_values['GRUB_DISTRIBUTOR'] == '$(lsb_release -i -s)'
    assert win.flashes == []


def test_edit_param_rejects_command_substitution_inside_double_quotes():
    """The old validator accepted `"$(reboot)"` because it only checked quotes."""
    gw = _bare_grubwiz({'GRUB_DISTRIBUTOR': {'allow_command_sub': True}})
    win = FakeWin(['"$(reboot)"', '"Ubuntu"'])

    gw.edit_param(win, 'GRUB_DISTRIBUTOR', re.compile(r'^.*$'))

    assert gw.param_values['GRUB_DISTRIBUTOR'] == '"Ubuntu"'
    assert any('Unsafe value' in message for message in win.flashes)


def test_expert_edit_allows_command_substitution_but_not_injection():
    gw = _bare_grubwiz({'GRUB_CUSTOM': {}})
    win = FakeWin(['x; reboot', '$(reboot)'])

    gw.expert_edit_param(win, 'GRUB_CUSTOM')

    assert gw.param_values['GRUB_CUSTOM'] == '$(reboot)'
    assert len(win.flashes) == 1
    assert 'quote the value' in win.flashes[0]
    assert "';'" in win.flashes[0]


# --- Shipped config consistency ------------------------------------------

def _processed_canned():
    """Load the packaged YAML the way CannedConfig does, without user state."""
    cfg = object.__new__(CannedConfig)
    cfg.data = YAML().load(
        files('grub_wiz').joinpath('canned_config.yaml').read_text(encoding='utf-8'))
    cfg._process_config()
    return cfg


def _param(cfg, name):
    for section, params in cfg.data.items():
        if section.startswith('_'):
            continue
        if name in params:
            return params[name]
    raise KeyError(name)


def test_only_the_command_spec_opts_in():
    cfg = _processed_canned()
    assert _param(cfg, 'GRUB_DISTRIBUTOR')['allow_command_sub'] is True
    for name in ('GRUB_GFXMODE', 'GRUB_THEME', 'GRUB_CMDLINE_LINUX',
                 'GRUB_EARLY_INITRD_LINUX_STOCK', 'GRUB_DEFAULT'):
        assert _param(cfg, name)['allow_command_sub'] is False


def test_shipped_enums_are_safe_shell_values():
    cfg = _processed_canned()
    for section, params in cfg.data.items():
        if section.startswith('_'):
            continue
        for name, param_cfg in params.items():
            for value in param_cfg.get('enums', {}):
                ok, reason = check_shell_value(str(value))
                assert ok, f'{name} enum {value!r}: {reason}'


def test_every_shipped_enum_matches_its_own_edit_regex():
    cfg = _processed_canned()
    for section, params in cfg.data.items():
        if section.startswith('_'):
            continue
        for name, param_cfg in params.items():
            regex = param_cfg.get('edit_re')
            if not hasattr(regex, 'match'):
                continue
            for value in param_cfg.get('enums', {}):
                assert regex.match(str(value)), f'{name} enum {value!r}'


def test_early_initrd_enum_is_quoted_and_accepted():
    cfg = _processed_canned()
    param_cfg = _param(cfg, 'GRUB_EARLY_INITRD_LINUX_STOCK')
    both = '"intel-ucode.img amd-ucode.img"'
    assert both in param_cfg['enums']
    assert param_cfg['edit_re'].match(both)
    assert check_shell_value(both)[0]


def test_theme_regex_requires_quotes_only_for_spaces():
    cfg = _processed_canned()
    regex = _param(cfg, 'GRUB_THEME')['edit_re']
    assert regex.match('/boot/grub/themes/starfield/theme.txt')
    assert regex.match('"/boot/my themes/starfield/theme.txt"')
    assert not regex.match('/boot/my themes/starfield/theme.txt')


def test_gfxmode_values_are_accepted_unquoted():
    cfg = _processed_canned()
    regex = _param(cfg, 'GRUB_GFXMODE')['edit_re']
    for value in ('1024x768,auto', 'auto', '640x480'):
        assert regex.match(value), value
        assert check_shell_value(value)[0], value
