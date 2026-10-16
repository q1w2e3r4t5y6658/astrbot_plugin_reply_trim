# 回复整形（astrbot_plugin_reply_trim）

两个功能：**去掉回复首尾多余的空白/换行**，以及**按标点把长回复分段发出**。

## 一、首尾去空白

QQ 群里机器人气泡的文字前面经常多出一块空白，原因是两个叠在一起：

1. **LLM 自己吐的换行** —— 实测约 61% 的回复开头带 2~4 个换行；在人格提示词里写「不要空行」并不可靠
2. **AstrBot 加的换行** —— 开启 platform_settings.reply_with_mention 时，result_decorate/stage.py 会在 @ 之后插入一个换行

AstrBot 没有内置的「清理回复首尾空白」开关（content_cleanup_rule 只属于分段回复），本插件在**发送前**统一 strip 掉。

## 二、按标点分段发送

把一条长回复拆成几条依次发出（间隔 0.7~1.2 秒随机），更像真人在聊天。

**换行是硬边界**：模型自己换行 = 它明确要分条，这一刀绝不合并。

| 规则 | 默认 | 说明 |
|---|---|---|
| 分段符号 split_chars | 。？！ 加换行 | 在这些字符**后面**切段；换行按行硬切，不做合并 |
| 删除符号 drop_chars | 。！ | 分段后把句号、感叹号**删掉**；**问号保留** |
| 其他标点 | — | ，、：～…… 等**原样保留，也不作为分段点** |

### 保护规则（避免分得难看）

| 配置 | 默认 | 作用 |
|---|---|---|
| min_text_len | 0 | 整条太短就不分段；**默认 0 = 不设门槛**，调大可以减少碎消息 |
| min_segment_len | 6 | 某段太短就并进上一段，并把当时删掉的标点**补回来** |
| max_segments | 6 | 最多分几段，超出的并进最后一段 |
| protect_code | true | 检测到代码块、列表、引用、表格时整条不分段 |
| protect_quotes | true | **引号、括号内部不切段**，避免「前引号在这一条、后引号在下一条」 |
| segment_delay_min / max | 0.7 / 1.2 | 段间**随机**等待区间（秒），模拟真人打字节奏 |

### 群聊 / 私聊 / 黑名单

- group_split_enable（默认开）：群聊里也分段
- private_split_enable（默认开）：私聊里也分段
- blacklist：**不分段**的会话，填 **群号 / 用户号 / 完整会话标识**（如 `aiocqhttp:GroupMessage:12345`），命中的会话照常回复、只是不分段

### 私聊「正在输入」

补发下一段之前，先通过 OneBot 扩展动作 `set_input_status` 把机器人设为「正在输入」，**再**随机等 0.7~1.2 秒 —— 对方看到的是「正在打字」然后消息冒出来：

- typing_enable（默认开）、typing_event_type（默认 1）
- **只对私聊有效**：LLOneBot 8.x 的底层实现是 `setPrivateInputStatus`（`src/onebot11/action/llbot/user/SetInputStatus.ts`），群聊没有这个能力，插件自动跳过
- 调用失败只记 DEBUG 日志，绝不影响正常发送

## 只对纯文本的模型回复生效

带图片、@、引用等组件的回复链**整条不动**，不会把消息结构拆坏。

## 安装

把本目录放到 AstrBot/data/plugins/astrbot_plugin_reply_trim/，重启 AstrBot 或热重载插件。

> ⚠️ **如果 AstrBot 配置里设置了 plugin_set（插件白名单，不是 ["*"]），必须把
> astrbot_plugin_reply_trim 加进该名单**，否则本插件的钩子不会被调用（静默失效）。

## 看日志

默认只打 DEBUG 日志。在 AstrBot WebUI 的插件页把本插件日志级别调到 DEBUG 即可看到分段过程。

## License

MIT
