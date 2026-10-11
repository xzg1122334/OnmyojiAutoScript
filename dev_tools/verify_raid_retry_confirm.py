"""Offline realm-raid retry/refresh confirmation checks; no device actions."""
import argparse
import copy
import json
import os
import pickle
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description='离线验证个人突破再次挑战的确认，不操作模拟器。')
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
from tasks.RealmRaid.script_task import ScriptTask

crop = np.array(Image.open(args.screenshot).convert('RGB'))
x, y = args.offset
h, w = crop.shape[:2]
assert 0 <= x and 0 <= y and x+w <= 1280 and y+h <= 720
frame = np.zeros((720,1280,3), dtype=np.uint8)
frame[y:y+h,x:x+w] = crop
blank = np.zeros_like(frame)
runtime = ImageRuntime({'worker_count':1})


class Harness(ScriptTask):
    def __init__(self, frames, pending=False, unchecked=False):
        self.frames = frames
        self.image = frames[0]
        self.step = -1
        self.pending = pending
        self.unchecked = unchecked
        self.actions = []
        self.I_FRESH_ENSURE = copy.deepcopy(self.I_FRESH_ENSURE)

    def screenshot(self):
        self.step += 1
        assert self.step < len(self.frames), 'Retry failed to finish'
        self.image = self.frames[self.step]

    def appear(self, target, **kwargs):
        if target is self.I_FRESH_ENSURE:
            result = runtime.match_rule(target.to_service_payload(), image_bytes=pickle.dumps(self.image))
            return target._apply_match_result(result)
        if target is self.I_EXIT:
            assert not self.appear(self.I_FRESH_ENSURE), 'Popup must be checked before battle page'
            return self.step == len(self.frames)-1
        return target is self.I_FRESH

    def appear_then_click(self, target, interval=None):
        if target is self.I_SHOW_AGAIN:
            if self.unchecked and self.appear(self.I_FRESH_ENSURE):
                self.unchecked = False
                self.actions.append(('hide prompt', []))
                return True
            return False
        if target is self.I_FRESH_ENSURE:
            if self.step == 1 and not self.unchecked:
                return False  # A throttled click must block background controls.
            assert self.appear(target)
            self.actions.append(('confirm', list(target.roi_front)))
            return True
        assert target in (self.I_FIRE_AGAIN, self.I_FRESH)
        assert not self.appear(self.I_FRESH_ENSURE), 'Clicked background with dialog visible'
        self.actions.append(('retry' if target is self.I_FIRE_AGAIN else 'refresh', []))
        return True

    def wait_until_appear(self, *args):
        raise AssertionError('Pending confirmation must not wait for background retry button')


try:
    positive = Harness([frame])
    assert positive.appear(positive.I_FRESH_ENSURE)
    assert tuple(positive.I_FRESH_ENSURE.roi_front) == (665,408,177,63)
    assert not Image.open(positive.I_FRESH_ENSURE.file).info
    shifted = np.zeros_like(frame)
    shifted[10:,12:] = frame[:-10,:-12]
    moved = Harness([shifted])
    assert moved.appear(moved.I_FRESH_ENSURE)
    assert tuple(moved.I_FRESH_ENSURE.roi_front) == (677,418,177,63)
    cancel = frame.copy()
    cancel[385:500,630:885] = 0
    cancel[408:471,665:842] = frame[408:471,437:614]
    for negative in (cancel, blank):
        harness = Harness([negative])
        assert not harness.appear(harness.I_FRESH_ENSURE)

    paths = []
    for pending, unchecked in ((False,False),(True,False),(True,True)):
        flow = Harness([frame if pending else blank,frame,frame,blank], pending, unchecked)
        assert flow.fire_again() is True and flow.step == 3
        expected = [('hide prompt' if unchecked else 'confirm')] if pending else ['retry']
        expected.append('confirm')
        assert [a[0] for a in flow.actions] == expected, flow.actions
        assert flow.actions[-1][1] == [665,408,177,63]
        paths.append(flow.actions)

    # Refresh shares the same button asset: retain its confirmation-and-close flow.
    refresh = Harness([blank,frame,frame,blank])
    assert refresh.check_refresh(screenshot=False) is True
    assert refresh.actions == [('refresh', []), ('confirm', [665,408,177,63])]
    report = {'predicted_click':[665,408,177,63], 'retry_paths':paths,
              'checks':['button match and shift','red cancel and blank','retry confirmation',
                        'pending dialog recovery','cooldown blocks background retry',
                        'hide prompt checkbox','shared refresh confirmation']}
    output = ROOT/'dev_tools/local/raid-retry-confirm/checks.json'
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    print('PASS: retry and refresh confirmation; no emulator clicks sent.')
finally:
    runtime.shutdown()
