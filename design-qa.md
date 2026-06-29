# Design QA

- source visual truth: `/tmp/world-cup-ai-hub-screens/index.png`、`/tmp/world-cup-ai-hub-screens/pre-match-prediction.png`
- implementation screenshots: `/tmp/football-ui-desktop.png`、`/tmp/football-ui-mobile.png`、`/tmp/football-ui-markets.png`
- comparison evidence: `/tmp/football-ui-comparison.png`、`/tmp/football-ui-detail-comparison.png`
- viewport: desktop `1440 × 1024`；mobile `390 × 844`
- state: 深色主题；第一场展开；五类玩法页签选中

**Findings**

- 无可执行的 P0/P1/P2 问题。实现与参考保持一致的深色赛事控制台语言、荧光绿主色、球场网格、紧凑导航、高密度数据卡片和分段概率条，同时保留了竞彩足球特有的信息架构。
- 字体与层级：系统无衬线字体在中文和数字上清晰，标题、正文、辅助信息和概率数字层级明确；桌面与手机均未发生裁切或不可读换行。
- 间距与布局：桌面首屏、焦点卡、赛单和详情使用稳定的 14–20px 节奏；移动端改为单列，概率列未被隐藏。
- 颜色与状态：主色、警告色、客胜色和低对比辅助文字语义一致；正文与背景对比度可读。
- 图像与资产：该报告不依赖球队图片或外部网络资产；背景纹理与数据图表均由报告自身渲染，离线打开保持完整。
- 文案与内容：EV、Edge 已替换为“长期期望”“概率优势”，并明确区分“官方 SP”与“模型推演”。

**Focused region comparison**

- 首屏对照确认导航、滚动赛程、球场纹理、主标题、核心数字与右侧焦点面板的层级和密度与参考一致。
- 详情对照确认赛果概率、让球概率、比分、总进球和半全场信息均使用一致的卡片与状态语言；玩法页签可交互。

**Patches made since previous QA pass**

- 删除原页面的大面积空白首屏，改为紧凑的今日概览和核心场次。
- 修复移动端隐藏平局、客胜概率的规则。
- 新增四个详情页签与五类竞彩玩法。
- 增加官方玩法覆盖状态和无 SP 时的明确降级文案。
- 将专业缩写改为中文解释，并增加顶部“怎么看”区块。

**Implementation Checklist**

- [x] 桌面 1440 × 1024 视觉检查
- [x] 手机 390 × 844 视觉检查
- [x] 筛选、展开全部、玩法页签与打印按钮检查
- [x] 自包含 HTML 与离线资源检查
- [x] 参考图与实现图同屏对照

**Follow-up Polish**

- P3：未来如接入可合法再分发的球队徽标，可在比赛卡中增加真实队徽；当前纯文本队名是有意的离线与版权约束。

final result: passed
