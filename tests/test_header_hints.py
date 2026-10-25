"""Pin the header shortcuts and the EDIT-only RESTORE rule.

The EDIT header advertises RESTORE and WARNINGS-CONFIG, while REVIEW advertises
only WARNINGS-CONFIG because a restore would replace the configuration being
reviewed.  The warnings-configuration screen must also advertise the help key
alongside the other screens.
"""

from types import SimpleNamespace

from grub_wiz.main import (
    GrubWizScreen, HomeScreen, RestoreScreen, WarnScreen,
    HOME_ST, REVIEW_ST, RESTORE_ST, WARN_ST,
)


def make_common_screen(current):
    """Build a screen with just the collaborators add_common_head1() needs."""
    captured = []
    gw = SimpleNamespace(
        ss=SimpleNamespace(is_curr=lambda screen: screen == current),
        spins=SimpleNamespace(guide='Off'),
        get_diffs=lambda: {},
        add_fancy_header=captured.append,
        warn_db=SimpleNamespace(write_if_dirty=lambda: None),
    )
    screen = HomeScreen.__new__(HomeScreen)
    screen.gw = gw
    return screen, captured


def test_edit_header_offers_restore_and_warncfg_before_help():
    """EDIT exposes both destinations and keeps ?:help as the last cue."""
    screen, captured = make_common_screen(HOME_ST)

    screen.add_common_head1('EDIT')

    header = captured[0]
    assert '[R]estore' in header
    assert '[W]arnCfg' in header
    assert header.index('[R]estore') < header.index('?:help')
    assert header.index('[W]arnCfg') < header.index('?:help')


def test_review_header_offers_only_warncfg_before_help():
    """REVIEW does not advertise RESTORE, but still shows ESC:back."""
    screen, captured = make_common_screen(REVIEW_ST)

    screen.add_common_head1('REVIEW')

    header = captured[0]
    assert '[R]estore' not in header
    assert '[W]arnCfg' in header
    assert header.index('[W]arnCfg') < header.index('?:help')
    assert 'ESC:back' in header


def test_restore_is_available_only_from_edit():
    """The whitelist and the action guard must agree with the header hints."""
    assert RestoreScreen.come_from_whitelist == [HOME_ST]

    for current, expected in ((HOME_ST, [RESTORE_ST]),
                              (REVIEW_ST, [])):
        calls = []
        gw = SimpleNamespace(
            ss=SimpleNamespace(is_curr=lambda screen: screen == current),
            navigate_to=calls.append,
        )
        screen = GrubWizScreen.__new__(GrubWizScreen)
        screen.gw = gw

        screen.enter_restore_ACTION()

        assert calls == expected


def test_warnings_is_available_only_from_edit_and_review():
    """W is advertised there, so the guard must reject the other screens."""
    for current, expected in ((HOME_ST, [WARN_ST]),
                              (REVIEW_ST, [WARN_ST]),
                              (RESTORE_ST, [])):
        calls = []
        gw = SimpleNamespace(
            ss=SimpleNamespace(is_curr=lambda screen:
                               current in screen
                               if isinstance(screen, (tuple, list, set))
                               else screen == current),
            navigate_to=calls.append,
        )
        screen = GrubWizScreen.__new__(GrubWizScreen)
        screen.gw = gw

        screen.enter_warnings_ACTION()

        assert calls == expected


def test_warncfg_header_advertises_help_and_styles_escape():
    """WARNINGS-CONFIG must show ?:help and the same ESC:back cue as VIEW."""
    captured = []
    gw = SimpleNamespace(
        warn_db=SimpleNamespace(is_inhibit=lambda _key: False),
        search_bar=SimpleNamespace(get_display_string=lambda prefix: ''),
        add_fancy_header=captured.append,
    )
    screen = WarnScreen.__new__(WarnScreen)
    screen.gw = gw
    screen.win = SimpleNamespace(get_picked_context=lambda: None)

    screen.draw_head()

    header = captured[0]
    assert '?:help' in header
    assert 'ESC:back' in header
    assert 'ESC=back' not in header
