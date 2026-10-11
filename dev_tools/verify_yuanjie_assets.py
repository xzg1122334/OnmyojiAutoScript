"""Verify skin schema, rule replacement, matching and cropped asset contents."""
import copy
import argparse
import json
import os
import pickle
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description="验证缘结之庭识别，截图只读取、不复制。")
parser.add_argument("screenshots", type=Path, nargs="+", help="1280×720 庭院截图")
parser.add_argument("--report", type=Path, help="检查报告路径，默认保存在项目 dev_tools/local")
args = parser.parse_args()
sources = [path.resolve() for path in args.screenshots]
report_path = args.report.resolve() if args.report else PROJECT_ROOT / "dev_tools/local/yuanjie-runtime-checks.json"
os.chdir(PROJECT_ROOT)
sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
from PIL import Image

from module.config.config_model import ConfigModel
from module.image.runtime import ImageRuntime
from module.server.i18n import Addition
from tasks.Component.Costume.assets import CostumeAssets
from tasks.Component.Costume.config import CostumeConfig, MainType
from tasks.Component.Costume.costume_base import CostumeBase, main_costume_model
from tasks.GameUi.assets import GameUiAssets
from tasks.Pets.assets import PetsAssets

skin = MainType.COSTUME_MAIN_18
assert CostumeConfig(costume_main_type="costume_main_18").costume_main_type == skin
assert "costume_main_18" in CostumeConfig.model_json_schema()["$defs"]["MainType"]["enum"]
assert Addition.load_additions()["zh-CN"]["costume_main_18"] == "缘结之庭"
for path in Path("config").glob("oas*.json"):
    ConfigModel(**json.loads(path.read_text(encoding="utf-8")))

required = ["I_CHECK_MAIN", "I_MAIN_GOTO_EXPLORATION", "I_MAIN_GOTO_SUMMON", "I_MAIN_GOTO_TOWN", "I_PET_HOUSE"]
rules = CostumeAssets()
host = CostumeBase()
identities = {}
for name in required:
    original = getattr(PetsAssets if name == "I_PET_HOUSE" else GameUiAssets, name)
    setattr(host, name, copy.deepcopy(original))
    identities[name] = id(getattr(host, name))
host.check_costume_main(skin)
for name in required:
    replacement = getattr(rules, main_costume_model[skin][name])
    current = getattr(host, name)
    assert id(current) == identities[name], "Rule object references must remain valid"
    assert current.file == replacement.file
    assert current.roi_front == replacement.roi_front
    assert current.roi_back == replacement.roi_back
    assert current.threshold == replacement.threshold

frames = [np.array(Image.open(path).convert("RGB")) for path in sources]
assert all(frame.shape == (720, 1280, 3) for frame in frames), "截图需要完整的 1280×720 游戏区域"
manifest = json.loads(Path("tasks/Component/Costume/main18/image.json").read_text(encoding="utf-8"))
assert len(manifest) == len(required)
for data in manifest:
    template = Image.open(Path("tasks/Component/Costume/main18") / data["imageName"])
    x, y, width, height = map(int, data["roiFront"].split(","))
    assert x >= 490 and template.size == (width, height)
    assert not template.info, "Cropped PNGs must contain no screenshot metadata"

report = []
runtime = ImageRuntime({"worker_count": 1})
try:
    for name in required:
        rule = getattr(rules, main_costume_model[skin][name])
        matches = []
        for frame in frames:
            result = runtime.match_rule(rule.to_service_payload(), image_bytes=pickle.dumps(frame))
            assert result["matched"], (name, result)
            x, y, width, height = result["roi_front"]
            expected = rule.roi_front
            assert abs(x - expected[0]) <= 20 and abs(y - expected[1]) <= 20
            assert (width, height) == tuple(expected[2:])
            matches.append(round(result["score"], 5))
        assert not runtime.match_rule(rule.to_service_payload(), image_bytes=pickle.dumps(np.zeros_like(frames[0])))["matched"]
        report.append({"rule": name, "scores": matches, "threshold": rule.threshold})
finally:
    runtime.shutdown()

report_path.parent.mkdir(parents=True, exist_ok=True)
report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
print(json.dumps(report, indent=2))
print(f"PASS: schema, translation, existing accounts, rule replacement, {len(frames) * len(required)} positive matches, 5 blank-frame rejections, and privacy-safe crops.")
