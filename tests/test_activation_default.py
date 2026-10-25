"""Activation must write a usable value, not a documentation sentinel (M9).

``GRUB_TERMINAL`` shipped ``default: '#comment'``.  ``activate_param()`` used
that default verbatim, producing ``GRUB_TERMINAL=#comment`` in the sourced
config (the unquoted ``#`` even starts a shell comment).  Sentinels must fall
back to the first enum, and the shipped default is now a real value.
"""

from importlib.resources import files

from ruamel.yaml import YAML

from grub_wiz.GrubFile import GrubFile
from grub_wiz.main import GrubWiz, check_shell_value


def _bare_grubwiz(param_cfg):
    """A GrubWiz with only the attributes activation needs."""
    gw = object.__new__(GrubWiz)
    gw.param_cfg = param_cfg
    gw.param_values = {name: GrubFile.ABSENT for name in param_cfg}
    gw.saved_active_param_values = {}
    return gw


def test_comment_sentinel_falls_back_to_first_enum():
    gw = _bare_grubwiz({
        'GRUB_TERMINAL': {
            'default': '#comment',
            'enums': {'console': 'text', 'gfxterm': 'graphics'},
        },
    })

    assert gw.activate_param('GRUB_TERMINAL') is True
    assert gw.param_values['GRUB_TERMINAL'] == 'console'
    assert check_shell_value(gw.param_values['GRUB_TERMINAL'])[0]


def test_internal_sentinels_fall_back_to_first_enum():
    for sentinel in ('#absent', GrubFile.COMMENT, GrubFile.ABSENT):
        gw = _bare_grubwiz({
            'GRUB_TERMINAL': {
                'default': sentinel,
                'enums': {'console': 'text'},
            },
        })
        gw.activate_param('GRUB_TERMINAL')
        assert gw.param_values['GRUB_TERMINAL'] == 'console'


def test_sentinel_without_enums_becomes_empty_value():
    gw = _bare_grubwiz({'GRUB_OPTIONAL': {'default': '#comment', 'enums': {}}})

    gw.activate_param('GRUB_OPTIONAL')

    assert gw.param_values['GRUB_OPTIONAL'] == ''


def test_saved_active_value_wins_over_default():
    gw = _bare_grubwiz({'GRUB_TERMINAL': {'default': 'console', 'enums': {}}})
    gw.saved_active_param_values['GRUB_TERMINAL'] = 'gfxterm'

    gw.activate_param('GRUB_TERMINAL')

    assert gw.param_values['GRUB_TERMINAL'] == 'gfxterm'


def test_shipped_grub_terminal_default_is_a_writable_value():
    data = YAML().load(
        files('grub_wiz').joinpath('canned_config.yaml').read_text(encoding='utf-8'))
    cfg = data['Security & Advanced']['GRUB_TERMINAL']

    assert cfg['default'] not in ('#comment', '#absent',
                                  GrubFile.COMMENT, GrubFile.ABSENT)
    ok, reason = check_shell_value(str(cfg['default']))
    assert ok, reason
    assert cfg['default'] in cfg['enums']
