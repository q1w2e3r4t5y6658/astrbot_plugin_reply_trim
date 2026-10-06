# 回复首尾清理（astrbot_plugin_reply_trim）

去掉机器人回复**开头/结尾**多余的换行与空格。

## 解决什么问题

QQ 群里机器人气泡的文字前面经常多出一块空白，原因是两个叠在一起：

1. **LLM 自己吐的换行** —— 实测约 61% 的回复开头带 2~4 个换行；在人格提示词里写「不要空行」并不可靠。
2. **AstrBot 加的换行** —— 开启 platform_settings.reply_with_mention 时，
   result_decorate/stage.py 会在 @ 之后插入一个换行。

AstrBot 没有内置的「清理回复首尾空白」开关（content_cleanup_rule 只属于分段回复），
所以用本插件在**发送前**统一 strip 掉。

## 行为

- 只去掉**整条消息**的首尾空白；
- **不动消息中间的任何内容** —— 段与段之间故意的换行、空行都保留。

## 安装

把本目录放到 AstrBot/data/plugins/astrbot_plugin_reply_trim/，重启 AstrBot 或热重载插件即可，无需配置。

> ⚠️ **如果 AstrBot 配置里设置了 plugin_set（插件白名单，不是 ["*"]），必须把
> astrbot_plugin_reply_trim 加进该名单**，否则本插件的钩子不会被调用（静默失效）。

## 想看到清理日志？

默认只打 DEBUG 日志。在 AstrBot WebUI 的插件页把本插件日志级别调到 DEBUG 即可看到：

    [reply_trim] 已清理 1 段 | '\n\n（耳朵…' -> '（耳朵…'

## 说明

本插件只管 LLM 输出里多余的首尾空白。如果还开着 reply_with_mention，
AstrBot 会在 @ 之后自己再加一个换行（那是在本插件的钩子**之后**发生的，插件无法拦截）；
要彻底消除，请另外把 reply_with_mention 关掉（引用回复 reply_with_quote 可以保留）。

## License

MIT
