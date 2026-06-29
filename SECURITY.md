# 安全策略

请通过 GitHub Security Advisory 私下报告凭据泄漏、命令注入、HTML 注入或依赖供应链问题，不要先创建公开 Issue。

- API Key 只从环境变量读取，不写入报告或运行清单。
- HTML 报告转义用户内容，并将内联 JSON 的 `<` 转换为 Unicode 转义。
- 本项目不执行下注和资金操作。
