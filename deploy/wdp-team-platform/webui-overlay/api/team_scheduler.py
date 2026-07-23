"""
WDP 团队工作台 · 定时任务调度器（team_scheduler）.

Q2=A：由 web-ui 进程内的后台线程执行调度。

机制：
  - 后台守护线程，每 30 秒 tick 一次
  - 对每个 enabled 的任务，用 croniter 判断「上次调度时间 → 现在」之间是否跨过了 cron 触发点
  - 跨过则执行 run_task(triggered_by='schedule')
  - 用 last_run 防重复；进程重启后从 last_run 恢复，不会漏跑或重复跑同一分钟

部署（关键，见 docs 部署建议）：
  - 本地：默认启用（web-ui 启动即起线程）
  - 线上多副本：只在主 Agent Pod 设 WDP_SCHEDULER_ENABLED=1，其它副本设 =0，
    避免同一任务被多副本重复执行。或改用 K8s CronJob 调 main_agent_tasks.py（关掉本线程）。
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime  # 用于 last_run 字符串解析

logger = logging.getLogger(__name__)

_thread: threading.Thread | None = None
_stop = threading.Event()
_TICK_SECONDS = 30


def _should_fire(schedule: str, last_run_ts: float, now_ts: float) -> bool:
    """判断 (last_run, now] 区间内是否有 cron 触发点。全程用 epoch 秒避免时区偏移。"""
    try:
        from croniter import croniter
        # croniter 接受 epoch float 作为 start_time，get_next(float) 返回 epoch
        it = croniter(schedule, last_run_ts)
        nxt = it.get_next(float)
        return nxt <= now_ts
    except Exception as e:
        logger.debug('_should_fire error (%s): %s', schedule, e)
        return False


def _parse_last_run(s: str | None) -> float:
    if not s:
        return 0.0
    try:
        return datetime.strptime(s, '%Y-%m-%d %H:%M:%S').timestamp()
    except Exception:
        return 0.0


def _tick():
    from api import team_tasks as _tt
    cfg = _tt.load_config()
    now = time.time()
    changed = False
    for t in cfg.get('tasks', []):
        if not t.get('enabled'):
            continue
        sch = t.get('schedule') or ''
        last = _parse_last_run(t.get('last_run'))
        # 首次启用（last_run 为空）：以「现在」为基准，等下一个触发点，不立即跑
        if last == 0.0:
            t['last_run'] = time.strftime('%Y-%m-%d %H:%M:%S')
            t['last_status'] = t.get('last_status') or 'scheduled'
            changed = True
            continue
        if _should_fire(sch, last, now):
            logger.info('team-scheduler firing task: %s', t.get('id'))
            try:
                _tt.run_task(t.get('id'), triggered_by='schedule')
            except Exception as e:
                logger.warning('scheduled run_task %s failed: %s', t.get('id'), e)
    if changed:
        _tt.save_config(cfg)


def _loop():
    logger.info('team-scheduler thread started (tick=%ss)', _TICK_SECONDS)
    # 启动稍等，让 web-ui 完全就绪
    _stop.wait(10)
    while not _stop.is_set():
        try:
            _tick()
        except Exception as e:
            logger.warning('team-scheduler tick error: %s', e)
        _stop.wait(_TICK_SECONDS)
    logger.info('team-scheduler thread stopped')


def start():
    """启动调度线程（幂等）。受 WDP_SCHEDULER_ENABLED 控制。"""
    global _thread
    from api import team_tasks as _tt
    if not _tt._scheduler_enabled():
        logger.info('team-scheduler disabled (WDP_SCHEDULER_ENABLED=0)')
        return False
    if _thread and _thread.is_alive():
        return True
    _stop.clear()
    _thread = threading.Thread(target=_loop, name='team-scheduler', daemon=True)
    _thread.start()
    return True


def stop():
    _stop.set()
