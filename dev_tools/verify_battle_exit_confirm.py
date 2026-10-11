"""Check battle-exit matching and predicted clicks without connecting a device."""
import argparse
import copy
import json
import os
import pickle
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description='离线验证退出战斗的确定按钮，不操作模拟器。')
parser.add_argument('screenshot', type=Path)
parser.add_argument('--offset', nargs=2, type=int, default=(0, 0), metavar=('X', 'Y'))
args = parser.parse_args()
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

import numpy as np
from PIL import Image

from module.image.runtime import ImageRuntime
from tasks.Component.GeneralBattle.general_battle import GeneralBattle
from tasks.GameUi.page import page_battle_prepare, page_battle_result
from tasks.RealmRaid.script_task import ScriptTask

crop = np.array(Image.open(args.screenshot).convert('RGB'))
x, y = args.offset
h, w = crop.shape[:2]
assert 0 <= x and 0 <= y and x+w <= 1280 and y+h <= 720
frame = np.zeros((720, 1280, 3), dtype=np.uint8)
frame[y:y+h, x:x+w] = crop
blank = np.zeros_like(frame)
runtime = ImageRuntime({'worker_count': 1})


class Harness(ScriptTask):
    def __init__(self, initial, frames=(), exit_visible=True):
        self.image = initial
        self.frames = frames
        self.step = -1
        self.exit_visible = exit_visible
        self.actions = []
        self.I_EXIT_ENSURE = copy.deepcopy(self.I_EXIT_ENSURE)

    def screenshot(self):
        self.step += 1
        assert self.step < len(self.frames), 'Exit failed to complete'
        self.image = self.frames[self.step]

    def appear(self, target, **kwargs):
        if target is self.I_EXIT:
            return self.exit_visible
        assert target is self.I_EXIT_ENSURE
        result = runtime.match_rule(target.to_service_payload(), image_bytes=pickle.dumps(self.image))
        return target._apply_match_result(result)

    def appear_then_click(self, target, interval=None):
        if target is self.I_EXIT:
            assert not self.appear(self.I_EXIT_ENSURE), 'Clicked behind confirmation popup'
            assert interval == 6
        else:
            assert target is self.I_EXIT_ENSURE and interval == 0.8
            if self.step == 1:  # Simulate the click interval blocking a click.
                return False
        if not self.appear(target):
            return False
        self.actions.append((target.name, list(target.roi_front)))
        return True

    def ui_click_until_disappear(self, target, interval=None):
        assert target is self.I_EXIT_ENSURE and not self.appear(target)

    def current_page(self):
        assert not self.appear(self.I_EXIT_ENSURE), 'Popup must block background page handling'
        return page_battle_result if self.step == 3 else page_battle_prepare


try:
    assert ScriptTask.exit_battle is GeneralBattle.exit_battle
    positive = Harness(frame)
    assert positive.appear(positive.I_EXIT_ENSURE)
    assert tuple(positive.I_EXIT_ENSURE.roi_front) == (665,408,177,63)
    assert not Image.open(positive.I_EXIT_ENSURE.file).info

    shifted = np.zeros_like(frame)
    shifted[10:,12:] = frame[:-10,:-12]
    moved = Harness(shifted)
    assert moved.appear(moved.I_EXIT_ENSURE)
    assert tuple(moved.I_EXIT_ENSURE.roi_front) == (677,418,177,63)

    cancel = frame.copy()
    cancel[385:500,630:885] = 0
    cancel[408:471,665:842] = frame[408:471,437:614]
    for negative in (blank, cancel):
        check = Harness(negative)
        assert not check.appear(check.I_EXIT_ENSURE), 'Blank or cancel matched as confirm'

    paths = []
    for pending in (False, True):
        flow = Harness(frame if pending else blank,
                       [frame if pending else blank, frame, frame, blank],
                       exit_visible=not pending)
        with patch('tasks.Component.GeneralBattle.general_battle.GameUi.get_current_page',
                   side_effect=lambda task: task.current_page()):
            assert flow.exit_battle() is True
        assert flow.step == 3
        # A pending popup that stays visible may be confirmed again after the
        # interval; the background exit button must never be clicked meanwhile.
        expected = [flow.I_EXIT_ENSURE.name]*2 if pending else [flow.I_EXIT.name, flow.I_EXIT_ENSURE.name]
        assert [a[0] for a in flow.actions] == expected, flow.actions
        assert flow.actions[-1][1] == [665,408,177,63]
        paths.append(flow.actions)

    absent = Harness(blank, exit_visible=False)
    assert absent.exit_battle() is False and not absent.actions and absent.step == -1
    report = {'predicted_click': [665,408,177,63], 'paths': paths,
              'checks': ['actual RealmRaid inherited flow', 'shifted button', 'red cancel and blank',
                         'cooldown blocks background clicks', 'pending popup recovery', 'result before success',
                         'no exit control returns false']}
    output = ROOT / 'dev_tools/local/battle-exit-confirm/checks.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print('PASS: battle-exit confirmation; no emulator clicks sent.')
finally:
    runtime.shutdown()
