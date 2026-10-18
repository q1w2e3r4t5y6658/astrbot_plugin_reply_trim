"""回复整形插件：① 去掉首尾多余空白  ② 按标点/换行分段发送。

分段目的：让一条长回复拆成几条发出，更像真人在聊天。

分段规则：
- 「换行」是**硬边界**：模型自己换行 = 它明确要分条，这一刀绝不合并
- 标点分段符号（默认 「。？！」）在其**后面**切段
- 段尾若是 drop_chars（默认 「。！」）里的字符就**删掉**；「？」保留
- 其他符号（，、：～… 等）原样保留，也**不作为分段点**

保护规则（避免分得难看）：
- 整条太短（min_text_len，且没有换行）→ 不分段
- 某段太短（min_segment_len）→ 并到【下一段前面】，同一行不换行；只并最近的一个
- 看起来是代码/列表（``` / - / 1. / > 等）→ 整条不分段
- 引号/括号内部不切（protect_quotes）
- 群聊、私聊各自开关；黑名单里的会话不分段
- 私聊补发前会先发「正在输入」状态（typing_enable，仅私聊有效）
"""

from __future__ import annotations

import asyncio
import random
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
_QUOTE_OPENERS = "“「『（(【[《"
_QUOTE_CLOSERS = "”」』）)】]》"
_ELLIPSIS_CHARS = ".…"


def _plain_len(text: str) -> int:
    """只数"实字"：省略号和空白不算，用来判断「这句到底有多短」。"""
    return sum(1 for ch in str(text) if ch not in ".… \t\u3000")


def _group_short(segments: list[str], limit: int) -> list[str]:
    """把一串短段按「很短的那句才往后粘」分组。

    「哼...」+「不理你了」        -> 「哼...不理你了」（前面只有 1 个字，粘）
    「今天好累...」+「晚安...」+「好梦...」-> 「今天好累...」/「晚安...好梦...」
        （「今天好累」本身是完整的一句，不粘；「晚安」「好梦」都很短，粘一起）
    """
    out: list[str] = []
    group: list[str] = []
    for seg in segments:
        if group and _plain_len("".join(group)) <= limit:
            group.append(seg)
            continue
        if group:
            out.append("".join(group))
        group = [seg]
    if group:
        out.append("".join(group))
    return out


def _seg_len(seg: str) -> int:
    """算「这段算不算短」时用的长度：结尾的省略号（... / … / ......）只算 1 个字。

    「过来一点...」按 5 个字算，而不是 7 个 —— 不然明明是个短句却被当成整句，
    语气词就并不到后面那句话上了。
    """
    s = str(seg).rstrip(" \t\u3000")
    core = s.rstrip(_ELLIPSIS_CHARS)
    return len(core) + (1 if len(s) > len(core) else 0)


@register(
    "astrbot_plugin_reply_trim",
    "q1w2e3r4t5y6658",
    "去掉回复首尾多余空白，并按「。？！」与换行分段发送（句号感叹号删除、问号保留）",
    "1.4.8",
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
    # 会话名单：黑名单 / 白名单
    # ------------------------------------------------------------------ #
    @staticmethod
    def _match_entries(event: AstrMessageEvent, entries: list) -> bool:
        """填 完整会话标识 / 群号 / 用户号 都能匹配。"""
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

    def _is_blacklisted(self, event: AstrMessageEvent) -> bool:
        """命中黑名单的会话不分段（黑名单里填 群号 / 用户号 / 完整会话标识）。"""
        return self._match_entries(event, self._cfg_list("blacklist"))

    # ------------------------------------------------------------------ #
    # 分段算法
    # ------------------------------------------------------------------ #
    @classmethod
    def split_text(
        cls,
        text: str,
        split_chars: str,
        drop_chars: str,
        min_segment_len: int,
        max_segments: int,
        min_text_len: int = 0,
        protect_quotes: bool = True,
        tail_merge_len: int = 3,
    ) -> list[str]:
        """分段主流程。

        换行优先切段（模型主动换行=想分条）；太短的段（「呼...」「唔...」这种
        语气词/短句）会**并到下一段前面**，和句子在同一行，不换行。
        """
        text = str(text).replace("\r\n", "\n").replace("\r", "\n").strip()
        if not text:
            return []

        # 标点类分段符号（换行已单独处理，不算在内）
        punct_chars = "".join(ch for ch in split_chars if ch != "\n")

        # 整条既没有换行、又太短 → 不分（避免「嗯。好的。」被拆两条）
        if "\n" not in text and min_text_len and len(text) < int(min_text_len):
            return [text]

        segments: list[str] = []
        for block in text.split("\n"):
            block = block.strip()
            if not block:
                continue
            segments.extend(
                cls._split_block(
                    block, punct_chars, drop_chars, min_segment_len, protect_quotes
                )
            )

        if not segments:
            return [text]

        # 太短的段（语气词/拟声词）要并到【下一段的前面】，而不是上一段的后面：
        #   「呼...」+「真拿你没办法...」→「呼...真拿你没办法...」（同一行，不换行）✅
        # 并且**只并离长句最近的那一个**：前面还有短段就各自单独成条，
        # 免得三四个语气词全挤在同一个气泡里（QQ 里看着就是一整块）。
        if min_segment_len and len(segments) > 1:
            n = int(min_segment_len)
            merged: list[str] = []
            pending: list[str] = []
            for seg in segments:
                if _seg_len(seg) < n:
                    pending.append(seg)
                    continue
                if pending:
                    if len(pending) > 1:
                        merged.extend(_group_short(pending[:-1], tail_merge_len))
                    merged.append(pending[-1] + seg)
                    pending = []
                else:
                    merged.append(seg)
            if pending:
                # 整条末尾都是短段（没有长句可并）：按「很短的才往后粘」分组
                merged.extend(_group_short(pending, tail_merge_len))
            segments = merged

        # 段数上限：超出的用换行拼进最后一段（保留结构，不再粘连）
        if max_segments and len(segments) > max_segments:
            segments = segments[: max_segments - 1] + [
                "\n".join(segments[max_segments - 1 :])
            ]
        return segments

    @staticmethod
    def _split_block(
        block: str,
        punct_chars: str,
        drop_chars: str,
        min_segment_len: int,
        protect_quotes: bool = True,
    ) -> list[str]:
        """单个「块」（一行）内按标点切段，并做短段合并。

        protect_quotes=True 时，引号/括号内部的标点不会触发切段，
        避免出现「前引号在这一条、后引号在下一条」。
        """
        raw: list[str] = []
        buf: list[str] = []
        depth = 0
        ascii_quote = False
        for ch in block:
            buf.append(ch)
            if protect_quotes:
                if ch in _QUOTE_OPENERS:
                    depth += 1
                elif ch in _QUOTE_CLOSERS:
                    depth = max(0, depth - 1)
                elif ch == '"':
                    ascii_quote = not ascii_quote
            if ch in punct_chars and depth == 0 and not ascii_quote:
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

        # 同块内太短的段并进上一段
        merged: list[tuple[str, str]] = []
        for ptext, punct in pieces:
            if merged and len(merged[-1][0]) < min_segment_len:
                merged[-1] = (merged[-1][0] + merged[-1][1] + ptext, punct)
            else:
                merged.append((ptext, punct))
        return [t for t, _ in merged]

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
        # 总开关（之前漏了这个检查，关掉也照样生效）
        if not self._cfg_bool("enabled", True):
            return

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
        if self._cfg_bool("protect_code", True) and self._looks_like_code(text):
            logger.debug("[reply_trim] 疑似代码/列表，跳过分段")
            return

        segments = self.split_text(
            text,
            str(self._cfg("split_chars", _DEFAULT_SPLIT_CHARS)),
            str(self._cfg("drop_chars", _DEFAULT_DROP_CHARS)),
            int(self._cfg("min_segment_len", 6) or 0),
            int(self._cfg("max_segments", 6) or 0),
            int(self._cfg("min_text_len", 0) or 0),
            self._cfg_bool("protect_quotes", True),
            int(self._cfg("tail_merge_len", 3) or 0),
        )
        if len(segments) <= 1:
            return

        first, follow_up = segments[0], segments[1:]
        result.chain = [Plain(first)]
        pending_id = uuid4().hex
        self._pending[pending_id] = {
            "session": event.unified_msg_origin,
            "segments": follow_up,
            # 私聊「正在输入」要用：适配器句柄 + 对方 QQ + 是否群聊
            "bot": getattr(event, "bot", None),
            "user_id": str(event.get_sender_id() or ""),
            "is_group": is_group,
        }
        event.set_extra(_PENDING_KEY, pending_id)
        logger.debug("[reply_trim] 分段 %d 段，首段=%r", len(segments), first[:30])

    # ------------------------------------------------------------------ #
    # Hook 2：首段发出后 —— 异步补发剩余段
    # ------------------------------------------------------------------ #
    @filter.after_message_sent()
    async def after_message_sent(self, event: AstrMessageEvent) -> None:
        if not self._cfg_bool("enabled", True):
            return
        pending_id = str(event.get_extra(_PENDING_KEY, "") or "").strip()
        if not pending_id:
            return
        pending = self._pending.pop(pending_id, None)
        if not pending or not pending.get("segments"):
            return
        task = asyncio.create_task(self._send_remaining(pending))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _random_delay(self) -> float:
        """段间随机等待，模拟真人打字节奏（默认 0.7~1.2 秒）。"""
        try:
            low = float(self._cfg("segment_delay_min", 0.7) or 0)
            high = float(self._cfg("segment_delay_max", 1.2) or 0)
        except Exception:  # noqa: BLE001
            low, high = 0.7, 1.2
        if high < low:
            low, high = high, low
        if high <= 0:
            return 0.0
        if low <= 0:
            return high
        return random.uniform(low, high)

    async def _notify_typing(self, pending: dict) -> None:
        """私聊里先发一个「正在输入」状态，再等一会儿，像真人正在打字。

        走 OneBot 扩展 action set_input_status（LLOneBot/NapCat 都有）。
        底层实现是 setPrivateInputStatus，**只对私聊有效**，群聊直接跳过。
        """
        if not self._cfg_bool("typing_enable", True):
            return
        if pending.get("is_group"):
            return
        bot = pending.get("bot")
        target = str(pending.get("user_id") or "").strip()
        if bot is None or not target:
            return
        call_action = getattr(bot, "call_action", None)
        if not callable(call_action):
            return
        try:
            await call_action(
                "set_input_status",
                user_id=target,
                event_type=int(self._cfg("typing_event_type", 1) or 1),
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("[reply_trim] 设置输入状态失败: %s", exc)

    async def _send_remaining(self, pending: dict) -> None:
        session = pending.get("session")
        try:
            for seg in pending["segments"]:
                await self._notify_typing(pending)
                delay = self._random_delay()
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