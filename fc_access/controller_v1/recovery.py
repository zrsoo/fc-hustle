"""Deterministic official-document recovery. Desktop UI only; never an EA request.

The supervisor runs this between two owned workers after the stale-document
bid-denial signature. It reloads the official Web App tab and walks the normal
sign-in screens with a fixed, bounded policy: one allowlisted control per
observed screen, a step/click budget and an absolute deadline. A security
challenge, unknown page or exhausted budget ends recovery; it is never bypassed.
No credential, cookie, token, field value or session identifier is read.
"""
from collections import Counter
import json
import os
from pathlib import Path
import subprocess
import time

SCRIPT = Path(__file__).with_name('recovery.ps1')
LOGIN = ('Login', 'Log In')
CONTINUE = ('Continue', "Let's Play", 'Start')
# Finite reasons the script may emit; anything else is reported generically.
UI_REASONS = ('user_security_challenge_required', 'foreground_changed', 'intended_tab_ambiguous',
              'official_EA_page_required', 'action_not_allowlisted', 'normal_action_ambiguous_or_missing',
              'official_EA_signin_required', 'account_label_invalid', 'email_control_unavailable',
              'unique_saved_account_suggestion_required', 'exactly_one_Edge_window_required',
              'Edge_foreground_control_failed', 'Edge_input_detach_failed', 'verified_window_handle_required')


class UIStepFailed(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def powershell(action, *, window=0, name='', account='', timeout=45):
    argv = ['powershell', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
            '-File', str(SCRIPT), '-Action', action]
    if window: argv += ['-WindowHandle', str(int(window))]
    if name: argv += ['-Name', name]
    if account: argv += ['-Account', account]
    # The owned service is detached; never flash a console on the user's desktop.
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                              stdin=subprocess.DEVNULL, creationflags=flags)
    except subprocess.TimeoutExpired:
        raise UIStepFailed('ui_step_timeout') from None
    except OSError:
        raise UIStepFailed('ui_unavailable') from None
    if done.returncode != 0:
        raise UIStepFailed(next((r for r in UI_REASONS if r in done.stderr + done.stdout), 'ui_step_failed'))
    for line in reversed(done.stdout.splitlines()):
        line = line.strip()
        if line.startswith('{'):
            try: value = json.loads(line)
            except ValueError: break
            if type(value) is dict: return value
            break
    raise UIStepFailed('ui_output_invalid')


class DocumentRecovery:
    def __init__(self, account, *, ui=powershell, clock=time.monotonic, sleep=time.sleep,
                 deadline=150, settle=1.5, max_clicks=3, max_steps=60, cancelled=lambda: False):
        if type(account) is not str or not account or len(account) > 64 or \
                any(not (c.isalnum() or c in '_.-') for c in account):
            raise ValueError('invalid_account_label')
        self.account, self.ui, self.clock, self.sleep = account, ui, clock, sleep
        self.deadline, self.settle, self.max_clicks, self.max_steps = deadline, settle, max_clicks, max_steps
        self.cancelled = cancelled
        self.steps = []

    def _step(self, action, **fields):
        if len(self.steps) >= self.max_steps: raise UIStepFailed('recovery_step_budget_exhausted')
        # The account label is never retained in evidence, only that it was used.
        self.steps.append(dict(action=action, **{k: v for k, v in fields.items() if k != 'account'}))
        return self.ui(action, **{k: v for k, v in fields.items() if k in {'window', 'name', 'account'}})

    def run(self):
        end = self.clock() + self.deadline
        clicks = Counter(); ready = 0; selections = 0; selected = False; screen = None
        try:
            window = self._step('observe').get('window')
            if type(window) is not int or window <= 0: raise UIStepFailed('ui_output_invalid')
            self._step('reload', window=window)
            while self.clock() < end:
                if self.cancelled(): return self._result('CANCELLED', 'OPERATIONAL_STOP')
                self.sleep(self.settle)
                seen = self._step('observe', window=window)
                if seen.get('challenge') is True:
                    return self._result('CHALLENGE', 'USER_SECURITY_CHALLENGE')
                actions = [a for a in seen.get('actions') or [] if type(a) is str]
                kind = seen.get('kind')
                if kind != screen:
                    # The web app legitimately needs Login before and after the
                    # EA sign-in: limit repeated clicks per screen visit.
                    screen = kind; clicks.clear()
                self.steps[-1].update(kind=kind if kind in {'official_webapp', 'official_EA_signin'} else 'other',
                                      ready=seen.get('ready') is True, actions=actions)
                if kind == 'official_webapp':
                    selected = False
                    name = next((a for a in LOGIN + CONTINUE if a in actions), None)
                    if name is None and seen.get('ready') is True:
                        # Two consecutive settled observations of the loaded app.
                        ready += 1
                        if ready >= 2: return self._result('READY', None)
                        continue
                    ready = 0
                    if name: self._click(window, name, clicks)
                    continue
                ready = 0
                if kind == 'official_EA_signin':
                    # Pick the saved account once per sign-in visit, then continue.
                    if seen.get('email_field') is True and not selected and selections < 2 and 'SIGN IN' not in actions:
                        selections += 1; selected = True
                        self._step('select-account', window=window, account=self.account)
                        continue
                    name = next((a for a in ('NEXT', 'SIGN IN') + CONTINUE if a in actions), None)
                    if name: self._click(window, name, clicks)
                    continue
                return self._result('FAILED', 'UNEXPECTED_PAGE')
            return self._result('FAILED', 'RECOVERY_TIMEOUT')
        except UIStepFailed as error:
            if error.reason == 'user_security_challenge_required':
                return self._result('CHALLENGE', 'USER_SECURITY_CHALLENGE')
            return self._result('FAILED', error.reason)

    def _click(self, window, name, clicks):
        if clicks[name] >= self.max_clicks: raise UIStepFailed('normal_action_repeated')
        clicks[name] += 1
        self._step('click', window=window, name=name)

    def _result(self, outcome, reason):
        # Steps contain only allowlisted actions/kinds; the window handle is local.
        steps = [{k: v for k, v in s.items() if k != 'window'} for s in self.steps]
        return dict(outcome=outcome, reason=reason, steps=steps)
