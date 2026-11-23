#!/usr/bin/env python3
r""" grub-wiz: the help grub file editor assistant """


import copy
import curses as cs
import logging
import os
import re
import subprocess
import sys
import textwrap
import time
import traceback
import unicodedata
from argparse import ArgumentParser
from pathlib import Path
from types import SimpleNamespace

from console_window import (
    Appearance,
    BasicHelpScreen,
    BasicTextScreen,
    ConsoleWindow,
    ConsoleWindowOpts,
    Context,
    IncrementalSearchBar,
    InlineConfirmation,
    OptionSpinner,
    Screen,
    ScreenStack,
    Theme,
    semantic_attr,
)
from console_window import cli as display_cli
from console_window import help as display_help

from . import __version__
from .BackupMgr import BASELINE_TAG, RESYNC_TAG, BackupMgr
from .BackupTag import change_tag
from .CannedConfig import CannedConfig, has_edit_regex, is_expert_edit
from .DistroVars import DistroVars
from .Glyphs import Glyphs
from .GrubCfgParser import entries_to_enums, get_top_level_grub_entries
from .GrubFile import GrubFile
from .GrubWriter import GrubWriter
from .ParamDiscovery import ParamDiscovery
from .SyncCheck import run_sync_check
from .UiPrefs import UiPrefs
from .UserConfigDir import UserConfigDir
from .WarnDB import WarnDB
from .WizValidator import WizValidator

HOME_ST, REVIEW_ST, RESTORE_ST, VIEW_ST, COMPARE_ST, WARN_ST, HELP_ST, THEME_ST = (
    0, 1, 2, 3, 4, 5, 6, 7)
SCREENS = 'HOME REVIEW RESTORE VIEW COMPARE WARN HELP THEMES'.split() # screen names

TAKEN_NAV_KEYS = [cs.KEY_LEFT, cs.KEY_RIGHT]
QUIT_KEY = 0x3
BACKUP_TAG_PATTERN = re.compile(r'^[-_+~A-Za-z0-9]+$')


logger = logging.getLogger(__name__)
theme_attr = semantic_attr

def initial_theme_name(cli_theme, prefs=None):
    """The canonical theme to start on, with ``mono`` as a real theme."""
    remembered = ''
    if prefs is not None:
        try:
            remembered = prefs.load()
        # A broken preference store must not stop the editor from starting.
        except Exception:
            remembered = ''
    if not isinstance(remembered, str):
        remembered = ''
    return Theme.resolve(Appearance.resolve_appearance(
        cli_theme=cli_theme or None,
        saved_theme=remembered,
        environ=os.environ,
    ))


class Tab:
    """Column layout for the body: parameter name left, value right."""
    def __init__(self, cols, param_wid):
        """           g
        >----left----|a |---right ---|
         |<---lwid-->|p |<---rwid--->|
         la          lz ra           rz

        :param self: provides access to the "tab" positions :param cols:
        columns in window :param param_wid: max wid of all param names
        """
        self.cols = cols
        self.la = 1
        self.lz = 1 + param_wid + 4
        self.lwid = self.lz - self.la
        self.gap = 2
        self.ra = self.lz + 2
        self.rz = self.cols
        self.rwid = self.rz - self.ra
        self.wid = self.rz - self.la


def display_width(text):
    """Return the terminal cell width of *text*."""
    width = 0
    for char in str(text):
        if unicodedata.combining(char):
            continue
        width += 2 if unicodedata.east_asian_width(char) in ('W', 'F') else 1
    return width


def truncate_to_width(text, width, ellipsis=None):
    """Truncate *text* so its terminal cell width does not exceed *width*."""
    if ellipsis is None:
        ellipsis = Glyphs.ellipsis()
    text = str(text)
    if display_width(text) <= width:
        return text
    budget = width - display_width(ellipsis)
    used, kept = 0, []
    for char in text:
        if unicodedata.combining(char):
            char_width = 0
        elif unicodedata.east_asian_width(char) in ('W', 'F'):
            char_width = 2
        else:
            char_width = 1
        if used + char_width > budget:
            break
        kept.append(char)
        used += char_width
    return ''.join(kept) + ellipsis


class InlineSearchPrompt:
    """A search prompt drawn and edited in place, with a movable caret."""
    def __init__(self, on_change=None, on_accept=None, on_cancel=None):
        self._editor = InlineConfirmation()
        self._text = ''
        self._start_text = ''
        self._notified = ''
        self.on_change = on_change
        self.on_accept = on_accept
        self.on_cancel = on_cancel

    def start(self, initial_text: str = '') -> None:
        self._text = initial_text
        self._start_text = initial_text
        self._notified = initial_text
        self._editor.start(mode='text', initial=initial_text)

    def handle_key(self, key: int) -> bool:
        if not self.is_active:
            return False
        if key in (10, 13):  # ENTER accepts even when nothing was typed
            self._accept()
            return True
        if key == 27:  # ESC restores the pattern that was active on entry
            self._cancel()
            return True

        # Every other key belongs to the line editor while the prompt is live.
        self._editor.handle_key(key)
        self._text = self._editor.input_buffer
        if self._text != self._notified:
            self._notified = self._text
            if self.on_change:
                self.on_change(self._text)
        return True

    def _accept(self) -> None:
        text = self._editor.input_buffer
        self._editor.cancel()
        self._text = text
        if self.on_accept:
            self.on_accept(text)

    def _cancel(self) -> None:
        self._editor.cancel()
        self._text = self._start_text
        if self.on_cancel:
            self.on_cancel(self._start_text)

    def get_display_string(self, prefix: str = '/', cursor_char: str = '█') -> str:
        if self.is_active:
            return self._editor.get_display_string(f'{prefix} ',
                                                   cursor_char=cursor_char)
        if self._text:
            return f'{prefix}{self._text}'
        return ''

    @property
    def is_active(self) -> bool:
        return self._editor.active

    @property
    def text(self) -> str:
        return self._editor.input_buffer if self.is_active else self._text

    @property
    def cursor_pos(self) -> int:
        return self._editor.cursor_pos


class GrubWizScreen(Screen):
    """ Grub-wiz specific Screen base class.  """
    def __init__(self, grub_wiz):
        """
        Initialize screen with grub_wiz instance.
        Sets both self.app (from parent) and self.gw (for backward compatibility).
        """
        super().__init__(grub_wiz)
        self.gw = self.app  # Backward compatibility: gw is an alias for app

    def add_fancy_header(self, line):
        """Add a header row using the app's current fancy-header mode."""
        mode = self.gw.spins.fancy_headers
        line_attr = cs.A_DIM if self.win.prompt_active else None
        super().add_fancy_header(line, mode=mode, line_attr=line_attr)

    def add_confirm_header(self, attr=None):
        """Draw a program/screen-scoped confirmation as the last header line."""
        if self.gw.confirm_scope != 'header':
            return
        self.add_prompt_header(
            attr=cs.A_BOLD if attr is None else attr, align='center')

    def add_confirm_item_line(self, item_key, attr=None, hint_attr=None):
        """Draw an item-scoped confirmation directly below that item."""
        if self.gw.confirm_scope != 'item':
            return
        if self.gw.confirm_item_key != item_key:
            return
        self.add_prompt_lines(
            attr=cs.A_BOLD if attr is None else attr,
            hint_attr=cs.A_DIM if hint_attr is None else hint_attr)

    def truncate_line(self, line):
        """Truncate *line* to the window width using cell-aware widths."""
        return truncate_to_width(line, self.win.cols - 1)

    def add_wrapped_body_line(self, line, indent, is_current, attr=None,
                              context=None):
        """Add a body line, wrapping it when it is the selected row.

        *attr* applies to every screen row the line wraps onto.
        Returns the number of screen lines added.
        """
        if not is_current:
            self.add_body(self.truncate_line(line), attr=attr, context=context)
            return 1
        wid = self.win.cols
        excess = display_width(line) - len(line)
        wrapped = textwrap.fill(line, width=max(wid - 1 - excess, 1),
                                subsequent_indent=' ' * indent)
        wraps = wrapped.split('\n')
        for idx, wrap in enumerate(wraps):
            if idx == 0:
                self.add_body(wrap, attr=attr, context=context)
            else:
                self.add_body(wrap, attr=attr,
                              context=Context(genre='TRANSIENT',
                                              pickable=False))
        return len(wraps)

    def escape_ACTION(self):
        """Handle ESC key - navigate back if possible"""
        if self.gw.ss.stack:
            self.gw.navigate_back()

    def quit_ACTION(self):
        """Quit through the app's unapplied-changes check."""
        if self.gw.request_quit():
            self.gw.running = False

    def help_mode_ACTION(self):
        """Handle ? key - navigate to help screen"""
        self.gw.navigate_to(HELP_ST)

    def enter_restore_ACTION(self):
        """Handle R key - navigate to restore screen (only from HOME)"""
        if self.gw.ss.is_curr(HOME_ST):
            self.gw.navigate_to(RESTORE_ST)

    def theme_screen_ACTION(self):
        """Open the COLOR THEME picker (``T``); a no-op when already on it."""
        if not self.gw.ss.is_curr(THEME_ST):
            self.gw.navigate_to(THEME_ST)

    def enter_warnings_ACTION(self):
        """Open WARNINGS-CONFIG, aimed at REVIEW's selected item.

        REVIEW can have warnings for the selected parameter,
        with some of them inhibited and therefore hidden.
        Opening the warnings screen at its first row would lose that context,
        so the selected REVIEW row is handed to the warnings screen before it redraws.
        On EDIT there is no warning context to carry, and the screen opens normally.
        """
        if not self.gw.ss.is_curr((HOME_ST, REVIEW_ST)):
            return
        warn_screen = (getattr(self.gw, 'screens', None) or {}).get(WARN_ST)
        context = None
        win = getattr(self.gw, 'win', None)
        if (warn_screen is not None
                and self.gw.ss.is_curr((REVIEW_ST,))
                and win is not None):
            context = win.get_picked_context()
        if self.gw.navigate_to(WARN_ST) and warn_screen is not None:
            warn_screen.set_entry_from_context(context)

    def previous_pick_anchors(self):
        """Return {body_row: stable_identity} from the previous draw."""
        return getattr(self, '_pick_anchors', None) or {}

    def apply_pick_anchors(self, anchors, target_key):
        """Store this frame's anchors and re-point the pick at *target_key*."""
        self._pick_anchors = anchors
        if target_key is not None:
            for row, key in anchors.items():
                if key == target_key:
                    self.win.pick_pos = row
                    return
        self._clamp_pick_to_pickable()

    def _clamp_pick_to_pickable(self):
        """Fallback: keep pick_pos in range and on a pickable body row."""
        win = self.win
        if not win.body.row_cnt:
            win.pick_pos = 0
            return
        contexts = getattr(win.body, 'contexts', [])
        pos = min(max(win.pick_pos, 0), win.body.row_cnt - 1)

        def pickable(row):
            if row < 0 or row >= len(contexts):
                return True
            ctx = contexts[row]
            return ctx is None or getattr(ctx, 'pickable', True)

        if not pickable(pos):
            for offset in range(1, win.body.row_cnt):
                after, before = pos + offset, pos - offset
                if after < win.body.row_cnt and pickable(after):
                    pos = after
                    break
                if before >= 0 and pickable(before):
                    pos = before
                    break
        win.pick_pos = pos

    def show_keys_ACTION(self):
        """ Show last key for demo"""
        self.app.win.set_demo_mode(enabled=None) # toggle it


class HomeScreen(GrubWizScreen):
    """HOME screen - parameter editing"""
    def __init__(self, gw):
        super().__init__(gw)
        self.search = ''
        self.regex = None

    def draw_screen(self):
        """Draw the editable parameter list and its header."""
        self.set_pick_mode(True)
        self.draw_body()
        self.draw_head()

    def body_param_lines(self, param_name, is_current):
        """ Build a body line for a param """
        gw = self.gw
        tab = self.get_tab()
        marker = ' '
        if not gw.is_active_param(param_name):
            marker = Glyphs.warn()
        value = gw.param_values[param_name]
        line = f'{marker} {param_name[5:]:·<{tab.lwid-2}}'
        indent = len(line)
        line += f'  {value}'
        wid = self.win.cols - 1 # effective width
        if display_width(line) > wid and is_current:
            line = textwrap.fill(line, width=wid,
                       subsequent_indent=' '*indent)
        elif display_width(line) > wid and not is_current:
            line = truncate_to_width(line, self.win.cols-1,
                                     ellipsis=Glyphs.ellipsis_tail())
        return line.splitlines()


    @staticmethod
    def left_side_box(lines, indent=3):
        """ draw a box """
        if len(lines) <= 0:
            return []
        rv = []
        chars = ['│'] * len(lines)
        if len(chars) >= 2:
            chars[0], chars[-1] = '╭', '╰'
        for idx, line in enumerate(lines):
            rv.append(line[:indent] + chars[idx] + line[indent+1:])
        return rv


    def draw_body(self):
        """Build the scrollable body of parameter sections and values."""
        gw = self.gw
        gw.hidden_stats = SimpleNamespace(param=0, warn=0)
        win = self.win # short hand
        picked = win.pick_pos
        # ``picked`` indexes the *previous* frame.
        # Translate it to a stable identity before rebuilding,
        # because the selected parameter's dropdown rows shift every row below it.
        target_key = self.previous_pick_anchors().get(picked)
        anchors = {}
        found_current = False
        first_visible_section = True

        for section_name, params in gw.sections.items():
            visible_params = []
            for param_name in params.keys():
                if param_name not in gw.param_cfg:
                    continue  # Param was filtered out (absent from system)

                if not gw.is_active_param(param_name):
                    gw.hidden_stats.param += 1

                if not gw.show_hidden_params and not gw.is_active_param(param_name):
                    continue
                if gw.show_hidden_params and self.regex:
                    if self.regex.search(param_name[5:]):
                        visible_params.append(param_name)
                else:
                    visible_params.append(param_name)

            if not visible_params: # and not gw.show_hidden_params:
                continue

            if not first_visible_section:
                self.add_body(' ', context=Context(genre='DECOR'))
            first_visible_section = False

            self.add_body(f'[{section_name}]', context=Context(genre='DECOR'))

            for param_name in visible_params:
                selected = bool(target_key is not None
                                and target_key[0] == 'param'
                                and target_key[1] == param_name)
                if target_key is None and picked == win.body.row_cnt:
                    selected = True
                param_lines = self.body_param_lines(param_name, selected)

                if not selected:
                    line = param_lines[0]
                    if len(param_lines) > 1:
                        line = line[:win.cols-2] + Glyphs.ellipsis_tail()
                    anchors[win.body.row_cnt] = ('param', param_name, 0)
                    self.add_body(line, context=Context(genre='param', param_name=param_name))
                    continue

                if target_key is None:
                    target_key = ('param', param_name, 0)
                found_current = True
                param_line_cnt = len(param_lines)
                emits = (param_lines if gw.has_live_item_confirm(param_name) else
                         param_lines + gw.drop_down_lines(param_name))

                view_size = win.scroll_view_size
                if len(emits) > view_size:
                    hide_cnt = 1 + len(emits) - view_size
                    emits = emits[0:view_size-1]
                    emits.append(f'... beware: {hide_cnt} HIDDEN lines ...')
                if len(emits) > 1:
                    emits = [emits[0]] + self.left_side_box(emits[1:])

                # Add parent param line
                anchors[win.body.row_cnt] = ('param', param_name, 0)
                self.add_body(emits[0], context=Context(genre='param', param_name=param_name))
                for idx, emit in enumerate(emits[1:], start=1):
                    self.add_body(emit,
                                  attr=(theme_attr(Theme.INFO)
                                        if idx >= param_line_cnt else None),
                                  context=Context(genre='TRANSIENT',
                                                  pickable=False))
                self.add_confirm_item_line(param_name)

        self.apply_pick_anchors(anchors, target_key)
        return found_current

    def add_common_head1(self, title):
        """Add the first header line shared by the HOME and REVIEW screens."""
        gw = self.gw
        header = f'{title} '
        level = gw.spins.guide
        review_screen = gw.ss.is_curr(REVIEW_ST)
        esc = ' ESC:back' if review_screen else ''
        destinations = ' [W]arnCfg' if review_screen else ' [R]estore [W]arnCfg'
        header += f' [g]uide={level}  [w]rite-grub   {esc}{destinations} ?:help [q]uit'
        header += f'  delta={len(gw.get_diffs())}'
        self.add_fancy_header(header)
        gw.warn_db.write_if_dirty()

    def add_common_head2(self, left):
        """Add the second header line with per-selection actions and search."""
        gw = self.gw
        param_name, _, enums, regex, value = gw.get_enums_regex()
        review_screen = gw.ss.is_curr(REVIEW_ST)

        tab = self.get_tab()
        ctx = gw.win.get_picked_context()
        if ctx:
            cat = ctx.genre
            ident = (getattr(ctx, 'warn_key', '') if cat == 'warn'
                     else getattr(ctx, 'param_name', ''))
        else:
            cat, ident = '', ''

        middle =  ''
        if cat == 'param':
            if enums:
                middle += Glyphs.nav()
            if has_edit_regex(regex):
                middle += ' [e]dit'
            if param_name:
                if gw.is_active_param( param_name):
                    middle += ' x:deact'
            if review_screen and param_name:
                if str(value) != str(gw.prev_values[param_name]):
                    middle += ' [u]ndo'

        if cat == 'warn' and review_screen:
            middle += ' x:allow-warning' if gw.warn_db.is_inhibit(
                        ident) else ' x:inhibit-warning'

        if not review_screen and gw.show_hidden_params:
            middle = f'{middle:<15}' ## so search does not move too much
            middle += gw.home_search_bar.get_display_string(prefix='  /')

        self.add_fancy_header(f'{left:<{tab.lwid}}  {middle}')

    def get_tab(self):
        """ get the tab positions of the print cols """
        return Tab(self.win.cols, self.gw.param_name_wid)

    def draw_head(self):
        """ HOME screen header"""
        gw = self.gw
        self.add_common_head1('EDIT')
        tab = self.get_tab()

        header, cnt = '', gw.hidden_stats.param
        if cnt:
            if gw.show_hidden_params:
                header += f's:hide-{cnt}-inact-params'
            else:
                header += f'[s]how-all-params({cnt}-inact)'
        header = f'{header:<{tab.lwid}}'

        self.add_common_head2(header)

    def hide_ACTION(self):
        """Handle 'x' key on HOME screen - toggle param activation"""
        gw = self.gw
        name, _, _, _, _ = gw.get_enums_regex()
        if name:
            if gw.is_active_param(name):
                gw.deactivate_param(name)
            else:
                gw.activate_param(name)

    def cycle_next_ACTION(self):
        """Handle cycle next key on HOME/REVIEW screen - advance to next enum value"""
        gw = self.gw
        name, _, enums, _, _ = gw.get_enums_regex()
        if enums:
            value = gw.param_values[name]
            found = gw.find_in(value, enums)
            gw.param_values[name] = found.next_value

    def cycle_prev_ACTION(self):
        """Handle cycle prev key on HOME/REVIEW screen - go to previous enum value"""
        gw = self.gw
        name, _, enums, _, _ = gw.get_enums_regex()
        if enums:
            value = gw.param_values[name]
            found = gw.find_in(value, enums)
            gw.param_values[name] = found.prev_value

    def edit_ACTION(self):
        """Handle 'e' key on HOME/REVIEW screen - edit parameter value"""
        gw = self.gw
        name, _, _, regex, _ = gw.get_enums_regex()
        if has_edit_regex(regex):
            gw.edit_param(self.win, name, regex)

    def expert_edit_ACTION(self):
        """Handle 'E' key on HOME/REVIEW screen - expert edit parameter"""
        gw = self.gw
        name, _, _, _, _ = gw.get_enums_regex()
        if name:
            gw.expert_edit_param(self.win, name)

    def show_hidden_ACTION(self):
        """Handle 's' key on HOME screen - toggle showing hidden params"""
        self.gw.show_hidden_params = not self.gw.show_hidden_params

    def write_ACTION(self):
        """Handle 'w' key on HOME screen - push to REVIEW screen"""
        gw = self.gw
        if gw.navigate_to(REVIEW_ST):
            gw.must_reviews = None  # reset
            gw.clues = []

    def slash_ACTION(self):
        """Start incremental search mode for parameter filtering"""
        if self.gw.show_hidden_params:
            self.gw.home_search_bar.start(self.search)
            self.gw.win.passthrough_mode = True

class ReviewScreen(HomeScreen):
    """REVIEW screen - show diffs and warnings"""

    def __init__(self, grub_wiz):
        """Constructor handles initial setup"""
        super().__init__(grub_wiz)
        self.gw.must_reviews = None
        self.gw.clues = []

    def on_resume(self):
        """Refresh review data when resuming after being covered"""
        self.gw.must_reviews = None
        self.gw.clues = []
        return True

    def draw_screen(self):
        """Draw the review list of changes and warnings."""
        self.set_pick_mode(True)
        self.draw_body()
        self.add_head()

    def add_head(self):
        """ Construct the review screen header
            Presumes the body was created with Context metadata.
        """
        gw = self.gw
        self.add_common_head1('REVIEW')

        header, cnt = '', gw.hidden_stats.warn
        if cnt:
            header = 's:hide' if gw.show_hidden_warns else '[s]how'
            header += f' {cnt} {Glyphs.warn()}-warns'
        header = f'{header:<24}'
        self.add_common_head2(header)
        self.add_confirm_header(attr=theme_attr(Theme.DANGER) | cs.A_BOLD)

    def draw_body(self):
        """Build the review list, grouping changed values with their warnings."""
        def add_review_item(param_name, value, old_value=None, heys=None):
            nonlocal reviews
            if param_name not in reviews:
                reviews[param_name] = SimpleNamespace(
                    value=value,
                    old_value=old_value,
                    heys=[] if heys is None else heys
                )
            return reviews[param_name]

        gw = self.gw
        reviews = {}
        gw.hidden_stats = SimpleNamespace(param=0, warn=0)
        diffs = gw.get_diffs()
        warns, all_warn_info = gw.wiz_validator.make_warns(gw.param_values)
        gw.warn_db.audit_info(all_warn_info)
        if gw.must_reviews is None:
            gw.must_reviews = set()
        for param_name in list(diffs.keys()):
            gw.must_reviews.add(param_name)
        for param_name, heys in warns.items():
            for hey in heys:
                words = re.findall(r'\b[_A-Z]+\b', hey[1])
                for word in words:
                    other_name = word
                    if f'GRUB_{word}'in gw.param_values:
                        other_name = f'GRUB_{word}'
                    elif word not in gw.param_values:
                        continue
                    gw.must_reviews.add(other_name)
                gw.must_reviews.add(param_name)

        for param_name in gw.param_names:
            if param_name not in gw.must_reviews:
                continue
            if param_name in diffs:
                old_value, new_value = diffs[param_name]
                item = add_review_item(param_name, new_value, old_value)
            else:
                value = gw.param_values[param_name]
                item = add_review_item(param_name, value)
            heys = warns.get(param_name, None)
            if heys:
                item.heys += heys

        picked = self.win.pick_pos
        # Translate the previous frame's row index into a stable identity;
        # see HomeScreen.draw_body() for why the absolute index cannot be reused.
        target_key = self.previous_pick_anchors().get(picked)
        anchors = {}

        for param_name, ns in reviews.items():
            tab = self.get_tab()
            selected = bool(target_key is not None
                            and target_key[0] == 'param'
                            and target_key[1] == param_name)
            if target_key is None and self.win.body.row_cnt == picked:
                selected = True
            param_lines = self.body_param_lines(param_name, selected)
            if target_key is None and selected:
                target_key = ('param', param_name, 0)

            # Add param lines with Context
            for idx, line in enumerate(param_lines):
                anchors[self.win.body.row_cnt] = ('param', param_name, idx)
                self.add_body(line, context=Context(genre='param', param_name=param_name))

            changed = bool(ns.old_value is not None
                           and str(ns.value) != str(ns.old_value))
            if changed:
                self.add_body(
                    f'{"└──────── was":>{tab.lwid}}  {ns.old_value}',
                    attr=theme_attr(Theme.SUCCESS),
                    context=Context(genre='TRANSIENT', pickable=False))

            for hey in ns.heys:
                warn_key = WarnDB.make_key(param_name, hey[1])
                is_inhibit = gw.warn_db.is_inhibit(warn_key)
                gw.hidden_stats.warn += int(is_inhibit)
                stars = Glyphs.severity() * len(hey[0])

                if not is_inhibit or gw.show_hidden_warns:
                    mark = Glyphs.warn() if is_inhibit else ' '
                    star_field = ' ' * max(4 - display_width(stars), 0) + stars
                    sub_text = f'└─────── {mark} {star_field}'
                    pad = max(tab.lwid - display_width(sub_text), 0)
                    line = f'{" " * pad}{sub_text}  {hey[1]}'
                    # Add warning line with Context - TRANSIENT keeps it with parent
                    warn_selected = bool(target_key is not None
                                         and target_key[0] == 'warn'
                                         and target_key[1] == warn_key)
                    if target_key is None and self.win.body.row_cnt == picked:
                        warn_selected = True
                        target_key = ('warn', warn_key, 0)
                    anchors[self.win.body.row_cnt] = ('warn', warn_key, 0)
                    self.add_wrapped_body_line(line, tab.lwid+2,
                                               warn_selected,
                                               attr=theme_attr(Theme.WARNING),
                                               context=Context(genre='warn', warn_key=warn_key))

            if selected and not gw.has_live_item_confirm(param_name):
                emits = gw.drop_down_lines(param_name)
                if len(emits) > 1:
                    emits = self.left_side_box(emits)
                for emit in emits:
                    self.add_body(emit, attr=theme_attr(Theme.INFO),
                                  context=Context(genre='TRANSIENT',
                                                  pickable=False))

            self.add_confirm_item_line(
                param_name, attr=theme_attr(Theme.DANGER) | cs.A_BOLD)

        self.apply_pick_anchors(anchors, target_key)

    def hide_ACTION(self):
        """Handle 'x' key on REVIEW screen - toggle warning suppression"""
        gw = self.gw
        ctx = self.win.get_picked_context()
        if ctx:
            if ctx.genre == 'warn':
                warn_key = getattr(ctx, 'warn_key', None)
                if warn_key:
                    opposite = not gw.warn_db.is_inhibit(warn_key)
                    gw.warn_db.inhibit(warn_key, opposite)
                    gw.warn_db.write_if_dirty()
            elif ctx.genre == 'param':
                param_name = getattr(ctx, 'param_name', None)
                if param_name:
                    gw.deactivate_param(param_name)

    def undo_ACTION(self):
        """Handle 'u' key on REVIEW screen - undo parameter change"""
        gw = self.gw
        name, _, _, _, _ = gw.get_enums_regex()
        if name:
            prev_value = gw.prev_values[name]
            gw.param_values[name] = prev_value

    def show_hidden_ACTION(self):
        """Handle 's' key on REVIEW screen - toggle showing hidden warnings"""
        self.gw.show_hidden_warns = not self.gw.show_hidden_warns

    def write_ACTION(self):
        """Handle 'w' key on REVIEW screen - confirm inline, then update grub."""
        diffs = self.gw.get_diffs()
        tag = RESYNC_TAG if not diffs else change_tag(diffs)
        self.gw.begin_commit_confirm(tag or None)

    def slash_ACTION(self):
        """Search is not available on REVIEW; '/' is a no-op."""
        return # does nothing here


class RestoreScreen(GrubWizScreen):
    """RESTORE screen - backup management"""
    come_from_whitelist = [HOME_ST]

    def __init__(self, grub_wiz):
        """Constructor handles initial backup list setup"""
        super().__init__(grub_wiz)
        self.gw.refresh_backup_list()
        self.bak_paths = []
        self.baseline_bak = None  # what to compare to

    def on_resume(self):
        """Refresh backup list when resuming"""
        self.gw.refresh_backup_list()
        return True

    def draw_screen(self):
        self.set_pick_mode(True)
        self.draw_body()
        self.add_head()

    def add_head(self):
        """Add the RESTORE header with the available selection actions."""
        pos, base = self.win.pick_pos, '[c]mp [b]aseline'
        if 0 <= pos < len(self.bak_paths):
            if self.bak_paths[pos] == self.baseline_bak:
                base = ''
        header = f'RESTORE [r]estore [d]el [t]ag [v]iew {base}    ESC:back ?:help [q]uit'
        self.add_fancy_header(header)

    def _ensure_reference(self):
        """ Make sure reference is something valid """
        gw = self.gw
        ref, new_ref = self.baseline_bak, None
        if ref:
            for pair in gw.ordered_backup_pairs:
                if pair[1] == ref:
                    new_ref = ref
                    break
        if not new_ref and gw.ordered_backup_pairs:
            new_ref = gw.ordered_backup_pairs[-1][1]
        self.baseline_bak = new_ref

    def draw_body(self):
        """List every backup, marking the current file and the CMP baseline."""
        gw = self.gw
        if not gw.ordered_backup_pairs:
            return
        self._ensure_reference()
        self.bak_paths = []
        for pair in gw.ordered_backup_pairs:
            checksum, bak_path = pair[0], pair[1]
            is_current = gw.backup_mgr.checksum_matches(checksum, gw.grub_checksum)
            prefix = Glyphs.current() if is_current else ' '
            ref = 'CMP' if self.baseline_bak == bak_path else '   '
            self.bak_paths.append(bak_path)
            self.add_body(f'{prefix} {ref} {bak_path.name}',
                          context=Context(genre='backup', bak_path=bak_path))
            self.add_confirm_item_line(bak_path)

    def baseline_ACTION(self):
        """Handle 'b' key on RESTORE screen - baseline for CMP"""
        gw = self.gw
        pos = self.win.pick_pos
        if 0 <= pos < len(gw.ordered_backup_pairs):
            bak_path = gw.ordered_backup_pairs[pos][1]
            self.baseline_bak = bak_path

    def compare_ACTION(self):
        """Handle 'c' key on RESTORE screen - set in compare mode"""
        gw = self.gw
        idx = self.win.pick_pos
        if 0 <= idx < len(self.bak_paths):
            bak_path = self.bak_paths[idx]
            ref_path = self.baseline_bak
            if bak_path and ref_path and bak_path != ref_path:
                if gw.navigate_to(COMPARE_ST):
                    compare_screen = gw.screens[COMPARE_ST]
                    compare_screen.bak1 = bak_path
                    compare_screen.bak2 = ref_path

    def restore_ACTION(self):
        """Handle 'r' key on RESTORE screen - ask inline, then restore.

        The confirmation is drawn under the picked row and takes one key (``y`` confirms,
        ``ESC`` cancels),
        so the listing and the name of the file being restored stay on screen.
        The restore itself runs from the prompt callback (``restore_chosen``)
        because the answer arrives after this action has returned.
        """
        gw = self.gw
        idx = self.win.pick_pos
        if not 0 <= idx < len(gw.ordered_backup_pairs):
            return
        target = gw.ordered_backup_pairs[idx][1]
        gw.begin_confirm(
            'Restore GRUB source from .bak?',
            on_confirm=lambda _answer: self.restore_chosen(target),
            scope='item', item_key=target)

    def restore_chosen(self, target):
        """Replace the GRUB source with *target* and reload the screens.

        Restore is deliberately the first half of a two-step operation:
        it replaces the GRUB *source* file (the backup manager's target,
        normally ``/etc/default/grub``) and reloads the screens from it,
        but it does **not** run ``update-grub``.  The restored settings become active only
        when the user later writes the configuration.
        That is intentional: a backup can be restored as a baseline
        for further edits without regenerating ``grub.cfg`` mid-session
        (and without the initramfs or reboot churn a write can trigger).
        """
        gw = self.gw
        if not gw.backup_mgr.restore_backup(target):
            reason = getattr(gw.backup_mgr, 'last_error', '') or 'unknown error'
            self.win.alert(message=f'ERR: restore of {target.name!r} failed: {reason}')
            return
        self.win.flash(
            message='OK: /etc/default/grub restored - press w to apply (update-grub)',
            duration=3.0)
        while gw.navigate_back():
            pass
        gw.reinit_gw()
        gw.reset_screen_stack()
        gw.grub_checksum = gw.backup_mgr.calc_checksum(gw.backup_mgr.target_path)

    def delete_ACTION(self):
        """Handle 'd' key on RESTORE screen - ask inline, then unlink.

        One key answers (``y`` or ``ESC``) and the
        prompt sits under the row it would remove.
        The unlink runs from the callback (``delete_chosen``) once the question is gone.
        """
        gw = self.gw
        idx = self.win.pick_pos
        if 0 <= idx < len(gw.ordered_backup_pairs):
            doomed = gw.ordered_backup_pairs[idx][1]
            gw.begin_confirm(
                'Delete .bak?',
                on_confirm=lambda _answer: self.delete_chosen(doomed),
                scope='item', item_key=doomed)

    def delete_chosen(self, doomed):
        """Unlink *doomed* and rebuild the inventory."""
        gw = self.gw
        try:
            os.unlink(doomed)
        except OSError as exce:
            self.win.alert(message=f'ERR: unlink({doomed}) [{exce}]')
        gw.refresh_backup_list()

    def tag_ACTION(self):
        """Handle 't' key on RESTORE screen - tag/retag selected backup

        The tag is asked for inline, under the picked row.
        The rename itself runs from the prompt's callback (``GrubWiz.apply_backup_tag``)
        because the answer arrives after this action has already returned.
        """
        gw = self.gw
        idx = self.win.pick_pos
        if 0 <= idx < len(gw.ordered_backup_pairs):
            chosen = gw.ordered_backup_pairs[idx][1]
            current = gw.backup_mgr.tag_from_name(chosen.name)
            gw.request_backup_tag(chosen, seed=current)

    def view_ACTION(self):
        """Handle 'v' key on RESTORE screen - view selected backup"""
        gw = self.gw
        idx = self.win.pick_pos
        if 0 <= idx < len(gw.ordered_backup_pairs):
            try:
                gw.bak_path = gw.ordered_backup_pairs[idx][1]
                gw.bak_lines = gw.bak_path.read_text().splitlines()
                assert isinstance(gw.bak_lines, list)
                gw.navigate_to(VIEW_ST)
            except (OSError, UnicodeDecodeError) as ex:
                self.win.alert(f'ERR: cannot slurp {gw.bak_path} [{ex}]')

class CompareScreen(BasicTextScreen, GrubWizScreen):
    """COMPARE screen - compare two backups side by side."""
    come_from_whitelist = [RESTORE_ST]

    def __init__(self, grub_wiz):
        """Constructor validates backup data is loaded"""
        super().__init__(grub_wiz)
        self.bak1 = None # will be a Path
        self.bak2 = None # will be a Path
        self.cnt1, self.cnt2 = None, None
        self.results = None

    def on_pop(self):
        """Clean up backup view data when screen is removed"""
        self.results = None
        return True

    def draw_screen(self):
        """Draw the side-by-side comparison and its header."""
        # diff_lines() first: it is what fills in cnt1/cnt2 for the header.
        self.set_text(lines=self.diff_lines(), head=self.head_lines())
        super().draw_screen()

    def head_lines(self):
        """Header naming both backups and their line counts."""
        return ['COMPARE   ESC:back',
                f'< {self.bak1.name} [#lines={self.cnt1}]',
                f'> {self.bak2.name} [#lines={self.cnt2}]']

    def diff_lines(self):
        """Render (and cache) the diff between the two selected backups."""
        def get_val(param, data):
            entry = data.get(param)
            if entry is None:
                return GrubFile.ABSENT, None
            return entry.value, entry.line_num

        gw = self.gw

        if self.results is None:
            self.results, lines = [], []
            grub1 = GrubFile(gw.param_cfg, self.bak1)
            grub2 = GrubFile(gw.param_cfg, self.bak2)
            data1 = grub1.param_data
            data2 = grub2.param_data
            params = sorted(list(set(data1.keys()) | set(data2.keys())))
            self.cnt1 = len(grub1.lines)
            self.cnt2 = len(grub2.lines)

            for param in params:
                value1, num1 = get_val(param, data1)
                value2, num2 = get_val(param, data2)
                if value1 == value2:
                    continue
                line1 = '' if num1 is None else grub1.lines[num1].strip()
                line2 = '' if num2 is None else grub2.lines[num2].strip()

                lines.append('')

                prefix1 = '< '
                content1 = line1
                lines.append(prefix1 + content1)

                prefix2 = '> '
                content2 = line2
                lines.append(prefix2 + content2)

            self.results = lines

        cols = self.win.cols
        wid = cols - 3  # Account for '< ' or '> ' prefix (2 chars) + margin
        wrapped = []
        for line in self.results:
            if not line:
                wrapped.append('')
                continue

            if line.startswith('< ') or line.startswith('> '):
                prefix = line[:2]
                content = line[2:]

                if len(line) <= cols - 1:
                    wrapped.append(line)
                else:
                    wrapped.append(prefix + content[:wid])
                    content = content[wid:]

                    while content:
                        indent = '  '  # 2 spaces to align with content after prefix
                        chunk_size = cols - len(indent) - 1
                        wrapped.append(indent + content[:chunk_size])
                        content = content[chunk_size:]
            else:
                wrapped.append(line)
        return wrapped


class ViewScreen(GrubWizScreen):
    """VIEW screen - view backup contents"""
    # Can only be accessed from RESTORE screen
    come_from_whitelist = [RESTORE_ST]

    def on_pop(self):
        """Clean up backup view data when screen is removed"""
        self.gw.bak_lines = None
        self.gw.bak_path = None
        return True

    def draw_screen(self):
        """Draw the selected backup's contents and its header."""
        self.set_pick_mode(False)
        self.draw_body()
        self.add_head()

    def add_head(self):
        """Add the VIEW header naming the displayed backup."""
        gw = self.gw
        header = f'VIEW  {gw.bak_path.name!r}  ESC:back ?:help [q]uit'
        self.add_fancy_header(header)

    def draw_body(self):
        """Render the selected backup with line numbers and wrapping."""
        gw = self.gw
        wid = self.win.cols - 7 # 4 num + SP before + 2SP after
        indent = ' ' * 6 # align wrapped text past the 4-digit index column
        for idx, line in enumerate(gw.bak_lines):
            self.add_body(f'{idx:>4}', attr=cs.A_BOLD)
            self.add_body(f'  {line[:wid]}', resume=True)
            line = line[wid:]
            while line:
                self.add_body(f'{indent}{line[:wid]}')
                line = line[wid:]

class WarnScreen(GrubWizScreen):
    """WARNINGS Screen"""
    come_from_whitelist = [HOME_ST, REVIEW_ST]

    def __init__(self, grub_wiz):
        """Constructor initializes search state"""
        super().__init__(grub_wiz)
        self.search = ''
        self.regex = None  # compiled
        self._entry_param = None
        self._entry_warn_key = None

    def set_entry_from_context(self, context):
        """Remember the REVIEW row that W came from for the next draw.

        A selected warning row has one exact target.
        A selected parameter row asks for the first
        warning under that parameter that is still shown,
        or the first inhibited one when every warning for it is hidden.
        """
        self._entry_param = None
        self._entry_warn_key = None
        if context is None:
            return
        genre = getattr(context, 'genre', '')
        if genre == 'warn':
            warn_key = getattr(context, 'warn_key', None)
            if warn_key:
                self._entry_warn_key = warn_key
                self._entry_param = warn_key.split(': ', 1)[0]
        elif genre == 'param':
            self._entry_param = getattr(context, 'param_name', None)

    def on_pop(self):
        """Save any changes when screen is removed"""
        self.gw.warn_db.write_if_dirty()
        return True

    def draw_screen(self):
        """Draw the warnings-configuration body and header."""
        self.set_pick_mode(True)
        self.draw_body()
        self.draw_head()

    def draw_head(self):
        """Add the WARNINGS-CONFIG header with the inhibit action and search."""
        gw = self.gw
        db = gw.warn_db
        ctx = self.win.get_picked_context()
        inh = False
        if ctx and ctx.genre == 'warn':
            warn_key = getattr(ctx, 'warn_key', None)
            if warn_key:
                inh = db.is_inhibit(warn_key)
        line = 'WARNINGS-CONFIG'
        line += f"   [x]:{'allow-warning' if inh else 'inhibit-warning'}"
        line += '   ?:help'
        # Show search bar (with cursor if active, or just text if not)
        line += gw.search_bar.get_display_string(prefix='   /')
        line += '   ESC:back [q]uit'
        self.add_fancy_header(line)


    def refresh_warn_info(self):
        """ Recompute warning metadata from the live parameter values."""
        gw = self.gw
        warns, all_warn_info = gw.wiz_validator.make_warns(gw.param_values)
        gw.warn_db.audit_info(all_warn_info)
        return warns

    def draw_body(self):
        """List every known warning, filtered by the search regex."""
        gw = self.gw
        warns = self.refresh_warn_info()
        db = gw.warn_db
        all_info = db.all_info
        keys = sorted(all_info.keys())
        prev_param = None
        entry_param = self._entry_param
        entry_warn_key = self._entry_warn_key
        self._entry_param = self._entry_warn_key = None
        current_keys = set()
        if entry_param:
            for _stars, message in warns.get(entry_param, []):
                current_keys.add(WarnDB.make_key(entry_param, message))
        rows_by_key = {}
        first_shown = first_hidden = None
        row = 0

        for key in keys:
            sev = all_info[key]
            stars = Glyphs.sev_star() * sev

            inh = 'X' if db.is_inhibit(key) else ' '

            # Split key into param_name and message
            if ': ' in key:
                param_name, message = key.split(': ', 1)
                # Strip GRUB_ prefix
                display_param = param_name.replace('GRUB_', '', 1)

                # Create full line for searching (always has param name)
                full_line = f'[{inh}] {stars:>4} {display_param}: {message}'

                # Check if same param as previous DISPLAYED line
                if param_name == prev_param:
                    # Omit param name, just show message with proper spacing
                    line = f'[{inh}] {stars:>4} {" " * (len(display_param) + 2)}{message}'
                else:
                    # Show full line with param name
                    line = full_line
            else:
                # No colon in key, show as-is
                full_line = line = f'[{inh}] {stars:>4} {key}'
                param_name = None

            # Search against full_line, but display line
            if not self.regex or self.regex.search(full_line):
                if entry_param and key in current_keys:
                    if db.is_inhibit(key):
                        if first_hidden is None:
                            first_hidden = row
                    elif first_shown is None:
                        first_shown = row
                rows_by_key[key] = row
                self.add_body(line, context=Context(genre='warn', warn_key=key))
                # Only update prev_param for lines that are actually displayed
                prev_param = param_name
                row += 1

        target_row = rows_by_key.get(entry_warn_key) if entry_warn_key else None
        if target_row is None:
            target_row = (first_shown if first_shown is not None
                          else first_hidden)
        if target_row is not None:
            self.win.pick_pos = target_row


    def hide_ACTION(self):
        """Toggle suppression of the selected warning."""
        gw = self.gw
        ctx = self.win.get_picked_context()
        if ctx and ctx.genre == 'warn':
            warn_key = getattr(ctx, 'warn_key', None)
            if warn_key:
                opposite = not gw.warn_db.is_inhibit(warn_key)
                gw.warn_db.inhibit(warn_key, opposite)
                gw.warn_db.write_if_dirty()

    def slash_ACTION(self):
        """Start the inline search prompt with a movable caret."""
        self.gw.search_bar.start(self.search)
        self.gw.win.passthrough_mode = True

class _PrefsThemeStore:
    """``ThemeStore`` over the running application's ``UiPrefs``."""
    @staticmethod
    def _prefs():
        return getattr(GrubWiz.singleton, 'prefs', None)

    def load(self):
        prefs = self._prefs()
        return prefs.load() if prefs is not None else None

    def save(self, name):
        prefs = self._prefs()
        if prefs is None:
            return
        GrubWiz.singleton.theme_name = name
        prefs.save(name)


#: One store object, shared by the CLI help text and the picker.
PREFS_THEME_STORE = _PrefsThemeStore()


ThemeScreen = Theme.create_picker_screen(
    GrubWizScreen,
    cycle_key='t',
    store=PREFS_THEME_STORE,
    note='The choice is remembered for the next start.')


class HelpScreen(GrubWizScreen, BasicHelpScreen):
    """HELP screen: nav keys, the scoped option list, notes, and font check."""

    def extra_help_paragraphs(self):
        """Non-binding copy: the theme picker and what it remembers."""
        return (display_help.theme_paragraph('T', 't', remembered=True),)


# --- Shell-value validation for /etc/default/grub --------------------------
#
# A parameter value is written verbatim after ``PARAM=``
# and the file is *sourced* by the distro's GRUB scripts.
# The value must therefore stay a single shell word: spaces
# split the assignment (``PARAM=a reboot`` runs ``reboot``),
# ``;``/``&``/``|`` chain commands, ``$``/backticks expand, and ``#`` starts a comment.
# Everything else that GRUB values commonly use (``, = + : / @ %``, brackets,
# etc.) is fine unquoted.
# Command substitution is accepted only for parameters whose ``_re_specs_``
# entry opts in with ``allow_command_sub: true`` (GRUB_DISTRIBUTOR), or in expert-edit mode.

_UNQUOTED_FORBIDDEN = frozenset(' \t\n\r\x0b\x0c\'"\\$`;&|<>(){}!#~')


def _is_control_char(char):
    """True for C0/DEL control characters, which must never be written."""
    return ord(char) < 0x20 or ord(char) == 0x7f


def _check_command_substitution(value):
    """Validate a whole-value ``$(...)`` command substitution."""
    depth = 0
    quote = None
    escaped = False
    for index, char in enumerate(value):
        if escaped:
            escaped = False
            continue
        if quote:
            if char == quote:
                quote = None
            elif char == '\\' and quote == '"':
                escaped = True
            continue
        if char in ('"', "'"):
            quote = char
        elif char == '\\':
            escaped = True
        elif char == '(':
            depth += 1
        elif char == ')':
            depth -= 1
            if depth < 0:
                return False, "unbalanced ')' in command substitution"
            if depth == 0 and index != len(value) - 1:
                return False, 'command substitution must be the whole value'
    if quote:
        return False, 'unterminated quote in command substitution'
    if depth != 0:
        return False, "unbalanced '(' in command substitution"
    return True, ''


def check_shell_value(value, allow_command_sub=False):
    """Check that *value* can be written as ``PARAM=value`` safely."""
    if not value:
        return True, ''
    if any(_is_control_char(char) for char in value):
        return False, 'value contains a control character'

    if value[0] == "'":
        if len(value) < 2 or value[-1] != "'":
            return False, "single-quoted value must end with '"
        if "'" in value[1:-1]:
            return False, "use \"'\\''\" to put a single quote inside '...'"
        return True, ''

    if value[0] == '"':
        if len(value) < 2 or value[-1] != '"':
            return False, 'double-quoted value must end with "'
        inner = value[1:-1]
        index = 0
        while index < len(inner):
            char = inner[index]
            if char == '\\':
                if index + 1 < len(inner) and inner[index + 1] in '\\"':
                    index += 2
                    continue
                return False, 'only \\\\ and \\" are allowed inside "..."'
            if char in '"$`':
                return False, ('no expansion or command substitution inside '
                               '"..."; use an unquoted $(...) if intended')
            index += 1
        return True, ''

    if value.startswith('$('):
        if not allow_command_sub:
            return False, 'command substitution is not allowed for this parameter'
        return _check_command_substitution(value)

    if value[0] == '`':
        if not allow_command_sub:
            return False, 'command substitution is not allowed for this parameter'
        if len(value) < 2 or value[-1] != '`':
            return False, 'backtick command substitution must end with a backtick'
        if '`' in value[1:-1]:
            return False, 'backtick command substitution cannot contain a backtick'
        return True, ''

    forbidden = sorted(set(value) & _UNQUOTED_FORBIDDEN)
    if forbidden:
        shown = ' '.join(repr(char) for char in forbidden)
        return False, f'quote the value; unquoted {shown} is interpreted by the shell'
    return True, ''


def prompt_line(prompt: str, default: str = '') -> str:
    """``input()`` that survives a closed or non-interactive stdin."""
    try:
        return input(prompt)
    except EOFError:
        return default


def prompt_key(win, seconds: float):
    """Return one key, turning Ctrl-C into the quit key."""
    try:
        return win.prompt(seconds=seconds)
    except KeyboardInterrupt:
        return QUIT_KEY


class GrubWiz:
    """Application state and behavior for the grub-wiz TUI."""
    singleton = None

    long_params = ('GRUB_CMDLINE_LINUX GRUB_CMDLINE_LINUX_DEFAULT'
            ' GRUB_CMDLINE_XEN_DEFAULT GRUB_BADRAM GRUB_PRELOAD_MODULES'
            ' GRUB_SERIAL_COMMAND GRUB_GFXMODE GRUB_THEME GRUB_BACKGROUND'
            ' GRUB_TERMINAL_INPUT GRUB_TERMINAL_OUTPUT').split()

    def __init__(self, cli_opts=None):
        GrubWiz.singleton = self
        self.cli_opts = cli_opts
        self.win = None # place 1st
        self.canned_config = CannedConfig()
        self.distro_vars = DistroVars(self.canned_config.data)
        self.spinner = None
        self.spins = None
        self.sections = None
        self.param_cfg = None
        self.hidden_stats = None
        self.prev_pos = None
        self.defined_param_names = None # all of them
        self.param_names = None
        self.param_values = None
        self.saved_active_param_values = None # for deactivate/activate scenario
        self.param_defaults = None
        self.prev_values = None
        self.param_name_wid = 0
        self.menu_entries = None
        self.backup_mgr = BackupMgr(target_path=Path(self.distro_vars.etc_grub))
        self.warn_db = None
        self.grub_writer = GrubWriter(distro_vars=self.distro_vars)
        self.param_discovery = ParamDiscovery.get_singleton()
        self.wiz_validator = None
        self.backups = None
        self.ordered_backup_pairs = None
        self.must_reviews = None
        self.clues = []
        self.next_prompt_seconds = [3.0]
        self.ss = None
        self.prefs = UiPrefs()
        self.theme_name = initial_theme_name(
            getattr(cli_opts, 'theme', None) if cli_opts else None, self.prefs)
        self.running = True
        self.is_other_os = None # don't know yet
        self.show_hidden_params = False
        self.show_hidden_warns = False
        self.grub_checksum = ''
        self.bak_lines = None # the currently viewed .bak file
        self.bak_path = None
        self.screens = []
        self.confirm_scope, self.confirm_item_key = 'header', None
        self.reinit_gw()

    CONFIRM_GAP = '  '

    @staticmethod
    def confirm_glyph():
        """The active question marker (Unicode, or ASCII under ``--ascii``)."""
        return Glyphs.alert()

    @classmethod
    def confirm_answer_hint(cls, mode):
        """Trailing answer hint for the one-key confirmations."""
        return cls.CONFIRM_GAP.join((f'["{mode}" or ESC]', Glyphs.alert()))

    def begin_confirm(self, prompt, *, on_confirm=None, on_cancel=None,
                      mode='y', seed='', scope='header', item_key=None,
                      hint=''):
        """Start an inline confirmation; return False without a window."""
        if self.win is None:
            return False
        self.confirm_scope, self.confirm_item_key = scope, item_key
        return self.win.begin_prompt(
            f'{self.confirm_glyph()}{self.CONFIRM_GAP}{prompt}',
            hint=hint, mode=mode, seed=seed,
            on_confirm=on_confirm,
            on_cancel=on_cancel,
            answer_hint=self.confirm_answer_hint(mode))

    def begin_commit_confirm(self, tag=None):
        """Ask inline, then commit; the action applies to the whole program."""
        return self.begin_confirm(
            'Commit changes and update GRUB?',
            on_confirm=lambda _answer: self.update_grub(tag=tag, confirmed=True),
            scope='header')

    def reset_screen_stack(self):
        """Rebuild the screen stack after /etc/default/grub is replaced."""
        self.ss = ScreenStack(self.win, self.spins, SCREENS, self.screens)
        if self.spinner is not None:
            self.spinner.stack = self.ss
            self.ss.spinner = self.spinner
            self.ss.obj = self.spinner.default_obj

    def reinit_gw(self):
        """ Call to initialize or re-initialize with new /etc/default/grub """
        self.param_cfg = {}
        self.param_values, self.prev_values = {}, {}
        self.saved_active_param_values = {}
        self.param_defaults = {}
        self.must_reviews = None
        self.ss = None
        self.sections = copy.deepcopy(self.canned_config.data)
        section_names = list(self.sections.keys())
        for section_name in section_names:
            if section_name.startswith('_'):
                del self.sections[section_name]

        self.param_discovery.ensure_discovered()

        names = []
        for params in self.sections.values():
            for name in params.keys():
                names.append(name)
        absent_param_names = set(self.param_discovery.get_absent(names))
        self.defined_param_names = names

        for params in self.sections.values():
            for param_name, cfg in params.items():
                if param_name not in absent_param_names:
                    self.param_cfg[param_name] = cfg
                    self.param_defaults[param_name] = cfg['default']
        if self.wiz_validator is None:
            initramfs_tool = (os.path.basename(self.distro_vars.update_initramfs)
                              if self.distro_vars.update_initramfs else None)
            self.wiz_validator = WizValidator(self.param_cfg,
                                              initramfs_tool=initramfs_tool)
        else:
            self.wiz_validator.bind_param_cfg(self.param_cfg)

        self.grub_file = GrubFile(supported_params=self.param_cfg,
                                  file_path=self.distro_vars.etc_grub)
        if self.grub_file.extra_params:
            section_name = 'Unvalidated Params'
            extras = {}
            for extra, cfg in self.grub_file.extra_params.items():
                extras[extra] = cfg
                self.param_cfg[extra] = cfg
                self.param_defaults[extra] = cfg['default']
            self.sections[section_name] = extras
        self.param_names = list(self.param_cfg.keys())
        self.prev_pos = -1024  # to detect direction

        name_wid = 0
        for param_name in self.param_names:
            name_wid = max(name_wid, len(param_name))
            value = self.grub_file.param_data[param_name].value
            self.param_values[param_name] = value
        self.param_name_wid = name_wid - len('GRUB_')
        self.prev_values.update(self.param_values)
        self.menu_entries = get_top_level_grub_entries(
                                self.distro_vars.grub_cfg)
        try:
            self.param_cfg['GRUB_DEFAULT']['enums'].update(
                entries_to_enums(self.menu_entries))
        except (KeyError, AttributeError, TypeError):
            # GRUB_DEFAULT is filtered out or has no enum mapping;
            # menu entries are then simply not offered as choices.
            pass
        self.warn_db = WarnDB(param_cfg=self.param_cfg)

        warns, all_warn_info = self.wiz_validator.make_warns(self.param_values)
        self.warn_db.audit_info(all_warn_info)
        self.warn_db.write_if_dirty()  # Persist any cleanup from orphaned warnings

        self.refresh_backup_list()

    def register_keys(self, spinner):
        """Register every application key on *spinner*."""

        spinner.add_key('help_mode', '? - enter help screen', genre='action')

        spinner.add_key('cycle_next', 'RIGHT,SP - next cycle value',
                        genre='action', keys=[cs.KEY_RIGHT, ord(' ')])
        spinner.add_key('cycle_prev', 'LEFT,BS,C - prev cycle value',
                        genre='action',
                        keys=[ord('C'), cs.KEY_LEFT, cs.KEY_BACKSPACE])
        spinner.add_key('edit', 'e - edit value', genre='action')
        spinner.add_key('expert_edit', 'E - expert edit (minimal validation)',
                        genre='action', keys=[ord('E')])
        spinner.add_key('undo', 'u - revert value', genre='action')

        spinner.add_key('hide', 'x - inh/allow warnings', genre='action')
        spinner.add_key('show_hidden', 's - show/hide inactive params',
                        genre='action')
        spinner.add_key('write', 'w - write params and run "grub-update"',
                        genre='action')

        spinner.add_key('guide', 'g - guidance level',
                        vals=['Off', 'Enums', 'Full'])
        spinner.add_key('fancy_headers',
                        'f - cycle fancy headers (Off/Underline/Reverse)',
                        vals=['Underline', 'Reverse', 'Off'])

        spinner.add_key('enter_restore', 'R - enter restore screen',
                        genre='action')
        spinner.add_key('enter_warnings', 'W - enter WARNINGs screen',
                        genre='action')

        spinner.add_key('restore',
                        'r - restore selected backup [in restore screen]',
                        genre='action')
        spinner.add_key('delete',
                        'd - delete selected backup [in restore screen]',
                        genre='action')
        spinner.add_key('tag',
                        't - tag/retag a backup file [in restore screen]',
                        genre='action')
        spinner.add_key('view',
                        'v - view a backup file [in restore screen]',
                        genre='action')
        spinner.add_key('baseline',
                        'b - set CMP baseline [in restore screen]',
                        genre='action')
        spinner.add_key('compare',
                        'c - compare with baseline [in restore screen]',
                        genre='action')

        spinner.add_key('slash', '/ - filter pattern [in WARNINGS screen]',
                        genre='action')

        spinner.add_key('_search_enter', '', keys=[10, 13])
        spinner.add_key('show_keys', 'K - show keys (demo mode)',
                        genre='action')

        spinner.add_key('theme_screen', 'T - color theme picker',
                        genre='action')
        spinner.add_key('spin_theme', 't - cycle color theme', genre='action')

    def setup_win(self):
        """Create the console window, screens, key bindings, and search bars."""
        # LEFT/RIGHT drive cycle_prev/cycle_next on this app.
        win_opts = ConsoleWindowOpts(
            head_line=True,
            ctrl_c_terminates=False,
            return_if_pos_change=True,
            single_cell_scroll_indicator=True,
            dialog_abort='ESC',
            answer_show_redraws=self.cli_opts.answer_timeout_debug,
            min_cols_rows=(70, 10),  # Allow smaller terminals (down from default 20 rows)
            taken_nav_keys=TAKEN_NAV_KEYS,
            theme=self.theme_name,
        )

        # Create ConsoleWindow first (needed by screen objects)
        self.win = ConsoleWindow(win_opts)
        self.win.prompt_separator_attr = cs.A_DIM

        import curses
        rows, cols = self.win.scr.getmaxyx()
        min_cols, min_rows = win_opts.min_cols_rows
        while rows < min_rows or cols < min_cols:
            self.win.scr.clear()
            error_msg = f"Terminal too small: {cols}x{rows} (need at least {min_cols}x{min_rows})"
            try:
                self.win.scr.addstr(0, 0, error_msg, curses.A_REVERSE)
                self.win.scr.addstr(2, 0, "Please resize your terminal to continue...")
                self.win.scr.addstr(3, 0, "(or press ESC to exit)")
            except curses.error:
                pass  # Terminal too small even for error message
            self.win.scr.refresh()
            key = self.win.scr.getch()
            if key == 27:  # ESC key
                self.win.stop_curses()
                print(f"\n{error_msg}")
                print(f"Please resize your terminal to at least {min_cols}x{min_rows} and try again.\n")
                import sys
                sys.exit(1)
            if key == curses.KEY_RESIZE:
                curses.update_lines_cols()
            rows, cols = self.win.scr.getmaxyx()

        # Initialize screen objects and ScreenStack (with None for spins - will be set later)
        self.screens = {
            HOME_ST: HomeScreen(self),
            REVIEW_ST: ReviewScreen(self),
            RESTORE_ST: RestoreScreen(self),
            VIEW_ST: ViewScreen(self),
            COMPARE_ST: CompareScreen(self),
            WARN_ST: WarnScreen(self),
            HELP_ST: HelpScreen(self),
            THEME_ST: ThemeScreen(self),
        }
        self.ss = ScreenStack(self.win, None, SCREENS, self.screens)

        spinner = self.spinner = OptionSpinner(stack=self.ss,
                                               nav_keys=win_opts.nav_keys,
                                               escape_keys=[27])
        self.spins = self.spinner.default_obj
        self.register_keys(spinner)

        # Create the inline search prompt for WarnScreen filtering
        def on_search_change(text):
            """ Compile the search regex incrementally as user types. """
            warn_screen = self.screens.get(WARN_ST)
            if warn_screen:
                warn_screen.search = text
                try:
                    warn_screen.regex = re.compile(text, re.IGNORECASE) if text else None
                except re.error:
                    # Invalid regex, keep previous regex
                    pass

        def on_search_accept(text):
            """ Finalize search: ensure the text is saved and exit passthrough mode. """
            warn_screen = self.screens.get(WARN_ST)
            if warn_screen:
                warn_screen.search = text
                try:
                    warn_screen.regex = re.compile(text, re.IGNORECASE) if text else None
                except re.error:
                    # Invalid regex at end - keep previous regex
                    pass
            self.win.passthrough_mode = False

        def on_search_cancel(original_text):
            """ Restore original search text and exit passthrough mode. """
            warn_screen = self.screens.get(WARN_ST)
            if warn_screen:
                warn_screen.search = original_text
                try:
                    warn_screen.regex = re.compile(original_text, re.IGNORECASE) if original_text else None
                except re.error:
                    warn_screen.regex = None
            self.win.passthrough_mode = False

        self.search_bar = InlineSearchPrompt(
            on_change=on_search_change,
            on_accept=on_search_accept,
            on_cancel=on_search_cancel
        )

        def on_home_search_change(text):
            """ Compile the search regex incrementally as user types. """
            home_screen = self.screens.get(HOME_ST)
            if home_screen:
                home_screen.search = text
                try:
                    home_screen.regex = re.compile(text, re.IGNORECASE) if text else None
                except re.error:
                    # Invalid regex, keep previous regex
                    pass

        def on_home_search_accept(text):
            """ Finalize search: ensure the text is saved and exit passthrough mode """
            home_screen = self.screens.get(HOME_ST)
            if home_screen:
                home_screen.search = text
                try:
                    home_screen.regex = re.compile(text, re.IGNORECASE) if text else None
                except re.error:
                    # Invalid regex at end - keep previous regex
                    pass
            self.win.passthrough_mode = False

        def on_home_search_cancel(original_text):
            """ Restore original search text and exit passthrough mode. """
            home_screen = self.screens.get(HOME_ST)
            if home_screen:
                home_screen.search = original_text
                try:
                    home_screen.regex = re.compile(original_text, re.IGNORECASE) if original_text else None
                except re.error:
                    home_screen.regex = None
            self.win.passthrough_mode = False

        self.home_search_bar = IncrementalSearchBar(
            on_change=on_home_search_change,
            on_accept=on_home_search_accept,
            on_cancel=on_home_search_cancel
        )

        self.win.set_handled_keys(self.spinner)

    def get_enums_regex(self):
        """Return the selected parameter's name, config, enums, regex, and value."""
        enums, regex, param_name, value = None, None, None, None
        if self.ss.is_curr((REVIEW_ST, HOME_ST)):
            # Get context for the current line
            ctx = self.win.get_picked_context()
            if ctx and ctx.genre == 'param':
                param_name = getattr(ctx, 'param_name', None)
        if not param_name:
            return '', {}, {}, '', None

        cfg = self.param_cfg[param_name]
        enums = cfg.get('enums', None)
        regex = cfg.get('edit_re', None)
        value = self.param_values.get(param_name, None)
        return param_name, cfg, enums, regex, value


    def is_warn_hidden(self, param_name, hey):
        """True when the warning is inhibited and hidden warnings are off."""
        if not self.show_hidden_warns:
            warn_key = f'{param_name} {hey[1]}'
            return self.warn_db.is_inhibit(warn_key)
        return False

    def get_diffs(self):
        """ get the key/value pairs with differences"""
        diffs = {}
        for key, value in self.prev_values.items():
            new_value = self.param_values[key]
            if str(value) != str(new_value):
                diffs[key] = (value, new_value)
        return diffs

    def has_live_item_confirm(self, item_key):
        """True when the live inline prompt belongs to *item_key*."""
        return bool(self.win is not None and self.win.prompt_active
                    and self.confirm_scope == 'item'
                    and self.confirm_item_key == item_key)




    def is_active_param(self, param_name):
        """ is the param neither commented out nor absent? """
        value = self.param_values.get(param_name, None)
        if value is not None:
            if value not in (GrubFile.COMMENT, GrubFile.ABSENT):
                return True
            return False
        # A parameter with no known value is not an active parameter.
        return False

    _NON_WRITABLE_DEFAULTS = ('#comment', '#absent',
                              GrubFile.COMMENT, GrubFile.ABSENT)

    def _activation_default(self, param_name):
        """Return a writable value for activating ``param_name``."""
        cfg = self.param_cfg.get(param_name, {})
        default = cfg.get('default', '')
        if default is None or default in self._NON_WRITABLE_DEFAULTS:
            enums = cfg.get('enums') or {}
            default = next(iter(enums), '')
        return default

    def activate_param(self, param_name):
        """Give a commented or absent parameter a writable value.

        Returns ``True`` when a value was restored or defaulted,
        ``False`` when the parameter was already active.
        """
        value = self.param_values.get(param_name, None)
        if value in (GrubFile.COMMENT, GrubFile.ABSENT):
            value = self.saved_active_param_values.get(param_name, None)
            if value is None:
                value = self._activation_default(param_name)
            self.param_values[param_name] = value
            return True
        return False # or False is better?

    def deactivate_param(self, param_name):
        """ make a param inactive by commenting it out
            - save the value in case activated
        """
        value = self.param_values.get(param_name, None)
        if value not in (GrubFile.COMMENT, GrubFile.ABSENT):
            self.saved_active_param_values[param_name] = value
            if self.prev_values[param_name] == GrubFile.ABSENT:
                self.param_values[param_name] = GrubFile.ABSENT
            else:
                self.param_values[param_name] = GrubFile.COMMENT
            return True
        return False




    def drop_down_lines(self, param_name):
        """Build the guidance and enum lines shown under the selected parameter."""
        def gen_enum_lines():
            nonlocal cfg, wid
            enums = cfg['enums']
            if not enums:
                return []
            value = self.param_values[param_name]
            edit = ' or [e]dit' if has_edit_regex(cfg['edit_re']) else ''
            wrapped = f': {Glyphs.nav()} {edit}:\n'
            for enum, descr in cfg['enums'].items():
                # The catalog's resolved-choice marker, one cell in both modes;
                # an unselected entry keeps the column blank.
                marker = (Glyphs.get('choice') if str(enum) == str(value)
                          else ' ')
                line = f'  {marker} {enum}: {descr}\n'
                wrapped += textwrap.fill(line, width=wid-1, subsequent_indent=' '*5)
                wrapped += '\n'
            return wrapped.split('\n')

        if self.spins.guide == 'Off':
            return []

        cfg = self.param_cfg.get(param_name, None)
        if not cfg:
            return ''
        emits, wraps = [], [] # lines to emit
        lead = '    '
        wid = self.win.cols - len(lead)

        if self.spins.guide == 'Full':
            text = cfg['guidance']
            lines = text.split('\n')
            for line in lines:
                if line.strip() == '%ENUMS%':
                    wraps += gen_enum_lines()
                else:
                    wrapped = textwrap.fill(line, width=wid-1, subsequent_indent=' '*5)
                    wraps += wrapped.split('\n')
        elif self.spins.guide == 'Enums':
            wraps += gen_enum_lines()
        emits = [f'{lead}{wrap}' for wrap in wraps if wrap]
        return emits

    @staticmethod
    def _answer_height(param_name):
        return 5 if param_name in GrubWiz.long_params else 1

    def _param_edit_hint(self, name, regex):
        """Short reminder of what the parameter accepts (dialog title hint)."""
        human_desc = self.param_cfg.get(name, {}).get('edit_re_human', '')
        if human_desc:
            return human_desc
        if not regex:
            return ''
        pure_regex = (regex.pattern if hasattr(regex, 'pattern')
                      else str(regex).encode().decode('unicode_escape'))
        return f'pat={pure_regex}'

    def _check_param_value(self, name, value, regex):
        """Return why *value* is refused, or '' when it may be stored."""
        cfg = self.param_cfg.get(name, {})
        if regex:
            # Handle both compiled patterns and string patterns
            if hasattr(regex, 'match'):
                matched = regex.match(str(value))
            else:
                matched = re.match(regex, str(value))
            if not matched:
                if cfg.get('edit_re_human'):
                    return f'must be: {cfg["edit_re_human"]}'
                pure_regex = (regex.pattern if hasattr(regex, 'pattern')
                              else str(regex).encode().decode('unicode_escape'))
                return f'must match: {pure_regex}'
        ok, reason = check_shell_value(
            value, allow_command_sub=bool(cfg.get('allow_command_sub', False)))
        if not ok:
            return f'must be a safe shell value ({reason})'
        return ''

    @staticmethod
    def _check_expert_value(value):
        """Expert mode still has to stay one shell word, nothing more."""
        ok, reason = check_shell_value(value, allow_command_sub=True)
        return '' if ok else f'must be a safe shell value ({reason})'

    def begin_param_edit(self, name, check, seed=None, hint='', invalid=False):
        """Type a value on a line under its parameter row.

        *check* returns '' for an acceptable answer and the reason otherwise.
        *hint* is drawn dim on the line below the prompt and says what the value may be
        -- before any mistake, not only after one
        -- so the prompt line itself only has to say how to finish.
        *invalid* only changes its wording: the refused text stays in the buffer, editable.

        The buffer starts as a copy of the current value; the row above keeps
        showing the old value, and ESC leaves ``param_values`` untouched.
        """
        if seed is None:
            seed = str(self.param_values.get(name, ''))
        prompt = ('Re-edit value, then ENTER or ESC' if invalid
                  else 'Edit value, then ENTER or ESC')
        return self.begin_confirm(
            prompt,
            on_confirm=lambda answer: self._apply_param_edit(
                name, answer, check, hint),
            mode='text', seed=seed, scope='item', item_key=name, hint=hint)

    def _apply_param_edit(self, name, value, check, hint=''):
        """Store the inline answer, or ask again with the text still there."""
        if check(value):
            self.begin_param_edit(name, check, seed=value, hint=hint,
                                  invalid=True)
            return
        self.param_values[name] = value

    def edit_param(self, win, name, regex):
        """Ask for the value until the answer is valid."""
        if is_expert_edit(regex):
            self.expert_edit_param(win, name)
            return

        check = lambda value: self._check_param_value(name, value, regex)  # noqa: E731
        if self._answer_height(name) == 1:
            self.begin_param_edit(name, check,
                                  hint=self._param_edit_hint(name, regex))
            return

        value = self.param_values[name]
        hint = self._param_edit_hint(name, regex)
        while True:
            prompt = f'Edit {name} [{hint}]'
            value = win.answer(prompt=prompt, seed=str(value),
                               height=self._answer_height(name))
            if value is None: # aborted
                return
            hint = check(value)
            if not hint:
                break
            win.flash(f'Invalid input - {hint}', duration=1.5)
        self.param_values[name] = value

    def expert_edit_param(self, win, name):
        """ Expert mode edit with minimal validation - escape hatch for grub-wiz errors """
        if self._answer_height(name) == 1:
            self.begin_param_edit(name, self._check_expert_value,
                                  hint='expert mode: minimal checks')
            return

        value = self.param_values[name]
        hint = 'expert mode: minimal checks'
        while True:
            prompt = f'Edit {name} [EXPERT MODE: {hint}]'
            value = win.answer(prompt=prompt, seed=str(value),
                               height=self._answer_height(name))
            if value is None: # aborted
                return
            hint = self._check_expert_value(value)
            if not hint:
                break
            win.flash(f'Unsafe value - {hint}', duration=2.0)
        self.param_values[name] = value

    def _is_valid_shell_token(self, value, allow_command_sub=False):
        """Return True when *value* is safe as a shell assignment value."""
        ok, _reason = check_shell_value(value, allow_command_sub)
        return ok

    def refresh_backup_list(self):
        """Rebuild the full backup inventory, newest first."""
        self.backups = self.backup_mgr.get_backups()
        self.ordered_backup_pairs = sorted(
            ((self.backup_mgr.checksum_from_name(name), path)
             for name, path in self.backups.items()),
            key=lambda item: self.backup_mgr.sort_key(item[1]),
            reverse=True,
        )

    @staticmethod
    def fold_backup_tag(answer):
        """Fold an entered tag into on-disk form without judging it.

        Generated tags use '+', '-' and '~', so a handwritten tag may use them too;
        runs of spaces and dashes become a single '-'.
        """
        return re.sub(r'[-\s]+', '-', (answer or '').strip())

    @classmethod
    def is_valid_backup_tag(cls, tag):
        """True when *tag* is a name BackupMgr can put in a filename."""
        return bool(BACKUP_TAG_PATTERN.match(tag or ''))

    def request_backup_tag(self, chosen, seed='', invalid=False):
        """Ask, in place, for the tag of the backup *chosen*."""
        prompt = ('Invalid tag, then ENTER or ESC' if invalid
                  else 'Edit tag, then ENTER or ESC')
        return self.begin_confirm( prompt,
            on_confirm=lambda answer: self.apply_backup_tag(chosen, answer),
            mode='text', seed=seed, scope='item', item_key=chosen)

    def apply_backup_tag(self, chosen, answer):
        """Rename *chosen* to the tag the inline prompt accepted."""
        tag = self.fold_backup_tag(answer)
        if not self.is_valid_backup_tag(tag):
            self.request_backup_tag(chosen, seed=tag, invalid=True)
            return
        new_name = self.backup_mgr.retagged_name(chosen.name, tag)
        new_path = chosen.parent / new_name
        if new_path != chosen:
            if os.path.lexists(new_path):
                self.win.status(text=f'ERR: {new_path.name} already exists',
                                level='error', timeout=5.0)
            else:
                try:
                    os.rename(chosen, new_path)
                except OSError as exce:
                    self.win.status(
                        text=f'ERR: rename({chosen.name}, {new_path.name}) [{exce}]',
                        level='error', timeout=5.0)
        self.refresh_backup_list()

    def do_start_up_backup(self):
        """Record the first state ever seen, and nothing else."""
        self.refresh_backup_list()
        if not self.backups:
            self.backup_mgr.create_backup(BASELINE_TAG)
            self.refresh_backup_list()
        self.grub_checksum = self.backup_mgr.calc_checksum(
            self.backup_mgr.target_path) # checksum of loaded grub

    def record_committed_backup(self, tag):
        """Snapshot the just-written configuration."""
        return self.backup_mgr.create_backup(tag)

    def really_wanna(self, act):
        """ Ask for explicit confirmation before a destructive action."""
        self.win.passthrough_mode = False
        cs.flushinp()
        answer = self.win.answer(seed='',
                         prompt=f"Enter 'yes' to {act}", height=1)
        if answer is None:
            return False
        return answer.strip().lower() == 'yes'

    def confirm_quit(self):
        """True when the user may leave without losing unapplied changes."""
        pending = len(self.get_diffs())
        if not pending:
            return True
        return self.really_wanna(
            f'quit and discard {pending} unapplied change(s)')

    def request_quit(self):
        """Handle a quit request (``q`` or Ctrl-C); True when the app stops."""
        if self.ss.is_curr(RESTORE_ST):
            self.navigate_back()
            return False
        return self.confirm_quit()

    def update_grub(self, tag=None, confirmed=False):
        """Commit staged changes, update GRUB, and offer reboot/poweroff."""
        if not confirmed and not self.really_wanna('commit changes and update GRUB'):
            return

        diffs = self.get_diffs()
        for param_name, pair in diffs.items():
            self.grub_file.param_data[param_name].new_value = pair[1]

        self.win.suspend_curses()
        time.sleep(.75)
        print("\033[2J\033[H") # 'clear'
        print('\n\n===== Leaving grub-wiz screens to update GRUB ====> ')
        user_config = UserConfigDir.get_singleton()
        candidate_path = user_config.staging_path(self.grub_writer.etc_grub)

        ok = self.grub_file.write_file(candidate_path)
        if not ok:
            try:
                if os.path.lexists(candidate_path):
                    os.unlink(candidate_path)
            except OSError:
                pass
        else:
            ok, commit_msg = self.grub_writer.commit_and_update(candidate_path)
            if not ok:
                print(commit_msg)
            else:
                self.record_committed_backup(tag)

        # Check if initramfs rebuild is needed
        if ok and self.distro_vars.update_initramfs:
            needs_rebuild, trigger, category = self.grub_writer.should_rebuild_initramfs(diffs)
            if needs_rebuild:
                # Format category name for display
                category_display = category.replace('_', ' ').title()
                print(f"\n{Glyphs.alert()}  {category_display} changes "
                      f"detected ('{trigger}').")
                print("Rebuilding initramfs ensures driver/module changes take effect at early boot.")

                space_info = self.grub_writer.check_initramfs_space()
                print(f"\nDisk space check: {space_info['message']}")

                if space_info['is_critical']:
                    print(f"\n{Glyphs.stop()} CRITICAL: Insufficient disk space!")
                    print("   Initramfs rebuild would likely FAIL and may brick your system.")
                    print("   Please free up space in /boot first.")
                    print("\nSkipping initramfs rebuild for safety.")
                elif not space_info['is_sufficient']:
                    print(f"\n{Glyphs.alert()}  Space is tight. "
                          "Proceeding is risky but may work.")
                    choice = prompt_line(
                        'Continue with rebuild anyway? [y/N]: ').strip().lower()
                    if choice != 'y':
                        print('\nSkipping initramfs rebuild.')
                        print('Note: Some changes may not take effect until initramfs is rebuilt.')
                    else:
                        initramfs_ok, initramfs_msg = self.grub_writer.run_initramfs_update()
                        if initramfs_ok:
                            print(f'\n{Glyphs.ok()} Initramfs rebuilt successfully')
                        else:
                            print(f'\n{Glyphs.fail()} Initramfs rebuild failed:\n{initramfs_msg}')
                            print('Your GRUB changes are applied, but initramfs was not rebuilt.')
                else:
                    # Sufficient space, normal prompt
                    choice = prompt_line(
                        '\nRebuild initramfs now? [y/N]: ').strip().lower()
                    if choice == 'y':
                        initramfs_ok, initramfs_msg = self.grub_writer.run_initramfs_update()
                        if initramfs_ok:
                            print(f'\n{Glyphs.ok()} Initramfs rebuilt successfully')
                        else:
                            print(f'\n{Glyphs.fail()} Initramfs rebuild failed:\n{initramfs_msg}')
                            print('Your GRUB changes are applied, but initramfs was not rebuilt.')
                            print('You may need to rebuild it manually later.')
                    else:
                        print('\nSkipping initramfs rebuild.')
                        print('Note: Some changes may not take effect until initramfs is rebuilt.')

        if ok:
            print('\nOK ... /etc/default/grub newly written/updated')
        else:
            print('\nFAIL ... changes NOT applied (previous /etc/default/grub kept)')
        print('\n\nChoose:')
        if ok:
            print('  [r]eboot now')
            print('  [p]oweroff')
        print('  [q]uit')
        print('  ENTER to return to grub-wiz screen')

        choice = prompt_line('\n> ').strip().lower()

        if choice == 'r':
            print('\nRebooting...')
            subprocess.run(['reboot'], check=False)
            sys.exit(0)  # Won't reach here, but just in case
        elif choice == 'p':
            print('\nPowering off...')
            subprocess.run(['poweroff'], check=False)
            sys.exit(0)  # Won't reach here, but just in case
        elif choice == 'q':
            print('\nQuitting grub-wiz...')
            sys.exit(0)  # Won't reach here, but just in case
        # Otherwise continue to grub-wiz
        else:
            time.sleep(1.5) # show start up messages breifly
            self.win.resume_curses()
            if ok:
                self.reinit_gw()
                self.reset_screen_stack()
                # The commit already recorded this state;
                # asking the startup rule again would only add a RESYNC for it.
                # Refresh the checksum the RESTORE screen marks as "current" instead.
                self.grub_checksum = self.backup_mgr.calc_checksum(
                    self.backup_mgr.target_path)
                self.refresh_backup_list()

    def find_in(self, value, enums=None, cfg=None):
        """ Find the value in the list of choices using only
        string comparisons (because representation uncertain)

        Returns ns (.idx, .next_idx, .next_value, .prev_idx, .prev_value)
        """
        def normalize_value(val):
            """Remove outer quotes for comparison"""
            s = str(val)
            # Strip outer quotes (both single and double)
            if len(s) >= 2 and s[0] in ('"', "'") and s[-1] == s[0]:
                return s[1:-1]
            return s

        choices = None
        if cfg:
            enums = cfg.get(enums, [])
        if enums:
            choices = list(enums.keys())
        assert choices

        # Normalize the value for comparison (strip quotes)
        norm_value = normalize_value(value)

        idx = -1 # default to before first
        for ii, choice in enumerate(choices):
            if norm_value == normalize_value(choice):
                idx = ii
                break
        next_idx = (idx+1) % len(choices)
        next_value = choices[next_idx] # choose next
        prev_idx = (idx+len(choices)-1) % len(choices)
        prev_value = choices[prev_idx] # choose next
        return SimpleNamespace(idx=idx, choices=choices,
                       next_idx=next_idx, next_value=next_value,
                       prev_idx=prev_idx, prev_value=prev_value)

    def navigate_to(self, screen_num):
        """Navigate to a screen with validation hooks.

        Args: screen_num: Screen number to navigate to

        Returns: True if navigation succeeded, False if blocked
        """
        result = self.ss.push(screen_num, self.prev_pos)
        if result is not None:
            self.prev_pos = result
            return True
        return False

    def navigate_back(self):
        """ Navigate back to previous screen with validation hooks.

        Returns: True if navigation succeeded, False if blocked or no stack
        """
        result = self.ss.pop()
        if result is not None:
            self.prev_pos = result
            # Reset cached data when going back
            self.must_reviews = None
            self.bak_lines, self.bak_path = None, None
            return True
        return False

    def handle_escape(self):
        """ Generic escape handler with context awareness.
         
           Returns: True if escape was handled, False otherwise
        """
        if self.ss.stack:
            return self.navigate_back()
        return False

    def main_loop(self):
        """Run the draw/prompt/dispatch loop until the user quits."""
        self.setup_win()
        win = self.win
        self.next_prompt_seconds = [0.1, 0.1]

        while self.running:
            screen = self.ss.get_curr_obj()
            screen.clear()
            screen.draw_screen()

            win.render()
            key = prompt_key(win, self.next_prompt_seconds[0])

            self.next_prompt_seconds.pop(0)
            if not self.next_prompt_seconds:
                self.next_prompt_seconds = [3.0]

            if key is None:
                # An idle wake-up (timeout or resize) is not an answer.
                continue

            if win.prompt_active:
                win.handle_prompt_key(key)
                continue

            if key == QUIT_KEY:
                if self.request_quit():
                    break
                continue

            if self.search_bar.is_active:
                if self.search_bar.handle_key(key):
                    continue
            elif self.home_search_bar.is_active:
                if self.home_search_bar.handle_key(key):
                    continue

            self.spinner.do_key(key, win)
            self.ss.perform_actions(self.spinner)

def rerun_module_as_root(module_name):
    """ rerun using the module name """
    if os.geteuid() != 0: # Re-run the script with sudo
        os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        vp = ['sudo', sys.executable, '-m', module_name] + sys.argv[1:]
        os.execvp('sudo', vp)


def build_parser():
    """The command line: grub-wiz's own switches plus console-window's.

    Separated from ``main()`` so the flags can be tested
    without running the editor (and without the sudo re-exec).
    """
    parser = ArgumentParser(description='grub-wiz: your grub-update guide')
    parser.add_argument('--version', action='version',
                        version=f'grub-wiz {__version__}',
                        help="show grub-wiz's version and exit")
    parser.add_argument('--discovery', '--parameter-discovery', default=None,
                        choices=('enable', 'disable', 'show'),
                        help='control/show parameter discovery state')
    parser.add_argument('--factory-reset', action='store_true',
                        help='restore out-of-box experience (but keeping .bak files)')
    parser.add_argument('--validate-custom-config', action='store_true',
                        help='test load ~/.config/grub-wiz/custom_config.yaml')
    parser.add_argument('--validator-demo', action='store_true',
                        help='for test only: run validator demo')
    parser.add_argument('--answer-timeout-debug', action='store_true',
                        help='for test only: enables screen redraw indicator')
    parser.add_argument('-k', '--keep-all-bak', action='store_true',
                        help='keep every backup; skip the start-up purge')
    display_cli.add_display_arguments(parser, theme_store=PREFS_THEME_STORE,
                                      prog='grub-wiz')
    return parser


def main():
    """Parse CLI options and start the TUI or the requested diagnostic mode."""
    opts = build_parser().parse_args()
    rerun_module_as_root('grub_wiz.main')

    wiz = GrubWiz(cli_opts=opts)
    if opts.validator_demo:
        wiz.wiz_validator.demo(wiz.param_defaults)
        sys.exit(0)

    if opts.validate_custom_config:
        using_path = str(wiz.canned_config.using_path)
        print(f'grub-wiz: using {using_path}')
        if 'custom_config.yaml' not in using_path:
            print("FAIL: custom config NOT being used (see warnings above)")
            sys.exit(1)
        print('OK: custom config is valid and in use')
        sys.exit(0)

    if opts.discovery is not None:
        if opts.discovery in ('enable', 'disable'):
            enabled = wiz.param_discovery.manual_enable(opts.discovery == 'enable')
            print(f'\nParameterDiscovery: {enabled=}')
        else:
            wiz.param_discovery.dump(wiz.defined_param_names)
            absent_params = wiz.param_discovery.get_absent(wiz.defined_param_names)
            print(f'\nPruned {absent_params=}')
        sys.exit(0)

    if opts.factory_reset:
        print('Factory reset: clearing user preferences...')
        deleted = []
        try:
            for target in (wiz.param_discovery.cache_file,
                           wiz.warn_db.yaml_path):
                if os.path.isfile(target):
                    os.unlink(target)
                    deleted.append(str(target))
            # The remembered theme has its own owner, which also clears its in-memory copy.
            # The CLI tests replace GrubWiz with a minimal stand-in,
            # so look for its preferences defensively.
            prefs = getattr(wiz, 'prefs', None)
            if prefs is not None and prefs.delete():
                deleted.append(str(prefs.yaml_path))
            if deleted:
                print(f'Deleted: {", ".join(deleted)}')
            else:
                print('No cached files to delete.')
            print('Factory reset complete. Backup files (.bak) preserved.')
        except OSError as whynot:
            print(f'ERR: failed "factory reset" [{whynot}]')
        sys.exit(0)

    display_cli.apply_display_arguments(opts, prog='grub-wiz')

    if not run_sync_check(wiz.distro_vars.etc_grub, wiz.distro_vars.grub_cfg):
        print('Aborting.')
        sys.exit(0)

    if not opts.keep_all_bak:
        wiz.backup_mgr.purge_backups()
    wiz.do_start_up_backup()

    time.sleep(1.0)
    wiz.main_loop()

def _restore_terminal():
    """Leave curses mode if a screen was started (best effort)."""
    win = GrubWiz.singleton.win if GrubWiz.singleton else None
    if win is not None:
        try:
            win.stop_curses()
        except (cs.error, OSError, RuntimeError, AttributeError):
            # Never mask the original failure while cleaning up.
            pass


def run_cli():
    """Console-script entry point."""
    try:
        main()
    except KeyboardInterrupt:
        _restore_terminal()
        print('\nInterrupted.')
        sys.exit(130)
    except SystemExit:
        _restore_terminal()
        raise
    except Exception as exce:
        _restore_terminal()
        print("exception:", str(exce))
        print(traceback.format_exc())
        sys.exit(15)


if __name__ == '__main__':
    run_cli()
