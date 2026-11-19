"""Spike: calm (5 users) -> sudden 100 users within a second -> back to calm; a probe user watches latency."""
import json
import os
import time

from locust import LoadTestShape

from locust_users import Customer, ProbeUser   # noqa: F401

PHASE_FILE = os.getenv("PERF_PHASE_FILE", "")


class Spike(LoadTestShape):
    phases = [(15, 5, 5, "baseline"), (30, 100, 100, "spike"), (55, 5, 50, "recovery")]   # until, users, rate, name
    _last = None

    def _announce(self, name):
        if PHASE_FILE and name != self._last:
            with open(PHASE_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps({"t": time.time(), "phase": name}) + "\n")
        self._last = name

    def tick(self):
        t = self.get_run_time()
        for until, users, rate, name in self.phases:
            if t < until:
                self._announce(name)
                return users, rate
        self._announce("end")
        return None
