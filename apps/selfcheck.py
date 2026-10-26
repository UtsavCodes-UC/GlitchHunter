import argparse
import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor


def request(base_url, path, headers=None):
    req = urllib.request.Request(
        base_url + path,
        data=b"",
        headers=headers or {},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def reset(base_url):
    status, _ = request(base_url, "/reset?balance=100")
    assert status == 200, f"reset returned {status}"


def state(base_url):
    with urllib.request.urlopen(base_url + "/state") as response:
        return json.loads(response.read())["balance"]


def withdraw(base_url, amount):
    return request(base_url, f"/withdraw?amount={amount}")[0]


def check_sequential(base_url):
    reset(base_url)
    assert withdraw(base_url, 80) == 200
    assert state(base_url) == 20
    assert withdraw(base_url, 80) == 409
    assert state(base_url) == 20

    reset(base_url)
    assert withdraw(base_url, 100) == 200
    assert state(base_url) == 0

    reset(base_url)
    assert withdraw(base_url, 101) == 409
    assert state(base_url) == 100
    print("Sequential checks: PASS")


def racing_withdraw(base_url, barrier):
    barrier.wait()
    return withdraw_with_delay(base_url)


def withdraw_with_delay(base_url):
    path = "/withdraw?" + urllib.parse.urlencode({"amount": 80})
    return request(base_url, path, {"X-Race-Delay": "30"})[0]


def check_races(base_url, trials):
    both_200 = one_200_one_409 = other = 0
    with ThreadPoolExecutor(max_workers=2) as executor:
        for _ in range(trials):
            reset(base_url)
            barrier = threading.Barrier(2)
            results = [
                executor.submit(racing_withdraw, base_url, barrier),
                executor.submit(racing_withdraw, base_url, barrier),
            ]
            statuses = [future.result() for future in results]
            if statuses == [200, 200]:
                both_200 += 1
            elif sorted(statuses) == [200, 409]:
                one_200_one_409 += 1
            else:
                other += 1
    print(
        f"Race trials: both_200={both_200}, "
        f"one_200_one_409={one_200_one_409}, other={other}, total={trials}"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("base_url", help="running wallet app URL")
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")
    check_sequential(base_url)
    check_races(base_url, 20)


if __name__ == "__main__":
    main()
