"""Offline stone OCR and summon flow checks; never connects to the emulator."""
import argparse
import copy
import json
import os
import pickle
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')
parser = argparse.ArgumentParser(description='离线检查鸣契石识别和召唤，不操作游戏。')
parser.add_argument('screenshot', type=Path, help='1280x720 鸣契数量选择弹窗截图')
args = parser.parse_args()

import numpy as np
from PIL import Image
from module.exception import GameStuckError
from module.image.runtime import ImageRuntime
from module.ocr.ppocr import TextSystem
from tasks.BondlingFairyland.script_task import ScriptTask

frame = np.array(Image.open(args.screenshot).convert('RGB'))
assert frame.shape == (720, 1280, 3)
rule = copy.deepcopy(ScriptTask.O_B_STONE_NUMBER)
rule.model = TextSystem()
current, remaining, total = rule.ocr(frame)
assert (current, remaining, total) == (7, 23, 30), 'Reference screenshot must read 7/30'
source = json.loads((ROOT/'tasks/BondlingFairyland/bf/ocr.json').read_text(encoding='utf-8'))
spec = next(item for item in source if item['itemName'] == 'b_stone_number')
assert list(map(int, spec['roiFront'].split(','))) == rule.roi
assert list(map(int, spec['roiBack'].split(','))) == rule.area
old = copy.deepcopy(ScriptTask.O_B_STONE_NUMBER)
old.model = rule.model
old.roi = [1135, 16, 78, 32]
old_result = old.ocr(frame)
runtime = ImageRuntime({'worker_count': 1})


class Harness(ScriptTask):
    def __init__(self, results=None):
        self.device = SimpleNamespace(image=frame.copy())
        self.clicked = []
        self.closed = False
        self.reads = 0
        self.shots = 0
        self.O_B_STONE_NUMBER = SimpleNamespace(ocr=self.read_number)
        self.results = None if results is None else iter(results)
        for name in ('I_STONE_SURE', 'I_BUY_PLUS', 'I_STONE_CLOSE', 'I_GI_SURE'):
            setattr(self, name, copy.deepcopy(getattr(self, name)))

    def read_number(self, image):
        self.reads += 1
        return rule.ocr(image) if self.results is None else next(self.results)

    def screenshot(self):
        self.shots += 1
        assert self.shots <= 8, 'Summon did not finish within fixture'

    def appear(self, target, **kwargs):
        result = runtime.match_rule(target.to_service_payload(), image_bytes=pickle.dumps(self.device.image))
        return target._apply_match_result(result)

    def appear_then_click(self, target, **kwargs):
        if not self.appear(target):
            return False
        self.clicked.append(target.name)
        if target is self.I_STONE_SURE:
            self.device.image = np.zeros_like(frame)
        return True

    def ui_click_until_disappear(self, target, **kwargs):
        assert target is self.I_STONE_CLOSE
        self.closed = True


try:
    with patch('tasks.BondlingFairyland.script_task.sleep', lambda _: None):
        actual = Harness()
        assert actual.appear(actual.I_STONE_SURE), 'Real summon button not recognized'
        assert actual.run_stone(True)
        assert actual.I_STONE_SURE.name in actual.clicked and not actual.closed
        recovered = Harness([(0, 0, 0), (7, 23, 30)])
        assert recovered.run_stone(True) and recovered.reads == 2 and not recovered.closed
        empty = Harness([(0, 30, 30), (0, 30, 30)])
        assert empty.run_stone(True) is False and empty.closed and empty.reads == 2
        assert not empty.clicked
        transient_zero = Harness([(0, 30, 30), (7, 23, 30)])
        assert transient_zero.run_stone(True) and not transient_zero.closed
        for results in (
            [(0, 0, 0)] * 3,
            [(0, 30, 30), (0, 0, 0), (0, 30, 30)],
        ):
            unknown = Harness(results)
            try:
                unknown.run_stone(True)
            except GameStuckError:
                pass
            else:
                raise AssertionError('Unconfirmed OCR result was treated as exhausted or summoned')
            assert unknown.reads == 3 and not unknown.closed and not unknown.clicked
        disabled = Harness([])
        assert disabled.run_stone(False) is False and disabled.closed and disabled.reads == 0
        assert not disabled.clicked

    report = {
        'old_counter': old_result, 'new_counter': [current, remaining, total],
        'summon_clicks': actual.clicked,
        'checks': ['real 7/30 OCR and summon button', 'source and generated ROI agree',
                   'unknown then positive retries', 'two consecutive zero reads exit',
                   'transient zero recovers', 'unknown results fail without exhaustion or clicks',
                   'unknown resets consecutive zero count', 'disabled does not summon'],
    }
    output = ROOT/'dev_tools/local/bondling-stone/checks.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print('PASS: stone OCR and summon flow; no game clicks sent.')
finally:
    runtime.shutdown()
