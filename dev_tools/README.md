### 这三个都是窗口的管理工具

塞进仓库并不是一个很好的选择，现已移出，已链接形式提供，请查阅文档[**模拟器支持**](https://runhey.github.io/OnmyojiAutoScript-website/docs/user-manual/emulator-support)

- Spyxx (微软自家的)
- ViewWizard2(简易版本)
- ViewWizard3

### 识别回归检查

从项目根目录运行，截图只读取，不复制到仓库；报告默认保存在 Git 忽略的 dev_tools/local。

```powershell
.\toolkit\python.exe -B dev_tools/verify_yuanjie_assets.py <庭院截图路径> [其他庭院截图路径]
.\toolkit\python.exe -B dev_tools/verify_greed_confirm.py <确认弹窗截图路径>
```

贪吃鬼工具也支持弹窗局部截图，用 --offset X Y 指定它在 1280×720 原图中的左上角位置。该工具只记录预期点击，不操作模拟器。

结界选卡离线检查使用已有模板和模拟的收益文字，验证星级限制、排除六星及收益与星级的对应关系，不连接模拟器：

```powershell
.\toolkit\python.exe -B dev_tools/verify_kekkai_cards.py
```

结界工具还支持 `--panels <截图目录>`，读取局部截图及 `panels.json` 中的位置和预期结果，
使用实际 OCR 验证收益与星级能对应到同一张卡，并在该目录保存 `screenshot-checks.json`。
本机参考截图和报告位于已忽略的 `dev_tools/local/card-rules`。

结界放卡的寄养位置确认弹窗检查：

```powershell
.\toolkit\python.exe -B dev_tools/verify_activation_confirm.py <弹窗截图路径> [--offset X Y]
```

工具只记录预期点击，验证确认、取消、点击间隔及激活流程，不连接模拟器。
诊断图和报告默认保存在项目内已忽略的 `dev_tools/local/activation-confirm`。

切换预设御魂的确认弹窗检查：

```powershell
.\toolkit\python.exe -B dev_tools/verify_switch_soul_confirm.py <弹窗截图路径> [--offset X Y]
```

工具验证默认和当前式神录皮肤的确认按钮、动态式神名称、弹窗关闭、点击间隔及失败停止；只记录预期点击，不连接模拟器。报告保存在已忽略的 `dev_tools/local/switch-soul-confirm`。

结界突破使用的通用战斗退出确认检查：

```powershell
.\toolkit\python.exe -B dev_tools/verify_battle_exit_confirm.py <弹窗截图路径> [--offset X Y]
```

验证“确定”与“取消”的区分、按钮位移、点击间隔及结算前不能报告退出成功。只记录预期点击，不连接模拟器；报告保存在已忽略的 `dev_tools/local/battle-exit-confirm`。

个人突破“再次挑战”和“刷新”的共用确认检查：

```powershell
.\toolkit\python.exe -B dev_tools/verify_raid_retry_confirm.py <弹窗截图路径> [--offset X Y]
```

工具验证确定按钮、再战弹窗恢复、今日不再提示及刷新确认，只记录预期点击，不连接模拟器。报告保存在已忽略的 `dev_tools/local/raid-retry-confirm`。

战后“邀请队友继续战斗”的确认检查：

```powershell
.\toolkit\python.exe -B dev_tools/verify_invite_confirm.py <未勾选截图路径> <已勾选截图路径> [--offset X Y] [--checked-offset X Y]
```

验证确定按钮、默认邀请两种真实截图状态及八岐大蛇队长的奖励处理，防止弹窗期间随机点击。已勾选测试必须使用真实截图，不能把待测模板拼入测试图。也验证勾选状态未识别时最多等待五秒，再继续确认本次邀请。只记录预期点击，不连接模拟器；报告放在已忽略的 `dev_tools/local/invite-confirm`。

“获得奖励”弹窗识别和领取收尾检查：

```powershell
.\toolkit\python.exe -B dev_tools/verify_reward_popup.py <奖励截图路径> [--offset X Y] [--negative 其他弹窗截图路径]
```

验证当前大字标题、悬赏领取、点击间隔、弹窗关闭及旧版标题分支。只记录预期点击，不连接模拟器；报告保存在已忽略的 `dev_tools/local/reward-popup`。

契灵式盘数量上限提醒的勾选与确认检查：

```powershell
.\toolkit\python.exe -B dev_tools/verify_bondling_confirm.py <已勾选式盘弹窗截图> --unchecked-reference <真实棕色未勾选框截图> [--offset X Y]
```

验证已勾选状态直接确认、未勾选状态先打勾、点击冷却、弹窗优先于挑战，以及未启动时不能误报契灵数量 500。未勾选参考需为 1280×720、勾选框位置相同的真实截图；工具只替换局部勾选框构造状态夹具，不使用待测模板构造正例。报告放在已忽略的 `dev_tools/local/bondling-confirm`。
