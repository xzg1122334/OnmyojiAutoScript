"""Offline activation-popup checks; records predicted clicks without a device connection."""
import argparse
import copy
import json
import os
import pickle
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description='离线验证结界放卡的寄养位置确认弹窗，不操作模拟器。')
parser.add_argument('screenshot', type=Path)
parser.add_argument('--offset', nargs=2, type=int, default=(0, 0), metavar=('X', 'Y'))
args = parser.parse_args()
source = args.screenshot.resolve()
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

import numpy as np
from PIL import Image
from unittest.mock import patch

from module.image.runtime import ImageRuntime
from tasks.KekkaiActivation.config import ActivationConfig
from tasks.KekkaiActivation.script_task import ScriptTask

crop = np.array(Image.open(source).convert('RGB'))
x, y = args.offset
h, w = crop.shape[:2]
assert 0 <= x and 0 <= y and x+w <= 1280 and y+h <= 720
frame = np.zeros((720, 1280, 3), dtype=np.uint8)
frame[y:y+h, x:x+w] = crop
runtime = ImageRuntime({'worker_count': 1})


class Harness(ScriptTask):
    def __init__(self, image, cooldown=False):
        self.image = image
        self.cooldown = cooldown
        self.clicked = []
        self.I_A_ACTIVATION_CONFIRM_DIALOG = copy.deepcopy(self.I_A_ACTIVATION_CONFIRM_DIALOG)
        self.I_A_ACTIVATION_CONFIRM = copy.deepcopy(self.I_A_ACTIVATION_CONFIRM)

    def appear(self, target, **kwargs):
        result = runtime.match_rule(target.to_service_payload(), image_bytes=pickle.dumps(self.image))
        return target._apply_match_result(result)

    def appear_then_click(self, target, interval=None):
        assert target is self.I_A_ACTIVATION_CONFIRM and interval == 0.6
        if self.cooldown or not self.appear(target):
            return False
        self.clicked.append(tuple(target.roi_front))
        return True


try:
    harness = Harness(frame)
    old = runtime.match_rule(harness.I_UI_CONFIRM.to_service_payload(), image_bytes=pickle.dumps(frame))
    assert harness.handle_activation_confirm() and len(harness.clicked) == 1
    assert harness.clicked[0] == (677, 383, 177, 61), harness.clicked
    # The supplied window crop is smaller than 1280x720; allow the missing margins.
    shifted_frame = np.zeros_like(frame)
    shifted_frame[32:, 12:] = frame[:-32, :-12]
    shifted = Harness(shifted_frame)
    assert shifted.handle_activation_confirm() and shifted.clicked == [(689, 415, 177, 61)]
    for rule in (harness.I_A_ACTIVATION_CONFIRM_DIALOG, harness.I_A_ACTIVATION_CONFIRM):
        assert not Image.open(rule.file).info

    unrelated = frame.copy()
    unrelated[230:370, 420:885] = 0
    negative = Harness(unrelated)
    assert not negative.handle_activation_confirm() and not negative.clicked

    throttled = Harness(frame, cooldown=True)
    assert throttled.handle_activation_confirm() and not throttled.clicked

    cancel_only = frame.copy()
    cancel_only[355:495, 635:890] = 0
    cancel_only[383:444, 677:854] = frame[383:444, 449:626]
    negative = Harness(cancel_only)
    assert negative.handle_activation_confirm() and not negative.clicked

    class FlowHarness(Harness):
        def __init__(self):
            super().__init__(frame)
            self.step = -1
            self.actions = []
            self.scheduled = []

        def goto_page(self, *args):
            pass

        def screenshot(self):
            self.step += 1
            assert self.step <= 5, 'Activation failed to finish'
            self.image = frame if self.step in (3, 4) else np.zeros_like(frame)
            self.cooldown = self.step == 3

        def check_card_status(self):
            return self.step > 0

        def check_card_effect(self):
            return False

        def screening_card(self, rule):
            self.actions.append('select valid card')

        def appear(self, target, **kwargs):
            if target is self.I_A_ACTIVATION_CONFIRM_DIALOG or target is self.I_A_ACTIVATION_CONFIRM:
                return super().appear(target, **kwargs)
            assert self.step not in (3, 4), 'Clicked or checked underlying controls while popup visible'
            return target is self.I_A_INVITE and self.step == 5

        def appear_then_click(self, target, interval=None):
            if target is self.I_A_ACTIVATION_CONFIRM:
                result = super().appear_then_click(target, interval)
                if result:
                    self.actions.append('confirm positions')
                return result
            assert self.step == 2, 'Unexpected underlying button attempt'
            if target is self.I_UI_CONFIRM:
                return False
            assert target is self.I_A_ACTIVATE_YELLOW
            self.actions.append('activate')
            return True

        def ocr_time(self, *args):
            return timedelta(hours=24)

        def set_next_run(self, *args, **kwargs):
            self.scheduled.append(kwargs)

    flow = FlowHarness()
    with patch('tasks.KekkaiActivation.script_task.time.sleep'):
        assert flow.run_activation(ActivationConfig()) is True
    assert flow.actions == ['select valid card', 'activate', 'confirm positions']
    assert len(flow.scheduled) == 1
    report = {'old_generic_confirm_score': old['score'], 'predicted_click': list(harness.clicked[0]),
              'flow': flow.actions, 'checks': ['dialog', 'unrelated dialog', 'cooldown', 'cancel button', 'activation flow']}
    path = ROOT / 'dev_tools/local/activation-confirm/checks.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print('PASS: activation dialog confirmed; underlying activation blocked during popup; no emulator clicks sent.')
finally:
    runtime.shutdown()
