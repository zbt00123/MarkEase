# -*- coding: utf-8 -*-
"""
MarkEase logging system (v2.1.2)

Design goals
------------
- Only errors / crashes are written to disk. Normal operation stays silent.
- Recent INFO events are kept in an in-memory ring buffer; when an error is
  recorded, the whole buffer is attached as ``recent_events`` so the log
  contains the "before / after" context of the failure.
- Output format: JSON Lines (one JSON object per line). Every key and value is
  written in English so the file can be uploaded to an AI for diagnosis.
- Log directory resolution order:
    1. <directory of MarkEase.exe>/logs           (frozen build)
    2. <project_root>/logs                        (development)
    3. %LOCALAPPDATA%\\MarkEase\\logs             (Windows fallback)
    4. ~/.markease/logs                           (cross-platform fallback)
- Fatal interpreter crashes (segfault, stack overflow, ...) are also captured
  by ``faulthandler`` into ``logs/fatal_crash.log``.
- Size-based rotation: each ``markease.log`` is rotated at 5 MB, up to 3
  backups (``markease.log.1`` ... ``markease.log.3``).

Public API
----------
- setup_logging(version, build_tag) -> Path | None
- record_event(event, message=None, level='INFO', **context)   # memory only
- log_error(event, message=None, exception=None, **context)
- log_critical(event, message=None, exception=None, **context)
- get_log_dir() -> Path | None
- get_log_file() -> Path | None
"""

import os
import sys
import json
import time
import threading
import traceback
import faulthandler
from collections import deque
from datetime import datetime, timezone
from pathlib import Path


# ============================================================
#  Configuration
# ============================================================
_RECENT_MAX = 300                      # ring buffer size (in memory)
_LOG_MAX_BYTES = 5 * 1024 * 1024       # 5 MB per file
_LOG_BACKUP_COUNT = 3


# ============================================================
#  Global state
# ============================================================
_initialized = False
_log_dir = None                        # type: Path | None
_log_file = None                       # type: Path | None
_log_lock = threading.Lock()
_recent = deque(maxlen=_RECENT_MAX)
_recent_lock = threading.Lock()
_faulthandler_file = None

_app_context = {
    'name': 'MarkEase',
    'version': '0.0.0',
    'build_tag': '',
    'platform': sys.platform,
}


# ============================================================
#  Helpers
# ============================================================
def _now_iso():
    try:
        return datetime.now(timezone.utc).strftime(
            '%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
    except Exception:
        try:
            return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        except Exception:
            return ''


def _platform_label():
    try:
        if sys.platform == 'win32':
            return 'Windows'
        if sys.platform == 'darwin':
            return 'macOS'
        return 'Linux'
    except Exception:
        return 'Unknown'


def _make_record(level, event, message=None, exception=None, context=None):
    """Build the base JSON record."""
    rec = {
        'timestamp': _now_iso(),
        'level': level,
        'event': event,
        'app': _app_context.get('name', 'MarkEase'),
        'version': _app_context.get('version', '0.0.0'),
        'build_tag': _app_context.get('build_tag', ''),
        'platform': _platform_label(),
        'python_version': sys.version.split()[0],
        'process_id': os.getpid(),
        'thread_name': threading.current_thread().name,
    }
    if message is not None:
        rec['message'] = str(message)
    if exception is not None:
        try:
            rec['exception'] = {
                'type': type(exception).__name__,
                'message': str(exception),
                'traceback': ''.join(traceback.format_exception(
                    type(exception), exception, exception.__traceback__)),
            }
        except Exception as e:
            rec['exception'] = {
                'type': 'Exception',
                'message': 'failed to format exception: %s' % e,
                'traceback': '',
            }
    if context:
        rec['context'] = context
    return rec


def _rotate_if_needed():
    """Rotate markease.log when it exceeds _LOG_MAX_BYTES."""
    try:
        if _log_file is None or not _log_file.exists():
            return
        try:
            size = _log_file.stat().st_size
        except Exception:
            return
        if size < _LOG_MAX_BYTES:
            return

        # Shift existing backups: .2 -> .3, .1 -> .2
        for i in range(_LOG_BACKUP_COUNT - 1, 0, -1):
            src = _log_file.with_name(_log_file.name + '.%d' % i)
            dst = _log_file.with_name(_log_file.name + '.%d' % (i + 1))
            if src.exists():
                try:
                    if dst.exists():
                        dst.unlink()
                    src.rename(dst)
                except Exception:
                    pass

        # Current -> .1
        first_backup = _log_file.with_name(_log_file.name + '.1')
        try:
            if first_backup.exists():
                first_backup.unlink()
        except Exception:
            pass
        try:
            _log_file.rename(first_backup)
        except Exception:
            pass
    except Exception:
        pass


def _write_record(rec):
    """Serialize one record to disk. Never raises."""
    if _log_file is None:
        return
    try:
        line = json.dumps(rec, ensure_ascii=False, default=str)
    except Exception:
        try:
            line = json.dumps({
                'timestamp': _now_iso(),
                'level': 'ERROR',
                'event': 'log_serialize_failure',
                'message': 'failed to serialize log record',
            })
        except Exception:
            return

    try:
        with _log_lock:
            try:
                _rotate_if_needed()
            except Exception:
                pass
            with open(_log_file, 'a', encoding='utf-8') as f:
                f.write(line)
                f.write('\n')
                f.flush()
    except Exception:
        pass


# ============================================================
#  Public API
# ============================================================
def record_event(event, message=None, level='INFO', **context):
    """
    Store an event in the in-memory ring buffer.
    Never written to disk on its own; only surfaced when an error is logged
    afterwards (as ``recent_events``).
    """
    try:
        rec = _make_record(level, event, message, None, context or None)
        with _recent_lock:
            _recent.append(rec)
    except Exception:
        pass


def log_error(event, message=None, exception=None, **context):
    """
    Write an ERROR record to disk, including a snapshot of the in-memory
    ring buffer as ``recent_events``.
    """
    try:
        rec = _make_record('ERROR', event, message, exception,
                           context or None)
        try:
            with _recent_lock:
                recent_snapshot = list(_recent)
            if recent_snapshot:
                rec['recent_events'] = recent_snapshot
        except Exception:
            pass
        _write_record(rec)
        return rec
    except Exception:
        return None


def log_critical(event, message=None, exception=None, **context):
    """
    Write a CRITICAL record, flush stdout/stderr, and return the record.
    Used for uncaught exceptions and watchdog timeouts.
    """
    try:
        rec = _make_record('CRITICAL', event, message, exception,
                           context or None)
        try:
            with _recent_lock:
                recent_snapshot = list(_recent)
            if recent_snapshot:
                rec['recent_events'] = recent_snapshot
        except Exception:
            pass
        _write_record(rec)
        try:
            sys.stdout.flush()
        except Exception:
            pass
        try:
            sys.stderr.flush()
        except Exception:
            pass
        return rec
    except Exception:
        return None


def get_log_dir():
    return _log_dir


def get_log_file():
    return _log_file


# ============================================================
#  Directory resolution
# ============================================================
def _is_writable_dir(path):
    """Return True if ``path`` can be created and written to."""
    try:
        p = Path(path)
        p.mkdir(parents=True, exist_ok=True)
        test_file = p / '.mk_write_test'
        test_file.write_text('ok', encoding='utf-8')
        try:
            test_file.unlink()
        except Exception:
            pass
        return True
    except Exception:
        return False


def _resolve_log_dir():
    """
    Return the first writable log directory, or None if none is usable.
    Priority:
        1. <exe_dir>/logs          (PyInstaller frozen build)
        2. <project_root>/logs     (development)
        3. %LOCALAPPDATA%/MarkEase/logs
        4. ~/.markease/logs
    """
    candidates = []

    # 1) frozen build: next to the executable
    try:
        if getattr(sys, 'frozen', False):
            exe_dir = Path(sys.executable).resolve().parent
            candidates.append(exe_dir / 'logs')
        else:
            # 2) development: project root (this file lives in app/)
            proj_root = Path(__file__).resolve().parent.parent
            candidates.append(proj_root / 'logs')
    except Exception:
        pass

    # 3) Windows local appdata
    try:
        local_app = os.environ.get('LOCALAPPDATA')
        if local_app:
            candidates.append(Path(local_app) / 'MarkEase' / 'logs')
    except Exception:
        pass

    # 4) user home fallback
    try:
        candidates.append(Path.home() / '.markease' / 'logs')
    except Exception:
        pass

    for c in candidates:
        try:
            if _is_writable_dir(c):
                return c
        except Exception:
            continue
    return None


# ============================================================
#  faulthandler
# ============================================================
def _setup_faulthandler(log_dir):
    """
    Enable faulthandler and redirect its output to logs/fatal_crash.log.
    This captures fatal interpreter crashes (segfault, stack overflow, ...)
    that would otherwise kill the process silently.
    """
    global _faulthandler_file
    try:
        crash_path = Path(log_dir) / 'fatal_crash.log'
        _faulthandler_file = open(crash_path, 'a', encoding='utf-8')
        try:
            _faulthandler_file.write(
                '\n===== Session started: %s =====\n' % _now_iso())
            _faulthandler_file.flush()
        except Exception:
            pass
        faulthandler.enable(file=_faulthandler_file, all_threads=True)
    except Exception:
        _faulthandler_file = None


# ============================================================
#  Exception hooks
# ============================================================
def _install_excepthooks():
    """Install sys.excepthook and threading.excepthook."""
    # ---- main thread ----
    try:
        original_hook = sys.excepthook

        def _hook(exc_type, exc_value, exc_tb):
            try:
                log_critical(
                    'uncaught_exception',
                    message='%s: %s' % (exc_type.__name__, exc_value),
                    exception=exc_value,
                    source='sys.excepthook',
                )
            except Exception:
                pass
            try:
                original_hook(exc_type, exc_value, exc_tb)
            except Exception:
                pass

        sys.excepthook = _hook
    except Exception:
        pass

    # ---- background threads ----
    try:
        original_thread_hook = getattr(threading, 'excepthook', None)
        if original_thread_hook is not None:
            def _thread_hook(args):
                try:
                    thread_name = ''
                    try:
                        thread_name = args.thread.name if args.thread else ''
                    except Exception:
                        thread_name = ''
                    log_critical(
                        'uncaught_exception',
                        message='%s: %s' % (args.exc_type.__name__,
                                            args.exc_value),
                        exception=args.exc_value,
                        source='threading.excepthook',
                        thread=thread_name,
                    )
                except Exception:
                    pass
                try:
                    original_thread_hook(args)
                except Exception:
                    pass

            threading.excepthook = _thread_hook
    except Exception:
        pass


# ============================================================
#  Init
# ============================================================
def setup_logging(version='0.0.0', build_tag=''):
    """
    Initialize the logging subsystem.

    Parameters
    ----------
    version   : str  current app version, e.g. "2.1.2"
    build_tag : str  front-end build tag, e.g. "render-v23"

    Returns
    -------
    Path | None  the resolved log directory, or None if none was writable.
    """
    global _initialized, _log_dir, _log_file

    if _initialized:
        return _log_dir

    try:
        _app_context['version'] = str(version or '0.0.0')
        _app_context['build_tag'] = str(build_tag or '')
        _app_context['platform'] = _platform_label()
    except Exception:
        pass

    try:
        log_dir = _resolve_log_dir()
    except Exception:
        log_dir = None

    if log_dir is None:
        _initialized = True
        return None

    try:
        _log_dir = Path(log_dir)
        _log_file = _log_dir / 'markease.log'
    except Exception:
        _initialized = True
        return None

    # faulthandler must run before any C-level crash can occur
    try:
        _setup_faulthandler(_log_dir)
    except Exception:
        pass

    # global exception hooks
    try:
        _install_excepthooks()
    except Exception:
        pass

    _initialized = True
    return _log_dir