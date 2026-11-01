"""Keep the Windows website running after sign-in or a manual start."""
from pathlib import Path
import argparse
import ctypes
from ctypes import wintypes
import json
import msvcrt
import os
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
RUNTIME = ROOT / 'web/.runtime'
PAUSED = RUNTIME / 'server.stopped'
STATE = RUNTIME / 'watchdog.json'
INTERVAL = 5

# A retained handle identifies the original process even if its PID is reused.
kernel = ctypes.WinDLL('kernel32', use_last_error=True)
kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel.OpenProcess.restype = wintypes.HANDLE
kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel.WaitForSingleObject.restype = wintypes.DWORD
kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
kernel.GetExitCodeProcess.restype = wintypes.BOOL
kernel.CloseHandle.argtypes = [wintypes.HANDLE]
kernel.CloseHandle.restype = wintypes.BOOL
HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def health(url):
    with HTTP.open(url + '/api/v1/healthz', timeout=3) as response:
        info = json.load(response)
    if info.get('generation') != 'local_cpu':
        raise RuntimeError('The port does not belong to this website')
    return int(info['server_pid'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8976)
    args = parser.parse_args()
    url = f'http://127.0.0.1:{args.port}'
    RUNTIME.mkdir(parents=True, exist_ok=True)
    # Windows releases the lock even if the watcher is forcibly terminated.
    lock = (RUNTIME / 'watchdog.lock').open('a+b')
    if lock.seek(0, 2) == 0:
        lock.write(b'0')
        lock.flush()
    lock.seek(0)
    try:
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        lock.close()
        return 0

    handle = None
    watched_pid = None
    failures = 0
    paused = False
    with (RUNTIME / 'autostart.log').open('a', encoding='utf-8', buffering=1) as log:
        def record(message):
            log.write(time.strftime('%Y-%m-%d %H:%M:%S') + ' ' + message + '\n')

        def state(status):
            temp = STATE.with_suffix('.tmp')
            temp.write_text(json.dumps({'pid': os.getpid(), 'server_pid': watched_pid,
                                        'url': url, 'status': status}, indent=2), 'utf-8')
            temp.replace(STATE)

        record(f'Watchdog started: pid={os.getpid()}, url={url}')
        try:
            while True:
                try:
                    if PAUSED.exists():
                        if handle:
                            kernel.CloseHandle(handle)
                            handle = None
                            watched_pid = None
                        if not paused:
                            record('Manual stop requested; automatic restart paused')
                            state('paused')
                            paused = True
                        time.sleep(INTERVAL)
                        continue
                    paused = False
                    if handle:
                        result = kernel.WaitForSingleObject(handle, 0)
                        if result == 258:  # WAIT_TIMEOUT: this exact process is alive.
                            time.sleep(INTERVAL)
                            continue
                        if result != 0:
                            raise ctypes.WinError(ctypes.get_last_error())
                        code = wintypes.DWORD()
                        kernel.GetExitCodeProcess(handle, ctypes.byref(code))
                        record(f'Website exited: pid={watched_pid}, exit_code={code.value}; restarting')
                        kernel.CloseHandle(handle)
                        handle = None
                        watched_pid = None
                        state('restarting')
                    try:
                        watched_pid = health(url)
                    except Exception:
                        record('Website unavailable; invoking existing startup manager')
                        result = subprocess.run(
                            [sys.executable, str(ROOT / 'web/manage.py'), 'start',
                             '--public', '--port', str(args.port), '--supervised'],
                            cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
                        if PAUSED.exists():
                            continue
                        if result.returncode:
                            raise RuntimeError(f'Startup manager exited with code {result.returncode}')
                        watched_pid = health(url)
                    handle = kernel.OpenProcess(0x100000 | 0x1000, False, watched_pid)
                    if not handle:
                        raise ctypes.WinError(ctypes.get_last_error())
                    if health(url) != watched_pid:
                        kernel.CloseHandle(handle)
                        handle = None
                        raise RuntimeError('Website process changed during attachment')
                    failures = 0
                    state('watching')
                    record(f'Website healthy; watching pid={watched_pid}')
                except Exception as exc:
                    failures += 1
                    delay = min(60, 5 * (2 ** min(failures - 1, 4)))
                    record(f'Recovery error: {exc}; retry in {delay}s')
                    time.sleep(delay)
        finally:
            if handle:
                kernel.CloseHandle(handle)
            STATE.unlink(missing_ok=True)
            lock.close()


if __name__ == '__main__':
    raise SystemExit(main())
