# Real tmux round-trip — Escape key via _send_escape_key

Run: 2026-07-30T10:50:11.221985+00:00

Session: `monitor-cc-escape-probe-aa100f76`

`tmux has-session` before send: **True**

Exact command sent by `_send_escape_key`: `tmux send-keys -t monitor-cc-escape-probe-aa100f76 Escape`

`_send_escape_key` return value: **True**

## Pane capture BEFORE Escape

```
(empty)
```

## Pane capture AFTER Escape

```
GOT_BYTE:'\x1b'
```

## Result

Escape byte (`\x1b`) arrived at the reader process: **True**

