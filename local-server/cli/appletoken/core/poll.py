
import time

from .api import (PP_POLL_FAST, PP_POLL_FAST_COUNT, PP_POLL_MAX_TRIES,
                  PP_POLL_SLOW, PP_TERMINAL, VIDEO_POLL_429, VIDEO_POLL_FACTOR,
                  VIDEO_POLL_MAX, VIDEO_POLL_START, VIDEO_TERMINAL)
from .errors import ApiError

VIDEO_TIMEOUT = 30 * 60

STILL_RUNNING_HINT = (
    "還在跑，不是失敗。可以之後再用同一個 id 查。"
    "如果長時間都不動，通常是平台端的上游服務暫時異常，不是你的描述或帳號設定造成的——"
    "請稍後再查；持續發生請聯絡我們。")

class PollResult:
    def __init__(self, data, timed_out=False, elapsed=0.0, tries=0):
        self.data = data or {}
        self.timed_out = timed_out
        self.elapsed = elapsed
        self.tries = tries

    @property
    def status(self):
        return self.data.get("status")

    @property
    def ok(self):
        return self.status == "completed"

    def __repr__(self):
        return "<PollResult status=%s timed_out=%s tries=%d>" % (
            self.status, self.timed_out, self.tries)

def poll_video(wb, job_id, timeout=VIDEO_TIMEOUT, sleep=time.sleep,
               now=time.monotonic, on_tick=None):
    started = now()
    delay = VIDEO_POLL_START
    tries = 0
    data = {}
    while True:
        if now() - started > timeout:
            return PollResult(data, timed_out=True, elapsed=now() - started,
                              tries=tries)
        tries += 1
        try:
            data = wb.job_status(job_id, retry=False)
        except ApiError as e:
            if e.status == 429:
                delay = min(delay * 2, VIDEO_POLL_429)
                sleep(delay)
                continue
            raise
        if on_tick:
            on_tick(data, tries)
        if data.get("status") in VIDEO_TERMINAL:
            return PollResult(data, elapsed=now() - started, tries=tries)
        sleep(delay)
        delay = min(delay * VIDEO_POLL_FACTOR, VIDEO_POLL_MAX)

def poll_post_process(wb, pp_id, max_tries=PP_POLL_MAX_TRIES, sleep=time.sleep,
                      now=time.monotonic, on_tick=None):
    started = now()
    data = {}
    for i in range(max_tries):
        try:
            data = wb.post_process_status(pp_id, retry=False)
        except ApiError as e:
            if e.status == 429:
                sleep(PP_POLL_SLOW)
                continue
            raise
        if on_tick:
            on_tick(data, i + 1)
        if data.get("status") in PP_TERMINAL:
            return PollResult(data, elapsed=now() - started, tries=i + 1)
        sleep(PP_POLL_FAST if i < PP_POLL_FAST_COUNT else PP_POLL_SLOW)
    return PollResult(data, timed_out=True, elapsed=now() - started,
                      tries=max_tries)
