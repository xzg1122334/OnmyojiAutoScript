"""Regression checks for the live stuck dialog, without clicking the emulator."""
import copy
import argparse
import json
import os
import pickle
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description="离线验证贪吃鬼确认弹窗，不操作模拟器。")
parser.add_argument("screenshot", type=Path, help="1280×720 截图或弹窗局部截图")
parser.add_argument("--offset", type=int, nargs=2, default=(0, 0), metavar=("X", "Y"), help="局部截图左上角在原图中的位置")
parser.add_argument("--report", type=Path, help="检查报告路径，默认保存在项目 dev_tools/local")
args = parser.parse_args()
source = args.screenshot.resolve()
report_path = args.report.resolve() if args.report else PROJECT_ROOT / "dev_tools/local/greed-confirm-checks.json"
os.chdir(PROJECT_ROOT)
sys.path.insert(0, str(PROJECT_ROOT))

import cv2
import numpy as np
from PIL import Image

from module.image.runtime import ImageRuntime
from tasks.GlobalGame.assets import GlobalGameAssets
from tasks.SoulsTidy.assets import SoulsTidyAssets
from tasks.SoulsTidy.script_task import ScriptTask

image = np.array(Image.open(source).convert("RGB"))
x, y = args.offset
height, width = image.shape[:2]
assert 0 <= x and 0 <= y and x + width <= 1280 and y + height <= 720
frame = np.zeros((720, 1280, 3), dtype=np.uint8)
frame[y:y + height, x:x + width] = image

runtime = ImageRuntime({"worker_count": 1})

class Harness(SoulsTidyAssets):
    def __init__(self, image, cooldown=False):
        self.image = image
        self.cooldown = cooldown
        self.clicked = []
        self.I_ST_FEED_CONFIRM = copy.deepcopy(self.I_ST_FEED_CONFIRM)
        self.I_ST_FEED_CONFIRM_DIALOG = copy.deepcopy(self.I_ST_FEED_CONFIRM_DIALOG)

    def appear(self, target):
        result = runtime.match_rule(target.to_service_payload(), image_bytes=pickle.dumps(self.image))
        return target._apply_match_result(result)

    def appear_then_click(self, target, interval=None):
        assert target is self.I_ST_FEED_CONFIRM
        assert interval == 0.5
        if self.cooldown or not self.appear(target):
            return False
        self.clicked.append(target.roi_front.copy())
        return True

try:
    old = runtime.match_rule(GlobalGameAssets.I_UI_CONFIRM.to_service_payload(), image_bytes=pickle.dumps(frame))
    scores = {}
    for name in ("I_ST_FEED_CONFIRM_DIALOG", "I_ST_FEED_CONFIRM"):
        rule = getattr(SoulsTidyAssets, name)
        result = runtime.match_rule(rule.to_service_payload(), image_bytes=pickle.dumps(frame))
        assert result["matched"], (name, result)
        assert result["score"] > 0.95
        scores[name] = round(result["score"], 5)
        image = Image.open(rule.file)
        assert image.size != (1280, 720) and not image.info

    live = Harness(frame)
    assert ScriptTask.handle_greed_feed_confirm(live)
    assert len(live.clicked) == 1
    x, y, width, height = live.clicked[0]
    assert 650 <= x <= 680 and 395 <= y <= 425
    assert (width, height) == (178, 64)

    # A matching yellow button alone must not confirm a different dialog.
    unrelated = frame.copy()
    unrelated[245:360, 420:875] = 0
    wrong_dialog = Harness(unrelated)
    assert not ScriptTask.handle_greed_feed_confirm(wrong_dialog)
    assert not wrong_dialog.clicked

    # When the click interval has not elapsed, the popup still blocks actions
    # against the underlying feeding/closing interface.
    throttled = Harness(frame, cooldown=True)
    assert ScriptTask.handle_greed_feed_confirm(throttled)
    assert not throttled.clicked

    # A red cancel button cannot be selected as the yellow confirm button.
    no_confirm = frame.copy()
    no_confirm[385:490, 630:860] = 0
    no_confirm[408:472, 665:843] = frame[408:472, 437:615]
    cancel_only = Harness(no_confirm)
    assert ScriptTask.handle_greed_feed_confirm(cancel_only)
    assert not cancel_only.clicked

    report = {"old_generic_confirm_score": round(old["score"], 5), "new_scores": scores, "checks": 4}
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    print("PASS: supplied dialog recognized, correct confirm targeted, unrelated dialogs rejected, cooldown blocks underlying actions, cancel rejected. No emulator clicks sent.")
finally:
    runtime.shutdown()
