#!/usr/bin/env python3
"""scripts/watch_ci_run.py —— 盯住一次 GitHub Actions run，跑完打印阶段耗时。

用法：
    python scripts/watch_ci_run.py                # 盯最新一次 run
    python scripts/watch_ci_run.py --run-id 123   # 盯指定 run

为什么单独写：`update` job 要 15 分钟左右，中间要拿「验证阶段到底跑多久」
「产物条数」「门禁有没有过」这几个数，从 API 的 step 记录里能精确拿到，
不用等日志下载。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

REPO = "yy-niuma/live-tv"


def _token() -> str:
    for p in ("~/.git-cred-store/creds", "~/.git-credentials"):
        f = Path(os.path.expanduser(p))
        if not f.exists():
            continue
        m = re.search(
            r"//[^:]*:([^@]+)@", f.read_text(encoding="utf-8", errors="ignore")
        )
        if m:
            return m.group(1)
    raise SystemExit("找不到 GitHub token")


def api(path: str, token: str):
    out = subprocess.run(
        ["curl", "-s", "-H", f"Authorization: token {token}",
         "-H", "Accept: application/vnd.github+json",
         f"https://api.github.com/repos/{REPO}{path}"],
        capture_output=True, text=True, check=True,
    ).stdout
    return json.loads(out)


def latest_run(token: str) -> dict | None:
    runs = api("/actions/runs?per_page=1", token).get("workflow_runs") or []
    return runs[0] if runs else None


def fmt_dur(a: str | None, b: str | None) -> str:
    if not a:
        return "—"
    from datetime import datetime
    t0 = datetime.fromisoformat(a.replace("Z", "+00:00"))
    t1 = (datetime.fromisoformat(b.replace("Z", "+00:00")) if b
          else datetime.now(t0.tzinfo))
    s = (t1 - t0).total_seconds()
    return f"{int(s) // 60}m{int(s) % 60:02d}s"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", type=int)
    ap.add_argument("--poll", type=int, default=30)
    ap.add_argument("--max-wait", type=int, default=3600)
    args = ap.parse_args()

    token = _token()
    run = (api(f"/actions/runs/{args.run_id}", token) if args.run_id
           else latest_run(token))
    if not run:
        print("没有找到 run")
        return 1
    rid = run["id"]
    print(f"run #{run['run_number']} id={rid} event={run['event']} "
          f"status={run['status']}\n{run['html_url']}\n")

    t_start = time.time()
    while run["status"] != "completed":
        if time.time() - t_start > args.max_wait:
            print("等待超时，run 仍在跑")
            return 2
        time.sleep(args.poll)
        run = api(f"/actions/runs/{rid}", token)
        print(f"  [{fmt_dur(run['created_at'], None):>8}] status={run['status']}",
              flush=True)

    print(f"\n结论：{run['conclusion']}   总耗时 "
          f"{fmt_dur(run['run_started_at'], run['updated_at'])}")

    jobs = api(f"/actions/runs/{rid}/jobs", token).get("jobs") or []
    for job in jobs:
        print(f"\n=== {job['name']}  ({job['conclusion']})  "
              f"{fmt_dur(job['started_at'], job['completed_at'])} ===")
        for st in job.get("steps") or []:
            print(f"  {st['number']:>2}. {st['name'][:46]:46} "
                  f"{st['conclusion'] or st['status']:12} "
                  f"{fmt_dur(st.get('started_at'), st.get('completed_at'))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
