#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Custom Wrapper for python curses, providing structured window management
and an interactive option/key handler.

This module provides two main classes: :py:class:`ConsoleWindow` for handling
the screen, scrolling, and input; and :py:class:`OptionSpinner` for managing
a set of key-driven application settings.
"""
# pylint: disable=too-many-instance-attributes,too-many-arguments
# pylint: disable=invalid-name,broad-except,too-many-branches,global-statement
# pylint: disable=line-too-long,too-many-statements,too-many-locals

import sys
import traceback
import atexit
import signal
import time
import curses
import textwrap
from types import SimpleNamespace
from curses.textpad import rectangle, Textbox
dump_str = None

ctrl_c_flag = False


class ConsoleWindowOpts:
    """
    Options class for ConsoleWindow with enforced valid members using __slots__.
    All options have sensible defaults.
    """
    __slots__ = ['head_line', 'head_rows', 'body_rows', 'body_cols', 'keys',
                 'pick_mode', 'pick_size', 'mod_pick', 'ctrl_c_terminates',
                 'return_if_pos_change', 'min_cols_rows', 'dialog_abort', 'dialog_return']

    def __init__(self, **kwargs):
        """
        Initialize ConsoleWindowOpts with defaults. All parameters are optional.

        :param head_line: If True, draws a horizontal line between header and body (default: True)
        :param head_rows: Maximum capacity of internal header pad (default: 50)
        :param body_rows: Maximum capacity of internal body pad (default: 200)
        :param body_cols: Maximum width for content pads (default: 200)
        :param keys: Collection of key codes explicitly returned by prompt (default: None)
        :param pick_mode: If True, enables item highlighting/selection (default: False)
        :param pick_size: Number of rows highlighted as single 'pick' unit (default: 1)
        :param mod_pick: Optional callable to modify highlighted text (default: None)
        :param ctrl_c_terminates: If True, Ctrl-C terminates; if False, returns key 3 (default: True)
        :param return_if_pos_change: If True, prompt returns when pick position changes (default: False)
        :param min_cols_rows: Minimum terminal size as (cols, rows) tuple (default: (70, 20))
        :param dialog_abort: How ESC aborts dialogs: None, "ESC", "ESC-ESC" (default: "ESC")
        :param dialog_return: Which key submits dialogs: "ENTER", "TAB" (default: "ENTER")
        """
        self.head_line = kwargs.get('head_line', True)
        self.head_rows = kwargs.get('head_rows', 50)
        self.body_rows = kwargs.get('body_rows', 200)
        self.body_cols = kwargs.get('body_cols', 200)
        self.keys = kwargs.get('keys', None)
        self.pick_mode = kwargs.get('pick_mode', False)
        self.pick_size = kwargs.get('pick_size', 1)
        self.mod_pick = kwargs.get('mod_pick', None)
        self.ctrl_c_terminates = kwargs.get('ctrl_c_terminates', True)
        self.return_if_pos_change = kwargs.get('return_if_pos_change', False)
        self.min_cols_rows = kwargs.get('min_cols_rows', (70, 20))
        self.dialog_abort = kwargs.get('dialog_abort', 'ESC')
        self.dialog_return = kwargs.get('dialog_return', 'ENTER')

        # Validate dialog_abort
        if self.dialog_abort not in [None, 'ESC', 'ESC-ESC']:
            raise ValueError(f"dialog_abort must be None, 'ESC', or 'ESC-ESC', got {self.dialog_abort!r}")

        # Validate dialog_return
        if self.dialog_return not in ['ENTER', 'TAB']:
            raise ValueError(f"dialog_return must be 'ENTER' or 'TAB', got {self.dialog_return!r}")

def ctrl_c_handler(sig, frame):
    """
    Custom handler for SIGINT (Ctrl-C).
    Sets a global flag to be checked by the main input loop.
    """
    global ctrl_c_flag
    ctrl_c_flag = True

def ignore_ctrl_c():
    """
    Ignores the **SIGINT** signal (Ctrl-C) to prevent immediate termination.
    Used during curses operation.
    """
    signal.signal(signal.SIGINT, signal.SIG_IGN)

def restore_ctrl_c():
    """
    Restores the default signal handler for **SIGINT** (Ctrl-C).
    Called upon curses shutdown.
    """
    signal.signal(signal.SIGINT, signal.default_int_handler)

class OptionSpinner:
    """
    Manages a set of application options where the value can be rotated through
    a fixed set of values (spinner) or requested via a dialog box (prompt) by
    pressing a single key.

    It also generates a formatted help screen based on the registered options.
    """
    def __init__(self):
        """
        Initializes the OptionSpinner, setting up internal mappings for options
        and keys.
        """
        self.options, self.keys = [], []
        self.margin = 4 # + actual width (1st column right pos)
        self.align = self.margin # + actual width (1st column right pos)
        self.default_obj = SimpleNamespace() # if not given one
        self.attr_to_option = {} # given an attribute, find its option ns
        self.key_to_option = {} # given key, options namespace
        self.keys = set()

    @staticmethod
    def _make_option_ns():
        """Internal helper to create a default namespace for an option."""
        return SimpleNamespace(
            keys=[],
            descr='',
            obj=None,
            attr='',
            vals=None,
            prompt=None,
            comments=[],
            category=None,
        )

    def get_value(self, attr, coerce=False):
        """
        Get the current value of the given attribute.

        :param attr: The name of the attribute (e.g., 'help_mode').
        :param coerce: If True, ensures the value is one of the valid 'vals'
                       or an empty string for prompted options.
        :type attr: str
        :type coerce: bool
        :returns: The current value of the option attribute.
        :rtype: Any
        """
        ns = self.attr_to_option.get(attr, None)
        obj = ns.obj if ns else None
        value = getattr(obj, attr, None) if obj else None
        if value is None and obj and coerce:
            if ns.vals:
                if value not in ns.vals:
                    value = ns.vals[0]
                    setattr(obj, attr, value)
            else:
                if value is None:
                    value = ''
                    setattr(ns.obj, ns.attr, '')
        return value

    def _register(self, ns):
        """Create the internal mappings needed for a new option namespace."""
        assert ns.attr not in self.attr_to_option
        self.attr_to_option[ns.attr] = ns
        for key in ns.keys:
            assert key not in self.key_to_option, f'key ({chr(key)}, {key}) already used'
            self.key_to_option[key] = ns
            self.keys.add(key)
        self.options.append(ns)
        self.align = max(self.align, self.margin+len(ns.descr))
        self.get_value(ns.attr, coerce=True)

    def add(self, obj, specs):
        """
        **Compatibility Method.** Adds options using an older array-of-specs format.

        A spec is a list or tuple like::

            ['a - allow auto suggestions', 'allow_auto', True, False],
            ['/ - filter pattern', 'filter_str', self.filter_str],

        The key is derived from the first character of the description string.
        It is recommended to use :py:meth:`add_key` for new code.

        :param obj: The object holding the option attributes (e.g., an argparse namespace).
        :param specs: An iterable of option specifications.
        :type obj: Any
        :type specs: list
        """
        for spec in specs:
            ns = self._make_option_ns()
            ns.descr = spec[0]
            ns.obj = obj
            ns.attr = spec[1]
            ns.vals=spec[2:]
            if None in ns.vals:
                idx = ns.vals.index(None)
                ns.vals = ns.vals[:idx]
                ns.comments = ns.vals[idx+1:]
            ns.keys = [ord(ns.descr[0])]
            self._register(ns)

    def add_key(self, attr, descr, obj=None, vals=None, prompt=None,
                keys=None, comments=None, category=None):
        """
        Adds an option that is toggled by a key press.

        The option can be a **spinner** (rotates through a list of ``vals``) or
        a **prompt** (requests string input via a dialog).

        :param attr: The name of the attribute for the value; referenced as ``obj.attr``.
        :param descr: The description of the key (for help screen).
        :param obj: The object holding the value. If None, uses ``self.default_obj``.
        :param vals: A list of values. If provided, the option is a spinner.
        :param prompt: A prompt string. If provided instead of ``vals``, the key press
                       will call :py:meth:`ConsoleWindow.answer`.
        :param keys: A single key code or a list of key codes (integers or characters)
                     that will trigger this option. If None, uses the first letter of
                     ``descr``.
        :param comments: Additional line(s) for the help screen item (string or list of strings).
        :param category: (action, cycle, prompt)
        :type attr: str
        :type descr: str
        :type obj: Any
        :type vals: list or None
        :type prompt: str or None
        :type keys: int or list or tuple or None
        :type comments: str or list or tuple or None
        :type category: str or None
        :raises AssertionError: If both ``vals`` and ``prompt`` are provided, or neither is.
        :raises AssertionError: If a key is already registered.
        """

        ns = self._make_option_ns()
        if keys:
            ns.keys = list(keys) if isinstance(keys, (list, tuple, set)) else [keys]
        else:
            ns.keys = [ord(descr[0])]
        if comments is None:
            ns.comments = []
        else:
            ns.comments = list(comments) if isinstance(keys, (list, tuple)) else [comments]
        ns.descr = descr
        ns.attr = attr
        ns.obj = obj if obj else self.default_obj
        if vals:
            ns.vals, ns.category = vals, 'cycle'
        elif prompt:
            ns.prompt, ns.category = prompt, 'prompt'
        else:
            ns.category = 'action'
        self._register(ns)

    @staticmethod
    def show_help_nav_keys(win):
        """
        Displays the standard navigation keys blurb in the provided ConsoleWindow.

        :param win: The :py:class:`ConsoleWindow` instance to write to.
        :type win: ConsoleWindow
        """
        for line in ConsoleWindow.get_nav_keys_blurb().splitlines():
            if line:
                win.add_header(line)

    def show_help_body(self, win):
        """
        Writes the formatted list of all registered options and their current
        values to the body of the provided :py:class:`ConsoleWindow`.

        :param win: The :py:class:`ConsoleWindow` instance to write to.
        :type win: ConsoleWindow
        """
        win.add_body('Type keys to alter choice:', curses.A_UNDERLINE)

        for ns in self.options:
            # get / coerce the current value
            value = self.get_value(ns.attr)
            assert value is not None, f'cannot get value of {repr(ns.attr)}'

            colon = '' if ns.category == 'action' else ':'
            win.add_body(f'{ns.descr:>{self.align}}{colon} ')

            if ns.category in ('cycle', 'prompt'):
                choices = ns.vals if ns.vals else [value]
                for choice in choices:
                    shown = f'{choice}'
                    if isinstance(choice, bool):
                        shown = "ON" if choice else "off"
                    win.add_body(' ', resume=True)
                    win.add_body(shown, resume=True,
                        attr=curses.A_REVERSE if choice == value else None)

            for comment in ns.comments:
                win.add_body(f'{"":>{self.align}}:  {comment}')

    def do_key(self, key, win):
        """
        Processes a registered key press.

        If the option is a spinner, it rotates to the next value. If it
        requires a prompt, it calls ``win.answer()`` to get user input.

        :param key: The key code received from :py:meth:`ConsoleWindow.prompt`.
        :param win: The :py:class:`ConsoleWindow` instance for dialogs.
        :type key: int
        :type win: ConsoleWindow
        :returns: The new value of the option, or None if the key is unhandled.
        :rtype: Any or None
        """
        ns = self.key_to_option.get(key, None)
        if ns is None:
            return None
        value = self.get_value(ns.attr)
        if ns.category == 'cycle':
            idx = ns.vals.index(value) if value in ns.vals else -1
            value = ns.vals[(idx+1) % len(ns.vals)] # choose next
        elif ns.category == 'prompt':
            value = win.answer(prompt=ns.prompt, seed=str(value))
        elif ns.category == 'action':
            value = True

        setattr(ns.obj, ns.attr, value)
        return value

class ConsoleWindow:
    """
    A high-level wrapper around the curses library that provides a structured
    interface for terminal applications.

    The screen is divided into a fixed-size **Header** area and a scrollable
    **Body** area, separated by an optional line. It manages screen
    initialization, cleanup, rendering, and user input including scrolling
    and an optional item selection (pick) mode.
    """
    timeout_ms = 200
    static_scr = None
    nav_keys = """
        Navigation:      H/M/L:      top/middle/end-of-page
          k, UP:  up one row             0, HOME:  first row
        j, DOWN:  down one row           $, END:  last row
          Ctrl-u:  half-page up     Ctrl-b, PPAGE:  page up
          Ctrl-d:  half-page down     Ctrl-f, NPAGE:  page down
    """
    def __init__(self, opts=None, head_line=None, head_rows=None, body_rows=None,
                 body_cols=None, keys=None, pick_mode=None, pick_size=None,
                 mod_pick=None, ctrl_c_terminates=None):
        """
        Initializes the ConsoleWindow, sets up internal pads, and starts curses mode.

        :param opts: ConsoleWindowOpts instance with all options (recommended)
        :param head_line: DEPRECATED - use opts. If True, draws a horizontal line between header and body.
        :param head_rows: DEPRECATED - use opts. Maximum capacity of internal header pad.
        :param body_rows: DEPRECATED - use opts. Maximum capacity of internal body pad.
        :param body_cols: DEPRECATED - use opts. Maximum width for content pads.
        :param keys: DEPRECATED - use opts. Collection of key codes returned by prompt.
        :param pick_mode: DEPRECATED - use opts. If True, enables item highlighting/selection.
        :param pick_size: DEPRECATED - use opts. Number of rows highlighted as single pick unit.
        :param mod_pick: DEPRECATED - use opts. Optional callable to modify highlighted text.
        :param ctrl_c_terminates: DEPRECATED - use opts. If True, Ctrl-C terminates; if False, returns key 3.
        :type opts: ConsoleWindowOpts or None
        """
        # Enforce either opts OR deprecated parameters, not both
        has_opts = opts is not None
        has_deprecated = any(p is not None for p in [head_line, head_rows, body_rows, body_cols,
                                                       keys, pick_mode, pick_size, mod_pick, ctrl_c_terminates])

        if has_opts and has_deprecated:
            raise ValueError("Cannot use both 'opts' and deprecated parameters. Use opts only.")

        # Use opts or create default
        if has_opts:
            self.opts = opts
        elif has_deprecated:
            # Backward compatibility: create opts from deprecated parameters
            self.opts = ConsoleWindowOpts(
                head_line=head_line if head_line is not None else True,
                head_rows=head_rows if head_rows is not None else 50,
                body_rows=body_rows if body_rows is not None else 200,
                body_cols=body_cols if body_cols is not None else 200,
                keys=keys,
                pick_mode=pick_mode if pick_mode is not None else False,
                pick_size=pick_size if pick_size is not None else 1,
                mod_pick=mod_pick,
                ctrl_c_terminates=ctrl_c_terminates if ctrl_c_terminates is not None else True
            )
        else:
            # No parameters provided - use all defaults
            self.opts = ConsoleWindowOpts()

        # Modify signal handlers based on user choice
        global ignore_ctrl_c, restore_ctrl_c
        if self.opts.ctrl_c_terminates:
            # then never want to ignore_ctrl_c (so defeat the ignorer/restorer)
            def noop():
                return
            ignore_ctrl_c = restore_ctrl_c = noop
            self.ctrl_c_terminates = self.opts.ctrl_c_terminates
        else:
            # If not terminating, override the original signal functions
            # to set the custom handler, which will pass key 3 via the flag.
            def _setup_ctrl_c():
                signal.signal(signal.SIGINT, ctrl_c_handler)
            def _restore_ctrl_c():
                signal.signal(signal.SIGINT, signal.default_int_handler)
            ignore_ctrl_c = _setup_ctrl_c
            restore_ctrl_c = _restore_ctrl_c

        self.scr = self._start_curses()

        self.head = SimpleNamespace(
            pad=curses.newpad(self.opts.head_rows, self.opts.body_cols),
            rows=self.opts.head_rows,
            cols=self.opts.body_cols,
            row_cnt=0,  # no. head rows added
            texts = [],
            view_cnt=0,  # no. head rows viewable (NOT in body)
        )
        self.body = SimpleNamespace(
            pad = curses.newpad(self.opts.body_rows, self.opts.body_cols),
            rows= self.opts.body_rows,
            cols=self.opts.body_cols,
            row_cnt = 0,
            texts = []
        )
        self.mod_pick = self.opts.mod_pick # call back to modify highlighted row
        self.hor_line_cnt = 1 if self.opts.head_line else 0 # no. h-lines in header
        self.scroll_pos = 0  # how far down into body are we?
        self.max_scroll_pos = 0
        self.pick_pos = 0 # in highlight mode, where are we?
        self.last_pick_pos = -1 # last highlighted position
        self.pick_mode = self.opts.pick_mode # whether in highlight mode
        self.pick_size = self.opts.pick_size # whether in highlight mode
        self.rows, self.cols = 0, 0
        self.body_cols, self.body_rows = self.opts.body_cols, self.opts.body_rows
        self.scroll_view_size = 0  # no. viewable lines of the body
        self.handled_keys = set(self.opts.keys) if isinstance(self.opts.keys, (set, list)) else []
        self.pending_keys = set()
        self._set_screen_dims()
        self.calc()

    def get_pad_width(self):
        """
        Returns the maximum usable column width for content drawing.

        :returns: The width in columns.
        :rtype: int
        """
        return min(self.cols-1, self.body_cols)

    @staticmethod
    def get_nav_keys_blurb():
        """
        Returns a multiline string describing the default navigation key bindings
        for use in help screens.

        :returns: String of navigation keys.
        :rtype: str
        """
        return textwrap.dedent(ConsoleWindow.nav_keys)

    def _set_screen_dims(self):
        """Recalculate dimensions based on current terminal size."""
        rows, cols = self.scr.getmaxyx()
        same = bool(rows == self.rows and cols == self.cols)
        self.rows, self.cols = rows, cols
        return same

    def _check_min_size(self):
        """
        Checks if current terminal size meets minimum requirements.
        Blocks with a message if too small, waiting for resize or ESC.

        :returns: True if size is acceptable, False if user pressed ESC to abort
        :rtype: bool
        """
        min_cols, min_rows = self.opts.min_cols_rows

        while self.rows < min_rows or self.cols < min_cols:
            self.scr.clear()
            msg1 = f"Min size: {min_cols}x{min_rows}"
            msg2 = f"Current: {self.cols}x{self.rows}"
            try:
                self.scr.addstr(0, 0, msg1, curses.A_REVERSE)
                self.scr.addstr(1, 0, msg2, curses.A_REVERSE)
            except curses.error:
                pass  # Terminal too small even for message
            self.scr.refresh()

            # Wait for key
            key = self.scr.getch()
            if key == 27:  # ESC to abort
                return False
            if key == curses.KEY_RESIZE:
                curses.update_lines_cols()
                self._set_screen_dims()

        return True

    @staticmethod
    def _start_curses():
        """
        For compatibility only. Used to be private, but that was annoying.
        """
        return ConsoleWindow.start_curses()

    @staticmethod
    def start_curses():
        """
        Performs the Curses initial setup: initscr, noecho, cbreak, curs_set(0),
        keypad(1), and sets up the timeout.

        :returns: The main screen object.
        :rtype: _curses.window
        """
        # The signal setup is handled in __init__ (via ignore_ctrl_c call below)
        atexit.register(ConsoleWindow.stop_curses)
        ignore_ctrl_c()
        ConsoleWindow.static_scr = scr = curses.initscr()
        curses.noecho()
        curses.cbreak()
        curses.curs_set(0)
        scr.keypad(1)
        scr.timeout(ConsoleWindow.timeout_ms)
        scr.clear()
        return scr

    def set_pick_mode(self, on=True, pick_size=1):
        """
        Toggles the item highlighting/selection mode for the body area.

        If pick mode is enabled or the pick size changes, it forces a redraw
        of all body lines to clear any previous highlighting attributes.

        :param on: If True, enables pick mode.
        :param pick_size: The number of consecutive rows to highlight as one unit.
        :type on: bool
        :type pick_size: int
        """
        was_on, was_size = self.pick_mode, self.pick_size
        self.pick_mode = bool(on)
        self.pick_size = max(pick_size, 1)
        if self.pick_mode and (not was_on or was_size != self.pick_size):
            self.last_pick_pos = -2 # indicates need to clear them all

    @staticmethod
    def stop_curses():
        """
        Curses shutdown (registered to be called on exit). Restores the terminal
        to its pre-curses state.
        """
        if ConsoleWindow.static_scr:
            curses.nocbreak()
            curses.echo()
            ConsoleWindow.static_scr.keypad(0)
            curses.endwin()
            ConsoleWindow.static_scr = None
            restore_ctrl_c()

    def calc(self):
        """
        Recalculates the screen geometry, viewable areas, and maximum scroll position.

        :returns: True if the screen geometry has changed, False otherwise.
        :rtype: bool
        """
        same = self._set_screen_dims()
        self.head.view_cnt = min(self.rows - self.hor_line_cnt, self.head.row_cnt)
        self.scroll_view_size = self.rows - self.head.view_cnt - self.hor_line_cnt
        self.max_scroll_pos = max(self.body.row_cnt - self.scroll_view_size, 0)
        self.body_base = self.head.view_cnt + self.hor_line_cnt
        return not same

    def _put(self, ns, *args):
        """
        Adds text to the head/body pad using a mixed argument list.

        Allows interleaving of text (str/bytes) and curses attributes (int).
        Text segments before an attribute are flushed with that attribute.
        """
        def flush(attr=None):
            nonlocal self, is_body, row, text, seg, first
            if (is_body and self.pick_mode) or attr is None:
                attr = curses.A_NORMAL
            if seg and first:
                ns.pad.addstr(row, 0, seg[0:self.get_pad_width()], attr)
            elif seg:
                _, x = ns.pad.getyx()
                cols = self.get_pad_width() - x
                if cols > 0:
                    ns.pad.addstr(seg[0:cols], attr)
            text += seg
            seg, first, attr = '', False, None

        is_body = bool(id(ns) == id(self.body))
        if ns.row_cnt < ns.rows:
            row = max(ns.row_cnt, 0)
            text, seg, first = '', '', True
            for arg in args:
                if isinstance(arg, bytes):
                    arg = arg.decode('utf-8')
                if isinstance(arg, str):
                    seg += arg  # note: add w/o spacing
                elif arg is None or isinstance(arg, (int)):
                    # assume arg is attribute ... flushes text
                    flush(attr=arg)
            flush()
            ns.texts.append(text)  # text only history
            ns.row_cnt += 1

    def put_head(self, *args):
        """
        Adds a line of text to the header pad, supporting mixed text and attributes.

        :param args: Mixed arguments of str/bytes (text) and int (curses attributes).
        :type args: Any
        """
        self._put(self.head, *args)

    def put_body(self, *args):
        """
        Adds a line of text to the body pad, supporting mixed text and attributes.

        :param args: Mixed arguments of str/bytes (text) and int (curses attributes).
        :type args: Any
        """
        self._put(self.body, *args)

    def _add(self, ns, text, attr=None, resume=False):
        """Internal method to add text to pad using its namespace (simpler version of _put)."""
        is_body = bool(id(ns) == id(self.body))
        if ns.row_cnt < ns.rows:
            row = max(ns.row_cnt - (1 if resume else 0), 0)
            if (is_body and self.pick_mode) or attr is None:
                attr = curses.A_NORMAL
            if resume:
                _, x = ns.pad.getyx()
                cols = self.get_pad_width() - x
                if cols > 0:
                    ns.pad.addstr(text[0:cols], attr)
                    ns.texts[row] += text
            else:
                ns.pad.addstr(row, 0, text[0:self.cols], attr)
                ns.texts.append(text)  # text only history
                ns.row_cnt += 1

    def add_header(self, text, attr=None, resume=False):
        """
        Adds a line of text to the header pad.

        :param text: The text to add.
        :param attr: Curses attribute (e.g., curses.A_BOLD).
        :param resume: If True, adds the text to the current, incomplete line.
        :type text: str
        :type attr: int or None
        :type resume: bool
        """
        self._add(self.head, text, attr, resume)

    def add_body(self, text, attr=None, resume=False):
        """
        Adds a line of text to the body pad.

        :param text: The text to add.
        :param attr: Curses attribute (e.g., curses.A_BOLD).
        :param resume: If True, adds the text to the current, incomplete line.
        :type text: str
        :type attr: int or None
        :type resume: bool
        """
        self._add(self.body, text, attr, resume)

    def draw(self, y, x, text, text_attr=None, width=None, leftpad=False, header=False):
        """
        Draws the given text at a specific position (row=y, col=x) on a pad.

        This method is useful for structured or overlay drawing, but is less
        efficient than the standard add/put methods.

        :param y: The row index on the pad.
        :param x: The column index on the pad.
        :param text: The text to draw (str or bytes).
        :param text_attr: Optional curses attribute.
        :param width: Optional fixed width for the drawn text (pads/truncates).
        :param leftpad: If True and ``width`` is used, left-pads with spaces.
        :param header: If True, draws to the header pad, otherwise to the body pad.
        :type y: int
        :type x: int
        :type text: str or bytes
        :type text_attr: int or None
        :type width: int or None
        :type leftpad: bool
        :type header: bool
        """
        ns = self.head if header else self.body
        text_attr = text_attr if text_attr else curses.A_NORMAL
        if y < 0 or y >= ns.rows or x < 0 or x >= ns.cols:
            return # nada if out of bounds
        ns.row_cnt = max(ns.row_cnt, y+1)

        uni = text if isinstance(text, str) else text.decode('utf-8')

        if width is not None:
            width = min(width, self.get_pad_width() - x)
            if width <= 0:
                return
            padlen = width - len(uni)
            if padlen > 0:
                if leftpad:
                    uni = padlen * ' ' + uni
                else:  # rightpad
                    uni += padlen * ' '
            text = uni[:width].encode('utf-8')
        else:
            text = uni.encode('utf-8')

        try:
            while y >= len(ns.texts):
                ns.texts.append('')
            ns.texts[y] = ns.texts[y][:x].ljust(x) + uni + ns.texts[y][x+len(uni):]
            ns.pad.addstr(y, x, text, text_attr)
        except curses.error:
            # curses errors on drawing the last character on the screen; ignore
            pass


    def highlight_picked(self):
        """
        Highlights the current selection and un-highlights the previous one.
        Called internally during :py:meth:`render_once` when in pick mode.
        """
        def get_text(pos):
            nonlocal self
            return self.body.texts[pos][0:self.cols] if pos < len(self.body.texts) else ''

        if not self.pick_mode:
            return
        pos0, pos1 = self.last_pick_pos, self.pick_pos
        if pos0 == -2: # special flag to clear all formatting
            for row in range(self.body.row_cnt):
                line = get_text(row).ljust(self.get_pad_width())
                self.body.pad.addstr(row, 0, get_text(row), curses.A_NORMAL)
        if pos0 != pos1:
            if 0 <= pos0 < self.body.row_cnt:
                for i in range(self.pick_size):
                    line = get_text(pos0+i).ljust(self.get_pad_width())
                    self.body.pad.addstr(pos0+i, 0, line, curses.A_NORMAL)
            if 0 <= pos1 < self.body.row_cnt:
                for i in range(self.pick_size):
                    line = get_text(pos1+i)
                    if self.mod_pick:
                        line = self.mod_pick(line)
                    line = line.ljust(self.get_pad_width())
                    self.body.pad.addstr(pos1+i, 0, line, curses.A_REVERSE)
                self.last_pick_pos = pos1

    def _scroll_indicator_row(self):
        """Internal helper to compute the scroll indicator row position."""
        if self.max_scroll_pos <= 1:
            return self.body_base
        y2, y1 = self.scroll_view_size-1, 1
        x2, x1 = self.max_scroll_pos, 1
        x = self.scroll_pos
        pos = y1 + (y2-y1)*(x-x1)/(x2-x1)
        return min(self.body_base + int(max(pos, 0)), self.rows-1)

    def _scroll_indicator_col(self):
        """Internal helper to compute the scroll indicator column position."""
        if self.pick_mode:
            return self._calc_indicator(
                self.pick_pos, 0, self.body.row_cnt-1, 0, self.cols-1)
        return self._calc_indicator(
            self.scroll_pos, 0, self.max_scroll_pos, 0, self.cols-1)

    def _calc_indicator(self, pos, pos0, pos9, ind0, ind9):
        """Internal helper to calculate indicator position based on content position."""
        if self.max_scroll_pos <= 0:
            return -1 # not scrollable
        if pos9 - pos0 <= 0:
            return -1 # not scrollable
        if pos <= pos0:
            return ind0
        if pos >= pos9:
            return ind9
        ind = int(round(ind0 + (ind9-ind0+1)*(pos-pos0)/(pos9-pos0+1)))
        return min(max(ind, ind0+1), ind9-1)

    def render(self, redraw=False):
        """
        Draws the content of the pads to the visible screen.

        :param redraw: If True, forces a complete redraw of all pads and the screen
                    to clear terminal corruption.

        This method wraps :py:meth:`render_once` in a loop to handle spurious
        ``curses.error`` exceptions that can occur during screen resizing.
        """
        for _ in range(128):
            try:
                self.render_once(redraw)
                return
            except curses.error:
                time.sleep(0.16)
                self._set_screen_dims()
                continue
        try:
            self.render_once(redraw)
        except Exception:
            ConsoleWindow.stop_curses()
            print(f"""curses err:
    head.row_cnt={self.head.row_cnt}
    head.view_cnt={self.head.view_cnt}
    hor_line_cnt={self.hor_line_cnt}
    body.row_cnt={self.body.row_cnt}
    scroll_pos={self.scroll_pos}
    max_scroll_pos={self.max_scroll_pos}
    pick_pos={self.pick_pos}
    last_pick_pos={self.last_pick_pos}
    pick_mode={self.pick_mode}
    pick_size={self.pick_size}
    rows={self.rows}
    cols={self.cols}
""")
            raise


    def fix_positions(self, delta=0):
        """
        Ensures the vertical scroll and pick positions are within valid boundaries,
        adjusting the scroll position to keep the pick cursor visible.

        :param delta: An optional change in position (e.g., from key presses).
        :type delta: int
        :returns: The indent amount for the body content (1 if pick mode is active, 0 otherwise).
        :rtype: int
        """
        self.calc()
        if self.pick_mode:
            self.pick_pos += delta
        else:
            self.scroll_pos += delta
            self.pick_pos += delta

        indent = 0
        if self.body_base < self.rows:
            ind_pos = 0 if self.pick_mode else self._scroll_indicator_row()
            if self.pick_mode:
                self.pick_pos = max(self.pick_pos, 0)
                self.pick_pos = min(self.pick_pos, self.body.row_cnt-1)
                if self.pick_pos >= 0:
                    self.pick_pos -= (self.pick_pos % self.pick_size)
                if self.pick_pos < 0:
                    self.scroll_pos = 0
                elif self.scroll_pos > self.pick_pos:
                    # light position is below body bottom
                    self.scroll_pos = self.pick_pos
                elif self.scroll_pos < self.pick_pos - (self.scroll_view_size - self.pick_size):
                    # light position is above body top
                    self.scroll_pos = self.pick_pos - (self.scroll_view_size - self.pick_size)
                self.scroll_pos = max(self.scroll_pos, 0)
                self.scroll_pos = min(self.scroll_pos, self.max_scroll_pos)
                indent = 1
            else:
                self.scroll_pos = max(self.scroll_pos, 0)
                self.scroll_pos = min(self.scroll_pos, self.max_scroll_pos)
                self.pick_pos = self.scroll_pos + ind_pos - self.body_base
                # indent = 1 if self.body.row_cnt > self.scroll_view_size else 0
        return indent


    # Assuming this function is part of a class with attributes like self.scr, self.head, self.body, etc.

    def render_once(self, redraw: bool = False):
        """
        Performs the actual rendering of header, horizontal line, and body pads.
        Handles pick highlighting and scroll bar drawing.

        :param redraw: If True, forces a complete redraw of all pads and the screen
                    to clear terminal corruption.
        """

        # --- 1. Preparation and Conditional Redrawwin ---

        if redraw:
            # Mark the main screen and all pads as requiring a full repaint.
            self.scr.redrawwin()
            self.head.pad.redrawwin()
            self.body.pad.redrawwin()

        indent = self.fix_positions()

        # --- 2. Screen Drawing (Highlighting, Scrollbar, Separator) ---

        if indent > 0 and self.pick_mode:
            self.scr.vline(self.body_base, 0, ' ', self.scroll_view_size)
            if self.pick_pos >= 0:
                pos = self.pick_pos - self.scroll_pos + self.body_base
                self.scr.addstr(pos, 0, '>', curses.A_REVERSE)

        if self.head.view_cnt < self.rows:
            self.scr.hline(self.head.view_cnt, 0, curses.ACS_HLINE, self.cols)
            ind_pos = self._scroll_indicator_col()
            if ind_pos >= 0:
                bot, cnt = ind_pos, 1
                if 0 < ind_pos < self.cols-1:
                    width = self.scroll_view_size/self.body.row_cnt*self.cols
                    bot = max(int(round(ind_pos-width/2)), 1)
                    top = min(int(round(ind_pos+width/2)), self.cols-1)
                    cnt = max(top - bot, 1)

                for idx in range(bot, bot+cnt):
                    self.scr.addch(self.head.view_cnt, idx, curses.ACS_HLINE, curses.A_REVERSE)

        # Instead of self.scr.refresh(), use pnoutrefresh/doupdate for efficiency.
        # The 'redrawwin' above handles the forced repaint, so we just call 'noutrefresh'.
        self.scr.noutrefresh()

        # --- 3. Pad Drawing (Body and Head) ---

        if self.body_base < self.rows:
            if self.pick_mode:
                self.highlight_picked()

            self.body.pad.noutrefresh(
                self.scroll_pos, 0,
                self.body_base, indent, self.rows-1, self.cols-1
            )

        if self.rows > 0:
            last_row = min(self.head.view_cnt, self.rows)-1
            if last_row >= 0:
                self.head.pad.noutrefresh(
                    0, 0,
                    0, indent, last_row, self.cols-1
                )

        # --- 4. Final Update (Only one physical screen update) ---
        curses.doupdate()


    def answer(self, prompt='Type string [then Enter]', seed='', width=80, height=5, esc_abort=None):
        """
        Presents a modal dialog box with working horizontal scroll indicators.
        Uses opts.dialog_abort to determine ESC behavior and opts.dialog_return for submit key.

        :param esc_abort: DEPRECATED. Use opts.dialog_abort instead. If provided, overrides opts.dialog_abort.
        """
        # Handle deprecated esc_abort parameter for backward compatibility
        if esc_abort is not None:
            dialog_abort = 'ESC' if esc_abort else None
        else:
            dialog_abort = self.opts.dialog_abort
        def draw_rectangle(scr, r1, c1, r2, c2):
            """Draws a box using standard curses characters."""
            scr.border(0)
            for r in range(r1, r2 + 1):
                if r == r1 or r == r2:
                    # Draw horizontal lines
                    for c in range(c1 + 1, c2):
                        scr.addch(r, c, curses.ACS_HLINE)
                if r > r1 and r < r2:
                    # Draw vertical lines
                    scr.addch(r, c1, curses.ACS_VLINE)
                    scr.addch(r, c2, curses.ACS_VLINE)
            # Draw corners
            scr.addch(r1, c1, curses.ACS_ULCORNER)
            scr.addch(r1, c2, curses.ACS_URCORNER)
            scr.addch(r2, c1, curses.ACS_LLCORNER)
            scr.addch(r2, c2, curses.ACS_LRCORNER)

        input_string = list(seed)
        cursor_pos = len(input_string)
        v_scroll_top = 0
        last_esc_time = None  # For ESC-ESC tracking 

        def calculate_geometry(self):
            # ... (Geometry calculation logic remains the same) ...
            self.rows, self.cols = self.scr.getmaxyx()
            min_cols, min_rows = self.opts.min_cols_rows
            min_height_needed = max(height + 4, min_rows)
            min_cols_needed = max(30, min_cols)
            if self.rows < min_height_needed or self.cols < min_cols_needed:
                return False, None, None, None, None

            max_display_width = self.cols - 6
            text_win_width = min(width, max_display_width)
            row0 = self.rows // 2 - (height // 2 + 1)
            row9 = row0 + height + 1
            col0 = (self.cols - (text_win_width + 2)) // 2

            return True, row0, row9, col0, text_win_width

        success, row0, row9, col0, text_win_width = calculate_geometry(self)
        if not success:
            return seed

        while True:
            try:
                success, row0, row9, col0, text_win_width = calculate_geometry(self)
                
                # --- RESIZE/TOO SMALL CHECK ---
                if not success:
                    min_cols, min_rows = self.opts.min_cols_rows
                    min_height_needed = max(height + 4, min_rows)
                    min_cols_needed = max(30, min_cols)
                    self.scr.clear()
                    msg = f"Min size: {min_cols_needed}x{min_height_needed}"
                    try:
                        self.scr.addstr(0, 0, msg, curses.A_REVERSE)
                    except curses.error:
                        pass  # Terminal too small even for message
                    self.scr.refresh()
                    key = self.scr.getch()
                    if key in [27]: return None
                    if key == curses.KEY_RESIZE: curses.update_lines_cols()
                    continue

                self.scr.clear()
                
                # Draw the box using the imported rectangle function
                draw_rectangle(self.scr, row0, col0, row9, col0 + text_win_width + 1)
                self.scr.addstr(row0, col0 + 1, prompt[:text_win_width])

                # --- Core Display and Scroll Indicator Logic ---

                wrapped_line_idx = cursor_pos // text_win_width
                cursor_offset_on_wrapped_line = cursor_pos % text_win_width

                # Vertical scroll adjustment
                if wrapped_line_idx < v_scroll_top:
                    v_scroll_top = wrapped_line_idx
                elif wrapped_line_idx >= v_scroll_top + height:
                    v_scroll_top = wrapped_line_idx - height + 1

                # Horizontal scroll start calculation
                h_scroll_start = max(0, cursor_offset_on_wrapped_line - text_win_width + 1)

                # Calculate total wrapped lines for overflow detection
                total_wrapped_lines = (len(input_string) + text_win_width - 1) // text_win_width
                if len(input_string) == 0:
                    total_wrapped_lines = 1
                
                # Display the visible lines
                for r in range(height):
                    current_wrapped_line_idx = v_scroll_top + r
                    
                    start_char_idx = current_wrapped_line_idx * text_win_width
                    end_char_idx = start_char_idx + text_win_width
                    
                    if start_char_idx > len(input_string) and r > 0:
                        break

                    raw_wrapped_line = "".join(input_string[start_char_idx:end_char_idx])
                    line_to_display = raw_wrapped_line
                    current_h_scroll_start = 0

                    is_cursor_line = (current_wrapped_line_idx == wrapped_line_idx)
                    
                    if is_cursor_line:
                        line_to_display = raw_wrapped_line[h_scroll_start:]
                        current_h_scroll_start = h_scroll_start
                        
                    # 1. Clear the content area (important for redraw integrity)
                    self.scr.addstr(row0 + 1 + r, col0 + 1, ' ' * text_win_width)
                    # 2. Display the text
                    self.scr.addstr(row0 + 1 + r, col0 + 1, line_to_display[:text_win_width])
                    
                    # --- SCROLL INDICATOR LOGIC ---
                    if is_cursor_line:
                        left_indicator = curses.ACS_VLINE 
                        right_indicator = curses.ACS_VLINE
                        
                        # Left Indicator Check
                        if current_h_scroll_start > 0:
                            # If content is scrolled right, show '<'
                            left_indicator = ord('<') 

                        # Right Indicator Check
                        full_line_len = len(raw_wrapped_line)
                        if full_line_len > current_h_scroll_start + text_win_width:
                            # If there's more content to the right, show '>'
                            right_indicator = ord('>') 
                        
                        # Draw Indicators (overwrite the border's vertical line)
                        self.scr.addch(row0 + 1 + r, col0, left_indicator)
                        self.scr.addch(row0 + 1 + r, col0 + text_win_width + 1, right_indicator)

                        # Highlight the cursor position
                        display_cursor_pos = cursor_pos - start_char_idx - current_h_scroll_start
                        char_at_cursor = line_to_display[display_cursor_pos] if display_cursor_pos < len(line_to_display) else " "

                        self.scr.addstr(row0 + 1 + r, col0 + 1 + display_cursor_pos,
                                        char_at_cursor, curses.A_REVERSE)

                        # Set the actual hardware cursor
                        self.scr.move(row0 + 1 + r, col0 + 1 + display_cursor_pos)

                # --- CORNER OVERFLOW INDICATORS ---
                # Upper left (one line down): show if scrolled down or scrolled right
                has_content_above = v_scroll_top > 0
                has_content_left = h_scroll_start > 0
                if has_content_above or has_content_left:
                    self.scr.addch(row0 + 1, col0, '◀', curses.A_BOLD)

                # Lower right (one line up): show if there's content below or to the right
                has_content_below = (v_scroll_top + height) < total_wrapped_lines
                # Check if cursor line has content beyond the visible window
                cursor_line_start = wrapped_line_idx * text_win_width
                cursor_line_end = cursor_line_start + text_win_width
                cursor_line_full_len = min(len(input_string), cursor_line_end) - cursor_line_start
                has_content_right = cursor_line_full_len > (h_scroll_start + text_win_width)
                if has_content_below or has_content_right:
                    self.scr.addch(row9 - 1, col0 + text_win_width + 1, '▶', curses.A_BOLD)

                # Footer and refresh
                submit_key = self.opts.dialog_return
                abort = ''
                if dialog_abort == 'ESC':
                    abort = ' or ESC to abort'
                elif dialog_abort == 'ESC-ESC':
                    abort = ' or ESC-ESC to abort'
                ending = f'{submit_key} to submit{abort}'
                self.scr.addstr(row9, col0 + 1 + text_win_width - len(ending), ending[:text_win_width])
                self.scr.refresh()
                curses.curs_set(0)  # Hide hardware cursor; reverse video shows position

                key = self.scr.getch()

                # --- Key Handling Logic ---
                # Handle dialog_return (submit)
                if self.opts.dialog_return == 'ENTER' and key in [10, 13]:
                    curses.curs_set(0)
                    return "".join(input_string)
                elif self.opts.dialog_return == 'TAB' and key == 9:
                    curses.curs_set(0)
                    return "".join(input_string)

                # Handle dialog_abort (ESC and ESC-ESC)
                if key == 27:
                    if dialog_abort == 'ESC':
                        return None
                    elif dialog_abort == 'ESC-ESC':
                        current_time = time.time()
                        if last_esc_time is not None and (current_time - last_esc_time) <= 1.0:
                            return None  # Double ESC within timeout
                        last_esc_time = current_time
                        # Single ESC - just update time and continue
                
                elif key == curses.KEY_UP:
                    target_pos = cursor_pos - text_win_width
                    cursor_pos = max(0, target_pos)

                elif key == curses.KEY_DOWN:
                    target_pos = cursor_pos + text_win_width
                    cursor_pos = min(len(input_string), target_pos)
                        
                # ... [KEY_LEFT, KEY_RIGHT, HOME, END, edits, ASCII] ...
                elif key == curses.KEY_LEFT: cursor_pos = max(0, cursor_pos - 1)
                elif key == curses.KEY_RIGHT: cursor_pos = min(len(input_string), cursor_pos + 1)
                elif key == curses.KEY_HOME: cursor_pos = 0
                elif key == curses.KEY_END: cursor_pos = len(input_string)
                elif key in [curses.KEY_BACKSPACE, 127, 8]:
                    if cursor_pos > 0:
                        input_string.pop(cursor_pos - 1)
                        cursor_pos -= 1
                elif key == curses.KEY_DC:
                    if cursor_pos < len(input_string):
                        input_string.pop(cursor_pos)

                # Map special characters to space unless they're the dialog_return key
                elif key in [9, 10, 13]:
                    # Check if this is the dialog_return key
                    is_return_key = False
                    if self.opts.dialog_return == 'TAB' and key == 9:
                        is_return_key = True
                    elif self.opts.dialog_return == 'ENTER' and key in [10, 13]:
                        is_return_key = True

                    if not is_return_key:
                        # Convert to space
                        input_string.insert(cursor_pos, ' ')
                        cursor_pos += 1

                elif 32 <= key <= 126:
                    input_string.insert(cursor_pos, chr(key))
                    cursor_pos += 1
                
                # --- Explicit Resize Handler ---
                elif key == curses.KEY_RESIZE:
                    curses.update_lines_cols()
                    continue
                    
            except curses.error:
                # Catch exceptions from drawing outside bounds during resize
                self.scr.clear()
                curses.update_lines_cols()
                self.rows, self.cols = self.scr.getmaxyx()
                # Drain any pending resize events to prevent infinite loop
                self.scr.nodelay(True)  # Make getch() non-blocking
                while True:
                    key = self.scr.getch()
                    if key == -1:  # No more keys in queue
                        break
                self.scr.nodelay(False)  # Restore blocking mode
                continue


    def flash(self, message='', duration=2.0):
        """
        Displays a brief flash message in the center of the screen.
        Auto-dismisses after duration seconds without requiring user input.

        :param message: The message to display
        :param duration: How long to show the message in seconds (default 0.5)
        """

        if self.rows < 3 or self.cols < len(message) + 4:
            return

        # Calculate centered position
        msg_len = min(len(message), self.cols - 4)
        row = self.rows // 2
        col = (self.cols - msg_len - 2) // 2

        # Draw a simple box with the message
        self.scr.clear()
        try:
            # Top border
            self.scr.addstr(row - 1, col, '┌' + '─' * msg_len + '┐', curses.A_BOLD | curses.A_REVERSE)
            # Message
            self.scr.addstr(row, col, '│' + message[:msg_len] + '│', curses.A_BOLD | curses.A_REVERSE)
            # Bottom border
            self.scr.addstr(row + 1, col, '└' + '─' * msg_len + '┘', curses.A_BOLD | curses.A_REVERSE)
        except curses.error:
            pass  # Ignore if terminal too small

        self.scr.refresh()
        time.sleep(duration)


    def alert(self, title='ALERT', message='', height=1, width=80):
        """
        Displays a blocking, modal alert box with a title and message.

        Waits for the user to press **ENTER** to acknowledge and dismiss the box.

        :param title: The title text for the alert box.
        :param message: The message body content.
        :param height: The height of the message area (number of lines).
        :param width: The visible width of the message area.
        :type title: str
        :type message: str
        :type height: int
        :type width: int
        """
        def mod_key(key):
            """Internal function to map Enter/Key_Enter to an arbitrary key code 7 for Textbox.edit to exit."""
            return  7 if key in (10, curses.KEY_ENTER) else key

        if self.rows < 2+height or self.cols < 30:
            return
        width = min(width, self.cols-3) # max text width
        row0 = (self.rows+height-1)//2 - 1
        row9 = row0 + height + 1
        col0 = (self.cols - (width+2)) // 2
        col9 = col0 + width + 2 - 1

        self.scr.clear()
        for row in range(self.rows):
            self.scr.insstr(row, 0, ' '*self.cols, curses.A_REVERSE)
        pad = curses.newpad(20, 200)
        win = curses.newwin(1, 1, row9-1, col9-2) # input window (dummy for Textbox)
        rectangle(self.scr, row0, col0, row9, col9)
        self.scr.addstr(row0, col0+1, title[0:width], curses.A_REVERSE)
        pad.addstr(message)
        ending = 'Press ENTER to ack'[:width]
        self.scr.addstr(row9, col0+1+width-len(ending), ending)
        self.scr.refresh()
        pad.refresh(0, 0, row0+1, col0+1, row9-1, col9-1)

        # Use a dummy Textbox with a dummy window to block until Enter is pressed
        curses.curs_set(0) # ensure cursor is off
        Textbox(win).edit(mod_key).strip()
        return

    def clear(self):
        """
        Clears all content from both the header and body pads and resets internal
        counters in preparation for adding new screen content.
        """
        self.scr.clear()
        self.head.pad.clear()
        self.body.pad.clear()
        self.head.texts, self.body.texts, self.last_pick_pos = [], [], -1
        self.head.row_cnt = self.body.row_cnt = 0

    def prompt(self, seconds=1.0):
        """
        Waits for user input for up to ``seconds``.

        Handles terminal resize events and built-in navigation keys, updating
        scroll/pick position as needed.

        :param seconds: The maximum time (float) to wait for input.
        :type seconds: float
        :returns: The key code if it is one of the application-defined ``keys``,
                  or None on timeout or if a navigation key was pressed.
        :rtype: int or None
        """
        global ctrl_c_flag
        ctl_b, ctl_d, ctl_f, ctl_u = 2, 4, 6, 21
        begin_mono = time.monotonic()
        while True:
            if time.monotonic() - begin_mono >= seconds:
                break
            while self.pending_keys:
                key = self.pending_keys.pop()
                if key in self.handled_keys:
                    return key

            key = self.scr.getch()
            if ctrl_c_flag:
                if key in self.handled_keys:
                    self.pending_keys.add(key)
                ctrl_c_flag = False # Reset flag
                if 0x3 in self.handled_keys:
                    return 0x3 # Return the ETX key code
                continue

            if key == curses.ERR:
                continue


            if key in (curses.KEY_RESIZE, ) or curses.is_term_resized(self.rows, self.cols):
                self._set_screen_dims()
                if not self._check_min_size():
                    # User pressed ESC to abort during size check
                    if 27 in self.handled_keys:
                        return 27
                break

            # App keys...
            if key in self.handled_keys:
                return key # return for handling

            # Navigation Keys...
            pos = self.pick_pos if self.pick_mode else self.scroll_pos
            delta = self.pick_size if self.pick_mode else 1
            was_pos = pos
            if key in (ord('k'), curses.KEY_UP):
                pos -= delta
            elif key in (ord('j'), curses.KEY_DOWN):
                pos += delta
            elif key in (ctl_b, curses.KEY_PPAGE):
                pos -= self.scroll_view_size
            elif key in (ctl_u, ):
                pos -= self.scroll_view_size//2
            elif key in (ctl_f, curses.KEY_NPAGE):
                pos += self.scroll_view_size
            elif key in (ctl_d, ):
                pos += self.scroll_view_size//2
            elif key in (ord('0'), curses.KEY_HOME):
                pos = 0
            elif key in (ord('$'), curses.KEY_END):
                pos = self.body.row_cnt - 1
            elif key in (ord('H'), ):
                pos = self.scroll_pos
            elif key in (ord('M'), ):
                pos = self.scroll_pos + self.scroll_view_size//2
            elif key in (ord('L'), ):
                pos = self.scroll_pos + self.scroll_view_size-1

            if self.pick_mode:
                self.pick_pos = pos
            else:
                self.scroll_pos = pos
                self.pick_pos = pos

            self.fix_positions()

            if pos != was_pos:
                self.render()
                if self.opts.return_if_pos_change:
                    return None
        return None

def no_runner():
    """Appease sbrun"""

if __name__ == '__main__':
    def main():
        """Test program"""
        def do_key(key):
            nonlocal spin, win, opts, pick_values
            value = spin.do_key(key, win)
            if key in (ord('p'), ord('s')):
                win.set_pick_mode(on=opts.pick_mode, pick_size=opts.pick_size)
                if not opts.pick_mode:
                    opts.prev_pick = pick_values[win.pick_pos//win.pick_size]
            elif key == ord('n'):
                win.alert(title='Info', message=f'got: {value}')
            elif opts.quit:
                opts.quit = False
                sys.exit(key)
            return value

        spin = OptionSpinner()
        spin.add_key('help_mode', '? - toggle help screen', vals=[False, True])
        spin.add_key('pick_mode', 'p - toggle pick mode, turn off to pick current line', vals=[False, True])
        spin.add_key('pick_size', 's - #rows in pick', vals=[1, 2, 3])
        spin.add_key('name', 'n - select name', prompt='Provide Your Name:')
        spin.add_key('mult', 'm - row multiplier', vals=[0.5, 0.9, 1.0, 1.1, 2, 4, 16])
        spin.add_key('quit', 'q,CTL-C - quit the app', category='action', keys={0x3, ord('q')})
        opts = spin.default_obj

        win = ConsoleWindow(head_line=True, keys=spin.keys,
                            ctrl_c_terminates=False, body_rows=4000)
        opts.name = ""
        opts.prev_pick = 'n/a'
        pick_values = []
        for loop in range(100000000000):
            body_size = int(round(win.scroll_view_size*opts.mult))
            # body_size = 4000 # temp to test scroll pos indicator when big
            if opts.help_mode:
                win.set_pick_mode(False)
                spin.show_help_nav_keys(win)
                spin.show_help_body(win)
            else:
                win.set_pick_mode(opts.pick_mode, opts.pick_size)
                win.add_header(f'{time.monotonic():.3f} [p]ick={opts.pick_mode}'
                            + f' s:#rowsInPick={opts.pick_size} [n]ame [m]ult={opts.pick_size} ?=help [q]uit')
                win.add_header(f'Header: {loop} name="{opts.name}"  {opts.prev_pick=}')
                pick_values = []
                for idx, line in enumerate(range(body_size//opts.pick_size)):
                    value = f'{loop}.{line}'
                    win.put_body(f'Main pick: {value}')
                    pick_values.append(value)
                    for num in range(1, opts.pick_size):
                        win.draw(num+idx*opts.pick_size, 0, f'  addon: {loop}.{line}')
            win.render(redraw=bool(loop%2))
            _ = do_key(win.prompt(seconds=5))
            win.clear()

    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as exce:
        ConsoleWindow.stop_curses()
        print("exception:", str(exce))
        print(traceback.format_exc())
        if dump_str:
            print(dump_str)
