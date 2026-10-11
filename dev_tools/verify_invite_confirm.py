"""Offline post-battle teammate-invitation checks; never connects to a device."""
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
parser = argparse.ArgumentParser(description='离线验证战后邀请队友确认，不操作模拟器。')
parser.add_argument('screenshot', type=Path)
parser.add_argument('checked_screenshot', type=Path)
parser.add_argument('--offset', nargs=2, type=int, default=(0,0), metavar=('X','Y'))
parser.add_argument('--checked-offset', nargs=2, type=int, default=(0,0), metavar=('X','Y'))
args = parser.parse_args()
os.chdir(ROOT)
sys.path.insert(0,str(ROOT))
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

import numpy as np
from PIL import Image
from module.image.runtime import ImageRuntime
from tasks.Component.GeneralBattle.general_battle import BattleAction
from tasks.Orochi.config import UserStatus
from tasks.Orochi.script_task import ScriptTask

def load_frame(path, offset):
    crop = np.array(Image.open(path).convert('RGB'))
    x,y = offset
    h,w = crop.shape[:2]
    assert 0 <= x and 0 <= y and x+w <= 1280 and y+h <= 720
    result = np.zeros((720,1280,3),dtype=np.uint8)
    result[y:y+h,x:x+w] = crop
    return result


frame = load_frame(args.screenshot, args.offset)
checked = load_frame(args.checked_screenshot, args.checked_offset)
blank = np.zeros_like(frame)
no_checkbox = frame.copy()
no_checkbox[330:395,525:605] = frame[335,530]
runtime = ImageRuntime({'worker_count':1})


class Harness(ScriptTask):
    def __init__(self, initial, frames=(), default=True, cooldown=()):
        self.image = initial
        self.frames = frames
        self.step = -1
        self.cooldown = cooldown
        self.clicked = []
        self.config = SimpleNamespace(orochi=SimpleNamespace(
            orochi_config=SimpleNamespace(user_status=UserStatus.LEADER),
            invite_config=SimpleNamespace(default_invite=default)))
        for name in ('I_GI_SURE','I_I_NO_DEFAULT','I_I_DEFAULT'):
            setattr(self,name,copy.deepcopy(getattr(self,name)))

    def screenshot(self):
        self.step += 1
        assert self.step < len(self.frames), 'Invite flow did not finish'
        self.image = self.frames[self.step]

    def appear(self,target,**kwargs):
        result = runtime.match_rule(target.to_service_payload(),image_bytes=pickle.dumps(self.image))
        return target._apply_match_result(result)

    def appear_then_click(self,target,interval=None):
        assert target in (self.I_GI_SURE,self.I_I_NO_DEFAULT) and interval == 1
        if self.step in self.cooldown or not self.appear(target):
            return False
        self.clicked.append((target.name,list(target.roi_front)))
        return True

    def is_in_room(self,*args):
        return not self.image.any()

    def click(self,*args,**kwargs):
        raise AssertionError('Reward handler fell through to random clicks during invitation')


try:
    positive = Harness(frame)
    assert positive.appear(positive.I_GI_SURE)
    assert positive.appear(positive.I_I_NO_DEFAULT)
    assert not positive.appear(positive.I_I_DEFAULT)
    selected = Harness(checked)
    assert selected.appear(selected.I_I_DEFAULT) and not selected.appear(selected.I_I_NO_DEFAULT)
    for name in ('I_GI_SURE','I_I_NO_DEFAULT','I_I_DEFAULT'):
        assert not Image.open(getattr(positive,name).file).info

    shifted = np.zeros_like(frame)
    shifted[10:,12:] = frame[:-10,:-12]
    moved = Harness(shifted)
    assert moved.appear(moved.I_GI_SURE) and moved.appear(moved.I_I_NO_DEFAULT)
    assert tuple(moved.I_GI_SURE.roi_front) == (677,418,177,63)
    cancel = frame.copy()
    cancel[385:500,630:885] = 0
    cancel[408:471,665:842] = frame[408:471,437:614]
    assert not Harness(cancel).appear(Harness(cancel).I_GI_SURE)
    assert Harness(blank).check_and_invite() is False

    paths = []
    cases = [
        (frame,[frame,frame,checked,checked,checked,blank],True,(0,3),['GI_I_NO_DEFAULT','GI_GI_SURE']),
        (frame,[frame,frame,blank],False,(0,),['GI_GI_SURE']),
        (checked,[checked,checked,checked,blank],True,(1,),['GI_GI_SURE']),
        (no_checkbox,[no_checkbox,no_checkbox,blank],True,(0,),['GI_GI_SURE']),
    ]
    for initial,frames,default,cooldown,expected in cases:
        flow = Harness(initial,frames,default,cooldown)
        assert flow._handle_reward(SimpleNamespace(),SimpleNamespace()) == BattleAction.CONTINUE
        assert [a[0] for a in flow.clicked] == expected, flow.clicked
        assert flow.clicked[-1][1] == [665,408,177,63]
        assert flow.step == len(frames)-1
        paths.append(flow.clicked)

    class BoundedDefaultWait:
        def __init__(self, limit):
            assert limit == 5
            self.calls = 0

        def start(self):
            return self

        def reached(self):
            self.calls += 1
            return self.calls >= 3

    fallback = Harness(frame,[frame,no_checkbox,no_checkbox,no_checkbox,blank])
    with patch('tasks.Component.GeneralInvite.general_invite.Timer',BoundedDefaultWait):
        assert fallback._handle_reward(SimpleNamespace(),SimpleNamespace()) == BattleAction.CONTINUE
    assert [a[0] for a in fallback.clicked] == ['GI_I_NO_DEFAULT','GI_GI_SURE']
    assert fallback.step == 4
    paths.append(fallback.clicked)
    report = {'predicted_click':[665,408,177,63],'paths':paths,
              'checks':['button and both real screenshot checkbox states','shifted popup','red cancel and blank',
                        'Orochi leader reward hook blocks random clicks','default on and off',
                        'already checked','failure popup without checkbox','click cooldown',
                        'unknown checkbox state waits at most five seconds']}
    output = ROOT/'dev_tools/local/invite-confirm/checks.json'
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    print('PASS: invitation confirmation; no emulator clicks sent.')
finally:
    runtime.shutdown()
