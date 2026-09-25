# trim → compress 证明（claude-jev-gate）

- order_ok：**True**
- 输入消息数：121 → 输出：6
- chars：47819 → 1454
- 事件类型顺序：['trim', 'compress', 'trim_then_compress_pipeline']
- failures：none

## 管线

```json
[
  {
    "step": "trim",
    "order": 1,
    "chars_before": 47819,
    "chars_after": 7837,
    "messages_before": 121,
    "messages_after": 53,
    "turns_before": 40,
    "turns_kept": 6,
    "tool_msgs_dropped": 68,
    "keep_last_n_turns": 6,
    "drop_old_tool_noise": true
  },
  {
    "step": "compress",
    "order": 2,
    "chars_before": 7837,
    "chars_after": 1454,
    "messages_before": 53,
    "messages_after": 6,
    "mid_dropped": 48,
    "stub": true,
    "focus_topic": "prove"
  }
]
```
