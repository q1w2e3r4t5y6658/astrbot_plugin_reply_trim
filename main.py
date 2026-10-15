"""回复整形插件：① 去掉首尾多余空白  ② 按标点分段发送。

分段目的：让一条长回复拆成几条发出，更像真人在聊天。

分段规则：
- 在 split_chars（默认 「。？！」 和换行）**之后**切段
- 段尾若是 drop_chars 里的字符（默认 「。！」）就**删掉**；「？」保留
- 其他符号（，、：～… 等）原样保留，也**不作为分段点**

保护规则（避免"分得难看"）：
- 整条太短（min_text_len）→ 不分段
- 某段太短（min_segment_len）→ 并进上一段，并把当时删掉的标点补回来
- 看起来是代码/列表（``` / - / 1. / > 等）→ 整条不分段
- 群聊、私聊各自开关；黑名单里的会话一律不分段
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.message_components import Plain
from astrbot.api.star import Context, Star, register

TRIM_CHARS = "\n\r\t \u3000"
_PENDING_KEY = "_reply_trim_pending_segments"
_DEFAULT_SPLIT_CHARS = "。？！\n"
_DEFAULT_DROP_CHARS = "。！"
_CODE_FENCES = ("```", "~~~")
_LIST_PREFIXES = ("- ", "* ", "+ ", "> ", "#", "| ", "1. ", "2. ", "3. ")


@register(
    "astrbot_plugin_reply_trim",
    "q1w2e3r4t5y6658",
    "去掉回复首尾多余空白，并按「。？！」分段发送（句号感叹号删除、问号保留）",
    "1.2.0",
    "https://github.com/q1w2e3r4t5y6658/astrbot_plugin_reply_trim",
)
class ReplyTrimPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig = None):
        super().__init__(context)
        self.config = config
        self._pending: dict[str, dict] = {}
        self._tasks: set[asyncio.Task] = set()

    # ------------------------------------------------------------------ #
    # 配置读取（容错：配置缺失时一律回退默认值）
    # ------------------------------------------------------------------ #
    def _cfg(self, key: str, default):
        try:
            if self.config is None:
                return default
            value = self.config.get(key, default)
            return default if value in (None, "") else value
        except Exception:  # noqa: BLE001
            return default

    def _cfg_bool(self, key: str, default: bool) -> bool:
        try:
            if self.config is None:
                return default
            return bool(self.config.get(key, default))
        except Exception:  # noqa: BLE001
            return default

    def _cfg_list(self, key: str) -> list:
        try:
            if self.config is None:
                return []
            value = self.config.get(key, [])
            if isinstance(value, str):
                return [x for x in value.replace(",", "\n").split("\n") if x.strip()]
            if isinstance(value, (list, tuple)):
                return list(value)
            return []
        except Exception:  # noqa: BLE001
            return []

    # ------------------------------------------------------------------ #
    # 黑名单：支持填 完整会话标识 / 群号 / 用户号
    # ------------------------------------------------------------------ #
    def _is_blacklisted(self, event: AstrMessageEvent) -> bool:
        entries = self._cfg_list("blacklist")
        if not entries:
            return False
        umo = str(getattr(event, "unified_msg_origin", "") or "").strip()
        sid = umo.split(":")[-1].strip() if umo else ""
        try:
            gid = str(event.get_group_id() or "").strip()
        except Exception:  # noqa: BLE001
            gid = ""
        for raw in entries:
            entry = str(raw).strip()
            if not entry:
                continue
            if entry == umo or (sid and entry == sid) or (gid and entry == gid):
                return True
        return False

    # ------------------------------------------------------------------ #
    # 分段算法
    # ------------------------------------------------------------------ #
    @staticmethod
    def split_text(
        text: str,
        split_chars: str,
        drop_chars: str,
        min_segment_len: int,
        max_segments: int,
    ) -> list[str]:
        """按 split_chars 切段；段尾在 drop_chars 里的字符删掉；太短的段并进上一段。"""
        raw: list[str] = []
        buf: list[str] = []
        for ch in text:
            buf.append(ch)
            if ch in split_chars:
                raw.append("".join(buf))
                buf = []
        if buf:
            raw.append("".join(buf))

        # 去尾部要删的标点，并记住它（合并时补回来，避免把话粘连）
        pieces: list[tuple[str, str]] = []
        for piece in raw:
            piece = piece.strip()
            if not piece:
                continue
            punct = ""
            if piece[-1] in drop_chars:
                punct = piece[-1]
                piece = piece[:-1].rstrip()
            if piece:
                pieces.append((piece, punct))

        # 太短的段并进上一段
        merged: list[tuple[str, str]] = []
        for ptext, punct in pieces:
            if merged and len(merged[-1][0]) < min_segment_len:
                merged[-1] = (merged[-1][0] + merged[-1][1] + ptext, punct)
            else:
                merged.append((ptext, punct))
        segments = [t for t, _ in merged]

        # 段数上限：超出的全部并进最后一段
        if max_segments and len(segments) > max_segments:
            segments = segments[: max_segments - 1] + [
                "".join(segments[max_segments - 1 :])
            ]
        return segments

    @staticmethod
    def _looks_like_code(text: str) -> bool:
        """代码块 / 列表 / 引用 / 表格 —— 分段会毁格式，整条不动。"""
        if any(fence in text for fence in _CODE_FENCES):
            return True
        for line in text.split("\n"):
            s = line.strip()
            if not s:
                continue
            if s.startswith(_LIST_PREFIXES):
                return True
            if len(s) > 2 and s[0].isdigit() and s[1:3] in (". ", "、", "．"):
                return True
        return False

    @staticmethod
    def _is_plain_model_result(result) -> bool:
        """只处理「纯文本的模型回复」；带图片/引用/@等的链一律不动。"""
        chain = getattr(result, "chain", None)
        if not isinstance(chain, list) or not chain:
            return False
        if not all(isinstance(c, Plain) for c in chain):
            return False
        for name in ("is_model_result", "is_llm_result"):
            fn = getattr(result, name, None)
            if callable(fn):
                try:
                    return bool(fn())
                except Exception:  # noqa: BLE001
                    return False
        return True

    # ------------------------------------------------------------------ #
    # Hook 1：发送前 —— 去首尾空白 + 换首段 + 登记补发
    # ------------------------------------------------------------------ #
    @filter.on_decorating_result()
    async def on_decorating_result(self, event: AstrMessageEvent) -> None:
        result = event.get_result()
        chain = getattr(result, "chain", None)
        if not chain:
            return

        # ① 首尾去空白（只动首个/末个非空文本段）
        if self._cfg_bool("trim_enable", True):
            texts = [
                c
                for c in chain
                if isinstance(getattr(c, "text", None), str)
                and c.text.strip(TRIM_CHARS)
            ]
            if texts:
                texts[0].text = texts[0].text.lstrip(TRIM_CHARS)
                texts[-1].text = texts[-1].text.rstrip(TRIM_CHARS)

        # ② 按标点分段
        if not self._cfg_bool("split_enable", True):
            return
        if self._is_blacklisted(event):
            logger.debug("[reply_trim] 命中黑名单，不分段: %s", event.unified_msg_origin)
            return

        is_group = bool(event.get_group_id())
        if is_group and not self._cfg_bool("group_split_enable", True):
            return
        if (not is_group) and not self._cfg_bool("private_split_enable", True):
            return

        if not self._is_plain_model_result(result):
            return
        text = "".join(c.text for c in chain)
        if not text.strip():
            return
        if len(text.strip()) < int(self._cfg("min_text_len", 20) or 0):
            return
        if self._cfg_bool("protect_code", True) and self._looks_like_code(text):
            logger.debug("[reply_trim] 疑似代码/列表，跳过分段")
            return

        segments = self.split_text(
            text,
            str(self._cfg("split_chars", _DEFAULT_SPLIT_CHARS)),
            str(self._cfg("drop_chars", _DEFAULT_DROP_CHARS)),
            int(self._cfg("min_segment_len", 6) or 0),
            int(self._cfg("max_segments", 6) or 0),
        )
        if len(segments) <= 1:
            return

        first, follow_up = segments[0], segments[1:]
        result.chain = [Plain(first)]
        pending_id = uuid4().hex
        self._pending[pending_id] = {
            "session": event.unified_msg_origin,
            "segments": follow_up,
        }
        event.set_extra(_PENDING_KEY, pending_id)
        logger.debug("[reply_trim] 分段 %d 段，首段=%r", len(segments), first[:30])

    # ------------------------------------------------------------------ #
    # Hook 2：首段发出后 —— 异步补发剩余段
    # ------------------------------------------------------------------ #
    @filter.after_message_sent()
    async def after_message_sent(self, event: AstrMessageEvent) -> None:
        pending_id = str(event.get_extra(_PENDING_KEY, "") or "").strip()
        if not pending_id:
            return
        pending = self._pending.pop(pending_id, None)
        if not pending or not pending.get("segments"):
            return
        task = asyncio.create_task(self._send_remaining(pending))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _send_remaining(self, pending: dict) -> None:
        session = pending.get("session")
        try:
            delay = float(self._cfg("segment_delay", 1.2) or 0)
            for seg in pending["segments"]:
                if delay > 0:
                    await asyncio.sleep(delay)
                ok = await self.context.send_message(
                    session, MessageChain([Plain(seg)])
                )
                if not ok:
                    logger.warning("[reply_trim] 补发失败，会话=%s", session)
                    return
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("[reply_trim] 补发异常: %s", exc)

    async def terminate(self) -> None:
        for task in list(self._tasks):
            if not task.done():
                task.cancel()
        self._tasks.clear()
        self._pending.clear()
