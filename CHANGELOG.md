# 更新日志

本文件记录 **回复整形**（astrbot_plugin_reply_trim）的版本变更。
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

---

## [1.4.4] - 2026-10-17

### 变更
- **太短的段会并入上一段**（跨换行也生效）
  - 之前换行是「硬边界」，模型每行都会变成独立一条消息，导致「呼...」「唔...」「也是...」这类语气词单独占一条
  - 现在长度 < `min_segment_len` 的段会用换行并入上一条，形成一个多行气泡
  - 建议 `min_segment_len` 设 5~8；设 2 时几乎没有合并效果

---

## [1.4.3] - 2026-10-17

### 新增
- 插件图标 `logo.png`（256×256）：剪刀把一条消息剪成多条气泡，对应本插件的分段功能

---

## [1.4.2] - 2026-10-16

### 变更
- **`min_text_len` 默认从 20 改为 0**（不设门槛）
  - 起因：群里机器人回复普遍只有 9~15 字，全被「短回复保护」挡掉，看起来像分段失效
  - 现在默认短回复也按标点分段；想减少碎消息再把它调大
  - 注意：**有换行的回复一直是硬分段、不受此门槛影响**

---

## [1.4.1] - 2026-10-15

### 文档
- README 移除已删除的白名单说明，补上私聊「正在输入」章节

---

## [1.4.0] - 2026-10-15

### 新增
- **私聊「正在输入」**：补发下一段之前，先通过 OneBot 扩展动作 `set_input_status` 把机器人状态设为「正在输入」，再随机等 0.7~1.2 秒 —— 对方看到的就是「正在打字」然后消息冒出来
  - 配置：`typing_enable`（默认开）、`typing_event_type`（默认 1）
  - LLOneBot 8.x 的底层实现是 `setPrivateInputStatus`，**只对私聊有效**，群聊自动跳过
  - 调用失败只记 DEBUG 日志，绝不影响正常发送

### 变更
- **移除白名单模式**：只保留黑名单（`blacklist`），配置更简单

---

## [1.3.1] - 2026-10-15

### 文档
- README / metadata 同步到 1.3.0 的最新行为（名单模式、引号保护、随机延迟、换行硬边界）

---

## [1.3.0] - 2026-10-15

### 修复
- **总开关 `enabled` 之前完全无效**：代码只检查了 trim_enable / split_enable / group_split_enable / private_split_enable / protect_code，**唯独漏了 enabled**，导致面板上关掉插件它照常分段。现在 on_decorating_result 和 after_message_sent 都会检查

### 新增
- **白名单模式** `list_mode`：blacklist（默认，黑名单里的会话不分段）/ whitelist（只有白名单里的会话分段，白名单留空 = 全部允许）
- **引号/括号内部不切段** `protect_quotes`（默认开）：避免出现「前引号在这一条、后引号在下一条」

### 说明
- 「正在输入」状态没做：aiocqhttp（QQ）适配器没有实现 send_typing，调用是空操作，加了也是死代码

---

## [1.2.2] - 2026-10-15

### 变更
- **段间间隔改为随机 0.7~1.2 秒**（每段独立取值），模拟真人打字节奏；原来的固定 1.2 秒太机械
- 配置项 `segment_delay` 拆成 `segment_delay_min` / `segment_delay_max`

---

## [1.2.1] - 2026-10-15

### 修复
- **换行不再被合并**：模型自己用换行分出的段是「硬边界」，绝不会被 min_segment_len 粘回去。之前的实现在「…… / 还笑呢 / ……尾巴都要翘到天上去咯 / ……不理你了」这种多行回复里，会把前几行粘成一句读不通的长句，还把换行整个吃掉
- min_text_len（整条太短保护）现在**只在没有换行时生效** —— 模型主动换行就说明它想分条，不该被「太短」拦下
- 段数超上限时，改用**换行拼接**溢出的段（原来是无分隔直接粘，会把词粘在一起）

---

## [1.2.0] - 2026-10-15

### 新增
- **分段符号扩充**：在「。？」基础上加入 **「！」** 和 **换行**（模型自己换行也视为分段信号）
- **群聊分段开关** `group_split_enable`（默认开）+ **私聊开关** `private_split_enable`
- **会话黑名单** `blacklist`：填群号 / 用户号 / 完整会话标识，命中的会话照常回复但**不分段**
- **短回复保护** `min_text_len`（默认 20）：整条太短就不分段，避免「嗯。好的。」被拆成两条
- **超短段合并** `min_segment_len`（默认 6）：某段太短就并进上一段，并把当时删掉的标点**补回来**
- **代码保护** `protect_code`：检测到代码块、列表、引用、表格时整条不分段

### 变更
- 默认删除符号从「。」改为「。！」（问号仍保留）

---

## [1.1.0] - 2026-10-08

### 新增
- 按「。？」分段发送：按句号分段时**删除句号**，问号**保留**
- 段间间隔与最大段数可配置

---

## [1.0.2] - 2026-10-06

### 变更
- 清理日志由 INFO 降为 DEBUG

---

## [1.0.1] - 2026-10-06

### 修复
- 关键：AstrBot 会按配置里的 plugin_set 白名单过滤插件，新插件不加进白名单则钩子不会被调用

---

## [1.0.0] - 2026-10-06

### 新增
- 首个版本：去掉机器人回复整条消息首尾多余的换行与空格，不影响消息中间内容

---

[1.4.4]: https://github.com/q1w2e3r4t5y6658/astrbot_plugin_reply_trim/releases/tag/v1.4.4
[1.4.3]: https://github.com/q1w2e3r4t5y6658/astrbot_plugin_reply_trim/releases/tag/v1.4.3
[1.4.2]: https://github.com/q1w2e3r4t5y6658/astrbot_plugin_reply_trim/releases/tag/v1.4.2
[1.4.1]: https://github.com/q1w2e3r4t5y6658/astrbot_plugin_reply_trim/releases/tag/v1.4.1
[1.4.0]: https://github.com/q1w2e3r4t5y6658/astrbot_plugin_reply_trim/releases/tag/v1.4.0
[1.3.1]: https://github.com/q1w2e3r4t5y6658/astrbot_plugin_reply_trim/releases/tag/v1.3.1
[1.3.0]: https://github.com/q1w2e3r4t5y6658/astrbot_plugin_reply_trim/releases/tag/v1.3.0
[1.2.2]: https://github.com/q1w2e3r4t5y6658/astrbot_plugin_reply_trim/releases/tag/v1.2.2
[1.2.1]: https://github.com/q1w2e3r4t5y6658/astrbot_plugin_reply_trim/releases/tag/v1.2.1
[1.2.0]: https://github.com/q1w2e3r4t5y6658/astrbot_plugin_reply_trim/releases/tag/v1.2.0
[1.1.0]: https://github.com/q1w2e3r4t5y6658/astrbot_plugin_reply_trim/releases/tag/v1.1.0
