"""
Dashboard lockup diagnostics.

Enable with environment variable DASHBOARD_DEBUG=1 (or true/yes).

Writes:
  - paper_logs/dashboard_perf.jsonl  — server-side timing per write (append)
  - web/dashboard_{mode}_health.json  — tiny sidecar next to HTML (poll without full reload)

Client (when debug HTML is generated): console timings + optional on-page debug strip.
"""
from __future__ import annotations

import json
import logging
import os
import time
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, Iterator, Optional

EASTERN = None  # lazy

_write_seq = 0


def _tz():
    global EASTERN
    if EASTERN is None:
        import pytz
        EASTERN = pytz.timezone('US/Eastern')
    return EASTERN


def dashboard_debug_enabled() -> bool:
    return os.environ.get('DASHBOARD_DEBUG', '').strip().lower() in ('1', 'true', 'yes', 'on')


def perf_log_path() -> str:
    return os.environ.get(
        'DASHBOARD_PERF_LOG',
        os.path.join('paper_logs', 'dashboard_perf.jsonl'),
    )


def health_sidecar_path(html_path: str) -> str:
    base, _ = os.path.splitext(html_path)
    return f'{base}_health.json'


def next_write_seq() -> int:
    global _write_seq
    _write_seq += 1
    return _write_seq


def append_perf_record(record: Dict[str, Any]) -> None:
    path = perf_log_path()
    os.makedirs(os.path.dirname(os.path.abspath(path)) or '.', exist_ok=True)
    record.setdefault('ts', datetime.now(_tz()).isoformat())
    try:
        with open(path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(record, default=str) + '\n')
    except OSError as e:
        logging.warning('dashboard perf log append failed: %s', e)


def write_health_sidecar(
    html_path: str,
    *,
    write_label: str,
    connected: bool,
    timings_ms: Dict[str, float],
    html_bytes: int,
    chart_points: int,
    last_data_receipt: Optional[datetime],
    write_seq: int,
    error: Optional[str] = None,
) -> None:
    path = health_sidecar_path(html_path)
    now = datetime.now(_tz())
    last_receipt_iso = None
    data_age_sec = None
    if last_data_receipt is not None:
        lr = last_data_receipt
        if lr.tzinfo is None:
            lr = _tz().localize(lr)
        last_receipt_iso = lr.isoformat()
        data_age_sec = round((now - lr).total_seconds(), 1)

    payload = {
        'write_seq': write_seq,
        'write_label': write_label,
        'connected': connected,
        'wall_ts': now.isoformat(),
        'html_bytes': html_bytes,
        'chart_points': chart_points,
        'timings_ms': timings_ms,
        'last_data_receipt': last_receipt_iso,
        'data_age_sec': data_age_sec,
        'health_name': os.path.basename(path),
        'error': error,
    }
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    tmp = path + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp, path)
    except OSError as e:
        logging.warning('dashboard health sidecar write failed: %s', e)


@contextmanager
def timed_section(timings: Dict[str, float], key: str) -> Iterator[None]:
    t0 = time.perf_counter()
    yield
    timings[key] = round((time.perf_counter() - t0) * 1000, 1)


def log_dashboard_write(
    *,
    write_label: str,
    html_path: str,
    connected: bool,
    timings_ms: Dict[str, float],
    html_bytes: int,
    chart_points: int,
    last_data_receipt: Optional[datetime],
    error: Optional[str] = None,
    write_seq: Optional[int] = None,
) -> int:
    """Record perf + health sidecar; return write sequence."""
    seq = write_seq if write_seq is not None else next_write_seq()
    total_ms = timings_ms.get('total_ms')
    if total_ms is None:
        total_ms = sum(v for k, v in timings_ms.items() if k != 'async_wait_ms')
        timings_ms = dict(timings_ms)
        timings_ms['total_ms'] = round(total_ms, 1)

    record = {
        'event': 'dashboard_write',
        'write_seq': seq,
        'write_label': write_label,
        'html_path': html_path,
        'connected': connected,
        'html_bytes': html_bytes,
        'chart_points': chart_points,
        'timings_ms': timings_ms,
        'error': error,
    }
    append_perf_record(record)

    write_health_sidecar(
        html_path,
        write_label=write_label,
        connected=connected,
        timings_ms=timings_ms,
        html_bytes=html_bytes,
        chart_points=chart_points,
        last_data_receipt=last_data_receipt,
        write_seq=seq,
        error=error,
    )

    level = logging.ERROR if error else (logging.WARNING if timings_ms.get('total_ms', 0) >= 5000 else logging.INFO)
    logging.log(
        level,
        'Dashboard write #%s [%s] html=%.1fKB chart_pts=%s total=%.0fms %s',
        seq,
        write_label or '?',
        html_bytes / 1024,
        chart_points,
        timings_ms.get('total_ms', 0),
        f'ERR={error}' if error else 'ok',
    )

    return seq


def client_debug_script_block(health_basename: str) -> str:
    """Injected into generated HTML when DASHBOARD_DEBUG is enabled."""
    return f"""
        window.__DASHBOARD_DEBUG__ = true;
        window.__DASHBOARD_HEALTH_URL__ = '{health_basename}';
        (function() {{
            var t0 = performance.now();
            var panel = document.createElement('pre');
            panel.id = 'dash-debug-panel';
            panel.style.cssText = 'position:fixed;bottom:0;right:0;max-width:420px;max-height:40vh;overflow:auto;background:#1e1e1e;color:#9cdcfe;font:11px/1.4 monospace;padding:8px 10px;z-index:99999;border-radius:8px 0 0 0;opacity:0.92';
            function log(msg) {{
                console.log('[dash-debug]', msg);
                if (!panel.parentNode) document.body.appendChild(panel);
                panel.textContent = (panel.textContent ? panel.textContent + '\\n' : '') + msg;
                var lines = panel.textContent.split('\\n');
                if (lines.length > 24) panel.textContent = lines.slice(-24).join('\\n');
            }}
            window.addEventListener('load', function() {{
                log('full reload ' + (performance.now() - t0).toFixed(0) + 'ms');
                var raw = document.getElementById('chart-payload');
                if (raw) log('chart-payload chars=' + (raw.textContent || '').length);
            }});
            function pollHealth() {{
                fetch(window.__DASHBOARD_HEALTH_URL__ + '?_=' + Date.now(), {{ cache: 'no-store' }})
                    .then(function(r) {{ return r.json(); }})
                    .then(function(h) {{
                        log('health seq=' + h.write_seq + ' ' + h.write_label + ' htmlKB=' +
                            ((h.html_bytes || 0) / 1024).toFixed(0) + ' gen=' +
                            (h.timings_ms && h.timings_ms.generate_html) + 'ms');
                    }})
                    .catch(function(e) {{ log('health fetch fail: ' + e); }});
            }}
            pollHealth();
            setInterval(pollHealth, 10000);
        }})();
    """
