# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from time import sleep
from typing import Union

from module.atom.click import RuleClick
from module.atom.long_click import RuleLongClick
from module.atom.ocr import RuleOcr
from module.base.timer import Timer
from module.exception import GameStuckError
from tasks.base_task import BaseTask
from tasks.Component.SwitchSoul.assets import SwitchSoulAssets
from module.logger import logger


def switch_parser(switch_str: str) -> tuple:
    switch_list = switch_str.split(',')
    if len(switch_list) != 2:
        raise ValueError('Switch_str must be 2 length')
    return int(switch_list[0]), int(switch_list[1])


class SwitchSoul(BaseTask, SwitchSoulAssets):

    def run_switch_soul(self, target: tuple | list[tuple] | str):
        """
        保证在式神录的界面
        :return:
        """
        if isinstance(target, str):
            try:
                target = switch_parser(target)
            except ValueError:
                logger.error('Switch soul config error')
                return
        self.click_preset()
        self.switch_souls(target)

    def click_preset(self) -> None:
        """
        点击预设
        :return:
        """
        while 1:
            self.screenshot()
            if self.appear(self.I_SOU_SWITCH_1):
                break
            if self.appear(self.I_SOU_SWITCH_2):
                break
            if self.appear(self.I_SOU_SWITCH_3):
                break
            if self.appear(self.I_SOU_SWITCH_4):
                break
            if self.appear(self.I_SOU_TEAM_PRESENT):
                break
            if self.appear_then_click(self.I_SOUL_PRESET, interval=2):
                continue
        logger.info('Click preset in switch soul')

    def switch_soul_one(self, group: int, team: int) -> None:
        """
        设置一个队伍的预设御魂
        :param group: 只能是[1-7]
        :param team: 只能是[1-4]
        :return:
        """

        def get_group_assets(group: int) -> tuple:
            match = {
                1: tuple([self.C_SOU_GROUP_1, self.I_SOU_CHECK_GROUP_1]),
                2: tuple([self.C_SOU_GROUP_2, self.I_SOU_CHECK_GROUP_2]),
                3: tuple([self.C_SOU_GROUP_3, self.I_SOU_CHECK_GROUP_3]),
                4: tuple([self.C_SOU_GROUP_4, self.I_SOU_CHECK_GROUP_4]),
                5: tuple([self.C_SOU_GROUP_5, self.I_SOU_CHECK_GROUP_5]),
                6: tuple([self.C_SOU_GROUP_6, self.I_SOU_CHECK_GROUP_6]),
                7: tuple([self.C_SOU_GROUP_7, self.I_SOU_CHECK_GROUP_7]),
            }
            return match[group]

        def get_team_asset(team: int):
            match = {
                1: self.I_SOU_SWITCH_1,
                2: self.I_SOU_SWITCH_2,
                3: self.I_SOU_SWITCH_3,
                4: self.I_SOU_SWITCH_4,
            }
            return match[team]

        # 滑动至分组最上层(分組過多, 导致第一个分组显示不全)
        cur_text = ""
        while 1:
            self.screenshot()
            compare1 = self.O_SS_GROUP_NAME.detect_and_ocr(self.device.image)
            ocr_text = str([result.ocr_text for result in compare1])
            # 相等时 滑动到最上层
            if cur_text == ocr_text:
                break
            cur_text = ocr_text
            # 向上滑动
            self.swipe(self.S_SS_GROUP_SWIPE_UP, 1.5)
            # 等待滑动动画
            sleep(0.5)

        if group < 1 or group > 7:
            raise ValueError('Switch soul_one group must be in [1-7]')
        if team < 1 or team > 4:
            raise ValueError('Switch soul_one team must be in [1-4]')
        # 这一步是选择组
        target_click, target_check = get_group_assets(group)
        # while 1:
        #     self.screenshot()
        #     if self.click(target_click, interval=1):
        #         continue
        #     if self.appear(target_check):
        #         break
        # 2023.8.5 修改为无反馈的点击切换
        for i in range(2):
            self.click(target_click)
            sleep(0.5)
        # 点击队伍
        target_team = get_team_asset(team)
        self._apply_soul_preset(
            lambda: self.appear_then_click(target_team, interval=3),
            f'group {group} team {team}',
        )
        logger.info(f'Switch soul_one group {group} team {team}')

    def _apply_soul_preset(self, select_team, description: str) -> None:
        """确认更换御魂；两次成功点击仍无弹窗时按已装备处理。"""
        timeout = Timer(30).start()
        confirmed = False
        popup_seen = False
        closed_frames = 0
        attempts = 0
        while not timeout.reached():
            self.screenshot()
            if self.appear(self.I_SOU_SWITCH_DIALOG):
                popup_seen = True
                closed_frames = 0
                if self.appear_then_click(self.I_SOU_SWITCH_SURE, interval=0.8):
                    confirmed = True
                    logger.info(f'Confirm preset souls: {description}')
                sleep(0.2)
                continue
            if self.appear(self.I_SOU_SWITCH_SURE):
                popup_seen = True
                # 黄色按钮仍在但弹窗内容没有匹配时，不点击未知确认框。
                closed_frames = 0
                sleep(0.2)
                continue
            if self.appear_then_click(self.I_CHECK_BLOCK, interval=0.8):
                attempts = 0
                closed_frames = 0
                continue
            if confirmed or (attempts >= 2 and not popup_seen):
                closed_frames += 1
                if closed_frames >= 2:
                    if not confirmed:
                        logger.info(f'两次点击目标队伍均无确认弹窗，按御魂已装备继续: {description}')
                    return
                sleep(0.2)
                continue
            if attempts < 2 and select_team():
                attempts += 1
                sleep(1.5 if attempts == 2 else 0.8)
            else:
                sleep(0.2)
        raise GameStuckError(f'未完成预设御魂切换确认: {description}，停止本次任务')

    def switch_souls(self, target: tuple or list[tuple]) -> None:
        """
        切换御魂
        :param target: [(1, 1), (2, 2), (3, 3), (4, 4)]  或者是单独的一个元组(4, 4) 第一个是组, 第二个是队伍
        :return:
        """
        if isinstance(target, tuple):
            target = [target]
        for group, team in target:
            group = int(group)
            team = int(team)
            self.switch_soul_one(group, team)

    def exit_shikigami_records(self) -> None:
        """
        退出式神录的界面
        :return:
        """
        while 1:
            self.screenshot()
            if not self.appear(self.I_SOU_CHECK_IN):
                break
            if self.appear_then_click(self.I_RECORD_SOUL_BACK, interval=3.5):
                continue
        logger.info('Exit shikigami records')

    def run_switch_soul_by_name(self, groupName, teamName):
        """
        保证在式神录的界面
        :return:
        """
        if isinstance(groupName, str) and isinstance(teamName, str):
            self.click_preset()
            self.switch_soul_by_name(groupName, teamName)

    def switch_soul_by_name(self, groupName, teamName):
        """
        保证在式神录的界面
        :return:
        """
        logger.hr('Switch soul by name')
        # 滑动至分组最上层
        last_group_text = ''
        while 1:
            self.screenshot()
            compare1 = self.O_SS_GROUP_NAME.detect_and_ocr(self.device.image)
            now_group_text = str([result.ocr_text for result in compare1])
            if now_group_text == last_group_text:
                break
            self.swipe(self.S_SS_GROUP_SWIPE_UP, 2)
            sleep(2.5)
            last_group_text = now_group_text
        logger.info('Swipe to top of group')

        # 判断有无目标分组
        while 1:
            self.screenshot()
            # 获取当前分组名
            results = self.O_SS_GROUP_NAME.detect_and_ocr(self.device.image)
            text1 = [result.ocr_text for result in results]
            # 判断当前分组有无目标分组
            result = set(text1).intersection({groupName})
            # 有则跳出检测
            if result and len(result) > 0:
                break
            self.swipe(self.S_SS_GROUP_SWIPE_DOWN)
            sleep(1.5)
        logger.info('Swipe down to find target group')

        # 选中分组
        while 1:
            self.screenshot()
            self.O_SS_GROUP_NAME.keyword = groupName
            if self.ocr_appear_click(self.O_SS_GROUP_NAME):
                break
        logger.info(f'Select group {groupName}')

        # 滑动至阵容最上层
        last_team_text = ''
        while 1:
            self.screenshot()
            compare1 = self.O_SS_TEAM_NAME.detect_and_ocr(self.device.image)
            now_team_text = str([result.ocr_text for result in compare1])
            # 向上滑动
            if now_team_text == last_team_text:
                break
            self.swipe(self.S_SS_TEAM_SWIPE_DOWN, 1.5)
            sleep(2)
            last_team_text = now_team_text
        logger.info('Swipe to top of team')

        # 判断当前分组有无目标阵容
        while 1:
            self.screenshot()
            # 获取当前阵容名
            results = self.O_SS_TEAM_NAME.detect_and_ocr(self.device.image)
            text1 = [result.ocr_text for result in results]
            # 判断当前分组有无目标阵容
            result = set(text1).intersection({teamName})
            # 有则跳出检测
            if result and len(result) > 0:
                break
            self.swipe(self.S_SS_TEAM_SWIPE_UP, 0.3)
        logger.info('Swipe up to find target team')

        # 选中分组
        logger.info(f'Select team {teamName}')
        # 切换御魂
        self.O_SS_TEAM_NAME.keyword = teamName
        self._apply_soul_preset(
            lambda: self.ocr_appear_click_by_rule(
                self.O_SS_TEAM_NAME, self.I_SOU_CLICK_PRESENT, interval=1.5,
            ),
            f'group {groupName} team {teamName}',
        )
        logger.info(f'Switch soul_one group {groupName} team {teamName}')

    def ocr_appear_click_by_rule(self,
                                 target: RuleOcr,
                                 action: Union[RuleClick, RuleLongClick] = None,
                                 interval: float = None,
                                 duration: float = None) -> bool:
        """
        ocr识别目标，如果目标存在，则触发动作
        :param target:
        :param action:
        :param interval:
        :param duration:
        :return:
        """
        appear = self.ocr_appear(target, interval)

        if not appear:
            return False

        x1, y1 = target.coord()
        x, y = action.coord()

        self.device.click(x=x, y=y1, control_name=target.name)
        return True


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    c = Config('oas1')
    d = Device(c)
    s = SwitchSoul(c, d)

    s.click_preset()
    # s.switch_soul_one(4, 1)
    # s.switch_soul_by_name('契灵', '茨球')
    s.switch_soul_by_name('默认分组', '队伍5')
