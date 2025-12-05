#!/usr/bin/env python3
"""
TODO:
 - insert section headers
 - align values
 - drop "GRUB_" prefix from param names
 - prompt if pattern
 - [w]rite command (start of)
"""
# pylint: disable=invalid_name,broad-exception-caught

import time
import textwrap
import traceback
import sys
from types import SimpleNamespace
from .ConsoleWindowCopy import OptionSpinner, ConsoleWindow
from .CannedConfig import CannedConfig
from .GrubParser import GrubParser

class GrubPal:
    """ TBD """
    singleton = None
    def __init__(self):
        GrubPal.singleton = self
        self.win = None # place 1st
        self.guide = 'Full' # None Brief Full
        self.spinner = None
        self.spins = None
        self.sections = CannedConfig().data
        self.params = {}
        self.positions = []
        self.prev_pos = -1024  # to detect direction
        for idx, (section, params) in enumerate(self.sections.items()):
            if idx > 0: # blank line before sections except 1st
                self.positions.append( SimpleNamespace(
                    param_name=None, section_name=' '))
            self.positions.append( SimpleNamespace(
                param_name=None, section_name=section))
            for param_name, payload in params.items():
                self.params[param_name] = payload
                self.positions.append(SimpleNamespace(
                    param_name=param_name, section_name=None))
        self.param_names = list(self.params.keys())
        self.param_values = {}
        self.parsed = GrubParser(params=self.param_names)
        name_wid = 0
        for param_name in self.param_names:
            name_wid = max(name_wid, len(param_name))
            value = self.parsed.vals.get(param_name, None)
            if value is None:
                value = self.params[param_name]['default']
            self.param_values[param_name] = value
        self.param_name_wid = name_wid - len('GRUB_')
    
    def setup_win(self):
        """TBD """
        spinner = self.spinner = OptionSpinner()
        self.spins = self.spinner.default_obj
        spinner.add_key('help_mode', '? - toggle help screen', vals=[False, True])
        spinner.add_key('next', 'n - next value in cycle', category='action')
        spinner.add_key('edit', 'e - edit value', category='action')
        spinner.add_key('guide', 'g - guidance toggle', vals=[True, False])
        spinner.add_key('quit', 'q,Q - quit the app', category='action', keys={ord('Q'), ord('q')})

        self.win = ConsoleWindow(head_line=True, keys=spinner.keys)
        self.win.opt_return_if_pos_change = True
        
    def _get_enums_checks(self):
        """ TBD"""
        enums, checks = None, None
        pos = self.adjust_picked_pos()
        param_name = self.positions[pos].param_name
        params = self.params[param_name]
        enums = params.get('enums', None)
        checks = params.get('checks', None)
        return param_name, params, enums, checks
        
    def add_guided_head(self):
        """ TBD"""
        header = ''
        _, _, enums, checks = self._get_enums_checks()
        if enums:
            header += ' [n]ext'
        if checks:
            header += ' [e]dit'

        guide = 'UIDE' if self.spins.guide else 'uide'
        header += f' [g]{guide} [q]uit'
        self.win.add_header(header)

    def adjust_picked_pos(self):
        """ This assumes:
          - section names are singular or blank + section
          - the 1st entry is a section name
          - the last entry is NOT a section name
        """
        win = self.win
        pos = win.pick_pos
        pos = max(min(len(self.positions)-1, pos), 1)
        if pos == win.pick_pos and pos == self.prev_pos:
            return pos
        up = bool(pos >= self.prev_pos)
        ns = self.positions[pos]
        while ns.section_name:
            if up:
                pos += 1
            else:
                pos -= 1
            ns = self.positions[pos]
        assert ns.param_name
        win.pick_pos = pos
        self.prev_pos = pos
        return pos


    def add_guided_body(self):
        """ TBD """
        win = self.win # short hand
        picked = self.adjust_picked_pos()
        emits = []
        view_size = win.scroll_view_size
        for pos, ns in enumerate(self.positions):
            if ns.section_name == ' ':
                win.add_body(f'{ns.section_name}')
                continue
            if ns.section_name:
                win.add_body(f'[{ns.section_name}]')
                continue

            param_name = ns.param_name
            value = self.param_values[param_name]
            dots = '.' * (self.param_name_wid-len(param_name)+8)
            param_line = f'  {param_name[5:]} {dots}  {value}'
            if not self.spins.guide or pos != picked:
                win.add_body(param_line)
                continue
            emits.append(param_line)
            text = self.params[param_name]['guidance']
            lines = text.split('\n')
            lead = '    '
            wid = win.cols - len(lead)
            for line in lines:
                wrapped = ''
                if line.strip() == '%ENUMS%':
                    value = self.param_values[param_name]
                    for enum, descr in self.params[param_name]['enums'].items():
                        star = '* ' if enum == value else '- '
                        line = f' {star}{enum}: {descr}\n'
                        wrapped += textwrap.fill(line, width=wid, subsequent_indent=' '*5)
                        wrapped += '\n'
                else:
                    wrapped += textwrap.fill(line, width=wid, subsequent_indent=' '*5)
                wraps = wrapped.split('\n')
                for wrap in wraps:
                    if wrap:
                        emits.append(f'{lead}{wrap}')
            # truncate the lines to show to all that fit..
            if len(emits) > view_size:
                hide_cnt = 1 + len(emits) - view_size
                emits = emits[0:view_size-1]
                emits.append(f'{lead}... beware: {hide_cnt} HIDDEN lines ...')
            for emit in emits:
                win.add_body(emit)
        # now ensure the whole block is viewable
        over = picked - win.scroll_pos + len(emits) - view_size
        if over > 0:
            win.scroll_pos += over # scroll back by number of out-of-view lines

    def main_loop(self):
        """ TBD """
        assert self.parsed.get_etc_default_grub()
        self.setup_win()
        win, spins = self.win, self.spins # shorthand
        seconds = 3.0
        
        while True:
            if spins.help_mode:
                win.set_pick_mode(False)
                self.spinner.show_help_nav_keys(win)
                self.spinner.show_help_body(win)
            else:
                win.set_pick_mode(True)
                self.add_guided_head()
                self.add_guided_body()
            win.render()
            key = win.prompt(seconds=seconds)
            seconds = 3.0
            if key is not None:
                self.spinner.do_key(key, win)
                if spins.quit:
                    spins.quit = False
                    break

                name, _, enums, checks = self._get_enums_checks()
                if spins.next:
                    spins.next = False
                    if enums:
                        value = self.param_values[name]
                        choices = list(enums.keys())
                        idx = choices.index(value) if value in choices else -1
                        value = choices[(idx+1) % len(choices)] # choose next
                        self.param_values[name] = value
                if spins.edit:
                    spins.edit = False
                    if checks:
                        value = self.param_values[name]
                        prompt = f'Edit {name}: {checks}'
                        value = win.answer(prompt=prompt, seed=str(value))
                        # TODO: validate answer and loop if needed
                        self.param_values[name] = value


            win.clear()


def main():
    """ TBD """
    pal = GrubPal()
    print(f'{len(pal.params)=}')
    print(f'{type(pal.params['GRUB_TIMEOUT'])=}')
    time.sleep(0.5)
    pal.main_loop()

if __name__ == '__main__':
    try:
        main()
    except Exception as exce:
        if GrubPal.singleton and GrubPal.singleton.win:
            GrubPal.singleton.win.stop_curses()
        print("exception:", str(exce))
        print(traceback.format_exc())
        sys.exit(15)

