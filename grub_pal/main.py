#!/usr/bin/env python3
"""
TODO:
 - handle wrapping values that are long
 - screen concept; (new func)  if self.act_on('variable', screens)
 - (ok) track changes to parameters (old and new values)
   - don't write immediately, but go to review screen
   - allow undoing changes
   - go back to main screen ESC (make ESC "go back")
   - commit from this screen
        Main Screen
          ↓ [w]rite
        Issues Screen (if issues exist)
          - List warnings/errors
          - Offer auto-fix for some
          ↓ [w]rite or ESC→back
        Review Screen
          - Show old→new for all changes
          - Allow undo per-param
          ↓ [w]rite or ESC→back
        Commit
          - Write /etc/default/grub
          - Run grub-update
          ↓
        Back to Main
        Notes:
            Skip issues screen if clean
            Skip review if no changes
            Each screen has clear "what will happen next" indicator
            ESC always = back/cancel safely
        Clean, intuitive, hard to accidentally break system.
 - ALTERNATIVE:
    - Managed Section,"Only show parameters that have changed.
      This keeps the screen clean. If a parameter's value is the same as
      the original file's value, it disappears from this review."
    - New Value Line,GRUB_TIMEOUT: 5 (The currently staged value).
       This line is the focus point for navigation and editing.
    - Old Value Line,was: 10 (Aligned below the new value).
      This provides the essential context for the change.
    - Issues Line,*** Issue: Value must be > 0 (The *** severity
      indicator works well in a TUI). This line only appears if validation fails.
    - [u] Undo Action,"If the cursor is on the GRUB_TIMEOUT line, pressing
      [u]undo immediately resets the new value back to the old value
      (10 in the example). If successful, the parameter disappears from the review screen."
    - Navigation Back,[b]ack to editor (Allows the user to return to the main
      configuration screen if they need to change something else).
    - Commit Action,[w]rite changes (The final commit action).
      This should trigger the warning screen if issues still exist.
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
from .GrubWriter import GrubWriter

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
        self.param_dicts = None
        self.positions = None
        self.mode = None
        self.prev_pos = None
        self.param_names = None
        self.param_values = None
        self.prev_values = None
        self.parsed = None
        self.param_name_wid = 0
        self.menu_entries = None
        self.backup_mgr = BackupMgr()
        self.grub_writer = GrubWriter()
        self.backups = None
        self.ordered_backup_pairs = None
        self._reinit()
        
    def _reinit(self):
        """ Call to initialize or re-initialize with new /etc/default/grub """
        self.param_dicts = {}
        self.positions = []
        self.mode = 'usual'  # 'restore
        self.param_values, self.prev_values = {}, {}
        self.sections = CannedConfig().data
        for idx, (section, params) in enumerate(self.sections.items()):
            if idx > 0: # blank line before sections except 1st
                self.positions.append( SimpleNamespace(
                    param_name=None, section_name=' '))
            self.positions.append( SimpleNamespace(
                param_name=None, section_name=section))
            for param_name, payload in params.items():
                self.param_dicts[param_name] = payload
                self.positions.append(SimpleNamespace(
                    param_name=param_name, section_name=None))
        self.param_names = list(self.param_dicts.keys())

        self.parsed = GrubParser(params=self.param_names)
        self.parsed.get_etc_default_grub()
        self.prev_pos = -1024  # to detect direction

        name_wid = 0
        for param_name in self.param_names:
            name_wid = max(name_wid, len(param_name))
            value = self.parsed.vals.get(param_name, None)
            if value is None:
                value = self.param_dicts[param_name]['default']
            self.param_values[param_name] = value
        self.param_name_wid = name_wid - len('GRUB_')
        self.prev_values.update(self.param_values)

        self.menu_entries = get_top_level_grub_entries()
        try:
            self.param_dicts['GRUB_DEFAULT']['enums'].update(self.menu_entries)
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
        spinner.add_key('escape', 'ESC - back to prev screen',
                        category="action", keys=[27,])
        spinner.add_key('quit', 'q,ctl-c - quit the app', category='action', keys={0x3, ord('q')})

        self.win = ConsoleWindow(head_line=True, keys=spinner.keys, ctrl_c_terminates=False)
        self.win.opt_return_if_pos_change = True
        
    def _get_enums_checks(self):
        """ TBD"""
        enums, checks = None, None
        pos = self.adjust_picked_pos()
        param_name = self.positions[pos].param_name
        params = self.param_dicts[param_name]
        enums = params.get('enums', None)
        checks = params.get('checks', None)
        return param_name, params, enums, checks

    def add_restore_head(self):
        """ TBD """
        header = '[d]elete [r]estore ?:help [q]uit'
        self.win.add_header(header)

    def add_restore_body(self):
        """ TBD """
        for pair in self.ordered_backup_pairs:
            self.win.add_body(pair[1].name)
        
    def get_diffs(self):
        """ get the key/value pairs with differences"""
        diffs = {}
        for key, value in self.prev_values.items():
            new_value = self.param_values[key]
            if str(value) != str(new_value):
                diffs[key] = (value, new_value)
        return diffs

    def add_guided_head(self):
        """ TBD"""
        header = ''
        _, _, enums, checks = self._get_enums_checks()
        if enums:
            header += ' [c]ycle'
        if checks:
            header += ' [e]dit'

        guide = 'UIDE' if self.spins.guide else 'uide'
        header += f' [g]{guide} [w]rite [R]estore ?:help [q]uit'
        chg_cnt = len(self.get_diffs())
        if chg_cnt:
            header += f'   #chg={chg_cnt}'
        self.win.add_header(header)

    def adjust_picked_pos(self):
        """ This assumes:
          - section names are singular or blank + section
          - the 1st entry is a section name
          - the last entry is NOT a section name
        """
        win, spins = self.win, self.spins # shorthand
        pos = win.pick_pos

        if self.mode != 'usual' or spins.help_mode:
            return pos

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
            text = self.param_dicts[param_name]['guidance']
            lines = text.split('\n')
            lead = '    '
            wid = win.cols - len(lead)
            for line in lines:
                wrapped = ''
                if line.strip() == '%ENUMS%':
                    wrapped += ': Cycle values with [c]:\n'
                    payload = self.param_dicts[param_name]
                    for enum, descr in payload['enums'].items():
                        star = '* ' if str(enum) == str(value) else '- '
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
        

    def refresh_backup_list(self):
        """ TBD """
        self.backups = self.backup_mgr.get_backups()
        self.ordered_backup_pairs = sorted(self.backups.items(),
                           key=lambda item: item[1], reverse=True)
    def do_start_up_backup(self):
        """ On startup
            - install the "orig" backup of none
            - offer to install any uniq backup
        """
        self.refresh_backup_list()
        checksum = self.backup_mgr.calc_checksum(GRUB_DEFAULT_PATH)
        if not self.backups:
            self.backup_mgr.create_backup('orig')

        elif checksum not in self.backups:
            regex = r'^[-_A-Za-z0-9]+$'
            hint = f'regex={regex}'
            while True:
                answer = self.win.answer(esc_abort=True, seed='custom',
                    prompt=f"Enter a tag to back up {GRUB_DEFAULT_PATH} [{hint}]]")
                if answer is None:
                    break
                answer = answer.strip()
                if re.match(regex, answer):
                    self.backup_mgr.create_backup(answer)
                    break

    def really_wanna(self, act):
        """ TBD """
        answer = self.win.answer(esc_abort=True, seed='y',
            prompt=f"Enter 'yes' to {act}")
        if answer is None:
            return False
        answer = answer.strip().lower()
        return answer.startswith('y')

    def update_grub(self):
        """ TBD """
        if not self.really_wanna('commit changes and update GRUB'):
            return

        contents =  "#--# NOTE: this file was built with 'grub-pal'\n"
        contents += "#--#     - We suggest updating the following params with 'grub-pal'\n"
        contents += "#--#       although not required'\n"
        for name, value in self.param_values.items():
            contents += f'{name}={value}\n'
        contents += "#--# NOTE: following are params NOT handled by 'grub-pal'\n"
        contents += "#--#     - update these manually.\n"
        contents += ''.join(self.parsed.other_lines)
        
        self.win.stop_curses()
        print("\033[2J\033[H") # 'clear'
        print('\n\n===== Left grub-pal to update GRUB ====> ')
        # print('Check for correctness...')
        # print('-'*60)
        # print(contents)
        # print('-'*60)
        commit_rv = self.grub_writer.commit_validated_grub_config(contents)
        if not commit_rv[0]: # failure
            print(commit_rv[1])
        else:
            install_rv = self.grub_writer.run_grub_update()
            if install_rv[0]:
                print(install_rv[1])
        input('\n\n===== Press ENTER to return to grub-pal ====> ')

        self.win._start_curses()
        self._reinit()
        self.do_start_up_backup()

    def main_loop(self):
        """ TBD """
        assert self.parsed.get_etc_default_grub()
        seconds = 3.0
        
        self.setup_win()
        self.do_start_up_backup()
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

            else: # usual mode
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
                        self.mode = 'usual'
                    else:
                        break

                name, _, enums, checks = '', None, [], []
                if self.mode == 'usual' and not spins.help_mode:
                    name, _, enums, checks = self._get_enums_checks()
                if spins.cycle:
                    spins.cycle = False
                    if self.mode == 'usual' and enums:
                        value = self.param_values[name]
                        choices = list(enums.keys())
                        idx = choices.index(value) if value in choices else -1
                        value = choices[(idx+1) % len(choices)] # choose next
                        self.param_values[name] = value
                if spins.edit:
                    spins.edit = False
                    if self.mode == 'usual' and checks:
                        self.edit_param(win, name, checks)
                        
                if spins.write:
                    spins.write = False
                    if self.mode == 'usual':
                        self.update_grub()

                if spins.enter_restore:
                    spins.enter_restore = False
                    if self.mode != 'restore':
                        self.mode = 'restore'
                        self.do_start_up_backup()

                if spins.restore:
                    spins.restore = False
                    if self.mode == 'restore':
                        idx = self.win.pick_pos
                        if 0 <= idx < len(self.ordered_backup_pairs):
                            key = self.ordered_backup_pairs[idx][0]
                            self.backup_mgr.restore_backup(self.backups[key])
                            self.mode = 'usual'
                            self._reinit()
                            self.do_start_up_backup()

                if spins.delete:
                    spins.delete = False
                    if self.mode == 'restore':
                        idx = self.win.pick_pos
                        if 0 <= idx < len(self.ordered_backup_pairs):
                            doomed = self.ordered_backup_pairs[idx][1]
                            if self.really_wanna(f'remove {doomed.name!r}'):
                                os.unlink(doomed)
                                self.refresh_backup_list()



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

