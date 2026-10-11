"""Offline reward-popup recognition and collection checks; no device actions."""
import argparse
import copy
import json
import os
import pickle
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description='离线验证获得奖励弹窗及领取收尾，不操作模拟器。')
parser.add_argument('screenshot',type=Path)
parser.add_argument('--offset',nargs=2,type=int,default=(0,0),metavar=('X','Y'))
parser.add_argument('--negative',type=Path)
args = parser.parse_args()
os.chdir(ROOT)
sys.path.insert(0,str(ROOT))
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

import numpy as np
from PIL import Image
from module.image.runtime import ImageRuntime
from tasks.GameUi.default_pages import page_reward
from tasks.WantedQuests.script_task import ScriptTask


def load_frame(path,offset=(0,0)):
    crop = np.array(Image.open(path).convert('RGB'))
    x,y = offset
    h,w = crop.shape[:2]
    assert 0 <= x and 0 <= y and x+w <= 1280 and y+h <= 720
    result = np.zeros((720,1280,3),dtype=np.uint8)
    result[y:y+h,x:x+w] = crop
    return result


frame = load_frame(args.screenshot,args.offset)
blank = np.zeros_like(frame)
runtime = ImageRuntime({'worker_count':1})


class Harness(ScriptTask):
    def __init__(self,image,frames=(),cooldown=()):
        self.image = image
        self.frames = frames
        self.step = -1
        self.cooldown = cooldown
        self.actions = []
        for name in ('I_UI_REWARD','I_UI_REWARD_LARGE'):
            setattr(self,name,copy.deepcopy(getattr(self,name)))

    def screenshot(self):
        self.step += 1
        assert self.step < len(self.frames), 'Collection failed to close popup'
        self.image = self.frames[self.step]

    def appear(self,target,threshold=None,**kwargs):
        if target is self.I_WQ_BOX:
            return self.step == 0
        payload = target.to_service_payload()
        if threshold is not None:
            payload['threshold'] = threshold
        result = runtime.match_rule(payload,image_bytes=pickle.dumps(self.image))
        return target._apply_match_result(result)

    def appear_then_click(self,target,action=None,interval=None,threshold=None):
        if target is self.I_WQ_BOX:
            assert not self.ui_reward_appear(), 'Clicked box behind reward popup'
        else:
            assert target in (self.I_UI_REWARD,self.I_UI_REWARD_LARGE)
            assert action is self.C_UI_REWARD and interval == 0.4
        if self.step in self.cooldown or not self.appear(target,threshold=threshold):
            return False
        self.actions.append((target.name,list((action or target).roi_front)))
        return True


class EarlyTimeout:
    # If recognition misses the popup, fail the test via an early timeout rather
    # than letting the fixture run out of screenshots.
    def __init__(self,limit):
        assert limit == 10
        self.calls = 0

    def start(self):
        return self

    def reached(self):
        self.calls += 1
        return self.calls >= 2


try:
    positive = Harness(frame)
    old = runtime.match_rule(positive.I_UI_REWARD.to_service_payload(),image_bytes=pickle.dumps(frame))
    assert not positive.appear(positive.I_UI_REWARD,threshold=0.6)
    assert positive.ui_reward_appear()
    assert tuple(positive.I_UI_REWARD_LARGE.roi_front) == (520,210,250,65)
    assert not Image.open(positive.I_UI_REWARD_LARGE.file).info
    assert page_reward.recognizer.evaluate(positive)
    shifted = np.zeros_like(frame)
    shifted[10:,12:] = frame[:-10,:-12]
    moved = Harness(shifted)
    assert moved.ui_reward_appear()
    assert tuple(moved.I_UI_REWARD_LARGE.roi_front) == (532,220,250,65)
    assert not Harness(blank).ui_reward_appear()
    without_title = frame.copy()
    without_title[165:300,465:825] = 0
    assert not Harness(without_title).ui_reward_appear()
    if args.negative:
        assert not Harness(load_frame(args.negative)).ui_reward_appear()

    flow = Harness(blank,[blank,frame,frame,frame,blank],cooldown=(1,3))
    with patch('tasks.base_task.Timer',EarlyTimeout), patch('tasks.base_task.sleep'), \
            patch('tasks.base_task.logger') as log:
        assert flow.ui_get_reward(flow.I_WQ_BOX) is True
        assert log.info.call_args.args == ('Get reward success',)
        assert not log.warning.called
    assert flow.step == 4
    assert flow.actions == [('WQ_WQ_BOX',list(flow.I_WQ_BOX.roi_front)),
                            ('UI_UI_REWARD_LARGE',[919,160,208,368])]

    pending = Harness(frame,[frame,blank])
    with patch('tasks.base_task.Timer',EarlyTimeout), patch('tasks.base_task.sleep'):
        assert pending.ui_get_reward(pending.I_WQ_BOX) is True
    assert pending.actions == [('UI_UI_REWARD_LARGE',[919,160,208,368])]

    class LegacyHarness(Harness):
        def appear(self,target,threshold=None,**kwargs):
            return target is self.I_UI_REWARD

    legacy = LegacyHarness(blank)
    assert legacy.ui_reward_appear() and legacy.ui_reward_appear_click()
    assert legacy.actions == [('UI_UI_REWARD',[919,160,208,368])]
    report = {'old_title_score':old['score'],'collection':flow.actions,
              'checks':['real reward screenshot','page reward recognition','shifted title','blank and missing title',
                        'cooldown blocks box clicks','wait for popup to close','no ten-second timeout',
                        'already open popup','legacy recognition path']}
    output = ROOT/'dev_tools/local/reward-popup/checks.json'
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    print('PASS: reward collection closes before timeout; no emulator clicks sent.')
finally:
    runtime.shutdown()
