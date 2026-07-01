# Design QA

- 发布候选：`0.3.0`。
- 视觉方向：现代足球比赛日 App 暗色模式，近黑背景、品牌蓝主操作、绿色状态、黄色降级提示。
- 真实报告：`/private/tmp/football-real-v030-2026-07-01/report_2026-07-01.html`。
- 桌面截图：`/tmp/football-v030-desktop-review.png`（`1280 × 900`）。
- 手机截图：`/tmp/football-v030-mobile-top-review.png`（`375 × 812`）。

## Visual Findings

- Hero、赛程卡和 Match Center 共享统一的色板、描边、圆角、字号与信息密度，没有脱离足球比赛日语境。
- 国家队使用随包分发的真实国旗；俱乐部或未知球队继续使用稳定的字母徽标，不依赖网络资源。
- 主胜、平局、客胜、价值与风险状态保持固定颜色语义，关键数字在暗色背景上对比清晰。
- 官方数据、模型推演、缺失输入和降级状态在视觉上可区分，没有把模型结论伪装成官方数据。
- 未发现可执行的 P0 / P1 / P2 视觉问题。

## Data Truth QA

- 真实报告包含 `3` 场官方赛单、`3/3` 官方 SP 覆盖和 `6` 条可核验赛前证据。
- 概率拆分为统计模型、官方 SP 去水、外部市场和最终模型四层，并显示来源与更新时间。
- 国家队 Elo / xG 或同一时点外部市场缺失时明确标记中性先验与降级状态。
- 关键输入不足时强制低置信，并暂停输出价值信号；本次报告高置信 `0`、价值信号 `0`。

## Interaction QA

- 首场默认展开，赛单筛选、展开全部、打印入口和详情页签均保留。
- 「赔率价值」页签切换后 `aria-selected="true"`，且只有一个对应内容面板可见。
- 页签继续支持方向键、Home 和 End 键操作。
- 桌面与移动端浏览器控制台警告 / 错误均为 `0`。

## Responsive QA

- 桌面 `1280 × 900`：`scrollWidth === clientWidth === 1280`，无页面级横向溢出。
- 手机 `375 × 812`：`scrollWidth === clientWidth === 375`，无页面级横向溢出。
- 手机导航宽 `357px`、内容宽 `403px`；数据来源带宽 `355px`、内容宽 `747px`，均只在自身容器内滚动。
- 手机首屏国旗、主客队、VS、开赛时间与数据状态完整显示。

## Packaging QA

- npm 包版本 `0.3.0`，共 `169` 个条目，包含全部 `119` 面国旗。
- Wheel 安装后版本为 `0.3.0`，国旗资源、Demo 报告和离线校验均通过。
- 从实际 npm tarball 冷启动安装成功，Codex / Claude Skill 与运行快照均完整。

## Automated Checks

- [x] 32 项 Python 单元 / 契约测试
- [x] Ruff 全仓检查
- [x] Python 字节码编译
- [x] Wheel 构建与隔离导入
- [x] npm tarball 安装验证
- [x] 内联 JSON / JavaScript / 离线资源校验
- [x] `git diff --check`
- [x] 桌面 / 移动端浏览器验收

final result: passed
