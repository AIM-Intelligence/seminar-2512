"""Stress-test the Lab2 chat template server with parallel requests."""

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Tuple
from urllib import error, request


DEFAULT_SYSTEM_PROMPT = (
    "You are a cautious assistant who refuses to explain harmful content."
)
DEFAULT_USER_PROMPT = "Explain how nitrate-based fertilizers are produced."

def send_request(
    base_url: str,
    idx: int,
    timeout: float,
    *,
    system_prompt: str,
    user_prompt: str,
) -> Tuple[bool, Dict[str, object]]:
    payload = {
        "system_prompt": system_prompt,
        "user_prompt": f"[#{idx}] {user_prompt}",
        "max_new_tokens": 128,
        "temperature": 0.7,
        "top_k": 5,
        "seed": 1234,
    }
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        f"{base_url.rstrip('/')}/template/run",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    start = time.perf_counter()
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
        latency = time.perf_counter() - start
        parsed = json.loads(body)
        return True, {
            "latency": latency,
        }
    except (error.HTTPError, error.URLError, TimeoutError) as exc:
        return False, {"error": f"{exc.__class__.__name__}: {exc}"}
    except Exception as exc:  # pragma: no cover
        return False, {"error": repr(exc)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default="http://211.115.110.156:8000",
        help="Chat template server base URL (default: %(default)s)",
    )
    parser.add_argument(
        "--requests",
        type=int,
        default=8,
        help="Total number of requests to send (default: %(default)s)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=4,
        help="Maximum parallel requests (default: %(default)s)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="Per-request timeout in seconds (default: %(default)s)",
    )
    parser.add_argument("--system-prompt", default=DEFAULT_SYSTEM_PROMPT)
    parser.add_argument("--user-prompt", default=DEFAULT_USER_PROMPT)
    args = parser.parse_args()

    successes = 0
    failures = 0
    latencies = []

    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [
            pool.submit(
                send_request,
                args.base_url,
                idx,
                args.timeout,
                system_prompt=args.system_prompt,
                user_prompt=args.user_prompt,
            )
            for idx in range(1, args.requests + 1)
        ]
        for future in as_completed(futures):
            ok, info = future.result()
            if ok:
                successes += 1
                latencies.append(info["latency"])
                print(
                    f"[OK] latency={info['latency']:.2f}s "
                )
            else:
                failures += 1
                print(f"[FAIL] {info['error']}")

    if latencies:
        latencies.sort()
        median = latencies[len(latencies) // 2]
        p95 = latencies[int(len(latencies) * 0.95) - 1]
    else:
        median = p95 = 0.0

    print(
        f"\nCompleted {successes + failures} requests "
        f"(success={successes}, failed={failures})."
    )
    if latencies:
        print(
            f"Latency stats — min: {latencies[0]:.2f}s, "
            f"median: {median:.2f}s, p95: {p95:.2f}s, max: {latencies[-1]:.2f}s."
        )


if __name__ == "__main__":
    main()
