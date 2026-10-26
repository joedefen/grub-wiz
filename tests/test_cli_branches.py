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
from grub_wiz.GrubCfgParser import main as parser_main


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
