"""Quick self-check of a running demo app.
usage: python selfcheck.py BASE_URL [--scenario wallet|inventory] [--trials 20]
Sequential behaviour must hold in both modes. The race check reports how many simultaneous pairs BOTH succeeded:
expect most of them in MODE=vuln and none in MODE=fixed (the numbers printed are the ones measured now)."""
import argparse
import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

SCENARIOS = {
    "wallet": {"path": "/withdraw", "key": "balance", "reset": {"balance": 100}, "race": {"amount": 80},
               # (reset params, call params, expected HTTP status, expected value of the state key afterwards)
               "seq": [({"balance": 100}, [({"amount": 80}, 200), ({"amount": 80}, 409)], 20),
                       ({"balance": 100}, [({"amount": 100}, 200)], 0),
                       ({"balance": 100}, [({"amount": 101}, 409)], 100)]},
    "inventory": {"path": "/checkout", "key": "stock", "reset": {"stock": 1}, "race": {"qty": 1},
                  "seq": [({"stock": 3}, [({"qty": 1}, 200), ({"qty": 1}, 200)], 1),
                          ({"stock": 1}, [({"qty": 1}, 200), ({"qty": 1}, 409)], 0)]},
}


def post(base, path, params, headers=None):
    req = urllib.request.Request(base + path + "?" + urllib.parse.urlencode(params), data=b"", headers=headers or {}, method="POST")
    try:
        with urllib.request.urlopen(req) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def state(base, key):
    with urllib.request.urlopen(base + "/state") as r:
        return json.loads(r.read())[key]


def check_sequential(base, sc):
    for reset, calls, want in sc["seq"]:
        assert post(base, "/reset", reset) == 200, "reset failed"
        for params, status in calls:
            got = post(base, sc["path"], params)
            assert got == status, f"{sc['path']} {params}: expected HTTP {status}, got {got}"
        got = state(base, sc["key"])
        assert got == want, f"state {sc['key']}: expected {want}, got {got}"
    print("Sequential checks: PASS")


def check_races(base, sc, trials):
    both = one = other = 0
    with ThreadPoolExecutor(max_workers=2) as ex:
        for _ in range(trials):
            post(base, "/reset", sc["reset"])
            bar = threading.Barrier(2)

            def go():
                bar.wait()
                return post(base, sc["path"], sc["race"], {"X-Race-Delay": "30"})

            statuses = [f.result() for f in (ex.submit(go), ex.submit(go))]
            if statuses == [200, 200]:
                both += 1
            elif sorted(statuses) == [200, 409]:
                one += 1
            else:
                other += 1
    print(f"Race trials: both_200={both}, one_200_one_409={one}, other={other}, total={trials}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("base_url")
    ap.add_argument("--scenario", default="wallet", choices=list(SCENARIOS))
    ap.add_argument("--trials", type=int, default=20)
    a = ap.parse_args()
    base = a.base_url.rstrip("/")
    check_sequential(base, SCENARIOS[a.scenario])
    check_races(base, SCENARIOS[a.scenario], a.trials)
