# P3 — strip_interrupt_marker probe run (2026-07-30T16:44:38.158818+00:00)

**Result: 28/28 checks passed**

| Check | Result |
|---|---|
| marker text captured in removed_chunks | PASS |
| block count unchanged (3) | PASS |
| marker block emptied to '.' | PASS |
| preceding tool_result block byte-identical | PASS |
| following wake-up block byte-identical | PASS |
| str shape -> '.' | PASS |
| list[text] shape -> block text '.' | PASS |
| list[tool_result+str] shape -> content '.' | PASS |
| list[tool_result+list] shape -> inner text '.' | PASS |
| longer top-level text block untouched | PASS |
| longer tool_result content untouched | PASS |
| longer top-level str content untouched | PASS |
| assistant-role message never touched (role gate) | PASS |
| user message changed | PASS |
| mod name is stripped_interrupt_marker | PASS |
| removed chunk recorded for user message | PASS |
| marker block in user message emptied | PASS |
| ops recorded for block 1 | PASS |
| 'IM' registered in RULES | PASS |
| RULES['IM'] full name is stripped_interrupt_marker | PASS |
| attribute_chunk(marker) resolves to 'IM' | PASS |
| 'IM' -> named function in _MSG_CODE_TO_FN (not missing) | PASS |
| mod fired: stripped_interrupt_marker | PASS |
| marker block emptied in modified payload | PASS |
| stripped_msg_removed carries the raw marker text | PASS |
| fn_map['msg.0.1'] present | PASS |
| fn_map['msg.0.1'] == '_apply_interrupt_marker_strip' (not 'unknown') | PASS |
| messages_delta carries the stripped marker text | PASS |
