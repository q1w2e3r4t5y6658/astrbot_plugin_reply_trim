"""去掉机器人回复「开头/结尾」多余的换行与空格。

问题：QQ 群里机器人的气泡，文字前面经常多出一块空白，由两个来源叠加：

1. LLM 自己吐的换行 —— 实测约 61% 的回复开头带 2~4 个换行；
   在人格提示词里写「不要空行」并不可靠。
2. AstrBot 加的换行 —— 开启 reply_with_mention 时，result_decorate/stage.py
   会在 @ 之后插入一个 "\n"。

AstrBot 没有内置的「清理回复首尾空白」开关（content_cleanup_rule 只属于分段回复），
所以这里用 on_decorating_result（发送消息前）钩子统一处理。

只动「整条消息的首尾」，不动中间任何内容 —— 段与段之间故意的换行不受影响。
"""

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

# 需要去掉的首尾字符：换行 / 回车 / 制表 / 半角空格 / 全角空格
TRIM_CHARS = "\n\r\t \u3000"


@register(
    "astrbot_plugin_reply_trim",
    "q1w2e3r4t5y6658",
    "去掉机器人回复开头/结尾多余的换行与空格（解决消息前面多一空行）",
    "1.0.2",
    "https://github.com/q1w2e3r4t5y6658/astrbot_plugin_reply_trim",
)
class ReplyTrimPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    @filter.on_decorating_result()
    async def trim_result(self, event: AstrMessageEvent):
        """发送前：去掉整条消息首个/末个非空文本段的首尾空白。"""
        result = event.get_result()
        chain = getattr(result, "chain", None)
        if not chain:
            return

        # 只挑「去掉空白后还有内容」的文本段，避免误伤段间的空行/分隔段
        texts = [
            comp
            for comp in chain
            if isinstance(getattr(comp, "text", None), str)
            and comp.text.strip(TRIM_CHARS)
        ]
        if not texts:
            return

        before = (texts[0].text[:12], texts[-1].text[-6:])
        texts[0].text = texts[0].text.lstrip(TRIM_CHARS)
        texts[-1].text = texts[-1].text.rstrip(TRIM_CHARS)
        after = (texts[0].text[:12], texts[-1].text[-6:])
        if before != after:
            # 默认 DEBUG，避免每条回复都刷日志；
            # 想看到效果可把本插件的日志级别调到 DEBUG（AstrBot WebUI 插件页可设）
            logger.debug(
                "[reply_trim] 已清理 %d 段 | %r -> %r",
                len(chain),
                before,
                after,
            )
