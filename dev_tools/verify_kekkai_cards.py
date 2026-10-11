"""Offline realm-card regression checks; never connects to or clicks the emulator."""
import os
import argparse
import copy
import json
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

parser = argparse.ArgumentParser(description='离线检查结界放卡和蹭卡，不连接模拟器。')
parser.add_argument('--panels', type=Path, help='包含 panels.json 和列表局部截图的目录，用于真实截图检查')
args = parser.parse_args()

import numpy as np
from PIL import Image
from pydantic import ValidationError

from module.image.runtime import ImageRuntime
from module.ocr.rpc import OcrRuntime
from tasks.KekkaiActivation.assets import KekkaiActivationAssets
from tasks.KekkaiActivation.config import ActivationConfig, CardType
from tasks.KekkaiActivation.script_task import ScriptTask
from tasks.KekkaiUtilize.config import UtilizeConfig, UtilizeRule, SelectFriendList
from tasks.KekkaiUtilize.script_task import ScriptTask as UtilizeTask


class Harness(ScriptTask):
    def __init__(self, con, frame, results):
        self.config = SimpleNamespace(kekkai_activation=SimpleNamespace(activation_config=con))
        self.swipes = []
        self.device = SimpleNamespace(image=frame, image_frame_id=None, swipe_adb=lambda *a, **k: self.swipes.append(a))
        self.O_CHECK_CARD_NUMBER = SimpleNamespace(roi=(305, 153, 107, 481), detect_and_ocr=lambda image: results)

    def screenshot(self):
        pass


def ocr_result(value, resource, center_y):
    y = center_y - 153
    return SimpleNamespace(ocr_text=f'{resource}+{value}', box=[[0, y-10], [90, y-10], [90, y+10], [0, y+10]])


runtime = ImageRuntime({'worker_count': 1})


class Client:
    def match_all_any_many(self, rules_data, image, **kwargs):
        return runtime.match_all_any_many(rules_data, image_bytes=pickle.dumps(image), threshold=kwargs.get('threshold'), nms_threshold=kwargs.get('nms_threshold', .3))


try:
    for low, high in [(5, 3), (2, 5), (3, 7)]:
        try:
            ActivationConfig(min_card_star=low, max_card_star=high)
        except ValidationError:
            pass
        else:
            raise AssertionError('Invalid star range accepted')

    with patch('module.atom.image_grid.get_image_client', return_value=Client()), patch('tasks.KekkaiActivation.script_task.time.sleep'):
        # Real template matcher + fake OCR exercise all available resource-star templates.
        for kind, resource in [(CardType.TAIKO, '勾玉'), (CardType.FISH, '体力')]:
            for star in (3, 4, 5, 6):
                con = ActivationConfig(card_type=kind, min_taiko_num=0, min_fish_num=0)
                frame = np.zeros((720, 1280, 3), np.uint8)
                harness = Harness(con, frame, [])
                target = harness.order_targets.images[6-star]
                crop = np.array(Image.open(target.file).convert('RGB'))
                h, w = crop.shape[:2]
                bottom = 300
                frame[bottom-h:bottom, 193:193+w] = crop
                harness.O_CHECK_CARD_NUMBER.detect_and_ocr = lambda image: [ocr_result(20, resource, bottom-45)]
                selected = harness.check_card_num()
                assert (selected is not None) == (star in (3, 4, 5)), (kind, star)
                print(f'PASS: {kind.value} {star} stars: {"allowed" if selected else "excluded"}')

        # Highest yield must not bypass the six-star exclusion, or pair with another row.
        con = ActivationConfig(min_taiko_num=0)
        harness = Harness(con, np.zeros((720, 1280, 3), np.uint8), [ocr_result(30, '勾玉', 245), ocr_result(8, '勾玉', 395)])
        matches = [(harness.I_CARDS_KAIKO_6, .99, (193, 227, 89, 73)), (harness.I_CARDS_KAIKO_3, .99, (193, 384, 89, 66))]
        with patch('module.atom.image_grid.ImageGrid.find_everyone', return_value=matches):
            selected = harness.check_card_num()
            assert selected is not None and selected.roi_front[1] == 385

        # Conflicting out-of-range matches at the same star row are rejected.
        conflict = [(harness.I_CARDS_KAIKO_5, .99, (193, 242, 88, 58)), (harness.I_CARDS_KAIKO_6, .95, (193, 227, 89, 73))]
        assert not harness._allowed_card_rows(conflict)
        assert not harness._allowed_card_rows(None)

        # Custom star range and minimum yield still apply; wrong resources never qualify.
        con.min_card_star = 4
        assert not harness._allowed_card_rows([matches[1]])
        con.min_card_star = 3
        con.min_taiko_num = 10
        with patch('module.atom.image_grid.ImageGrid.find_everyone', return_value=[matches[1]]):
            assert harness.check_card_num() is None
            harness.O_CHECK_CARD_NUMBER.detect_and_ocr = lambda image: [ocr_result(100, '体力', 395)]
            assert harness.check_card_num() is None
        con.min_taiko_num = 0

        # A type switch must refresh its scan targets rather than reuse cached Taiko templates.
        con.card_type = CardType.FISH
        assert all('FISH' in target.name for target in harness.order_targets.images)
        con.card_type = CardType.TAIKO

        # Existing unused card must never reach an activation click without validation.
        harness.goto_page = lambda *args: None
        harness.check_card_status = lambda: True
        harness.check_card_effect = lambda: False
        scheduled = []
        harness.set_next_run = lambda *args, **kwargs: scheduled.append(kwargs)
        harness.appear_then_click = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('Unexpected activation click'))
        assert harness.run_activation(con) is False and len(scheduled) == 1
        harness.check_card_effect = lambda: True
        from datetime import timedelta
        harness.ocr_time = lambda: timedelta(hours=1)
        assert harness.run_activation(con) is False and len(scheduled) == 2

    utilize = SimpleNamespace(config=SimpleNamespace(kekkai_utilize=SimpleNamespace(utilize_config=UtilizeConfig(utilize_rule=UtilizeRule.TAIKO))))
    for name in ('I_U_TAIKO_6', 'I_U_TAIKO_5', 'I_U_TAIKO_4', 'I_U_TAIKO_3'):
        setattr(utilize, name, getattr(UtilizeTask, name))
    targets = UtilizeTask.order_targets.__get__(utilize, UtilizeTask).images
    assert [target.name for target in targets] == ['UTILIZE_U_TAIKO_6', 'UTILIZE_U_TAIKO_5', 'UTILIZE_U_TAIKO_4', 'UTILIZE_U_TAIKO_3']

    class BorrowHarness(UtilizeTask):
        def __init__(self):
            self.config = utilize.config
            self.device = SimpleNamespace(image=None, image_frame_id=None)
            self.clicked = []
            self.values = iter([('太鼓', 67), ('太鼓', 67)])
            self.matches = [(self.I_U_TAIKO_5, .99, (500, 200, 80, 30)),
                            (self.I_U_TAIKO_6, .99, (500, 350, 80, 30))]
            self.__dict__['order_targets'] = SimpleNamespace(find_everyone=lambda *a, **k: self.matches)

        def screenshot(self):
            pass

        def click(self, target):
            self.clicked.append(tuple(target.roi_front))

        def check_card_num(self):
            return next(self.values)

        def appear(self, target):
            return True

        def _reset_utilize_friend_list(self, friend):
            pass

    with patch('tasks.KekkaiUtilize.script_task.time.sleep'):
        borrow = BorrowHarness()
        borrow._current_select_best()
        assert borrow.utilize_best_taiko_star == 6 and borrow.jade_max_num == 67
        borrow.clicked.clear()
        borrow.values = iter([('太鼓', 67)])
        assert borrow._locate_recorded_resource_card('太鼓', 67)
        assert borrow.clicked == [(500, 350, 80, 30)]

        # Three-star fallback must compare all cards and relocate the highest yield.
        borrow = BorrowHarness()
        borrow.matches = [(borrow.I_U_TAIKO_3, .99, (500, 200, 80, 30)),
                          (borrow.I_U_TAIKO_3, .99, (500, 350, 80, 30))]
        borrow.values = iter([('太鼓', 42), ('太鼓', 49)])
        borrow._current_select_best()
        assert borrow.utilize_best_taiko_star == 3 and borrow.jade_max_num == 49
        assert borrow.utilize_found_eligible_card
        borrow.clicked.clear()
        borrow.values = iter([('太鼓', 42), ('太鼓', 49)])
        assert borrow._locate_recorded_resource_card('太鼓', 49)
        assert borrow.clicked == [(500, 200, 80, 30), (500, 350, 80, 30)]
        borrow = BorrowHarness()
        borrow.matches = [(borrow.I_U_TAIKO_3, .99, (500, 200, 80, 30)),
                          (borrow.I_U_TAIKO_3, .99, (500, 350, 80, 30))]
        borrow.values = iter([('太鼓', 42), ('太鼓', 49), ('太鼓', 42), ('太鼓', 49)])
        assert borrow._select_optimal_resource_card(SelectFriendList.SAME_SERVER) is True
        assert borrow.clicked[-1] == (500, 350, 80, 30)

        # A four-star card wins over a three-star card even when yields are tied.
        borrow = BorrowHarness()
        borrow.matches = [(borrow.I_U_TAIKO_3, .99, (500, 200, 80, 30)),
                          (borrow.I_U_TAIKO_4, .99, (500, 350, 80, 30))]
        borrow.values = iter([('太鼓', 50), ('太鼓', 50)])
        borrow._current_select_best()
        assert borrow.utilize_best_taiko_star == 4 and borrow.jade_max_num == 50

    if args.panels:
        panels_dir = args.panels.resolve()
        cases = json.loads((panels_dir / 'panels.json').read_text(encoding='utf-8'))
        ocr_runtime = OcrRuntime({'worker_count': 1})
        report = []

        class OcrClient:
            def detect_and_ocr(self, image, **kwargs):
                return [SimpleNamespace(box=np.array(item['box']), ocr_text=item['ocr_text'], score=item['score'])
                        for item in ocr_runtime.detect_and_ocr(pickle.dumps(image), **kwargs)]

        try:
            with patch('module.atom.image_grid.get_image_client', return_value=Client()), \
                    patch('module.ocr.base_ocr.get_ocr_model', return_value=OcrClient()), \
                    patch('tasks.KekkaiActivation.script_task.time.sleep'):
                for case in cases:
                    crop = np.array(Image.open(panels_dir / case['file']).convert('RGB'))
                    x, y = case['offset']
                    height, width = crop.shape[:2]
                    assert x >= 0 and y >= 0 and x + width <= 1280 and y + height <= 720
                    frame = np.zeros((720, 1280, 3), np.uint8)
                    frame[y:y+height, x:x+width] = crop
                    con = ActivationConfig(card_type=case['type'], min_taiko_num=0, min_fish_num=0)
                    harness = Harness(con, frame, [])
                    harness.O_CHECK_CARD_NUMBER = copy.deepcopy(KekkaiActivationAssets.O_CHECK_CARD_NUMBER)
                    matches = harness.order_targets.find_everyone(frame)
                    rows = harness._allowed_card_rows(matches)
                    assert [star for _, star in rows] == case['allowed_stars'], (case['file'], rows)
                    results = harness.O_CHECK_CARD_NUMBER.detect_and_ocr(frame)
                    selected = harness.check_card_num()
                    assert selected is not None and not harness.swipes, case['file']
                    selected_texts = [item.ocr_text for item in results
                                      if abs(harness.O_CHECK_CARD_NUMBER.roi[1] + item.box[0][1] - selected.roi_front[1]) < 2]
                    import re
                    assert any(int(re.findall(r'\d+', text)[0]) == case['selected_yield'] for text in selected_texts if re.findall(r'\d+', text)), (case['file'], selected_texts)
                    report.append({'file': case['file'], 'allowed_stars': [star for _, star in rows],
                                   'selected_text': selected_texts, 'click_roi': list(selected.roi_front)})
                    print(f"PASS: screenshot {case['file']}, allowed stars {case['allowed_stars']}, selected yield {case['selected_yield']}")
        finally:
            ocr_runtime.shutdown()
        (panels_dir / 'screenshot-checks.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print('PASS: mixed stars, conflicting matches, unknown stars, existing unused card, configuration validation, and Taiko-only borrowing.')
finally:
    runtime.shutdown()
