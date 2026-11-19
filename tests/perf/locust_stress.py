"""Step stress: keep adding users until well past normal load (20 -> 50 -> 100 -> 150)."""
from locust import LoadTestShape

from locust_users import Customer, ProbeUser   # noqa: F401


class StepStress(LoadTestShape):
    stages = [(12, 20, 10), (24, 50, 10), (36, 100, 20), (60, 150, 25)]   # (until seconds, users, spawn rate)

    def tick(self):
        t = self.get_run_time()
        for until, users, rate in self.stages:
            if t < until:
                return users, rate
        return None
