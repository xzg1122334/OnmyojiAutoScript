"""Offline disk-limit reminder checks; no emulator connection or clicks."""
import argparse
import copy
import json
import os
import pickle
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description='离线验证契灵式盘上限弹窗，不操作游戏。')
parser.add_argument('screenshot', type=Path)
parser.add_argument('--offset', nargs=2, type=int, default=(0, 0))
parser.add_argument('--unchecked-reference', type=Path, required=True,
                    help='相同位置、棕色未勾选框的真实游戏截图')
args = parser.parse_args()
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

import numpy as np
from PIL import Image
from module.image.runtime import ImageRuntime
from module.exception import GameStuckError
from tasks.BondlingFairyland.script_task import ScriptTask

frame = np.zeros((720, 1280, 3), dtype=np.uint8)
crop = np.array(Image.open(args.screenshot).convert('RGB'))
x, y = args.offset
h, w = crop.shape[:2]
assert 0 <= x and 0 <= y and x+w <= 1280 and y+h <= 720
frame[y:y+h, x:x+w] = crop
reference = np.array(Image.open(args.unchecked_reference).convert('RGB'))
assert reference.shape == frame.shape
# The checkbox-off fixture comes from a separate real screenshot, not the template.
unchecked = frame.copy()
unchecked[342:380, 542:580] = reference[342:380, 542:580]
blank = np.zeros_like(frame)
runtime = ImageRuntime({'worker_count': 1})


class Harness(ScriptTask):
    def __init__(self, initial, frames=(), cooldown=()):
        self.image = initial
        self.frames = frames
        self.step = -1
        self.cooldown = cooldown
        self.clicked = []
        for name in ('I_PLATE_LIMIT_DIALOG', 'I_I_NO_DEFAULT', 'I_I_DEFAULT', 'I_GI_SURE'):
            setattr(self, name, copy.deepcopy(getattr(self, name)))

    def screenshot(self):
        self.step += 1
        assert self.step < len(self.frames), 'Challenge did not finish within fixture'
        self.image = self.frames[self.step]

    def appear(self, target, threshold=None, **kwargs):
        if target is self.I_BALL_FIRE:
            return bool(self.image.any())
        if target in (self.I_C_PLATE_LESS, self.I_UI_CONFIRM):
            return False
        payload = target.to_service_payload()
        if threshold is not None:
            payload['threshold'] = threshold
        return target._apply_match_result(runtime.match_rule(payload, image_bytes=pickle.dumps(self.image)))

    def appear_then_click(self, target, interval=None, **kwargs):
        assert interval == 1
        if self.step in self.cooldown or not self.appear(target, **kwargs):
            return False
        if target is self.I_BALL_FIRE:
            assert not self.appear(self.I_PLATE_LIMIT_DIALOG), 'Clicked challenge behind modal'
        self.clicked.append((target.name, list(target.roi_front)))
        return True


class BoundedWait:
    def __init__(self, seconds):
        assert seconds == 30
        self.calls = 0

    def start(self):
        return self

    def reached(self):
        self.calls += 1
        return self.calls >= 8


try:
    checked = Harness(frame)
    assert checked.appear(checked.I_PLATE_LIMIT_DIALOG)
    assert checked.appear(checked.I_I_DEFAULT) and not checked.appear(checked.I_I_NO_DEFAULT)
    assert checked.handle_plate_limit_confirm()
    assert checked.clicked == [('GI_GI_SURE', [665, 408, 177, 63])]
    off = Harness(unchecked)
    assert off.appear(off.I_I_NO_DEFAULT) and not off.appear(off.I_I_DEFAULT)
    assert off.handle_plate_limit_confirm()
    assert [a[0] for a in off.clicked] == ['GI_I_NO_DEFAULT']
    assert not Harness(reference).handle_plate_limit_confirm(), 'Unrelated invite modal handled as disk limit'
    assert not Harness(blank).handle_plate_limit_confirm()
    cancel = frame.copy()
    cancel[385:500, 630:885] = 0
    cancel[408:471, 665:842] = frame[408:471, 437:614]
    blocked = Harness(cancel)
    assert blocked.handle_plate_limit_confirm() and not blocked.clicked
    shifted = np.zeros_like(frame)
    shifted[10:, 12:] = frame[:-10, :-12]
    moved = Harness(shifted)
    assert moved.handle_plate_limit_confirm()
    assert moved.clicked == [('GI_GI_SURE', [677, 418, 177, 63])]

    paths = []
    with patch('tasks.BondlingFairyland.script_task.sleep', lambda _: None), \
         patch('tasks.BondlingFairyland.script_task.Timer', BoundedWait):
        for frames, cooldown, expected in (
            ([frame, frame, blank], (0,), ['GI_GI_SURE']),
            ([unchecked, unchecked, frame, frame, blank], (1, 2), ['GI_I_NO_DEFAULT', 'GI_GI_SURE']),
            ([reference, frame, frame, blank], (1,), ['BALL_BALL_FIRE', 'GI_GI_SURE']),
            ([blank], (), []),
        ):
            flow = Harness(frames[0], frames, cooldown)
            assert flow.run_alone()
            assert [a[0] for a in flow.clicked] == expected, flow.clicked
            paths.append(flow.clicked)
        stuck = Harness(reference, [reference]*8)
        try:
            stuck.run_alone()
        except GameStuckError as error:
            assert '500' not in str(error)
        else:
            raise AssertionError('Unresolved challenge was treated as success')
        assert len(stuck.clicked) == 3
        stuck_modal = Harness(cancel, [cancel]*8)
        try:
            stuck_modal.run_alone()
        except GameStuckError:
            pass
        else:
            raise AssertionError('Unresolved dialog did not time out')
        assert not stuck_modal.clicked

    for name in ('I_PLATE_LIMIT_DIALOG', 'I_I_NO_DEFAULT', 'I_I_DEFAULT', 'I_GI_SURE'):
        assert not Image.open(getattr(checked, name).file).info
    report = {'paths': paths, 'checks': [
        'real disk-limit checked checkbox and confirm', 'unchecked fixture from independent real screenshot',
        'checkbox cooldown blocks confirm', 'confirm cooldown blocks challenge', 'shifted dialog',
        'red cancel and unrelated invite modal rejected', 'challenge resumes after disk limit',
        'three attempts then bounded wait', 'unresolved dialog fails without claiming capacity 500']}
    output = ROOT/'dev_tools/local/bondling-confirm/checks.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print('PASS: disk-limit checkbox and confirmation; no game clicks sent.')
finally:
    runtime.shutdown()
