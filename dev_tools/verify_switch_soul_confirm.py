"""Offline preset-confirmation checks; never connects to or clicks a device."""
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
parser = argparse.ArgumentParser(description='离线验证切换预设御魂的确认弹窗，不操作模拟器。')
parser.add_argument('screenshot', type=Path)
parser.add_argument('--offset', nargs=2, type=int, default=(0, 0), metavar=('X', 'Y'))
args = parser.parse_args()
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

import numpy as np
from PIL import Image

from module.exception import GameStuckError
from module.image.runtime import ImageRuntime
from tasks.Component.Costume.config import ShikigamiType
from tasks.Component.Costume.costume_base import CostumeBase
from tasks.Component.CostumeShikigami.assets import CostumeShikigamiAssets
from tasks.Component.SwitchSoul.switch_soul import SwitchSoul

MODULE = 'tasks.Component.SwitchSoul.switch_soul'
crop = np.array(Image.open(args.screenshot).convert('RGB'))
x, y = args.offset
h, w = crop.shape[:2]
assert 0 <= x and 0 <= y and x+w <= 1280 and y+h <= 720
frame = np.zeros((720, 1280, 3), dtype=np.uint8)
frame[y:y+h, x:x+w] = crop
blank = np.zeros_like(frame)
runtime = ImageRuntime({'worker_count': 1})


class BoundedTimer:
    def __init__(self, limit):
        assert limit == 30
        self.calls = 0

    def start(self):
        return self

    def reached(self):
        self.calls += 1
        return self.calls > 12


class Harness(SwitchSoul):
    def __init__(self, frames, skin=False, cooldown_frames=()):
        self.frames = frames
        self.image = frames[0]
        self.step = -1
        self.cooldown_frames = cooldown_frames
        self.actions = []
        self.I_SOU_SWITCH_DIALOG = copy.deepcopy(self.I_SOU_SWITCH_DIALOG)
        self.I_SOU_SWITCH_SURE = copy.deepcopy(
            CostumeShikigamiAssets.I_SOU_SWITCH_SURE_12 if skin else self.I_SOU_SWITCH_SURE)
        self.I_CHECK_BLOCK = copy.deepcopy(self.I_CHECK_BLOCK)

    def screenshot(self):
        self.step += 1
        self.image = self.frames[min(self.step, len(self.frames)-1)]

    def appear(self, target, **kwargs):
        result = runtime.match_rule(target.to_service_payload(), image_bytes=pickle.dumps(self.image))
        return target._apply_match_result(result)

    def appear_then_click(self, target, interval=None):
        assert target in (self.I_SOU_SWITCH_SURE, self.I_CHECK_BLOCK)
        if not self.appear(target) or self.step in self.cooldown_frames:
            return False
        self.actions.append((target.name, tuple(target.roi_front), self.step))
        return True

    def select_team(self):
        # A team may only be reselected when no confirmation dialog is present.
        assert not self.appear(self.I_SOU_SWITCH_DIALOG)
        assert not self.appear(self.I_SOU_SWITCH_SURE)
        self.actions.append(('select', (), self.step))
        return True


def apply(harness, succeeds=True):
    with patch(MODULE+'.sleep'), patch(MODULE+'.Timer', BoundedTimer):
        if succeeds:
            harness._apply_soul_preset(harness.select_team, 'offline test')
        else:
            try:
                harness._apply_soul_preset(harness.select_team, 'offline test')
            except GameStuckError:
                return
            raise AssertionError('Unfinished switch was reported as successful')


try:
    mapped = CostumeBase()
    mapped.I_SOU_SWITCH_SURE = copy.deepcopy(SwitchSoul.I_SOU_SWITCH_SURE)
    mapped.check_costume_shikigami(ShikigamiType.COSTUME_SHIKIGAMI_12)
    assert mapped.I_SOU_SWITCH_SURE.file == CostumeShikigamiAssets.I_SOU_SWITCH_SURE_12.file
    assert tuple(mapped.I_SOU_SWITCH_SURE.roi_back) == (630, 385, 255, 115)
    assert mapped.I_SOU_SWITCH_SURE.threshold == 0.9

    clicks = {}
    for skin in (False, True):
        harness = Harness([blank, frame, frame, frame, blank, blank], skin, cooldown_frames=(1, 3))
        apply(harness)
        assert harness.step == 5, 'Must observe two closed frames before returning'
        assert [a[0] for a in harness.actions].count('select') == 1
        confirmations = [a for a in harness.actions if a[0] != 'select']
        assert len(confirmations) == 1 and confirmations[0][1] == (665, 408, 177, 63)
        clicks['skin12' if skin else 'default'] = list(confirmations[0][1])
        assert not Image.open(harness.I_SOU_SWITCH_SURE.file).info

    assert not Image.open(harness.I_SOU_SWITCH_DIALOG.file).info
    shifted = np.zeros_like(frame)
    shifted[10:, 12:] = frame[:-10, :-12]
    moved = Harness([shifted, blank, blank])
    apply(moved)
    assert moved.actions[0][1] == (677, 418, 177, 63)

    # Variable shikigami names must not be part of the dialog template.
    renamed = frame.copy()
    renamed[280:350, 588:862] = 0
    renamed[319:354, 419:588] = 0
    names = Harness([renamed, blank, blank])
    apply(names)
    assert names.actions[0][1] == (665, 408, 177, 63)

    unknown = frame.copy()
    unknown[255:350, 395:620] = 0
    blocked = Harness([unknown])
    apply(blocked, succeeds=False)
    assert not blocked.actions, 'Unknown confirmation must neither click nor reselect'

    cancel = frame.copy()
    cancel[385:500, 630:885] = 0
    cancel[408:471, 665:842] = frame[409:472, 437:614]
    blocked = Harness([cancel])
    apply(blocked, succeeds=False)
    assert not blocked.actions, 'Must never click the red cancel button'

    equipped = Harness([blank])
    apply(equipped)
    assert len(equipped.actions) == 2 and equipped.step == 3

    # Failed or throttled selection calls must not count as successful clicks.
    missing = Harness([blank])
    missing.select_team = lambda: False
    apply(missing, succeeds=False)
    assert not missing.actions

    one_click = Harness([blank])
    original_select = one_click.select_team
    one_click.select_team = lambda: original_select() if not one_click.actions else False
    apply(one_click, succeeds=False)
    assert len(one_click.actions) == 1

    throttled_select = Harness([blank])
    original_select = throttled_select.select_team
    throttled_select.select_team = lambda: original_select() if throttled_select.step in (0, 4) else False
    apply(throttled_select)
    assert [a[2] for a in throttled_select.actions] == [0, 4] and throttled_select.step == 6

    delayed = Harness([blank, blank, blank, frame, blank, blank])
    apply(delayed)
    assert len([a for a in delayed.actions if a[0] == 'select']) == 2
    assert delayed.actions[-1][0] != 'select' and delayed.step == 5

    disappeared = Harness([blank, cancel, blank])
    apply(disappeared, succeeds=False)
    assert len(disappeared.actions) == 2, 'Seen but unconfirmed dialog cannot use equipped fallback'

    persistent = Harness([frame])
    apply(persistent, succeeds=False)
    assert persistent.actions and all(a[0] != 'select' for a in persistent.actions)

    # Both numeric and named routes must call the guarded confirmation flow and
    # propagate its failure instead of reporting success to the calling task.
    class RouteHarness(SwitchSoul):
        def __init__(self, fails=False):
            self.device = SimpleNamespace(image=blank)
            self.O_SS_GROUP_NAME = SimpleNamespace(
                detect_and_ocr=lambda image: [SimpleNamespace(ocr_text='group')])
            self.O_SS_TEAM_NAME = SimpleNamespace(
                detect_and_ocr=lambda image: [SimpleNamespace(ocr_text='team')])
            self.fails = fails
            self.calls = []

        def screenshot(self):
            pass

        def swipe(self, *args):
            pass

        def click(self, *args):
            pass

        def ocr_appear_click(self, *args):
            return True

        def appear_then_click(self, target, interval=None):
            assert target is self.I_SOU_SWITCH_2 and interval == 3
            self.calls.append('numeric select')
            return True

        def ocr_appear_click_by_rule(self, target, action, interval=None):
            assert target is self.O_SS_TEAM_NAME and target.keyword == 'team'
            assert action is self.I_SOU_CLICK_PRESENT and interval == 1.5
            self.calls.append('named select')
            return True

        def _apply_soul_preset(self, select_team, description):
            assert select_team()
            if self.fails:
                raise GameStuckError('offline failure')

    for named in (False, True):
        for fails in (False, True):
            route = RouteHarness(fails)
            with patch(MODULE+'.sleep'), patch(MODULE+'.logger') as log:
                try:
                    if named:
                        route.switch_soul_by_name('group', 'team')
                    else:
                        route.switch_soul_one(4, 2)
                except GameStuckError:
                    assert fails
                else:
                    assert not fails
                successes = [call for call in log.info.call_args_list
                             if str(call.args[0]).startswith('Switch soul_one')]
                assert bool(successes) == (not fails)
            assert route.calls == ['named select' if named else 'numeric select']

    report = {'predicted_clicks': clicks, 'checks': [
        'default and skin12 mapping', 'shifted popup', 'variable names', 'click cooldown',
        'two closed frames', 'unknown dialog', 'red cancel', 'already equipped after two clicks',
        'failed and throttled selection', 'delayed popup', 'unconfirmed popup disappeared',
        'persistent popup timeout', 'numeric and named routes propagate failure',
    ]}
    output = ROOT / 'dev_tools/local/switch-soul-confirm/checks.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print('PASS: preset confirmation and failure propagation; no emulator clicks sent.')
finally:
    runtime.shutdown()
