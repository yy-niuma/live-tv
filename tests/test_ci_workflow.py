"""CI 配置的契约测试：离线、只解析 YAML，不发任何网络请求。

守的是什么（三条都是「改坏了没人发现」的类型）：

1. **触发面与防环**：`update` job 会 `git push origin HEAD:main`。一旦它自己也能被
   push 事件拉起，就是无限循环。这里断言 push 触发存在（只读检查要在主干跑），
   同时 update job 的 `if` 不存在 push 这条路径。
2. **可播性门禁**：`check_output.py` 只做结构体检，结构全对但全是死链的产物能
   一路绿灯。这里断言 update job 里真的调用了 `scripts/check_streams.py`、
   真的带了 `--max-bad-ratio`、阈值落在实测分布与历史退化之间的窄区间、
   且这一步排在 `git push` **之前**（排在后面等于没门禁）。
3. **时间预算**：update job 实测流水线 33.4 分钟，job timeout 45 分钟。
   任何一步的 timeout 一旦超过剩余预算，等于没写 —— 这里把上界钉死。

另外覆盖 `subscribe-health.yml`（订阅地址可达性回归）：它必须查两个 raw 地址、
要求 200 且 Content-Length > 0、且失败时真的非零退出（不是只打日志的摆设）。

刻意不做的事：不解析 workflow 的语义（不模拟 Actions 表达式求值），
只断言「配置文本里有这条接线」。真跑一遍要网络 + GitHub，不适合单测。
"""
from __future__ import annotations

from pathlib import Path

import yaml

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"
UPDATE_YML = WORKFLOWS / "update.yml"
SUBSCRIBE_YML = WORKFLOWS / "subscribe-health.yml"

# 阈值依据（2026-10-30 实测，8 个历史日期的真实产物逐份跑 check_streams.py）：
#   不可用占比 0.0% / 3.0% / 8.7% / 15.6% / 31.2% / 32.0% / 36.4% / 39.4%
# 最差一天 39.4% —— 阈值必须高于它，否则门禁在正常波动里就红了；
# 而 docs/source-discovery.md 记录的历史退化是 51.6%~68.3% 不可用 ——
# 阈值必须低于 60%，否则这些退化照样能过。区间就夹在这里。
WORST_MEASURED_BAD_RATIO = 0.394
MAX_SENSIBLE_BAD_RATIO = 0.60


def load(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def triggers(doc: dict):
    """取 `on:` 段。

    坑：YAML 1.1（PyYAML 默认）把裸键 `on` 解析成布尔 `True`，
    于是 `doc["on"]` 会 KeyError，实际键名是 `True`。两种都要兜住。
    """
    if "on" in doc:
        return doc["on"]
    return doc[True]


def steps_of(doc: dict, job: str) -> list[dict]:
    return doc["jobs"][job]["steps"]


def step_containing(steps: list[dict], needle: str) -> dict:
    for step in steps:
        if needle in (step.get("run") or ""):
            return step
    raise AssertionError(f"没有哪个步骤的 run 里包含 {needle!r}")


def index_of(steps: list[dict], needle: str) -> int:
    for i, step in enumerate(steps):
        if needle in (step.get("run") or ""):
            return i
    raise AssertionError(f"没有哪个步骤的 run 里包含 {needle!r}")


# ---------------------------------------------------------------------------
# (a) push 触发器
# ---------------------------------------------------------------------------
def test_push_trigger_on_main_exists() -> None:
    trig = triggers(load(UPDATE_YML))
    assert "push" in trig, "on: 里缺 push 触发 —— 主干推送后只读检查不会跑"
    branches = trig["push"]["branches"]
    assert "main" in branches, f"push 触发必须限定 main，实际 {branches}"


def test_existing_triggers_are_not_dropped() -> None:
    """加 push 不该顺手删掉定时任务、手动触发、PR 门禁。"""
    trig = triggers(load(UPDATE_YML))
    for name in ("schedule", "workflow_dispatch", "pull_request", "push"):
        assert name in trig, f"触发面 {name} 被删了"
    assert trig["schedule"][0]["cron"] == "0 0 * * *"


# ---------------------------------------------------------------------------
# (b) 防环设计
# ---------------------------------------------------------------------------
def test_update_job_never_runs_on_push() -> None:
    """锁 2：update 用**正面列举**，push 不在允许列表里。

    正面列举而不是 `!= 'pull_request'` 是刻意的：以后再加 release /
    repository_dispatch，update 也不会顺手跑生产（fail-closed）。
    """
    cond = load(UPDATE_YML)["jobs"]["update"]["if"]
    assert isinstance(cond, str) and cond.strip(), "update job 的 if 丢了"
    flat = " ".join(cond.split())

    assert "schedule" in flat, "update 必须允许 schedule"
    assert "workflow_dispatch" in flat, "update 必须允许手动触发"
    assert "push" not in flat, (
        "update job 的 if 里出现了 push —— update 会 git push 到 main，"
        f"这是自触发循环。当前条件：{flat!r}"
    )
    # 必须是「== 列举」而不是「!= 排除」
    assert "github.event_name ==" in flat, (
        f"update 的 if 必须是正面列举（== 'schedule' 之类），实际：{flat!r}"
    )


def test_bot_push_guard_exists() -> None:
    """锁 2b：万一推送改用 PAT（PAT 推送会产生 push 事件），bot 自己的产物提交
    也不该再跑只读检查。至少有一个 job 挡掉 github-actions[bot]。"""
    doc = load(UPDATE_YML)
    guards = [
        name for name, job in doc["jobs"].items()
        if "github-actions[bot]" in str(job.get("if", ""))
    ]
    assert guards, "没有任何 job 用 github.actor 挡掉 bot 推送，防环只剩一层"


def test_check_job_is_read_only() -> None:
    """只读检查不该拿到写令牌 —— 这是防环的成本侧约束。"""
    job = load(UPDATE_YML)["jobs"]["check"]
    assert job["permissions"] == {"contents": "read"}, job["permissions"]


# ---------------------------------------------------------------------------
# (c) 可播性门禁
# ---------------------------------------------------------------------------
def test_playability_gate_invokes_check_streams_with_threshold() -> None:
    steps = steps_of(load(UPDATE_YML), "update")
    gate = step_containing(steps, "check_streams.py")
    script = gate["run"]

    assert "output/hk_merged.m3u" in script, "门禁必须对 hk_merged 做探测"
    assert "--max-bad-ratio" in script, (
        "没带 --max-bad-ratio 时 check_streams.py 只要是「存在死链」就退 1，"
        "门禁会天天红；必须由阈值决定成败"
    )
    assert "--json" in script, "要留下逐条结果，否则红了无法定位"


def test_playability_gate_threshold_is_evidence_based() -> None:
    """阈值必须夹在「实测最差日」与「历史退化」之间，不能拍脑袋。"""
    steps = steps_of(load(UPDATE_YML), "update")
    gate = step_containing(steps, "check_streams.py")
    raw = (gate.get("env") or {}).get("MAX_BAD_RATIO")
    assert raw is not None, "门禁阈值应写在 step 的 env.MAX_BAD_RATIO 里"
    threshold = float(raw)

    assert threshold > WORST_MEASURED_BAD_RATIO, (
        f"阈值 {threshold:.2f} 不高于实测最差日 {WORST_MEASURED_BAD_RATIO:.1%}，"
        "正常波动就会把门禁打成红灯"
    )
    assert threshold <= MAX_SENSIBLE_BAD_RATIO, (
        f"阈值 {threshold:.2f} 太高，历史退化（>55% 不可用）也能过闸，门禁形同虚设"
    )


def test_playability_gate_retries_to_absorb_jitter() -> None:
    """网络探测有抖动：要有多轮重试，但判定仍靠 --max-bad-ratio 的退出码。"""
    steps = steps_of(load(UPDATE_YML), "update")
    script = step_containing(steps, "check_streams.py")["run"]
    assert "for attempt in 1 2" in script, "门禁应有两轮探测以吸收单轮抖动"
    assert "exit 1" in script, "两轮都超阈值时必须真的非零退出（不许永远绿）"


def test_playability_gate_runs_before_push_and_after_fuse() -> None:
    steps = steps_of(load(UPDATE_YML), "update")
    fuse = index_of(steps, "check_output.py")
    gate = index_of(steps, "check_streams.py")
    push = index_of(steps, "git push origin HEAD:main")
    assert fuse < gate, "可播性门禁应排在结构保险丝之后（先保结构，再保可播）"
    assert gate < push, "门禁排在 push 之后等于没门禁：坏产物已经推上 main 了"


def step_by_id(doc: dict, job: str, step_id: str) -> dict:
    for step in doc["jobs"][job]["steps"]:
        if step.get("id") == step_id:
            return step
    raise AssertionError(f"{job} 里没有 id={step_id!r} 的步骤")


def test_whitelist_blind_spot_is_probed_before_push() -> None:
    """白名单补测必须存在且在 push 之前。

    2026-10-30 全流程实测：门禁口径报 81/81 = 100% 可用，真实探测只有 67/81
    = 82.7%。差的 14 条全部是 config/whitelist.txt 命中的域名 ——
    src/validator.py 对它们 `return True` 而不发请求，于是门禁「看见」的
    100% 里有 15 条是定义上必然通过的。没有这一步，门禁绿灯就是假的。

    注意：按 **step id** 定位，不能按 "whitelist.txt" 子串找 —— 主门禁那一步
    也会读 whitelist.txt（只为了打警告），按子串会抓错步骤。
    """
    doc = load(UPDATE_YML)
    steps = steps_of(doc, "update")
    exempt = step_by_id(doc, "update", "playable_exempt")
    script = exempt["run"]
    assert "youtube" in script.lower(), "补测必须识别指向 youtube 的伪直播"
    assert "MAX_BAD_RATIO" in script, "补测结果要计入同一个硬阈值"
    assert "SystemExit(1)" in script, "补测超阈值必须失败"

    gate = index_of(steps, "check_streams.py")
    ex_i = steps.index(exempt)
    push = index_of(steps, "git push origin HEAD:main")
    assert gate < ex_i < push, "补测应紧跟主门禁、且仍在 push 之前"


def test_push_step_merges_remote_before_pushing() -> None:
    """push 前必须先 fetch+merge 远端 main。

    这个 job 从 checkout 到 push 要跑 ~20 分钟，期间 main 可能被推动
    （人工提交 / 上一轮迟到推送 / dispatch 与 schedule 撞车）。此时直接 push
    会被 non-fast-forward 拒绝 —— 2026-10-30 本地全流程验证时真实复现过。
    没有这条保护，"今天的产物没推上去、job 变红"就是必然会发生的事故。
    """
    steps = steps_of(load(UPDATE_YML), "update")
    push_step = step_containing(steps, "git push origin HEAD:main")
    script = push_step["run"]

    assert "git fetch origin main" in script, "push 前必须 fetch 远端 main"
    assert "git merge" in script, "push 前必须合并远端 main"
    assert "-X ours" in script, (
        "output/ 是生成物，冲突时应以本次运行为准（-X ours）"
    )
    fetch_i = script.index("git fetch origin main")
    push_i = script.index("git push origin HEAD:main")
    assert fetch_i < push_i, "顺序必须是先 fetch/merge 再 push"


def test_push_step_still_guarded_by_changes() -> None:
    """没有变更时不该产生空提交 / 无用推送。"""
    steps = steps_of(load(UPDATE_YML), "update")
    push_step = step_containing(steps, "git push origin HEAD:main")
    assert "steps.changes.outputs.changed" in str(push_step.get("if", "")), (
        "提交推送必须仍受 changed 条件约束"
    )


def test_gate_step_has_timeout() -> None:
    steps = steps_of(load(UPDATE_YML), "update")
    gate = step_containing(steps, "check_streams.py")
    timeout = gate.get("timeout-minutes")
    assert isinstance(timeout, int) and 1 <= timeout <= 5, (
        f"门禁单轮实测 3.8~13.3 秒、最坏两轮约 32 秒，"
        f"timeout 应在 1~5 分钟；实际 {timeout}"
    )


# ---------------------------------------------------------------------------
# (d) timeout 预算
# ---------------------------------------------------------------------------
def test_job_timeouts_fit_the_budget() -> None:
    """实测流水线 33.4 分钟，update 的 timeout 是 45 分钟 —— 不许再放大。"""
    jobs = load(UPDATE_YML)["jobs"]
    for name, job in jobs.items():
        timeout = job.get("timeout-minutes")
        assert isinstance(timeout, int) and timeout > 0, f"{name} 没有 timeout-minutes"

    assert jobs["update"]["timeout-minutes"] <= 45, (
        "update 超 45 分钟会撞上 GitHub 的作业上限并让当天产物停在半路"
    )
    assert jobs["check"]["timeout-minutes"] <= 15


def test_gate_cost_leaves_headroom_in_update_job() -> None:
    """门禁的声明成本必须留在 45 分钟预算内（含 33.4 分钟基线）。"""
    doc = load(UPDATE_YML)
    budget = doc["jobs"]["update"]["timeout-minutes"]
    baseline = 33.4  # 控制器实测完整流水线耗时（分钟）
    gate = step_containing(steps_of(doc, "update"), "check_streams.py")
    assert baseline + gate["timeout-minutes"] <= budget, (
        f"基线 {baseline} + 门禁上限 {gate['timeout-minutes']} 超出 job 预算 {budget}"
    )


# ---------------------------------------------------------------------------
# 订阅地址可达性回归（独立 workflow）
# ---------------------------------------------------------------------------
def test_subscribe_health_workflow_exists_and_triggers() -> None:
    assert SUBSCRIBE_YML.is_file(), "缺少 .github/workflows/subscribe-health.yml"
    trig = triggers(load(SUBSCRIBE_YML))
    assert "schedule" in trig, "订阅可达性必须每天自跑一次（bot push 不产生 push 事件）"
    assert "workflow_dispatch" in trig
    assert "push" in trig
    paths = " ".join(trig["push"].get("paths") or [])
    assert "output/" in paths, "push 触发应限定在产物路径上"


def test_subscribe_health_checks_both_raw_urls() -> None:
    doc = load(SUBSCRIBE_YML)
    job = doc["jobs"]["reachability"]
    script = "\n".join(s.get("run") or "" for s in job["steps"])
    env = job["steps"][1].get("env") or {}

    assert "raw.githubusercontent.com" in str(env.values()), "必须探测 raw 地址"
    assert "/main" in str(env.values()), "必须探测 main 分支上的产物"
    for name in ("output/all_merged.m3u", "output/hk_merged.m3u"):
        assert name in script, f"没有检查 {name}"

    lowered = script.lower()
    assert "content-length" in lowered, "必须校验 Content-Length"
    assert '"200"' in script, "必须要求 HTTP 200"
    assert "exit 1" in script, "拿不到 200 / 非空内容时必须非零退出"
    assert "for attempt in 1 2 3" in script, "raw CDN 会抖，需要重试"


def test_subscribe_health_is_read_only_and_bounded() -> None:
    job = load(SUBSCRIBE_YML)["jobs"]["reachability"]
    assert job["permissions"] == {"contents": "read"}, job["permissions"]
    assert isinstance(job["timeout-minutes"], int) and job["timeout-minutes"] <= 10


def test_subscribe_health_does_not_write_repo() -> None:
    """这个 job 只读：任何 git push / commit 都不该出现在它的脚本里。"""
    script = "\n".join(
        s.get("run") or "" for s in load(SUBSCRIBE_YML)["jobs"]["reachability"]["steps"]
    )
    for forbidden in ("git push", "git commit", "git add"):
        assert forbidden not in script, f"只读回归里出现了 {forbidden!r}"
