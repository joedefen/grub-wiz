"""CLI branches not covered by ``test_cli_args.py``.

The discovery switch and ``run_cli()`` cleanup are already tested.  These
tests cover custom-config validation, factory reset, the debug demo, and the
module entry points that are easy to run by accident.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import grub_wiz.DistroVars as dv_mod
import grub_wiz.main as cli
from console_window import Theme
from grub_wiz.Glyphs import Glyphs
from grub_wiz.GrubCfgParser import main as parser_main
from grub_wiz.UiPrefs import UiPrefs


@pytest.fixture(name='fake_wiz')
def fixture_fake_wiz(monkeypatch):
    wiz = SimpleNamespace()
    monkeypatch.setattr(cli, 'rerun_module_as_root', lambda _name: None)
    monkeypatch.setattr(cli, 'GrubWiz', lambda cli_opts=None: wiz)
    return wiz


def run_main(monkeypatch, *argv):
    monkeypatch.setattr(sys, 'argv', ['grub-wiz', *argv])
    with pytest.raises(SystemExit) as excinfo:
        cli.main()
    return excinfo.value.code


def test_validate_custom_config_success(monkeypatch, fake_wiz, capsys):
    fake_wiz.canned_config = SimpleNamespace(
        using_path=Path('/home/u/.config/grub-wiz/custom_config.yaml'))

    code = run_main(monkeypatch, '--validate-custom-config')

    assert code == 0
    output = capsys.readouterr().out
    assert 'custom config is valid and in use' in output


def test_validate_custom_config_failure(monkeypatch, fake_wiz, capsys):
    fake_wiz.canned_config = SimpleNamespace(
        using_path=Path('/usr/lib/grub-wiz/canned_config.yaml'))

    code = run_main(monkeypatch, '--validate-custom-config')

    assert code == 1
    assert 'custom config NOT being used' in capsys.readouterr().out


def test_factory_reset_deletes_caches_but_keeps_backups(monkeypatch, fake_wiz,
                                                        tmp_path, capsys):
    cache = tmp_path / 'system-params.yaml'
    warn_db = tmp_path / 'warn-db.yaml'
    backup = tmp_path / '20260101-000000-ABCDEF12.orig.bak'
    for path in (cache, warn_db, backup):
        path.write_text('data', encoding='utf-8')
    fake_wiz.param_discovery = SimpleNamespace(cache_file=cache)
    fake_wiz.warn_db = SimpleNamespace(yaml_path=warn_db)

    code = run_main(monkeypatch, '--factory-reset')

    assert code == 0
    assert not cache.exists()
    assert not warn_db.exists()
    assert backup.exists()
    assert 'Backup files (.bak) preserved' in capsys.readouterr().out


def test_factory_reset_also_clears_the_remembered_theme(monkeypatch, fake_wiz,
                                                        tmp_path, capsys):
    """The theme choice is user preference, so a reset must clear it too."""
    cache = tmp_path / 'system-params.yaml'
    warn_db = tmp_path / 'warn-db.yaml'
    for path in (cache, warn_db):
        path.write_text('data', encoding='utf-8')
    fake_wiz.param_discovery = SimpleNamespace(cache_file=cache)
    fake_wiz.warn_db = SimpleNamespace(yaml_path=warn_db)
    fake_wiz.prefs = UiPrefs()
    fake_wiz.prefs.set('theme', 'nord')

    code = run_main(monkeypatch, '--factory-reset')

    assert code == 0
    assert not fake_wiz.prefs.yaml_path.exists()
    assert fake_wiz.prefs.get('theme') is None
    assert 'ui-prefs.yaml' in capsys.readouterr().out


def test_factory_reset_with_nothing_to_delete(monkeypatch, fake_wiz,
                                              tmp_path, capsys):
    fake_wiz.param_discovery = SimpleNamespace(
        cache_file=tmp_path / 'missing-cache.yaml')
    fake_wiz.warn_db = SimpleNamespace(
        yaml_path=tmp_path / 'missing-warn-db.yaml')

    code = run_main(monkeypatch, '--factory-reset')

    assert code == 0
    assert 'No cached files to delete' in capsys.readouterr().out


def test_factory_reset_reports_os_error(monkeypatch, fake_wiz, tmp_path,
                                        capsys):
    cache = tmp_path / 'system-params.yaml'
    cache.write_text('data', encoding='utf-8')
    fake_wiz.param_discovery = SimpleNamespace(cache_file=cache)
    fake_wiz.warn_db = SimpleNamespace(yaml_path=tmp_path / 'warn-db.yaml')

    def deny(_path):
        raise OSError('permission denied')

    monkeypatch.setattr(cli.os, 'unlink', deny)

    code = run_main(monkeypatch, '--factory-reset')

    assert code == 0
    assert 'failed "factory reset"' in capsys.readouterr().out


def test_validator_demo_exits_zero(monkeypatch, fake_wiz):
    seen = []
    fake_wiz.param_defaults = {'GRUB_TIMEOUT': '5'}
    fake_wiz.wiz_validator = SimpleNamespace(
        demo=lambda defaults: seen.append(defaults))

    assert run_main(monkeypatch, '--validator-demo') == 0
    assert seen == [{'GRUB_TIMEOUT': '5'}]


@pytest.fixture(autouse=True)
def _restore_display_state():
    """The glyph mode and the theme are process-wide; never leak them."""
    previous_theme = Theme.get_current()
    Glyphs.register_all()
    Glyphs.set_ascii(False)
    yield
    Theme.set_active(previous_theme)
    Glyphs.register_all()
    Glyphs.set_ascii(False)


def apply_display(argv, capsys, monkeypatch=None):
    """Parse *argv* with the real parser, then run the app's display wiring."""
    opts = cli.build_parser().parse_args(argv)
    report = cli.display_cli.apply_display_arguments(opts, prog='grub-wiz')
    return report, capsys.readouterr().out


def test_the_parser_offers_the_library_display_switches(capsys):
    help_text = cli.build_parser().format_help()

    assert '--ascii' in help_text
    assert '--glyphs' in help_text
    assert '--theme' in help_text
    assert 'remembered' in help_text     # the store really does remember


def test_ascii_switch_forces_the_ascii_glyph_set(capsys):
    report, out = apply_display(['--ascii'], capsys)

    assert report.ascii_mode is True
    assert Glyphs.is_ascii() is True
    assert out.startswith('grub-wiz: ')


def test_ascii_can_be_turned_off_explicitly(capsys):
    """Symmetry with --ascii: --ascii=no means "force the Unicode set"."""
    report, _out = apply_display(['--ascii=no'], capsys)

    assert report.ascii_mode is False
    assert Glyphs.is_ascii() is False


def test_glyph_policy_follows_the_terminal_report(monkeypatch, capsys):
    """A terminal that cannot carry the glyphs must switch the app to ASCII."""
    monkeypatch.setenv('TERM', 'dumb')
    monkeypatch.delenv('CONSOLE_WINDOW_GLYPHS', raising=False)

    report, out = apply_display([], capsys)

    assert report.ascii_required is True
    assert Glyphs.is_ascii() is True
    assert 'TERM=dumb' in out


def test_theme_switch_seeds_the_first_window(monkeypatch, capsys):
    monkeypatch.setattr(Theme, '_current', None)

    apply_display(['--theme=gruvbox'], capsys)

    assert Theme.get_current() == 'gruvbox'


def test_grub_cfg_parser_cli_requires_one_path(capsys):
    assert parser_main([]) == 2
    assert 'usage:' in capsys.readouterr().err


def test_grub_cfg_parser_cli_prints_entries(tmp_path, capsys):
    cfg = tmp_path / 'grub.cfg'
    cfg.write_text(
        "menuentry 'Ubuntu' {\n"
        "  submenu 'Older kernels' {\n"
        "  }\n"
        "}\n",
        encoding='utf-8')

    assert parser_main([str(cfg)]) == 0
    output = capsys.readouterr().out
    assert "[MENUENTRY] 'Ubuntu'" in output
    assert "[SUBMENU  ] 'Older kernels'" in output


def test_grub_cfg_parser_cli_reports_no_entries(tmp_path, capsys):
    cfg = tmp_path / 'grub.cfg'
    cfg.write_text('set timeout=5\n', encoding='utf-8')

    assert parser_main([str(cfg)]) == 0
    assert 'No top-level boot entries' in capsys.readouterr().out


def test_distro_vars_module_main_prints_detection(monkeypatch, capsys):
    monkeypatch.setattr(
        dv_mod, 'DistroVars',
        lambda: SimpleNamespace(etc_grub='/etc/default/grub', is_crippled=False))

    dv_mod.main()

    assert 'etc_grub' in capsys.readouterr().out


def _run_startup(monkeypatch, fake_wiz, *argv):
    """Drive main() as far as the pre-curses work and return the call order."""
    calls = []
    fake_wiz.backup_mgr = SimpleNamespace(
        purge_backups=lambda: calls.append('purge'))
    fake_wiz.do_start_up_backup = lambda: calls.append('startup')
    fake_wiz.main_loop = lambda: calls.append('loop')
    fake_wiz.distro_vars = SimpleNamespace(
        etc_grub=Path('/etc/default/grub'),
        grub_cfg=Path('/boot/grub/grub.cfg'))
    monkeypatch.setattr(cli, 'rerun_module_as_root', lambda _name: None)
    monkeypatch.setattr(cli, 'GrubWiz', lambda cli_opts=None: fake_wiz)
    monkeypatch.setattr(cli, 'run_sync_check', lambda *_a, **_kw: True)
    monkeypatch.setattr(cli.time, 'sleep', lambda _seconds: None)
    monkeypatch.setattr(sys, 'argv', ['grub-wiz', *argv])

    cli.main()

    return calls


def test_startup_purges_before_the_first_backup(monkeypatch, fake_wiz):
    """The purge and the BASELINE record run before curses, purge first."""
    assert _run_startup(monkeypatch, fake_wiz) == ['purge', 'startup', 'loop']


def test_keep_all_bak_skips_only_the_purge(monkeypatch, fake_wiz):
    """-k keeps every backup; it must not suppress the one-time BASELINE."""
    assert _run_startup(monkeypatch, fake_wiz, '--keep-all-bak') == [
        'startup', 'loop']
    assert _run_startup(monkeypatch, fake_wiz, '-k') == ['startup', 'loop']
