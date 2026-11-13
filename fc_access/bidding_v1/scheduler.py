"""Finite scheduler seam: local delivery never consumes an EA request slot."""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class Work:
    command_id: str
    kind: str
    ready_at: float
    deadline: float
    priority: int = 0

    def __post_init__(self):
        from .contracts import token
        token(self.command_id)
        if self.kind not in {"read", "write"} or type(self.priority) is not int:
            raise ValueError("invalid_work")
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in (self.ready_at, self.deadline)) or self.ready_at >= self.deadline:
            raise ValueError("invalid_deadline")


class Scheduler:
    def __init__(self, clock, *, min_native_interval=0, concurrency=1, capacity=100, write_priority=1, journal=None, scope=None):
        if type(min_native_interval) not in (int, float) or not math.isfinite(min_native_interval) or min_native_interval < 0:
            raise ValueError("invalid_interval")
        if type(concurrency) is not int or concurrency < 1 or type(capacity) is not int or capacity < 1 or type(write_priority) is not int:
            raise ValueError("invalid_scheduler")
        self.clock, self.interval = clock, min_native_interval
        self.journal, self.scope = journal, scope
        if journal is not None:
            from .contracts import token
            token(scope)
        self.concurrency, self.capacity, self.write_priority = concurrency, capacity, write_priority
        self.queue, self.active, self.seen, self.skipped, self.metrics = {}, {}, set(), [], []
        self.last_native = -math.inf

    def enqueue(self, work):
        if work.command_id in self.seen:
            raise ValueError("duplicate_command")
        if len(self.queue)+len(self.active) >= self.capacity:
            raise ValueError("scheduler_full")
        self.seen.add(work.command_id)
        self.queue[work.command_id] = work

    def delivery(self, command_id, delivered_at, *, enqueued_at):
        # Telemetry only: no change to last_native or active concurrency.
        if delivered_at < enqueued_at:
            raise ValueError("negative_delivery")
        from .contracts import token
        token(command_id)
        latency = (delivered_at-enqueued_at)*1000
        if not math.isfinite(latency):
            raise ValueError("invalid_delivery")
        if self.journal:
            self.journal.record(self.scope, "DELIVERY_OBSERVED", {"local_delivery_ms": latency}, command_id=command_id)
        self.metrics.append({"command_id": command_id, "local_delivery_ms": latency})

    def next(self):
        now = self.clock()
        for key, work in list(self.queue.items()):
            if now >= work.deadline:
                if self.journal:
                    self.journal.record(self.scope, "DEADLINE_SKIPPED", command_id=key)
                self.skipped.append((key, "DEADLINE_SKIPPED"))
                del self.queue[key]
        if len(self.active) >= self.concurrency or now-self.last_native < self.interval:
            return None
        ready = [w for w in self.queue.values() if w.ready_at <= now]
        if not ready:
            return None
        work = min(ready, key=lambda w: (-(w.priority+(self.write_priority if w.kind == "write" else 0)), w.deadline, w.command_id))
        del self.queue[work.command_id]
        self.active[work.command_id] = now
        self.last_native = now  # Failed actual submissions also consume cadence.
        return work

    def complete(self, command_id, *, request_count=1):
        from .contracts import integer
        integer(request_count)
        started = self.active[command_id]
        latency = (self.clock()-started)*1000
        if not math.isfinite(latency) or latency < 0:
            raise ValueError("invalid_native_latency")
        if self.journal:
            self.journal.record(self.scope, "NATIVE_TIMING", {"native_service_ms": latency, "request_count": request_count}, command_id=command_id)
        del self.active[command_id]
        self.metrics.append({"command_id": command_id, "native_service_ms": latency, "request_count": request_count})
