# 更新日志

本文件记录 **回复首尾清理**（astrbot_plugin_reply_trim）的版本变更。
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)，格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

> AstrBot 插件管理页会读取本文件展示更新日志（支持 CHANGELOG.md / changelog.md / CHANGELOG / changelog）。

---

## [1.0.2] - 2026-10-06

### 变更
- 清理日志由 INFO 降为 **DEBUG**，避免每条回复都刷一行日志（需要排查时可在 WebUI 把本插件日志级别调到 DEBUG）

---

## [1.0.1] - 2026-10-06

### 修复
- ⚠️ **关键：AstrBot 会按配置里的 plugin_set 白名单过滤插件**（waking_check/stage.py）。
  新装的插件若未加入该白名单，on_decorating_result 钩子**根本不会被调用**，本插件会静默失效。

### 新增
- 加上清理日志，便于确认钩子是否真的被调用

---

## [1.0.0] - 2026-10-06

### 新增
- 首个版本：用 on_decorating_result（发送消息前）钩子，去掉机器人回复**整条消息**首尾多余的换行与空格
- 只动首尾，**不影响消息中间**任何内容（段与段之间故意的换行保留）

---

[1.0.2]: https://github.com/q1w2e3r4t5y6658/astrbot_plugin_reply_trim/releases/tag/v1.0.2
[1.0.1]: https://github.com/q1w2e3r4t5y6658/astrbot_plugin_reply_trim/releases/tag/v1.0.1
[1.0.0]: https://github.com/q1w2e3r4t5y6658/astrbot_plugin_reply_trim/releases/tag/v1.0.0
