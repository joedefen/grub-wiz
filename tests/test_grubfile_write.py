"""Sentinel-safe writes in ``GrubFile`` (AUDIT.md M9).

``GrubFile.ABSENT`` is an internal marker meaning "this parameter has no line
in the file".  It must never be written into the configuration, and the check
must not be an ``assert`` because assertions disappear under ``python -O``.

The previous code asserted only in the existing-line loop; the append path
could emit the literal ``≡`` for an absent parameter.
"""

import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from grub_wiz.GrubFile import GrubFile  # noqa: E402


def _grub(tmp_path, text, params):
    conf = tmp_path / 'grub'
    conf.write_text(text, encoding='utf-8')
    return GrubFile(params, file_path=str(conf))


def _write_to_string(grub):
    """Run ``write_file(use_stdout=True)`` and return the emitted text."""
    output = io.StringIO()
    with redirect_stdout(output):
        assert grub.write_file(use_stdout=True) is True
    return output.getvalue()


def test_absent_new_value_on_existing_line_is_ignored(tmp_path):
    """An inconsistent ABSENT value must not raise or alter the file."""
    grub = _grub(tmp_path, 'GRUB_TIMEOUT=5\n',
                 {'GRUB_TIMEOUT': {'guidance': ''}})
    grub.param_data['GRUB_TIMEOUT'].new_value = grub.ABSENT

    text = _write_to_string(grub)

    assert 'GRUB_TIMEOUT=5' in text
    assert grub.ABSENT not in text


def test_absent_new_value_for_absent_param_appends_nothing(tmp_path):
    """The append path must not write the literal ABSENT sentinel."""
    grub = _grub(tmp_path, 'GRUB_TIMEOUT=5\n',
                 {'GRUB_TIMEOUT': {'guidance': ''},
                  'GRUB_THEME': {'guidance': 'theme path'}})
    grub.param_data['GRUB_THEME'].new_value = grub.ABSENT

    text = _write_to_string(grub)

    assert grub.ABSENT not in text
    assert 'GRUB_THEME' not in text


def test_comment_sentinel_still_comments_an_existing_line(tmp_path):
    """The normal 'deactivate' path must keep working."""
    grub = _grub(tmp_path, 'GRUB_TIMEOUT=5\n',
                 {'GRUB_TIMEOUT': {'guidance': ''}})
    grub.del_parameter('GRUB_TIMEOUT')

    text = _write_to_string(grub)

    assert '#GRUB_TIMEOUT=5' in text
    assert grub.COMMENT not in text


def test_legal_value_for_absent_param_is_appended(tmp_path):
    """A formerly absent parameter with a real value is still added."""
    grub = _grub(tmp_path, 'GRUB_TIMEOUT=5\n',
                 {'GRUB_TIMEOUT': {'guidance': ''},
                  'GRUB_THEME': {'guidance': 'theme path'}})
    grub.set_new_value('GRUB_THEME', '"/boot/grub/themes/custom"')

    text = _write_to_string(grub)

    assert 'GRUB_THEME="/boot/grub/themes/custom"' in text
    assert grub.ABSENT not in text
