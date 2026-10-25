#!/usr/bin/env python3
r"""
    grub-wiz: the help grub file editor assistant

"""
# pylint: disable=invalid-name,broad-exception-caught
# pylint: disable=too-many-locals,too-few-public-methods,too-many-branches
# pylint: disable=too-many-nested-blocks,too-many-statements
# pylint: disable=too-many-public-methods,line-too-long
# pylint: disable=too-many-instance-attributes,too-many-lines


import sys
import os
import time
import textwrap
import traceback
import re
import unicodedata
import curses as cs
from argparse import ArgumentParser
from types import SimpleNamespace
from typing import Any #, Tuple #, Opt
from console_window import OptionSpinner, ConsoleWindow, ConsoleWindowOpts, Screen, ScreenStack, Context, IncrementalSearchBar
from console_window import NAVIGATION_KEYS
from .CannedConfig import CannedConfig, has_edit_regex, is_expert_edit
from .DistroVars import DistroVars
from .GrubFile import GrubFile
from .GrubCfgParser import get_top_level_grub_entries
from .BackupMgr import BackupMgr, GRUB_DEFAULT_PATH
from .WarnDB import WarnDB
from .GrubWriter import GrubWriter
from .WizValidator import WizValidator
from .ParamDiscovery import ParamDiscovery
from .UserConfigDir import UserConfigDir

HOME_ST, REVIEW_ST, RESTORE_ST, VIEW_ST, COMPARE_ST, WARN_ST, HELP_ST  = 0, 1, 2, 3, 4, 5, 6
SCREENS = 'HOME REVIEW RESTORE VIEW COMPARE WARN HELP'.split() # screen names


def release_arrow_keys_for_app():
    """Allow LEFT/RIGHT to be bound to app actions.

    console-window 2.0.1 reserves every code in ``NAVIGATION_KEYS``:
    ``OptionSpinner.add_key()`` rejects it and ``ConsoleWindow.prompt()``
    consumes it before the app sees it.  Neither cursor key has a scroll
    action, though: ``_navigation_target()`` maps UP/DOWN and the page keys
    only, so prompt() would silently swallow LEFT/RIGHT anyway.  The modules
    ``console_window.keys``, ``.spinner`` and ``.window`` all hold a reference
    to the same mutable set, so discarding the two codes in place un-reserves
    them everywhere.  Vertical navigation still works, and dialogs keep their
    left/right cursor editing via ``_DIALOG_SIMPLE_MOVES``, which does not
    consult this set.
    """
    NAVIGATION_KEYS.discard(cs.KEY_LEFT)
    NAVIGATION_KEYS.discard(cs.KEY_RIGHT)

class Tab:
    """ TBD """
    def __init__(self, cols, param_wid):
        """           g
        >----left----|a |---right ---|
         |<---lwid-->|p |<---rwid--->|
         la          lz ra           rz

        :param self: provides access to the "tab" positions
        :param cols: columns in window
        :param param_wid: max wid of all param names
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
    """Return the terminal cell width of *text*.

    Emoji and other East-Asian wide characters occupy two cells, while
    combining marks occupy none.  ``len()`` is therefore only correct for
    ASCII, and using it to pad a field silently misaligns everything after
    the first wide glyph (which is exactly what the warning stars are).
    """
    width = 0
    for char in str(text):
        if unicodedata.combining(char):
            continue
        width += 2 if unicodedata.east_asian_width(char) in ('W', 'F') else 1
    return width


def truncate_to_width(text, width, ellipsis='▶'):
    """Truncate *text* so its terminal cell width does not exceed *width*."""
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


# Note: Clue class has been replaced with Context from ConsoleWindow
# Context usage patterns:
#   Context(genre='DECOR') - non-pickable decorative lines (headers, separators)
#   Context(genre='param', param_name=...) - pickable parameter lines
#   Context(genre='TRANSIENT') - dropdown/conditional content (auto-visible with parent)
#   Context(genre='warn', warn_key=...) - pickable warning lines


# Extend Screen from ConsoleWindow to add grub-wiz specific behavior
class GrubWizScreen(Screen):
    """
    Grub-wiz specific Screen base class.
    Extends ConsoleWindow.Screen with backward-compatible 'gw' attribute.
    """
    def __init__(self, grub_wiz):
        """
        Initialize screen with grub_wiz instance.
        Sets both self.app (from parent) and self.gw (for backward compatibility).
        """
        super().__init__(grub_wiz)
        self.gw = self.app  # Backward compatibility: gw is an alias for app

    def slash_PROMPT(self, current: str):
        """ TBD """
        hint = 'must be a valid python regex'
        regex = None # compiled
        pattern = current

        while True:
            prompt = f'Enter search pattern [{hint}]'
            pattern = self.win.answer(prompt=prompt,
                                  seed=str(pattern), height=1)
            if pattern is None: # aborted
                return '', None

            if not pattern:
                return '', None
            try:
                regex = re.compile(pattern, re.IGNORECASE)
                return pattern, regex
            except Exception as whynot:
                hint = str(whynot)
                continue

    # App-level navigation actions (available on all screens)
    def escape_ACTION(self):
        """Handle ESC key - navigate back if possible"""
        if self.gw.ss.stack:
            self.gw.navigate_back()

    def help_mode_ACTION(self):
        """Handle ? key - navigate to help screen"""
        self.gw.navigate_to(HELP_ST)

    def enter_restore_ACTION(self):
        """Handle R key - navigate to restore screen (only from HOME/REVIEW)"""
        if self.gw.ss.is_curr((HOME_ST, REVIEW_ST)):
            self.gw.navigate_to(RESTORE_ST)

    def enter_warnings_ACTION(self):
        """Handle W key - navigate to warnings screen"""
        self.gw.navigate_to(WARN_ST)


class HomeScreen(GrubWizScreen):
    """HOME screen - parameter editing"""
    # Home screen has no restrictions - can navigate anywhere
    def __init__(self, gw):
        super().__init__(gw)
        self.search = ''
        self.regex = None

    def draw_screen(self):
        """ TBD """
        self.win.set_pick_mode(True)
        self.draw_body()
        self.draw_head()

    def body_param_lines(self, param_name, is_current):
        """ Build a body line for a param """
        gw = self.gw
        tab = self.get_tab()
        marker = ' '
        if not gw.is_active_param(param_name):
            marker = '✘'
        value = gw.param_values[param_name]
        line = f'{marker} {param_name[5:]:·<{tab.lwid-2}}'
        indent = len(line)
        line += f'  {value}'
        wid = self.win.cols - 1 # effective width
        if display_width(line) > wid and is_current:
            line = textwrap.fill(line, width=wid,
                       subsequent_indent=' '*indent)
        elif display_width(line) > wid and not is_current:
            line = truncate_to_width(line, self.win.cols-1, ellipsis='⯈')
        return line.splitlines()


    @staticmethod
    def left_side_box(lines, indent=3):
        """ draw a box """
        if len(lines) <= 0:
            return []
        rv = []
        chars = ['┃'] + ['│'] * (len(lines)-1)
        if len(chars) >= 2:
            chars[0], chars[-1] = '╭', '╰'
        for idx, line in enumerate(lines):
            rv.append(line[:indent] + chars[idx] + line[indent+1:])
        return rv


    def draw_body(self):
        """ TBD """
        gw = self.gw
        gw.hidden_stats = SimpleNamespace(param=0, warn=0)
        win = self.win # short hand
        picked = win.pick_pos
        found_current = False
        first_visible_section = True

        # Iterate through sections directly, hiding empty ones
        for section_name, params in gw.sections.items():
            # Collect visible params for this section
            visible_params = []
            for param_name in params.keys():
                if param_name not in gw.param_cfg:
                    continue  # Param was filtered out (absent from system)

                # Count inactive params regardless of visibility setting
                if not gw.is_active_param(param_name):
                    gw.hidden_stats.param += 1

                # Determine visibility for rendering
                if not gw.show_hidden_params and not gw.is_active_param(param_name):
                    continue
                if gw.show_hidden_params and self.regex:
                    if self.regex.search(param_name[5:]):
                        visible_params.append(param_name)
                else:
                    visible_params.append(param_name)

            # Skip empty sections when in compact mode (hiding params)
            if not visible_params: # and not gw.show_hidden_params:
                continue

            # Add blank line before sections (except first visible section)
            if not first_visible_section:
                win.add_body(' ', context=Context(genre='DECOR'))
            first_visible_section = False

            # Add section header - DECOR genre makes it non-pickable
            win.add_body(f'[{section_name}]', context=Context(genre='DECOR'))

            # Add visible params
            for param_name in visible_params:
                is_current = bool(picked == win.body.row_cnt)
                param_lines = self.body_param_lines(param_name, is_current)

                if not is_current:
                    line = param_lines[0]
                    if len(param_lines) > 1:
                        line = line[:win.cols-2] + '⯈'
                    win.add_body(line, context=Context(genre='param', param_name=param_name))
                    continue

                found_current = True
                emits = param_lines + gw.drop_down_lines(param_name)

                # Truncate if exceeds view size
                view_size = win.scroll_view_size
                if len(emits) > view_size:
                    hide_cnt = 1 + len(emits) - view_size
                    emits = emits[0:view_size-1]
                    emits.append(f'... beware: {hide_cnt} HIDDEN lines ...')
                if len(emits) > 1:
                    emits = [emits[0]] + self.left_side_box(emits[1:])

                # Add parent param line
                win.add_body(emits[0], context=Context(genre='param', param_name=param_name))
                # Add TRANSIENT dropdown lines (auto-visible with parent via ConsoleWindow)
                for emit in emits[1:]:
                    win.add_body(emit, context=Context(genre='TRANSIENT'))

        return found_current

    def add_common_head1(self, title):
        """ TBD"""
        gw = self.gw
        header = ''
        # Add timestamp when verbose headers enabled (helps verify refresh rate)
        if gw.spins.verbose_header:
            timestamp = time.strftime('%H:%M:%S')
            header = f'{timestamp} '
        header += f'{title} '
        level = gw.spins.guide
        esc = ' ESC:back' if gw.ss.is_curr(REVIEW_ST) else ''
        # more = 'm:less-hdr' if gw.spins.verbose_header else '[m]ore-hdr'
        header += f' [g]uide={level}  [w]rite-grub   {esc} ?:help [q]uit'
        header += f'  𝚫={len(gw.get_diffs())}'
        gw.add_fancy_header(header)
        gw.warn_db.write_if_dirty()

    def add_common_head2(self, left):
        """ TBD"""
        gw = self.gw
        param_name, _, enums, regex, value = gw.get_enums_regex()
        review_screen = gw.ss.is_curr(REVIEW_ST)

        if gw.spins.verbose_header:
            style = gw.spins.fancy_headers
            line = '[R]estoreScreen'
            line += '  [W]arningsScreen' if review_screen else ''
            line += f'  [f]ancy={style}'
            if regex:
                line += '  [E]xpertEdit'
            gw.add_fancy_header(line)

        tab = self.get_tab()
        picked = gw.win.pick_pos
        ctx = gw.win.get_picked_context()
        if ctx:
            cat, ident = ctx.genre, getattr(ctx, 'param_name', '')
        else:
            cat, ident = '', ''

        middle =  ''
        if cat == 'param':
            if enums:
                middle += '⮜–⮞'
            # EXPERT_EDIT is truthy but is not a regex; only a real regex means
            # the value will be validated, which is what [e]dit promises.
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
            # Show search bar (with cursor if active, or just text if not)
            middle += gw.home_search_bar.get_display_string(prefix='  /')

        gw.add_fancy_header(f'{left:<{tab.lwid}}  {middle}')

    def get_tab(self):
        """ get the tab positions of the print cols """
        return Tab(self.win.cols, self.gw.param_name_wid)

    def draw_head(self):
        """ HOME screen header"""
        gw = self.gw
        self.add_common_head1('EDIT')
        tab = self.get_tab()

        # if any param is hidden on this screen, then show
        header, cnt = '', gw.hidden_stats.param
        if cnt:
            if gw.show_hidden_params:
                header += f's:hide-{cnt}-inact-params'
            else:
                header += f'[s]how-all-params({cnt}-inact)'
        header = f'{header:<{tab.lwid}}'

        self.add_common_head2(header)
        # Note: ensure_visible_group() removed - Context TRANSIENT handles this automatically

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
    # Review screen can be accessed from HOME screen

    def __init__(self, grub_wiz):
        """Constructor handles initial setup"""
        super().__init__(grub_wiz)
        # Reset cached review data on construction
        self.gw.must_reviews = None
        self.gw.clues = []

    def on_resume(self):
        """Refresh review data when resuming after being covered"""
        # Reset cached review data when resuming
        self.gw.must_reviews = None
        self.gw.clues = []
        return True

    def draw_screen(self):
        """ TBD """
        self.win.set_pick_mode(True)
        self.add_body()
        self.add_head()

    def add_head(self):
        """ Construct the review screen header
            Presumes the body was created with Context metadata.
        """
        gw = self.gw
        self.add_common_head1('REVIEW')

        # if any warn is hidden on this screen, then show
        header, cnt = '', gw.hidden_stats.warn
        if cnt:
            header = 's:hide' if gw.show_hidden_warns else '[s]how'
            header += f' {cnt} ✘-warns'
        header = f'{header:<24}'
        self.add_common_head2(header)
        # Note: ensure_visible_group() removed - Context TRANSIENT handles this automatically

    def add_body(self):
        """ TBD """
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

        for param_name, ns in reviews.items():
            tab = self.get_tab()
            is_current = bool(self.win.body.row_cnt == picked)
            param_lines = self.body_param_lines(param_name, is_current)

            # Add param lines with Context
            for line in param_lines:
                self.win.add_body(line, context=Context(genre='param', param_name=param_name))

            changed = bool(ns.old_value is not None
                           and str(ns.value) != str(ns.old_value))
            if changed:
                # TRANSIENT line showing old value
                self.win.add_body(f'{"└──────── was":>{tab.lwid}}  {ns.old_value}',
                                context=Context(genre='TRANSIENT'))

            for hey in ns.heys:
                warn_key = WarnDB.make_key(param_name, hey[1])
                is_inhibit = gw.warn_db.is_inhibit(warn_key)
                gw.hidden_stats.warn += int(is_inhibit)
                stars = '🟌' * len(hey[0])

                if not is_inhibit or gw.show_hidden_warns:
                    mark = '✘' if is_inhibit else ' '
                    # Pad the star field by *cell* width (an emoji star is
                    # two cells), so the message starts at the same column
                    # for every severity.
                    star_field = ' ' * max(8 - display_width(stars), 0) + stars
                    sub_text = f'└─── {mark} {star_field}'
                    pad = max(tab.lwid - display_width(sub_text), 0)
                    line = f'{" " * pad}{sub_text}  {hey[1]}'
                    # Add warning line with Context - TRANSIENT keeps it with parent
                    cnt = gw.add_wrapped_body_line(line, tab.lwid+2,
                                                  self.win.body.row_cnt==picked,
                                                  context=Context(genre='warn', warn_key=warn_key))

            if is_current:
                emits = gw.drop_down_lines(param_name)
                if len(emits) > 1:
                    emits = self.left_side_box(emits)
                # Add TRANSIENT dropdown lines
                for emit in emits:
                    self.win.add_body(emit, context=Context(genre='TRANSIENT'))

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
        """Handle 'w' key on REVIEW screen - update grub"""
        # Note: update_grub is now a critical requirement, so is_crippled only indicates
        # missing grub_cfg (which affects menu entry enumeration, not update capability)
        self.gw.update_grub()

    def slash_ACTION(self):
        """ TBD"""
        return # does nothing here


class RestoreScreen(GrubWizScreen):
    """RESTORE screen - backup management"""
    # Can be accessed from HOME or REVIEW screens
    come_from_whitelist = [HOME_ST, REVIEW_ST]

    def __init__(self, grub_wiz):
        """Constructor handles initial backup list setup"""
        super().__init__(grub_wiz)
        # Initialize backup list
        self.gw.do_start_up_backup()
        self.gw.refresh_backup_list()
        self.bak_paths = []
        self.baseline_bak = None  # what to compare to

    def on_resume(self):
        """Refresh backup list when resuming"""
        self.gw.refresh_backup_list()
        return True

    def draw_screen(self):
        self.win.set_pick_mode(True)
        self.add_body()
        self.add_head()

    def add_head(self):
        """ TBD """
        gw = self.gw
        pos, base = self.win.pick_pos, '[c]mp [b]aseline'
        if 0 <= pos < len(self.bak_paths):
            if self.bak_paths[pos] == self.baseline_bak:
                base = ''
        header = f'RESTORE [r]estore [d]el [t]ag [v]iew {base}    ESC:back ?:help [q]uit'
        gw.add_fancy_header(header)

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

    def add_body(self):
        """ TBD """
        gw = self.gw
        if not gw.ordered_backup_pairs:
            return
        self._ensure_reference()
        self.bak_paths = []
        for pair in gw.ordered_backup_pairs:
            checksum, bak_path = pair[0], pair[1]
            prefix = '●' if checksum == gw.grub_checksum else ' '
            ref = 'CMP' if self.baseline_bak == bak_path else '   '
            self.bak_paths.append(bak_path)
            self.win.add_body(f'{prefix} {ref} {bak_path.name}',
                            context=Context(genre='backup', bak_path=bak_path))

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
        """Handle 'r' key on RESTORE screen - restore selected backup"""
        gw = self.gw
        idx = self.win.pick_pos
        if not 0 <= idx < len(gw.ordered_backup_pairs):
            return
        key = gw.ordered_backup_pairs[idx][0]
        target = gw.ordered_backup_pairs[idx][1]
        if not gw.really_wanna(f'restore {target.name!r}'):
            return
        # Only reinitialize when the file really was replaced.  A failed
        # restore leaves /etc/default/grub untouched, so rebuilding the
        # screens from it would silently discard the user's state for nothing.
        if not gw.backup_mgr.restore_backup(gw.backups[key]):
            self.win.alert(message=f'ERR: restore of {target.name!r} failed')
            return
        while gw.navigate_back():
            pass
        gw.reinit_gw()
        gw.reset_screen_stack()
        gw.do_start_up_backup()

    def delete_ACTION(self):
        """Handle 'd' key on RESTORE screen - delete selected backup"""
        gw = self.gw
        idx = self.win.pick_pos
        if 0 <= idx < len(gw.ordered_backup_pairs):
            doomed = gw.ordered_backup_pairs[idx][1]
            if gw.really_wanna(f'remove {doomed.name!r}'):
                try:
                    os.unlink(doomed)
                except Exception as exce:
                    self.win.alert(
                        message=f'ERR: unlink({doomed}) [{exce}]')
                gw.refresh_backup_list()

    def tag_ACTION(self):
        """Handle 't' key on RESTORE screen - tag/retag selected backup"""
        gw = self.gw
        idx = self.win.pick_pos
        if 0 <= idx < len(gw.ordered_backup_pairs):
            chosen = gw.ordered_backup_pairs[idx][1]
            tag = gw.request_backup_tag(f'Enter tag for {chosen.name}',
                                              seed='')
            if tag:
                new_name = re.sub(r'[^.]+\.bak$', f'{tag}.bak', chosen.name)
                new_path = chosen.parent / new_name
                if new_path != chosen:
                    try:
                        os.rename(chosen, new_path)
                    except Exception as exce:
                        self.win.alert(
                            message=f'ERR: rename({chosen.name}, {new_path.name}) [{exce}]')
                gw.refresh_backup_list()

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
            except Exception as ex:
                self.win.alert(f'ERR: cannot slurp {gw.bak_path} [{ex}]')

class CompareScreen(GrubWizScreen):
    """  Show the comparison of two backup files """
    come_from_whitelist = [RESTORE_ST]

    """COMPARE screen - compared two backups"""
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
        """ TBD """
        self.win.set_pick_mode(False)
        self.add_body()
        self.add_head()

    def add_body(self):
        """ TBD """
        def get_val(param, data):
            # param_data holds SimpleNamespace records; a parameter that only
            # exists in the other file is simply absent here.
            entry = data.get(param)
            if entry is None:
                return GrubFile.ABSENT, None
            return entry.value, entry.line_num

        gw = self.gw

        if self.results is None:
            self.results, lines = [], []
            # GrubFile already adds a SimpleNamespace record to param_data for
            # every unvalidated (extra) parameter it discovers, so extra_params
            # (which holds config dicts) must NOT be merged into param_data.
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

                # Add blank separator
                lines.append('')

                # Add line1 with wrapping
                prefix1 = '< '
                content1 = line1
                lines.append(prefix1 + content1)

                # Add line2 with wrapping
                prefix2 = '> '
                content2 = line2
                lines.append(prefix2 + content2)

            self.results = lines

        # Display with wrapping
        wid = self.win.cols - 3  # Account for '< ' or '> ' prefix (2 chars) + margin
        for line in self.results:
            if not line:
                self.win.add_body('')
                continue

            # Check if line starts with a prefix
            if line.startswith('< ') or line.startswith('> '):
                prefix = line[:2]
                content = line[2:]

                # First line with prefix
                if len(line) <= self.win.cols - 1:
                    self.win.add_body(line)
                else:
                    # Need to wrap
                    self.win.add_body(prefix + content[:wid])
                    content = content[wid:]

                    # Continuation lines with indentation
                    while content:
                        indent = '  '  # 2 spaces to align with content after prefix
                        chunk_size = self.win.cols - len(indent) - 1
                        self.win.add_body(indent + content[:chunk_size])
                        content = content[chunk_size:]
            else:
                self.win.add_body(line)

    def add_head(self):
        """ TBD """
        win = self.win
        win.add_header('COMPARE   ESC:back')
        win.add_header(f'< {self.bak1.name} [#lines={self.cnt1}]')
        win.add_header(f'> {self.bak2.name} [#lines={self.cnt2}]')


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
        """ TBD """
        self.win.set_pick_mode(False)
        self.add_body()
        self.add_head()

    def add_head(self):
        """ TBD """
        gw = self.gw
        header = f'VIEW  {gw.bak_path.name!r}  ESC:back ?:help [q]uit'
        gw.add_fancy_header(header)

    def add_body(self):
        """ TBD """
        gw = self.gw
        wid = self.win.cols - 7 # 4 num + SP before + 2SP after
        indent = ' ' * 6 # align wrapped text past the 4-digit index column
        for idx, line in enumerate(gw.bak_lines):
            self.win.add_body(f'{idx:>4}', attr=cs.A_BOLD)
            self.win.add_body(f'  {line[:wid]}', resume=True)
            line = line[wid:]
            while line:
                self.win.add_body(f'{indent}{line[:wid]}')
                line = line[wid:]

class WarnScreen(GrubWizScreen):
    """WARNINGS Screen"""
    # Can only be accessed from REVIEW screen
    come_from_whitelist = [HOME_ST, REVIEW_ST]

    def __init__(self, grub_wiz):
        """Constructor initializes search state"""
        super().__init__(grub_wiz)
        self.search = ''
        self.regex = None  # compiled

    def on_pop(self):
        """Save any changes when screen is removed"""
        # Save any inhibit changes before leaving
        self.gw.warn_db.write_if_dirty()
        return True

    def draw_screen(self):
        """ TBD """
        self.win.set_pick_mode(True)
        self.draw_body()
        self.draw_head()

    def draw_head(self):
        """ TBD """
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
        # Show search bar (with cursor if active, or just text if not)
        line += gw.search_bar.get_display_string(prefix='   /')
        line += '   ESC=back [q]uit'
        gw.add_fancy_header(line)

    def draw_body(self):
        """ TBD """
        gw = self.gw
        db = gw.warn_db
        all_info = db.all_info
        keys = sorted(all_info.keys())
        prev_param = None

        for key in keys:
            sev = all_info[key]
            stars = '🟍' * sev

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
                self.win.add_body(line, context=Context(genre='warn', warn_key=key))
                # Only update prev_param for lines that are actually displayed
                prev_param = param_name

    def hide_ACTION(self):
        """ TBD """
        gw = self.gw
        ctx = self.win.get_picked_context()
        if ctx and ctx.genre == 'warn':
            warn_key = getattr(ctx, 'warn_key', None)
            if warn_key:
                opposite = not gw.warn_db.is_inhibit(warn_key)
                gw.warn_db.inhibit(warn_key, opposite)
                gw.warn_db.write_if_dirty()

    def slash_ACTION(self):
        """Start incremental search mode"""
        self.gw.search_bar.start(self.search)
        self.gw.win.passthrough_mode = True

class HelpScreen(GrubWizScreen):
    """HELP screen"""
    def draw_screen(self):
        """ TBD """
        gw, win = self.gw, self.win
        self.win.set_pick_mode(False)
        gw.spinner.show_help_nav_keys(win)
        gw.spinner.show_help_body(win)


# --- Shell-value validation for /etc/default/grub --------------------------
#
# A parameter value is written verbatim after ``PARAM=`` and the file is
# *sourced* by the distro's GRUB scripts.  The value must therefore stay a
# single shell word: spaces split the assignment (``PARAM=a reboot`` runs
# ``reboot``), ``;``/``&``/``|`` chain commands, ``$``/backticks expand, and
# ``#`` starts a comment.  Everything else that GRUB values commonly use
# (``, = + : / @ %``, brackets, etc.) is fine unquoted.  Command substitution
# is accepted only for parameters whose ``_re_specs_`` entry opts in with
# ``allow_command_sub: true`` (GRUB_DISTRIBUTOR), or in expert-edit mode.

#: Characters that are unsafe in a bare (unquoted) assignment value.
_UNQUOTED_FORBIDDEN = frozenset(' \t\n\r\x0b\x0c\'"\\$`;&|<>(){}!#~')


def _is_control_char(char):
    """True for C0/DEL control characters, which must never be written."""
    return ord(char) < 0x20 or ord(char) == 0x7f


def _check_command_substitution(value):
    """Validate a whole-value ``$(...)`` command substitution.

    ``value`` starts with ``$(``.  Returns ``(ok, reason)``.  Quotes inside
    the command are honoured so parentheses in quoted text do not disturb the
    balance check, and the substitution must span the entire value.
    """
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
    """Check that *value* can be written as ``PARAM=value`` safely.

    Returns ``(ok, reason)``.  Accepted forms are an empty value, a bare word
    without shell metacharacters, a single- or double-quoted string with no
    expansions inside, and (only when *allow_command_sub* is true) a
    whole-value ``$(...)`` or backtick command substitution.

    Spaces, quotes and backslashes must be quoted because the shell would
    otherwise split the assignment or change its meaning; this mirrors what
    the file needs when edited by hand.
    """
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


class GrubWiz:
    """ TBD """
    singleton = None

    # parameters to give more answer space to
    long_params = ('GRUB_CMDLINE_LINUX GRUB_CMDLINE_LINUX_DEFAULT'
            ' GRUB_CMDLINE_XEN_DEFAULT GRUB_BADRAM GRUB_PRELOAD_MODULES'
            ' GRUB_SERIAL_COMMAND GRUB_GFXMODE GRUB_THEME GRUB_BACKGROUND'
            ' GRUB_TERMINAL_INPUT / GRUB_TERMINAL_OUTPUT').split()

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
        self.backup_mgr = BackupMgr()
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
        self.is_other_os = None # don't know yet
        self.show_hidden_params = False
        self.show_hidden_warns = False
        self.grub_checksum = ''
        self.bak_lines = None # the currently viewed .bak file
        self.bak_path = None
        self.screens = []
        self.reinit_gw()

    def reset_screen_stack(self):
        """Rebuild the screen stack after /etc/default/grub is replaced.

        ``OptionSpinner`` keeps a direct reference to the ``ScreenStack`` it
        was constructed with and uses it for every action-scoping and
        navigation decision.  Replacing ``self.ss`` therefore requires
        rebinding the spinner too; otherwise it keeps consulting the stale
        stack (and its dead ``curr``/``stack`` state).
        """
        self.ss = ScreenStack(self.win, self.spins, SCREENS, self.screens)
        if self.spinner is not None:
            self.spinner.stack = self.ss
            # Keep the spinner's option object and the stack's obj in sync;
            # OptionSpinner.default_obj's setter does the same when a stack
            # is present, but the assignment above bypasses it.
            self.ss.obj = self.spinner.default_obj

    def reinit_gw(self):
        """ Call to initialize or re-initialize with new /etc/default/grub """
        self.param_cfg = {}
        self.param_values, self.prev_values = {}, {}
        self.saved_active_param_values = {}
        self.param_defaults = {}
        self.must_reviews = None
        self.ss = None
        self.sections = self.canned_config.data
        section_names = list(self.sections.keys())
        for section_name in section_names:
            if section_name.startswith('_'):
                del self.sections[section_name]

        # Refresh the machine-wide discovery cache before filtering.  On a
        # fresh install this runs ``info grub`` for the first time; afterwards
        # it re-runs only when the cache is missing or older than a week.  The
        # UI therefore never filters (or fails to filter) based on an absent
        # or stale cache (audit H7).
        self.param_discovery.ensure_discovered()

        names = []
        for params in self.sections.values():
            for name in params.keys():
                names.append(name)
        absent_param_names = set(self.param_discovery.get_absent(names))
        self.defined_param_names = names

        # Build param_cfg, excluding absent params
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

        self.grub_file = GrubFile(supported_params=self.param_cfg)
        self.grub_file.read_file()
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
            self.param_cfg['GRUB_DEFAULT']['enums'].update(self.menu_entries)
        except Exception:
            pass
        self.warn_db = WarnDB(param_cfg=self.param_cfg)

        # Run startup audit to clean orphans and populate warning info
        warns, all_warn_info = self.wiz_validator.make_warns(self.param_values)
        self.warn_db.audit_info(all_warn_info)
        self.warn_db.write_if_dirty()  # Persist any cleanup from orphaned warnings

        self.refresh_backup_list()

    def setup_win(self):
        """TBD """
        # LEFT/RIGHT are used here for cycle_prev/cycle_next, so release them
        # from console-window's reserved navigation set before registering keys.
        release_arrow_keys_for_app()

        # Create ConsoleWindow first (needed by screen objects)
        win_opts = ConsoleWindowOpts()
        win_opts.head_line = True
        win_opts.ctrl_c_terminates = False
        win_opts.return_if_pos_change = True
        win_opts.single_cell_scroll_indicator = True
        win_opts.dialog_abort = 'ESC'
        win_opts.answer_show_redraws = self.cli_opts.answer_timeout_debug
        win_opts.min_cols_rows = (70, 10)  # Allow smaller terminals (down from default 20 rows)
        self.win = ConsoleWindow(win_opts)

        # Check terminal size at startup and wait for resize if too small
        import curses
        rows, cols = self.win.scr.getmaxyx()
        min_cols, min_rows = win_opts.min_cols_rows
        while rows < min_rows or cols < min_cols:
            # Terminal too small - show error and wait for resize
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
                # User wants to exit
                self.win.stop_curses()
                print(f"\n{error_msg}")
                print(f"Please resize your terminal to at least {min_cols}x{min_rows} and try again.\n")
                import sys
                sys.exit(1)
            if key == curses.KEY_RESIZE:
                curses.update_lines_cols()
            # Check size again
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
        }
        self.ss = ScreenStack(self.win, None, SCREENS, self.screens)

        # Create OptionSpinner with stack reference for proper action scoping
        spinner = self.spinner = OptionSpinner(stack=self.ss)
        self.spins = self.spinner.default_obj

        # Register all keys (with stack available, actions will be properly scoped)
        spinner.add_key('escape', 'ESC - back to prev screen', genre="action", keys=[27,])
        spinner.add_key('help_mode', '? - enter help screen', genre='action')
        spinner.add_key('verbose_header', 'm - more keys shown', vals=[False, True])
        spinner.add_key('quit', 'q,ctl-c - quit the app', genre='action', keys={0x3, ord('q')})

        spinner.add_key('cycle_next', '=>,SP - next cycle value',
                        genre='action', keys=[cs.KEY_RIGHT, ord(' ')])
        spinner.add_key('cycle_prev', '<=,BS - prev cycle value',
                        genre='action', keys=[ord('C'), cs.KEY_LEFT, cs.KEY_BACKSPACE])
        spinner.add_key('edit', 'e - edit value', genre='action')
        spinner.add_key('expert_edit', 'E - expert edit (minimal validation)', genre='action',
                            keys=[ord('E')])
        spinner.add_key('undo', 'u - revert value', genre='action')

        spinner.add_key('hide', 'x - inh/allow warnings', genre='action')
        spinner.add_key('show_hidden', 's - show/hide inactive params', genre='action')
        spinner.add_key('write', 'w - write params and run "grub-update"', genre='action')

        spinner.add_key('guide', 'g - guidance level', vals=['Off', 'Enums', "Full"])
        spinner.add_key('fancy_headers', 'f - cycle fancy headers (Off/Underline/Reverse)',
                        vals=['Underline', 'Reverse', 'Off'])


        spinner.add_key('enter_restore', 'R - enter restore screen', genre='action')
        spinner.add_key('enter_warnings', 'W - enter WARNINGs screen', genre='action')

        spinner.add_key('restore', 'r - restore selected backup [in restore screen]', genre='action')
        spinner.add_key('delete', 'd - delete selected backup [in restore screen]', genre='action')
        spinner.add_key('tag', 't - tag/retag a backup file [in restore screen]', genre='action')
        spinner.add_key('view', 'v - view a backup file [in restore screen]', genre='action')
        spinner.add_key('baseline', 'b - set CMP baseline [in restore screen]', genre='action')
        spinner.add_key('compare', 'c - compare with baseline [in restore screen]', genre='action')

        spinner.add_key('slash', '/ - filter pattern [in WARNINGS screen]', genre='action')

        # Add ENTER to handled keys so it passes through during search (no visible menu item)
        # This is needed for IncrementalSearchBar to receive ENTER key in passthrough mode
        spinner.add_key('_search_enter', '', keys=[10, 13])

        # Create incremental search bar for WarnScreen filtering
        def on_search_change(text):
            # Compile the search regex incrementally as user types
            warn_screen = self.screens.get(WARN_ST)
            if warn_screen:
                warn_screen.search = text
                try:
                    warn_screen.regex = re.compile(text, re.IGNORECASE) if text else None
                except re.error:
                    # Invalid regex, keep previous regex
                    pass

        def on_search_accept(text):
            # Finalize search: ensure the text is saved and exit passthrough mode
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
            # Restore original search text and exit passthrough mode
            warn_screen = self.screens.get(WARN_ST)
            if warn_screen:
                warn_screen.search = original_text
                try:
                    warn_screen.regex = re.compile(original_text, re.IGNORECASE) if original_text else None
                except re.error:
                    warn_screen.regex = None
            self.win.passthrough_mode = False

        self.search_bar = IncrementalSearchBar(
            on_change=on_search_change,
            on_accept=on_search_accept,
            on_cancel=on_search_cancel
        )

        # Create incremental search bar for HomeScreen parameter filtering
        def on_home_search_change(text):
            # Compile the search regex incrementally as user types
            home_screen = self.screens.get(HOME_ST)
            if home_screen:
                home_screen.search = text
                try:
                    home_screen.regex = re.compile(text, re.IGNORECASE) if text else None
                except re.error:
                    # Invalid regex, keep previous regex
                    pass

        def on_home_search_accept(text):
            # Finalize search: ensure the text is saved and exit passthrough mode
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
            # Restore original search text and exit passthrough mode
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

        # Important: Register keys with the window
        self.win.set_handled_keys(self.spinner)

    def get_enums_regex(self):
        """ TBD"""
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


    def truncate_line(self, line):
        """ TBD """
        return truncate_to_width(line, self.win.cols-1)

    def add_wrapped_body_line(self, line, indent, is_current, context=None):
        """ TBD """
        if not is_current:
            self.win.add_body(self.truncate_line(line), context=context)
            return 1

        wid = self.win.cols
        # textwrap counts code points; subtract the extra cells taken by any
        # double-width glyphs so a wrapped line cannot overflow the window.
        excess = display_width(line) - len(line)
        wrapped = textwrap.fill(line, width=max(wid-1-excess, 1),
                    subsequent_indent=' '*indent)
        wraps = wrapped.split('\n')
        for idx, wrap in enumerate(wraps):
            # First line gets the context, rest get TRANSIENT
            if idx == 0:
                self.win.add_body(wrap, context=context)
            else:
                self.win.add_body(wrap, context=Context(genre='TRANSIENT'))
        return len(wraps) # lines added

    def is_warn_hidden(self, param_name, hey):
        """ TBD """
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

    def add_fancy_header(self, line):
        """
        Wrapper that calls ConsoleWindow.add_fancy_header() with the current mode.
        Gets the mode from self.spins.fancy_headers and delegates to the window.
        """
        mode = self.spins.fancy_headers
        self.win.add_fancy_header(line, mode=mode)




    # Note: ensure_visible_group() and adjust_picked_pos_w_clues() have been removed
    # They are no longer needed - Context with genre='DECOR' auto-handles non-pickable lines
    # and TRANSIENT auto-abut ensures dropdown content stays visible

    def is_active_param(self, param_name):
        """ is the param neither commented out nor absent? """
        value = self.param_values.get(param_name, None)
        if value is not None:
            if value not in (GrubFile.COMMENT, GrubFile.ABSENT):
                return True
            return False
        return True # or False is better?

    def activate_param(self, param_name):
        """ TBD """
        value = self.param_values.get(param_name, None)
        if value in (GrubFile.COMMENT, GrubFile.ABSENT):
            value = self.saved_active_param_values.get(param_name, None)
            if value is None:
                value = self.param_cfg[param_name].get('default', '')
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
        """ TBD """
        def gen_enum_lines():
            nonlocal cfg, wid
            enums = cfg['enums']
            if not enums:
                return []
            value = self.param_values[param_name]
            edit = ' or [e]dit' if has_edit_regex(cfg['edit_re']) else ''
            # wrapped = f': 🡄 🡆 {edit}:\n'
            wrapped = f': ⮜–⮞ {edit}:\n'
            for enum, descr in cfg['enums'].items():
                star = ' ⯀ ' if str(enum) == str(value) else ' 🞏 '
                line = f' {star}{enum}: {descr}\n'
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

    def edit_param(self, win, name, regex):
        """ Prompt user for answer until gets it right"""

        # Check if this param uses EXPERT_EDIT mode
        if is_expert_edit(regex):
            self.expert_edit_param(win, name)
            return

        value = self.param_values[name]
        valid = False
        hint = ''

        # Get human description from config
        cfg = self.param_cfg.get(name, {})
        human_desc = cfg.get('edit_re_human', '')

        if human_desc:
            hint = human_desc
        elif regex:
            # Fallback to regex pattern if no human description
            if hasattr(regex, 'pattern'):
                pure_regex = regex.pattern
            else:
                pure_regex = str(regex).encode().decode('unicode_escape')
            hint = f'pat={pure_regex}'

        while not valid:
            prompt = f'Edit {name} [{hint}]'
            value = win.answer(prompt=prompt, seed=str(value),
                               height=self._answer_height(name))
            if value is None: # aborted
                return
            valid = True # until proven otherwise

            # First check regex if provided
            if regex:
                # Handle both compiled patterns and string patterns
                if hasattr(regex, 'match'):
                    match_result = regex.match(str(value))
                else:
                    match_result = re.match(regex, str(value))

                if not match_result:
                    valid = False
                    # Use human description in error message
                    if human_desc:
                        hint = f'must be: {human_desc}'
                    else:
                        if hasattr(regex, 'pattern'):
                            pure_regex = regex.pattern
                        else:
                            pure_regex = str(regex).encode().decode('unicode_escape')
                        hint = f'must match: {pure_regex}'
                    win.flash('Invalid input - please try again', duration=1.5)
                    continue

            # Then validate the shell boundary.  The value is written verbatim
            # as `PARAM=value` in a file that distro scripts source, so it must
            # stay one shell word; the regex above only checks GRUB semantics.
            # Command substitution is allowed only when this parameter's
            # config opts in (see _re_specs_.re_quoted_or_command_sub).
            ok, reason = check_shell_value(
                value, allow_command_sub=bool(cfg.get('allow_command_sub', False)))
            if not ok:
                valid = False
                hint = f'must be a safe shell value ({reason})'
                win.flash(f'Unsafe value - {reason}', duration=2.0)

        self.param_values[name] = value

    def expert_edit_param(self, win, name):
        """ Expert mode edit with minimal validation - escape hatch for grub-wiz errors """
        value = self.param_values[name]
        valid = False
        hint = 'expert mode: minimal checks'

        while not valid:
            prompt = f'Edit {name} [EXPERT MODE: {hint}]'
            value = win.answer(prompt=prompt, seed=str(value),
                               height=self._answer_height(name))
            if value is None: # aborted
                return

            # Minimal validation: the value must still stay one shell word.
            # Expert mode is an explicit administrator escape hatch, so a
            # whole-value command substitution is accepted here.
            ok, reason = check_shell_value(value, allow_command_sub=True)
            valid = ok
            if not ok:
                hint = f'must be a safe shell value ({reason})'
                win.flash(f'Unsafe value - {reason}', duration=2.0)

        self.param_values[name] = value

    def _is_valid_shell_token(self, value, allow_command_sub=False):
        """Return True when *value* is safe as a shell assignment value.

        Thin wrapper around :func:`check_shell_value` kept for callers that
        only need a boolean.
        """
        ok, _reason = check_shell_value(value, allow_command_sub)
        return ok


    def refresh_backup_list(self):
        """ TBD """
        self.backups = self.backup_mgr.get_backups()
        self.ordered_backup_pairs = sorted(self.backups.items(),
                           key=lambda item: item[1], reverse=True)

    def request_backup_tag(self, prompt, seed='custom'):
        """ Prompt user for a valid tag ... turn spaces into '-'
         automatically """
        regex = r'^[-_A-Za-z0-9]+$'
        hint = f'regex={regex}'
        while True:
            answer = self.win.answer(seed=seed,
                        prompt=f"{prompt} [{hint}]]", height=1)
            if answer is None:
                return None
            answer = answer.strip()
            answer = re.sub(r'[-\s]+', '-', answer)
            if re.match(regex, answer):
                return answer

    def do_start_up_backup(self):
        """ On startup
            - install the "orig" backup of none
            - offer to install any uniq backup
        """
        self.refresh_backup_list()
        checksum = self.backup_mgr.calc_checksum(GRUB_DEFAULT_PATH)
        if not self.backups:
            self.backup_mgr.create_backup('orig')
            self.refresh_backup_list()

        elif checksum not in self.backups:
            answer = self.request_backup_tag(f'Enter a tag to back up {GRUB_DEFAULT_PATH}')
            if answer:
                self.backup_mgr.create_backup(answer)
                self.refresh_backup_list()

        self.grub_checksum = checksum # checksum of loaded grub

    def really_wanna(self, act):
        """ Ask for explicit confirmation before a destructive action.

        The input starts empty, so Enter (or Esc) means "no": nothing is
        destroyed by a stray keypress.  Confirmation requires the entire
        answer to be ``yes`` (case/whitespace insensitive); ``y``, ``yeah``
        and any other prefix or typo are treated as a refusal.
        """
        # Ensure passthrough mode is off before prompting
        self.win.passthrough_mode = False
        # Flush input buffer to prevent stray keys from being processed
        cs.flushinp()
        # Prompt user for confirmation; empty seed => Enter does not confirm
        answer = self.win.answer(seed='',
                         prompt=f"Enter 'yes' to {act}", height=1)
        if answer is None:
            return False
        return answer.strip().lower() == 'yes'

    def update_grub(self):
        """ TBD """
        if not self.really_wanna('commit changes and update GRUB'):
            return

        diffs = self.get_diffs()
        for param_name, pair in diffs.items():
            self.grub_file.param_data[param_name].new_value = pair[1]

        self.win.stop_curses()
        time.sleep(.75)
        print("\033[2J\033[H") # 'clear'
        print('\n\n===== Leaving grub-wiz screens to update GRUB ====> ')
        # print('Check for correctness...')
        # print('-'*60)
        # print(contents)
        # print('-'*60)
        user_config = UserConfigDir.get_singleton()
        # Stage next to the target so os.replace() is atomic (same filesystem).
        # The staging name is unique and lives in a root-owned directory.
        candidate_path = user_config.staging_path(self.grub_writer.etc_grub)

        ok = self.grub_file.write_file(candidate_path)
        if not ok:
            # Staging failed before anything was touched; drop any partial file.
            try:
                if os.path.lexists(candidate_path):
                    os.unlink(candidate_path)
            except OSError:
                pass
        else:
            # Validate, install atomically, then run the GRUB update.  If the
            # update fails, GrubWriter restores the previous defaults file and
            # regenerates grub.cfg from it, so a rejected change cannot survive
            # the next boot.
            ok, commit_msg = self.grub_writer.commit_and_update(candidate_path)
            if not ok:
                print(commit_msg)

        # Check if initramfs rebuild is needed
        if ok and self.distro_vars.update_initramfs:
            needs_rebuild, trigger, category = self.grub_writer.should_rebuild_initramfs(diffs)
            if needs_rebuild:
                # Format category name for display
                category_display = category.replace('_', ' ').title()
                print(f"\n⚠️  {category_display} changes detected ('{trigger}').")
                print("Rebuilding initramfs ensures driver/module changes take effect at early boot.")

                # Check disk space before prompting
                space_info = self.grub_writer.check_initramfs_space()
                print(f"\nDisk space check: {space_info['message']}")

                # Determine if we should proceed
                if space_info['is_critical']:
                    print("\n🛑 CRITICAL: Insufficient disk space!")
                    print("   Initramfs rebuild would likely FAIL and may brick your system.")
                    print("   Please free up space in /boot first.")
                    print("\nSkipping initramfs rebuild for safety.")
                elif not space_info['is_sufficient']:
                    print("\n⚠️  Space is tight. Proceeding is risky but may work.")
                    choice = input('Continue with rebuild anyway? [y/N]: ').strip().lower()
                    if choice != 'y':
                        print('\nSkipping initramfs rebuild.')
                        print('Note: Some changes may not take effect until initramfs is rebuilt.')
                    else:
                        initramfs_ok, initramfs_msg = self.grub_writer.run_initramfs_update()
                        if initramfs_ok:
                            print('\n✓ Initramfs rebuilt successfully')
                        else:
                            print(f'\n✗ Initramfs rebuild failed:\n{initramfs_msg}')
                            print('Your GRUB changes are applied, but initramfs was not rebuilt.')
                else:
                    # Sufficient space, normal prompt
                    choice = input('\nRebuild initramfs now? [y/N]: ').strip().lower()
                    if choice == 'y':
                        initramfs_ok, initramfs_msg = self.grub_writer.run_initramfs_update()
                        if initramfs_ok:
                            print('\n✓ Initramfs rebuilt successfully')
                        else:
                            print(f'\n✗ Initramfs rebuild failed:\n{initramfs_msg}')
                            print('Your GRUB changes are applied, but initramfs was not rebuilt.')
                            print('You may need to rebuild it manually later.')
                    else:
                        print('\nSkipping initramfs rebuild.')
                        print('Note: Some changes may not take effect until initramfs is rebuilt.')

        if ok:
            os.system('\n\necho "OK ... /etc/default/grub newly written/updated"')
        else:
            os.system('\n\necho "FAIL ... changes NOT applied (previous /etc/default/grub kept)"')
        print('\n\nChoose:')
        if ok:
            print('  [r]eboot now')
            print('  [p]oweroff')
        print('  [q]uit')
        print('  ENTER to return to grub-wiz screen')

        choice = input('\n> ').strip().lower()

        if choice == 'r':
            print('\nRebooting...')
            os.system('reboot')
            sys.exit(0)  # Won't reach here, but just in case
        elif choice == 'p':
            print('\nPowering off...')
            os.system('poweroff')
            sys.exit(0)  # Won't reach here, but just in case
        elif choice == 'q':
            print('\nQuitting grub-wiz...')
            sys.exit(0)  # Won't reach here, but just in case
        # Otherwise continue to grub-wiz
        else:
            self.win.start_curses()
            if ok:
                self.reinit_gw()
                self.reset_screen_stack()
                self.do_start_up_backup()

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
        """
        Navigate to a screen with validation hooks.

        Args:
            screen_num: Screen number to navigate to

        Returns:
            True if navigation succeeded, False if blocked
        """
        result = self.ss.push(screen_num, self.prev_pos)
        if result is not None:
            self.prev_pos = result
            return True
        return False

    def navigate_back(self):
        """
        Navigate back to previous screen with validation hooks.

        Returns:
            True if navigation succeeded, False if blocked or no stack
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
        """
        Generic escape handler with context awareness.
        Returns:
            True if escape was handled, False otherwise
        """
        if self.ss.stack:
            return self.navigate_back()
        return False

    def main_loop(self):
        """ TBD """
        self.setup_win()
        self.do_start_up_backup()
        win, spins = self.win, self.spins # shorthand
        self.next_prompt_seconds = [0.1, 0.1]

        while True:

            screen_num = self.ss.curr.num
            self.screens[screen_num].draw_screen()

            win.render()
            key = win.prompt(seconds=self.next_prompt_seconds[0])

            self.next_prompt_seconds.pop(0)
            if not self.next_prompt_seconds:
                self.next_prompt_seconds = [3.0]

            if key is None:
                # Note: adjust_picked_pos_w_clues() removed - Context pickable handles this
                pass

            if key is not None:
                # Check if any search bar is active and should handle the key
                if self.search_bar.is_active:
                    if self.search_bar.handle_key(key):
                        # Key was handled by warn search bar, clear screen and redraw
                        win.clear()
                        continue
                elif self.home_search_bar.is_active:
                    if self.home_search_bar.handle_key(key):
                        # Key was handled by home search bar, clear screen and redraw
                        win.clear()
                        continue

                self.spinner.do_key(key, win)

                # Handle app-level quit action
                if spins.quit:
                    spins.quit = False
                    if self.ss.is_curr(RESTORE_ST):
                        self.navigate_back()
                    else:
                        break

                # Use perform_actions() to automatically handle all screen-specific actions
                # This replaces the manual action list and handles: cycle_next, cycle_prev,
                # undo, show_hidden, edit, expert_edit, hide, write, restore, delete, tag,
                # view, slash, baseline, compare, escape, help_mode, enter_restore, enter_warnings
                self.ss.perform_actions(self.spinner)

            win.clear()

def rerun_module_as_root(module_name):
    """ rerun using the module name """
    if os.geteuid() != 0: # Re-run the script with sudo
        os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        vp = ['sudo', sys.executable, '-m', module_name] + sys.argv[1:]
        os.execvp('sudo', vp)


def main():
    """ TBD """
    rerun_module_as_root('grub_wiz.main')
    parser = ArgumentParser(description='grub-wiz: your grub-update guide')
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
    opts = parser.parse_args()

    wiz = GrubWiz(cli_opts=opts)
    if opts.validator_demo:
        wiz.wiz_validator.demo(wiz.param_defaults)
        sys.exit(0)

    if opts.validate_custom_config:
        print(f'grub-wiz: using {wiz.canned_config.using_path}')
        if 'custom' not in str(wiz.canned_config.using_path):
            print("NOTE: custom config NOT being used")
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
            if deleted:
                print(f'Deleted: {", ".join(deleted)}')
            else:
                print('No cached files to delete.')
            print('Factory reset complete. Backup files (.bak) preserved.')
        except Exception as whynot:
            print(f'ERR: failed "factory reset" [{whynot}]')
        sys.exit(0)

    time.sleep(1.0)
    wiz.main_loop()

if __name__ == '__main__':
    try:
        main()
    except Exception as exce:
        if GrubWiz.singleton and GrubWiz.singleton.win:
            GrubWiz.singleton.win.stop_curses()
        print("exception:", str(exce))
        print(traceback.format_exc())
        sys.exit(15)
