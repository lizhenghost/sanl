"""全局任务进度管理器：抓取/测速/清理等后台任务统一注册进度，
前端通过 GET /api/tasks 拉取渲染进度条。内存态，进程重启自动清空。"""
import time
import threading
from typing import Dict, Optional


class Task:
    __slots__ = ("id", "name", "phase", "done", "total", "detail", "started_at", "finished_at", "error")

    def __init__(self, tid: str, name: str, total: int = 0):
        self.id = tid
        self.name = name
        self.phase = "running"
        self.done = 0
        self.total = total
        self.detail = ""
        self.started_at = time.time()
        self.finished_at: Optional[float] = None
        self.error: Optional[str] = None

    def to_dict(self) -> dict:
        pct = 0
        if self.total > 0:
            pct = round(min(100.0, self.done / self.total * 100), 1)
        elif self.phase == "running":
            pct = -1  # 不定进度（转圈）
        return {
            "id": self.id, "name": self.name, "phase": self.phase,
            "done": self.done, "total": self.total, "pct": pct,
            "detail": self.detail,
            "elapsed": round((self.finished_at or time.time()) - self.started_at, 1),
            "error": self.error,
        }


class TaskManager:
    def __init__(self):
        self._tasks: Dict[str, Task] = {}
        self._lock = threading.Lock()

    def start(self, tid: str, name: str, total: int = 0) -> Task:
        with self._lock:
            t = Task(tid, name, total)
            self._tasks[tid] = t
            self._gc_locked()
            return t

    def update(self, tid: str, done: Optional[int] = None, total: Optional[int] = None,
               detail: Optional[str] = None, phase: Optional[str] = None):
        with self._lock:
            t = self._tasks.get(tid)
            if not t:
                return
            if done is not None:
                t.done = done
            if total is not None:
                t.total = total
            if detail is not None:
                t.detail = str(detail)[:160]
            if phase is not None:
                t.phase = phase

    def finish(self, tid: str, error: Optional[str] = None):
        with self._lock:
            t = self._tasks.get(tid)
            if not t:
                return
            t.phase = "failed" if error else "done"
            t.error = error
            t.finished_at = time.time()
            if t.total == 0 and not error:
                t.done = t.total = 1

    def get_active(self) -> list:
        with self._lock:
            tasks = [t.to_dict() for t in self._tasks.values() if t.phase == "running"]
        # 最近完成的排在后面，前端可显示「刚刚完成」
        return sorted(tasks, key=lambda x: x["id"])

    def get_recent(self, limit: int = 5) -> list:
        with self._lock:
            finished = [t for t in self._tasks.values() if t.phase != "running"]
            finished.sort(key=lambda t: -(t.finished_at or 0))
            return [t.to_dict() for t in finished[:limit]]

    def _gc_locked(self, keep: int = 30):
        """只保留最近 30 个已完成任务，防内存增长"""
        finished = [t for t in self._tasks.values() if t.phase != "running"]
        if len(finished) <= keep:
            return
        finished.sort(key=lambda t: -(t.finished_at or 0))
        for t in finished[keep:]:
            self._tasks.pop(t.id, None)


task_manager = TaskManager()
