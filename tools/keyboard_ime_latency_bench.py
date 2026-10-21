#!/usr/bin/env python3
"""Opt-in pinyin latency check, exclusively in this helper's upper GTK field.

Uses synthetic fixtures, the real worker/native text route, and offscreen
keyboard/candidate drawing. Never saves typed text or changes user preferences.
Requires idle Steam. Physical touch/display latency is outside this test.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch

from keyboard_latency_bench import own_window, summary


def run_case(panel, own, rate, rounds):
    import cairo
    from keyboard_layout import KeyboardLayout
    from armada_dual_screen_input.keyboard_languages import KeyboardLanguages, KeyboardWorker
    from armada_dual_screen_input import keyboard_language_view, steam_keys

    GLib = panel.GLib
    loop = GLib.MainLoop()
    clock = time.perf_counter
    state = dict(dirty=True, error=None, round=0, phase='ready', started=clock(),
                 commit_at=None, expected='', received=False, rendered=0)
    timings, commits, draws, sources = {}, [], [], []
    replies = [0]
    own.guard(); own.entry.set_text('')

    class TimedWorker(KeyboardWorker):
        def __init__(self, runtime, deliver, dispatch):
            self.commands = []
            def received(result):
                replies[0] += 1
                index = result.get('id', 0)-1
                if 0 <= index < len(self.commands):
                    at, kind = self.commands[index]
                    timings.setdefault(kind, []).append((clock()-at)*1000)
                if result.get('status') not in ('ready',):
                    state['error'] = 'Unexpected worker status: '+str(result.get('status'))
                    loop.quit()
                deliver(result)
            super().__init__(runtime, received, dispatch)

        def submit(self, request):
            own.guard()
            self.commands.append((clock(), request['kind']))
            accepted = super().submit(request)
            if not accepted: self.commands.pop()
            return accepted

    languages = KeyboardLanguages('zh_CN', mode='game', runtime='/run/user/'+str(os.getuid()),
        changed=lambda: state.update(dirty=True), dispatch=GLib.idle_add,
        forward_key=lambda code: (_ for _ in ()).throw(AssertionError('No raw fixture keys')),
        worker_factory=TimedWorker)
    app = SimpleNamespace(kb_layout=KeyboardLayout(0,500,1240,580),
                          active_key_press=None, languages=languages)
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32,1240,1080)
    cr = cairo.Context(surface)

    def failed(error):
        state['error'] = str(error); loop.quit(); return False

    def changed(entry):
        if state['commit_at'] is not None and entry.get_text() == state['expected']:
            commits.append((clock()-state['commit_at'])*1000)
            state.update(commit_at=None, received=True)
    changed_id = own.entry.connect('changed', changed)

    def key(code):
        try:
            own.guard(); languages.key(code)
        except Exception as error: return failed(error)
        return False

    def paint():
        try:
            if state['dirty']:
                state['dirty'] = False; began = clock()
                steam_keys.draw_keyboard(app, cr)
                if keyboard_language_view.visible(languages):
                    keyboard_language_view.draw(cr, languages, 412)
                draws.append((clock()-began)*1000)
                state['rendered'] += 1
        except Exception as error: return failed(error)
        return True

    def step():
        try:
            own.guard()
            if clock()-state['started'] > 8+rounds*3:
                return failed('IME test deadline exceeded')
            if state['phase'] == 'ready' and languages.ready:
                state['phase'] = 'begin'
            if state['phase'] == 'begin':
                index = state['round']
                # Alternate explicit candidate selection and queued Space.
                codes, phrase = (([49,23,35,30,24], '你好') if index%2 == 0
                                 else ([31,35,23,36,23,18], '世界'))
                state.update(phase='typing', phrase=phrase, pinyin='nihao' if index%2==0 else 'shijie',
                             finish_at=clock()+len(codes)/rate, choose=index%2==0)
                for i,code in enumerate(codes):
                    sources.append(GLib.timeout_add(1+round(i*1000/rate),key,code))
            elif state['phase'] == 'typing' and clock() >= state['finish_at']:
                if state['choose'] and languages.preedit != state['pinyin']:
                    return True
                if state['choose'] and (not languages.candidates or languages.candidates[0] != state['phrase']):
                    return failed('Synthetic candidate mismatch')
                state.update(phase='committing', commit_at=clock(),
                             expected=state['expected']+state['phrase'])
                if state['choose']: languages.choose(0)
                else: languages.key(57)
            elif (state['phase'] == 'committing' and state['received']
                  and languages.worker and replies[0] == len(languages.worker.commands)):
                state.update(round=state['round']+1, received=False, phase='begin')
                if state['round'] == rounds:
                    loop.quit(); return False
        except Exception as error: return failed(error)
        return True

    try:
        languages.sync(True)
        sources.extend((GLib.timeout_add(5,step),
                        GLib.timeout_add(16,paint,priority=GLib.PRIORITY_HIGH_IDLE)))
        loop.run()
    finally:
        for source in sources:
            if GLib.MainContext.default().find_source_by_id(source): GLib.source_remove(source)
        own.entry.disconnect(changed_id)
        worker = languages.worker
        languages.close()
        if worker: worker._thread.join(timeout=1)
    return dict(rate_hz=rate, rounds=state['round'], expected_rounds=rounds,
                text_exact=own.entry.get_text()==state['expected'], error=state['error'],
                worker_response={kind:summary(values) for kind,values in timings.items()},
                commit_to_entry=summary(commits), render_cost=summary(draws))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-own-window-test',action='store_true',required=True)
    parser.add_argument('--rounds',type=int,default=6)
    parser.add_argument('--output',type=Path)
    args = parser.parse_args()
    if sys.platform != 'linux' or not 2 <= args.rounds <= 30:
        parser.error('Linux GTK and rounds from 2 through 30 required')
    sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'src'))
    with tempfile.TemporaryDirectory(prefix='ads-ime-bench-') as temp, \
            patch.dict(os.environ,{'XDG_STATE_HOME':temp}):
        own = own_window()
        try:
            from armada_dual_screen_input import panel_app as panel
            cases = [run_case(panel,own,rate,args.rounds) for rate in (5,10,15)]
        finally:
            own.window.destroy(); own.focus.close()
    result = dict(scope='own-gtk-field-real-ime-with-offscreen-keyboard',cases=cases,
        passed=all(c['text_exact'] and c['rounds']==args.rounds and not c['error'] for c in cases))
    encoded = json.dumps(result,indent=2)
    if args.output: args.output.write_text(encoded+'\n')
    print(encoded)
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
