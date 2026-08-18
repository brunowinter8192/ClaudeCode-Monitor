# INFRASTRUCTURE
import os
import re
import subprocess
import time

from ..constants import (
    RESET, GREEN, YELLOW, RED, DIM, ORANGE,
    INPUT_POLL_INTERVAL, SEARCH_MATCH_BG, SEARCH_CURRENT_BG,
)
from ..utils import format_timestamp, compute_header_rule_len, highlight_query_in_line
from ..input.click_handler import (
    setup_keyboard_input, restore_terminal, read_keypress, wait_for_input,
    enable_mouse, disable_mouse, read_mouse_event, copy_to_clipboard,
)
from .status import all_statuses, get_anomalies, PRESET_NAMES, _fetch_collections
from .errors import errors_today, errors_today_by_server
# From pane_error_log.py: shared exception-safe pane-error sink
from ..pane_error_log import log_pane_error
# From search_bar.py: shared search-bar mechanics (state, key/mouse handling, drag-select) --
# rollout sub-milestone 7, retrofitting the gpu pane onto the proxy pane's reference
# implementation. HIGHLIGHT-ONLY here (per the approved decision) -- no scroll/viewport exists
# in this pane at all (grepped: pane_height is accepted by _render_pane but never read), so
# there is no jump-to-match; n/N still cycles current_idx (which on-screen match gets
# SEARCH_CURRENT_BG vs SEARCH_MATCH_BG, and the N/M counter) with zero scroll call.
from .. import search_bar

GPU_POLL_INTERVAL         = 2.0   # seconds between server data refreshes
COLLECTIONS_POLL_INTERVAL = 30.0  # seconds between RAG collection count refreshes
TOGGLE_TIMEOUT            = 120   # seconds before [starting…]/[stopping…] label expires
IDLE_TIMEOUT              = int(os.getenv("RAG_SERVER_IDLE_TIMEOUT", "3600"))
_ANSI_RE          = re.compile(r'\x1b\[[0-9;]*[mKHJABCDEFGsuTXP]')

_toggle_state: dict = {}   # preset name or 'port-{N}' → ('starting'|'stopping', float ts)
_button_regions: dict = {} # (start_col, end_col, phys_row) → (action, target_str); phys_row shifted by _GPU_SEARCH_BAR_LINES since 2026-08-18

_GPU_SEARCH_BAR_LINES = 1  # fixed-height search bar row; the rule+[refresh] header (below it) shifts down by exactly this
_GPU_SEARCH_BAR_LABEL = 'search: '

# Search state -- permanent row-1 search bar. .matches holds 0-based indices into _render_pane's
# OWN (unshifted) lines list -- no click-interactivity concept for matches here (only buttons
# are clickable), so no coupling to physical row numbers at all.
_gpu_search: search_bar.SearchState = search_bar.SearchState()

# ORCHESTRATOR

# GPU pane event loop — 2s tick, keyboard toggle 1/2/3, r=refresh
def run_gpu_loop() -> None:
    last_output = None
    last_data_refresh = 0.0
    last_collections_refresh = 0.0
    force_refresh = False
    presets: list = []
    arbitrary: list = []
    anomalies: list = []
    today_errors: list = []
    error_counts: dict = {}
    collections: list = []

    setup_keyboard_input()
    enable_mouse()
    try:
        while True:
            try:
                input_changed = False

                while True:
                    char = read_keypress()
                    if char is None:
                        break
                    if char == '\033':
                        event = read_mouse_event(char)
                        if event is not None and event[0] != -1:
                            button, col, row = event
                            if button == 0:
                                if row == 1:  # search bar row -- focuses; also anchors a potential drag-select
                                    if search_bar.handle_search_mouse_press(_gpu_search, col, _GPU_SEARCH_BAR_LABEL):
                                        input_changed = True
                                else:
                                    # Click elsewhere ([refresh]/toggle buttons or unmapped) clears
                                    # any lingering drag-selection highlight
                                    if _gpu_search.sel_anchor is not None:
                                        input_changed = True
                                    search_bar.clear_selection(_gpu_search)
                                    for (sc, ec, er), (action, target) in list(_button_regions.items()):
                                        if row == er and sc <= col <= ec:
                                            if action == 'refresh':
                                                force_refresh = True
                                                input_changed = True
                                            elif target not in _toggle_state:
                                                _fire_button(action, target)
                                                input_changed = True
                                            break
                            elif button == 32 and _gpu_search.dragging:  # motion with left button held (0+32), row-1 drag active
                                if search_bar.handle_search_mouse_motion(_gpu_search, col, _GPU_SEARCH_BAR_LABEL):
                                    input_changed = True
                        elif event is not None:
                            # (-1,-1,-1) release sentinel -- no-op unless a row-1 drag was active
                            if search_bar.handle_search_mouse_release(_gpu_search, copy_to_clipboard):
                                input_changed = True
                        elif _gpu_search.focused:  # bare ESC -> cancel search
                            if search_bar.handle_search_cancel(_gpu_search):
                                input_changed = True
                    elif _gpu_search.focused:
                        on_commit = lambda state: _gpu_search_on_commit(
                            state, presets, arbitrary, anomalies, today_errors, error_counts, collections)
                        if search_bar.handle_search_input(_gpu_search, char, on_commit=on_commit):
                            input_changed = True
                    elif char == '/':
                        _gpu_search.focused = True
                        input_changed = True
                    elif char in ('n', 'N'):
                        if _jump_gpu_search_match(forward=(char == 'n')):
                            input_changed = True
                    elif char.isdigit() and char != '0':
                        idx = int(char) - 1
                        if idx < len(PRESET_NAMES):
                            name = PRESET_NAMES[idx]
                            if name not in _toggle_state:
                                _toggle_server(idx, presets)
                                input_changed = True
                    elif char in ('r', 'R'):
                        force_refresh = True
                        input_changed = True

                now = time.time()
                if force_refresh or now - last_data_refresh >= GPU_POLL_INTERVAL:
                    presets, arbitrary = all_statuses()
                    anomalies = get_anomalies()
                    today_errors = errors_today()
                    error_counts = errors_today_by_server()
                    last_data_refresh = now
                    input_changed = True
                    _expire_toggle_states(presets, arbitrary)

                if force_refresh or now - last_collections_refresh >= COLLECTIONS_POLL_INTERVAL:
                    collections = _fetch_collections()
                    last_collections_refresh = now
                    input_changed = True

                force_refresh = False

                if input_changed:
                    try:
                        term = os.get_terminal_size()
                        pane_width = term.columns
                        pane_height = term.lines - 1
                    except OSError:
                        pane_width = 100
                        pane_height = 30
                    current_match_line = (
                        _gpu_search.matches[_gpu_search.current_idx]
                        if _gpu_search.matches and _gpu_search.current_idx < len(_gpu_search.matches)
                        else None
                    )
                    body = _render_pane(pane_width, pane_height,
                                        presets, arbitrary, anomalies,
                                        today_errors, error_counts, collections,
                                        search_query=_gpu_search.query,
                                        search_match_line_set=_gpu_search.match_set,
                                        search_current_line=current_match_line)
                    # _render_pane's own _button_regions rows are relative to ITS OWN top (row 1
                    # = its own first line) -- shift by _GPU_SEARCH_BAR_LINES since the search
                    # bar now owns physical row 1 (mirrors worker_proxy_pane's identical
                    # rebuild-then-shift pattern; _render_pane itself stays unshifted/reusable,
                    # unaffected by callers that don't prepend a search bar -- see
                    # dev/click_ui/p4_gpu_news_button_probe.py, which calls it directly).
                    shifted = {(sc, ec, er + _GPU_SEARCH_BAR_LINES): v for (sc, ec, er), v in _button_regions.items()}
                    _button_regions.clear()
                    _button_regions.update(shifted)
                    output = _render_gpu_search_bar(pane_width) + '\n' + body
                    if output != last_output:
                        print("\033[2J\033[3J\033[H", end='', flush=True)
                        print(output, end='', flush=True)
                        last_output = output

                wait_for_input(INPUT_POLL_INTERVAL)
            except Exception:
                log_pane_error('gpu')
                wait_for_input(INPUT_POLL_INTERVAL)
    finally:
        disable_mouse()
        restore_terminal()

# FUNCTIONS

# Toggle preset server by 0-based index; context-dependent stop/restart/start
def _toggle_server(idx: int, presets: list) -> None:
    name = PRESET_NAMES[idx]
    s = next((p for p in presets if p['name'] == name), None)
    if s is None:
        return
    devnull = subprocess.DEVNULL
    if s['running'] and s['healthy']:
        subprocess.Popen(["rag-cli", "server", "stop", name],
                         stdout=devnull, stderr=devnull)
        _toggle_state[name] = ('stopping', time.time())
    elif s['running']:
        subprocess.Popen(["rag-cli", "server", "restart", name],
                         stdout=devnull, stderr=devnull)
        _toggle_state[name] = ('starting', time.time())
    else:
        subprocess.Popen(["rag-cli", "server", "start", name],
                         stdout=devnull, stderr=devnull)
        _toggle_state[name] = ('starting', time.time())


# Remove _toggle_state entries when action completed or timed out
def _expire_toggle_states(presets: list, arbitrary: list) -> None:
    now = time.time()
    for key in list(_toggle_state.keys()):
        action, ts = _toggle_state[key]
        if now - ts > TOGGLE_TIMEOUT:
            del _toggle_state[key]
            continue
        if key.startswith('port-'):
            try:
                port_n = int(key[5:])
            except ValueError:
                continue
            s = next((x for x in arbitrary if x['port'] == port_n), None)
        else:
            s = next((x for x in presets if x['name'] == key), None)
        if s is None:
            continue
        if action == 'starting' and s['running'] and s['healthy']:
            del _toggle_state[key]
        elif action == 'stopping' and not s['running']:
            del _toggle_state[key]


# Return colored status badge
def _badge(s: dict) -> str:
    if not s['running']:
        return f"{RED}○{RESET}"
    return f"{GREEN}●{RESET}" if s['healthy'] else f"{YELLOW}◐{RESET}"


# Return status label; shows [starting…]/[stopping…] while toggle in flight
def _status_text(s: dict) -> str:
    key = s['name'] if s['kind'] == 'preset' else f'port-{s["port"]}'
    if key in _toggle_state:
        action, _ = _toggle_state[key]
        return f"[{action}\u2026]"
    return "running" if s['running'] else "stopped"


# Remove ANSI escape codes to calculate visual display width
def _strip_ansi(s: str) -> str:
    return _ANSI_RE.sub('', s)


# on_commit callback for search_bar.handle_search_input (fires on Enter): calls _render_pane
# ONCE without search kwargs (plain baseline) to get the exact same lines the real render would
# show, splits on '\n', ANSI-strips each, and collects the 0-based indices whose text contains
# query, case-insensitive -- "exactly what's rendered" without needing a separate matcher
# function, since this pane has no collapse/expand state to force-open (everything is always
# fully shown). Always re-runs (not gated on query-unchanged), matching every other pane's
# convention.
def _gpu_search_on_commit(state: search_bar.SearchState, presets: list, arbitrary: list,
                           anomalies: list, today_errors: list, error_counts: dict,
                           collections: list) -> None:
    if not state.query:
        state.matches = []
        state.match_set = set()
        return
    try:
        pane_width = os.get_terminal_size().columns
    except OSError:
        pane_width = 100
    plain = _render_pane(pane_width, 0, presets, arbitrary, anomalies, today_errors, error_counts, collections)
    q = state.query.lower()
    matches = [i for i, line in enumerate(plain.split('\n')) if q in _strip_ansi(line).lower()]
    state.matches = matches
    state.match_set = set(matches)
    state.current_idx = 0

# Cycle the current match (updating which occurrence gets SEARCH_CURRENT_BG vs SEARCH_MATCH_BG,
# and the N/M counter) -- NO jump/scroll call, per the approved decision: this pane has no
# scroll/viewport infra at all (pane_height is accepted by _render_pane but never read), so
# there is nothing to jump to -- everything is either on screen (highlighted) or it isn't.
# Returns True if a cycle happened (False when there are no matches, e.g. before the first Enter).
def _jump_gpu_search_match(forward: bool) -> bool:
    if not _gpu_search.matches:
        return False
    _gpu_search.current_idx = (_gpu_search.current_idx + (1 if forward else -1)) % len(_gpu_search.matches)
    return True

# Render the always-visible search bar (row 1). Thin wrapper binding this pane's own label.
def _render_gpu_search_bar(pane_width: int) -> str:
    return search_bar.render_search_bar(_gpu_search, pane_width, label=_GPU_SEARCH_BAR_LABEL)


# Return countdown string from status dict; "" if stopped, "?" if state file missing
def _format_countdown(s: dict) -> str:
    if not s['running']:
        return ""
    if s.get('idle_state_missing'):
        return "?"
    idle_seconds = s.get('idle_seconds')
    if idle_seconds is None:
        return ""
    remaining = int(IDLE_TIMEOUT - idle_seconds)
    if remaining <= 0:
        return "stopping\u2026"
    if remaining >= 3600:
        h = remaining // 3600
        m = (remaining % 3600) // 60
        sec = remaining % 60
        return f"stops in {h}:{m:02d}:{sec:02d}"
    m = remaining // 60
    sec = remaining % 60
    return f"stops in {m:02d}:{sec:02d}"


# Return context-dependent button label; arbitrary rows always [stop]
def _button_label(s: dict) -> str:
    if s['kind'] == 'arbitrary':
        return '[stop]'
    if not s['running']:
        return '[start]'
    return '[stop]' if s['healthy'] else '[restart]'


# Fire-and-forget action via rag-cli; target is preset name or 'port-{N}' for arbitrary
def _fire_button(action: str, target: str) -> None:
    devnull = subprocess.DEVNULL
    if target.startswith('port-'):
        port = target[5:]
        subprocess.Popen(["rag-cli", "server", "stop", "--port", port],
                         stdout=devnull, stderr=devnull)
    else:
        subprocess.Popen(["rag-cli", "server", action, target],
                         stdout=devnull, stderr=devnull)
    _toggle_state[target] = ('starting' if action in ('start', 'restart') else 'stopping',
                              time.time())


# Build full pane content; updates _button_regions as side effect. (2026-08-18, rollout
# sub-milestone 7) search_query/search_match_line_set/search_current_line -- HIGHLIGHT-ONLY,
# applied as a SINGLE post-loop pass right before the final join (touches none of the per-section
# construction logic above it). No sentinel needed: this pane has no per-row background/zebra/
# hover loop at all (lines are plain ANSI-colored text, always the terminal's own default
# background) -- utils.highlight_query_in_line's default restore_bg='\\033[49m' is directly
# correct, same simple case as core/monitor_display.py's main pane. _button_regions' OWN row
# numbering stays relative to THIS function's own top (row 1 = its own first line) -- callers
# that prepend a search bar shift it externally (see gpu_pane.run_gpu_loop), so this function
# stays a reusable, standalone, directly-testable unit (dev/click_ui/p4_gpu_news_button_probe.py
# calls it directly and needed zero changes).
def _render_pane(pane_width: int, pane_height: int,
                 presets: list, arbitrary: list, anomalies: list,
                 today_errors: list, error_counts: dict,
                 collections: list, search_query: str = '',
                 search_match_line_set: set | None = None,
                 search_current_line: int | None = None) -> str:
    _button_regions.clear()
    lines: list[str] = []

    header_prefix = '  GPU Servers'
    refresh_btn = '[refresh]'
    rule_len, show_refresh = compute_header_rule_len(header_prefix, refresh_btn, 64, pane_width)
    header_text = f"{DIM}{'═' * rule_len}{RESET}{header_prefix}"
    if show_refresh:
        header_vis_len = len(_strip_ansi(header_text))
        header_pad = pane_width - header_vis_len - len(refresh_btn)
        _button_regions[(header_vis_len + header_pad + 1, header_vis_len + header_pad + len(refresh_btn), 1)] = ('refresh', 'refresh')
        lines.append(header_text + ' ' * header_pad + refresh_btn)
    else:
        lines.append(header_text)

    # Preset block — always 3 rows, digit-keyed [1]/[2]/[3]
    for i, s in enumerate(presets):
        badge      = _badge(s)
        status_txt = _status_text(s)
        countdown  = _format_countdown(s)
        port_str   = f"port {s['port']}"         if s['port']               else ""
        pid_str    = f"pid {s['pid']}"           if s['pid']                else ""
        rss_str    = f"RSS {s['rss_mb']} MB"     if s['rss_mb'] is not None else ""
        model_str  = (s.get('model_name') or '')[:20]
        err_n      = error_counts.get(s['name'], 0)
        err_col    = GREEN if err_n == 0 else ORANGE
        err_str    = f"errors today: {err_col}{err_n}{RESET}"
        btn        = _button_label(s)
        action     = ('stop' if s['healthy'] else 'restart') if s['running'] else 'start'
        content    = (f"[{i+1}] {s['name']:<16} {badge} {status_txt:<15} "
                      f"{countdown:<16} {port_str:<14} {pid_str:<13} "
                      f"{rss_str:<14} {model_str:<20} {err_str}")
        vis_len    = len(_strip_ansi(content))
        pad        = max(1, pane_width - vis_len - len(btn))
        phys_row   = len(lines) + 1
        _button_regions[(vis_len + pad + 1, vis_len + pad + len(btn), phys_row)] = (action, s['name'])
        lines.append(content + ' ' * pad + btn)

    # Arbitrary block — dynamic, sorted by port, no digit keys
    if arbitrary:
        lines.append("")
        lines.append(f"{DIM}{'─' * min(pane_width, 40)}  arbitrary{RESET}")
        for s in arbitrary:
            badge      = _badge(s)
            status_txt = _status_text(s)
            countdown  = _format_countdown(s)
            port_str   = f"port {s['port']}"         if s['port']               else ""
            pid_str    = f"pid {s['pid']}"           if s['pid']                else ""
            rss_str    = f"RSS {s['rss_mb']} MB"     if s['rss_mb'] is not None else ""
            model_str  = (s.get('model_name') or '')[:20]
            err_n      = error_counts.get(s['name'], 0)
            err_col    = GREEN if err_n == 0 else ORANGE
            err_str    = f"errors today: {err_col}{err_n}{RESET}"
            btn        = '[stop]'
            target     = f'port-{s["port"]}'
            content    = (f"    {s['name']:<12} {badge} {status_txt:<15} "
                          f"{countdown:<16} {port_str:<14} {pid_str:<13} "
                          f"{rss_str:<14} {model_str:<20} {err_str}")
            vis_len    = len(_strip_ansi(content))
            pad        = max(1, pane_width - vis_len - len(btn))
            phys_row   = len(lines) + 1
            _button_regions[(vis_len + pad + 1, vis_len + pad + len(btn), phys_row)] = ('stop', target)
            lines.append(content + ' ' * pad + btn)

    lines.append("")
    lines.append(f"{DIM}{'═' * min(pane_width, 64)}{RESET}  RAG Collections")
    if collections:
        for c in collections:
            lines.append(f"  {c['collection']:<32} {c['chunks']} chunks")
    else:
        lines.append(f"  {DIM}(none indexed){RESET}")

    lines.append("")
    lines.append(f"{DIM}{'═' * min(pane_width, 64)}{RESET}  Errors today (last 10)")

    recent = list(reversed(today_errors))[:10]
    if recent:
        for e in recent:
            ts_str  = format_timestamp(e.get("ts", ""))
            server  = e.get("server", "?")
            code    = e.get("code", "?")
            msg     = e.get("msg", "")
            prefix_plain = f"{ts_str}  {server:<12} {code:<14} "
            max_msg = max(0, pane_width - len(prefix_plain) - 1)
            if len(msg) > max_msg:
                msg = msg[:max_msg] + "\u2026"
            lines.append(f"{ts_str}  {server:<12} {ORANGE}{code:<14}{RESET} {msg}")
    else:
        lines.append(f"  {DIM}(no errors today){RESET}")

    if anomalies:
        n = len(anomalies)
        lines.append(
            f"  {YELLOW}\u26a0 {n} anomal{'y' if n == 1 else 'ies'} "
            f"(see logs/gpu_pane.log){RESET}"
        )

    if search_query and search_match_line_set:
        for idx in search_match_line_set:
            if 0 <= idx < len(lines):
                marker = SEARCH_CURRENT_BG if idx == search_current_line else SEARCH_MATCH_BG
                lines[idx] = highlight_query_in_line(lines[idx], search_query, marker)

    return "\n".join(lines)
