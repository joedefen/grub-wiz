#!/usr/bin/env python3
"""
TODO:
 - [w]rite command (start of at least)
 - launch/discover grub-update or whatever
 - writing YAML into .config directory and read it first (allow user extension)
 
 Backburner:
- Recovery mechanism - Consider documenting how users can restore from backup
  if something goes wrong (especially from a rescue environment).
- Distribution compatibility - Different distros use update-grub vs grub-mkconfig.
  Worth mentioning your compatibility scope.
- The "Boot Entry Management" TODO - This is actually quite complex since it
  involves parsing grub.cfg rather than just modifying /etc/default/grub.
  Consider whether this fits the "simple and safe" philosophy.
- Implement any of these:
    - get_menu_entries requires parsing /boot/grub/grub.cfg which can be tricky
    - get-res-list would need to query display capabilities (maybe via hwinfo, xrandr, or reading VESA modes)
"""
# pylint: disable=invalid_name,broad-exception-caught

import sys
import os
import time
import textwrap
import traceback
import re
from types import SimpleNamespace
from .ConsoleWindowCopy import OptionSpinner, ConsoleWindow
from .CannedConfig import CannedConfig
from .GrubParser import GrubParser
from .GrubCfgParser import get_top_level_grub_entries
from .BackupMgr import BackupMgr, GRUB_DEFAULT_PATH

class GrubPal:
    """ TBD """
    singleton = None
    def __init__(self):
        GrubPal.singleton = self
        self.win = None # place 1st
        self.guide = 'Full' # None Brief Full
        self.spinner = None
        self.spins = None
        self.sections = None
        self.params = {}
        self.positions = []
        self.mode = 'usual'  # 'restore
        self.prev_pos = None
        self.param_names = None
        self.param_values = {}
        self.parsed = None
        self.param_name_wid = 0
        self.menu_entries = None
        self.backup_mgr = BackupMgr()
        self.backups = None
        self._reinit()
        
    def _reinit(self):
        """ Call to initialize or re-initialize with new /etc/default/grub """
        self.sections = CannedConfig().data
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

        self.parsed = GrubParser(params=self.param_names)
        self.parsed.get_etc_default_grub()
        self.prev_pos = -1024  # to detect direction

        name_wid = 0
        for param_name in self.param_names:
            name_wid = max(name_wid, len(param_name))
            value = self.parsed.vals.get(param_name, None)
            if value is None:
                value = self.params[param_name]['default']
            self.param_values[param_name] = value
        self.param_name_wid = name_wid - len('GRUB_')

        self.menu_entries = get_top_level_grub_entries()
        try:
            self.params['GRUB_DEFAULT']['enums'].update(self.menu_entries)
        except Exception:
            pass
        self.mode = 'usual'  # 'restore
    
    def setup_win(self):
        """TBD """
        spinner = self.spinner = OptionSpinner()
        self.spins = self.spinner.default_obj
        spinner.add_key('help_mode', '? - toggle help screen', vals=[False, True])
        spinner.add_key('cycle', 'c - next value in cycle', category='action')
        spinner.add_key('edit', 'e - edit value', category='action')
        spinner.add_key('guide', 'g - guidance toggle', vals=[True, False])
        spinner.add_key('enter_restore', 'R - enter restore screen', category='action')
        spinner.add_key('restore', 'r - restore selected backup [in restore screen]', category='action')
        spinner.add_key('delete', 'd - delete selected backup [in restore screen]', category='action')
        spinner.add_key('write', 'w - write out current contents and run "grub-update"', category='action')
        spinner.add_key('quit', 'q,ctl-c - quit the app', category='action', keys={0x3, ord('q')})

        self.win = ConsoleWindow(head_line=True, keys=spinner.keys, ctrl_c_terminates=False)
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

    def add_restore_head(self):
        """ TBD """
        header = '[d]elete [r]estore ?:help [q]uit'
        self.win.add_header(header)

    def add_restore_body(self):
        """ TBD """
        paths = list(self.backups.values())
        paths.sort(reverse=True)
        for path in paths:
            self.win.add_body(path.name)
        
    def add_guided_head(self):
        """ TBD"""
        header = ''
        _, _, enums, checks = self._get_enums_checks()
        if enums:
            header += ' [c]ycle'
        if checks:
            header += ' [e]dit'

        guide = 'UIDE' if self.spins.guide else 'uide'
        header += f' [g]{guide} [R]estore ?:help [q]uit'
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
                    wrapped += ': Cycle values with [c]:\n'
                    payload = self.params[param_name]
                    for enum, descr in payload['enums'].items():
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

    def edit_param(self, win, name, checks):
        """ Prompt user for answer until gets it right"""
        value = self.param_values[name]
        valid = False
        hint, pure_regex = '', ''
        for key, check in checks.items():
            if key == 'regex':
                pure_regex = check.encode().decode('unicode_escape')
                hint += f'  pat={pure_regex}'
            else:
                hint += f'  {key}={check}'
        hint = hint[2:]

        while not valid:
            prompt = f'Edit {name} [{hint}]'
            value = win.answer(prompt=prompt, seed=str(value), esc_abort=True)
            if value is None: # aborted
                return
            valid = True # until proven otherwise
            for key, check in checks.items():
                if key == 'regex':
                    if not re.match(check, str(value)):
                        valid, hint = False, f'must match: {pure_regex}'
                        break
                elif key in ['min', 'max']:
                    ival = value
                    if isinstance(check, int):
                        try:
                            ival = int(value)
                        except Exception:
                            valid, hint = False, 'must be int'
                            break
                    else:
                        assert isinstance(check, str), f'Check {key} must be int or str'
                    if key == 'min' and ival < check:
                        valid, hint = False, f'must be >= {check}'
                        break
                    if key == 'max' and ival > check:
                        valid, hint = False, f'must be <= {check}'
                        break
                else:
                    assert False, f'Unknown check key: {key}'

        self.param_values[name] = value
        

    def do_start_up_backup(self):
        """ On startup
            - install the "orig" backup of none
            - offer to install any uniq backup
        """
        self.backups = self.backup_mgr.get_backups()
        checksum = self.backup_mgr.calc_checksum(GRUB_DEFAULT_PATH)
        if not self.backups:
            self.backup_mgr.create_backup('orig')

        elif checksum not in self.backups:
            regex = r'^[_A-Za-z0-9]+$'
            hint = 'regex={regex}'
            while True:
                answer = self.win.answer(esc_abort=True, seed='custom',
                    prompt=fr"Enter a tag to back up {GRUB_DEFAULT_PATH} [{hint}]]")
                if answer is None:
                    break
                answer = answer.strip()
                if re.match(regex, answer):
                    self.backup_mgr.create_backup(GRUB_DEFAULT_PATH)
                    break

    def main_loop(self):
        """ TBD """
        assert self.parsed.get_etc_default_grub()
        seconds = 3.0
        
        self.do_start_up_backup()
        self.setup_win()
        win, spins = self.win, self.spins # shorthand
        
        while True:
            if spins.help_mode:
                win.set_pick_mode(False)
                self.spinner.show_help_nav_keys(win)
                self.spinner.show_help_body(win)
            elif self.mode == 'restore':
                win.set_pick_mode(True)
                self.add_restore_head()
                self.add_restore_body()

            else: # normal mode
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
                    if self.mode == 'restore':
                        self.mode = 'normal'
                    else:
                        break

                name, _, enums, checks = self._get_enums_checks()
                if spins.cycle:
                    spins.cycle = False
                    if enums:
                        value = self.param_values[name]
                        choices = list(enums.keys())
                        idx = choices.index(value) if value in choices else -1
                        value = choices[(idx+1) % len(choices)] # choose next
                        self.param_values[name] = value
                if spins.edit:
                    spins.edit = False
                    if checks:
                        self.edit_param(win, name, checks)

                if spins.enter_restore:
                    spins.enter_restore = False
                    if self.mode != 'restore':
                        self.mode = 'restore'
                        self.backups = self.backup_mgr.get_backups()

                if spins.restore:
                    spins.restore = False
                    # TODO

                if spins.delete:
                    spins.delete = False
                    # TODO


            win.clear()

def rerun_module_as_root(module_name):
    """ rerun using the module name """
    if os.geteuid() != 0: # Re-run the script with sudo
        os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        vp = ['sudo', sys.executable, '-m', module_name] + sys.argv[1:]
        os.execvp('sudo', vp)


def main():
    """ TBD """
    rerun_module_as_root('grub_pal.main')
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

