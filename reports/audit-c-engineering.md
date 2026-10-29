# 工程质量审计报告

**审计对象**：`/home/hermes/.hermes/projects/live-tv` @ `f75575a`（2026-10-28，185 commits）
**审计范围**：零测试、CI 质量、依赖管理、代码结构、lint/类型、文档
**审计方式**：只读。未修改 `src/` 任何文件、未 commit/push。仅向 `.venv` 安装了 `ruff / mypy / pytest` 三个工具（不影响源码）。
**运行环境**：本机 venv = Python 3.14.4；另用 `/home/hermes/.local/bin/python3.11`（3.11.15）建了独立 venv 复测，因为 **CI 跑的是 3.11，本地 venv 是 3.14**（见 §2.6，两者性能差 1.8 倍）。

与其他子报告的关系：分类质量问题见 `audit-a-classification.md`，产物质量问题见 `audit-d-output.md`，控制器一手核查见 `00-controller-baseline.md`。本报告只做**工程层**（可测性/CI/依赖/结构/lint/文档），涉及产物的结论只引用不重复推导，冲突处以本报告实测命令输出为准。

---

## 一、现状盘点

### 1.1 代码规模（已逐文件复核）

| 文件 | 行数 | 占比 |
|---|---:|---:|
| `src/group/categorizer.py` | 670 | 31.0% |
| `src/group/normalize.py` | 318 | 14.7% |
| `src/logo_map.py` | 302 | 14.0% |
| `src/fetcher.py` | 187 | 8.7% |
| `src/generator.py` | 182 | 8.4% |
| `src/main.py` | 159 | 7.4% |
| `src/grouper.py` / `src/validator.py` | 92 / 92 | 8.5% |
| `src/config.py` | 57 | 2.6% |
| `src/lib/cache.py` / `whitelist.py` | 49 / 48 | 4.5% |
| `src/__init__.py` | 3 | — |
| `src/group/__init__.py`、`src/lib/__init__.py` | 1 / 1 | — |
| **合计** | **2161** | 14 个 .py |

任务书给的这组数字**正确**。补充：`config/` 另有 376 行配置（`alias.txt` 168 行 / `sources.yaml` 111 / `groups.yaml` 79 / `proxy.txt` 9 / `whitelist.txt` 9），这部分是**事实上的业务规则**，比任何单个 .py 都更容易改坏，但完全没有校验。

### 1.2 测试：零

```
$ find . -name 'test*' -not -path './.venv/*'
（空）
$ grep -rn "pytest" requirements.txt
（空）
```

比"没测试"更严重的是**没有回归可追溯性**：

```
$ git shortlog -sn --all
   182  github-actions[bot]
     3  yy-niuma
$ git log --format='%h %ad %an %s' --date=short --author=yy-niuma
d7c6d6b 2026-04-25 yy-niuma ci: 重写 GitHub Actions workflow
e0625e6 2026-04-25 yy-niuma fix: 全面修复HK/TW/MO频道过滤逻辑（162→86频道）
1f7265f 2026-04-25 yy-niuma feat: IPTV M3U 播放列表聚合工具 — 全面重构版
```

**185 个提交里只有 3 个人类提交，全部集中在 2026-04-25 一天**（"全面重构版"），此后 6 个月只有机器人每日提交产物。所以要纠正任务书里的一个前提：**"历史上修了至少 10 个分类 bug"在这份 git 历史里不可证**——代码是以"重构"形式整体写入的，没有逐条 fix 记录，也没有 CHANGELOG。带来的后果不是"不知道修过多少 bug"，而是：**任何一次分类行为变化都无法判断是"修好了"还是"改坏了"**，因为没有 before/after 断言，只有每天生成的新 m3u。

**回归已经发生且没人发现**（我用全历史扫描）：

```
$ # 遍历 182 个改动 hk_merged.m3u 的提交，数 #EXTINF
commits touching hk_merged: 182
hk channel count: min 18 max 39 last 33 mean 29.7
counts<=20: 13   counts>=100: 0
```

港澳台播放列表在**整个历史里从未超过 39 个频道**（13 次跌到 20 以下），而 `README.md:46` 写的是"**162 个频道**"。这不是"退化"，是 README 数字从来没有真实过（首发提交 2026-04-25 就是 36 个）。核心产物数量在 18~39 之间随上游源死活漂移，**没有任何机制在它掉到 18 时报警**。

### 1.3 依赖管理

```
$ cat requirements.txt
pyyaml>=6.0
aiohttp>=3.9.0
aiofiles>=23.0.0
charset-normalizer>=3.3.0
```

| 检查项 | 结果 |
|---|---|
| 版本 pin | 4 个**只有下界没有上界** |
| lock 文件 | 无（无 `requirements.lock` / `poetry.lock` / `uv.lock`） |
| 未使用的依赖 | **2 个**：`aiofiles`、`charset-normalizer`（`grep -rn "aiofiles\|charset_normalizer" src` → 0 命中；后者只是 aiohttp 的传递依赖） |
| 直接 import 的第三方 | 只有 `yaml`（2 处）、`aiohttp`（2 处） |
| Dependabot / Renovate | 无（`.github/` 下只有 `workflows/update.yml`） |
| `python_requires` | 无（无 pyproject/setup.py） |

链路脆弱性：CI 每天 `pip install -r requirements.txt` 装当时的最新版。aiohttp 目前是 3.14.5，历史上 3.x 有过破坏性行为调整（ClientSession 生命周期、超时语义）；这个项目**恰好重度依赖 aiohttp 的超时/HEAD 行为**（`validator.py:71`、`fetcher.py:101`）。一次上游 minor 变更就能让 CI 每天红，而本地 `.venv` 里装的是另一套版本——排查时会"本地好的"。

### 1.4 CI 概况

`.github/workflows/update.yml`（95 行，2026-04-25 后未再修改）：
`checkout → setup-python 3.11 → pip install → 抓取 → 生成 → 检查更新 → 提交推送 → 上传 artifact`，每日 UTC 0:00，`timeout-minutes: 30`。

**CI 里没有任何一步跑 lint / 类型检查 / 测试**——整个仓库的自动化只验证了"脚本没崩"。

### 1.5 静态检查实测

```
$ .venv/bin/python -m compileall -q src   → exit 0（14 文件全通过）
$ python3.11 -m compileall -q src         → exit 0（3.11 下语法也 OK）
```

ruff 0.17.3（本次装入 venv，未改源码）：

```
$ ruff check src                                  → Found 106 errors（11 个文件）
$ ruff check src --select E,F,W                   → Found 65 errors
$ ruff check src --select E,F,W,B,UP,SIM,C4,RET,ARG,PL,PT → Found 174 errors
```

`--select E,F,W` 的构成：

| 规则 | 数量 | 说明 |
|---|---:|---|
| E501 line-too-long | 49 | 大量 `PROVINCE_KEYWORDS`/`categorize()` 单行超 88 字符（最长 126，`validator.py:89`） |
| F401 unused-import | 9 | 见下表 |
| W293 blank-line-with-whitespace | 3 | |
| F541 f-string 无占位符 | 2 | `main.py:92`、`main.py:151` |
| F601 字典键重复 | 1 | `logo_map.py:47` |
| F841 局部变量未使用 | 1 | `normalize.py:113` 的 `original` |

9 个 F401（全部可 `--fix`，无害但说明代码没被工具碰过）：

```
src/fetcher.py:4:32    typing.Any 未使用
src/fetcher.py:6:25    dataclasses.dataclass 未使用（Channel 是手写类）
src/generator.py:3:8   re 未使用
src/group/categorizer.py:4:20/26  typing.Dict / typing.List 未使用（文件内也大量用 list/dict 字面量注解）
src/group/normalize.py:4:32  typing.Tuple 未使用
src/main.py:5:8        os 未使用
src/validator.py:3:8   re 未使用
src/validator.py:4:26  typing.Set 未使用
```

**ruff 抓到的两个真实缺陷**（不是风格问题）：

1. `logo_map.py:42` 与 `:47` 重复定义 `"viutv"` 键 —— 后者静默覆盖前者，扩展名映射时永远不会报错。
   ```
   $ ruff check src --select F601 --output-format concise
   src/logo_map.py:47:5: F601 Dictionary key literal `"viutv"` repeated
   ```
2. `normalize.py:113` `original = name` 从未使用（繁简转换前的快照，疑似早期"匹配失败回退原名"逻辑的残骸）。

mypy 2.4.0（`--ignore-missing-imports`，无任何配置，默认宽松模式）：

```
$ mypy src --ignore-missing-imports
Found 19 errors in 7 files (checked 14 source files)
```

按错误码分布（`mypy ... | grep -oP '\[[a-z-]+\]$' | sort | uniq -c`）：

```
      11 [assignment]        ← 其中 9 条是 "Incompatible default"（隐式 Optional：`def f(x: str = None)`）
       2 [arg-type]
       2 [union-attr]
       1 [var-annotated]
       1 [attr-defined]
       1 [operator]
       1 [misc]
```

即 **9 条是 `X = None` 而注解没写 `| None`**（`config.py:11`、`fetcher.py:36`、`validator.py:16`、`main.py:16` …），属于"注解写了但没写对"，尚未造成运行时错误。剩下 10 条里，**最有价值的是 `main.py` 的类型漂移**：

```
src/main.py:29: error: Incompatible types in assignment (Path 赋给 str 变量) [assignment]
src/main.py:30: error: "str" has no attribute "mkdir"  [attr-defined]
src/main.py:107: error: Unsupported left operand type for / ("str")  [operator]
```

即 `run(output_dir: str = None)` 里 `output_dir = Path(output_dir)` 把参数改成了 Path，注解却还是 `str`——调用方传 `str` 时一切正常，一旦有人按注解传 Path 再拿去做字符串拼接就会炸。注解目前是**装饰性**的，不是契约。

另外 `fetcher.py:90` 的 `Item "None" of "Semaphore | None" has no attribute "__aenter__"`（2 条）也是真隐患：`self._semaphore` 在 `__init__` 里是 `None`，只有在 `fetch_all()` 开头才被赋值；`_fetch_url` 若被单独调用就是 `AttributeError`。

`print()` 混在库里：**41 处 print，0 处 logging**。

```
$ grep -rn "print(" src --include=*.py | wc -l        → 41
$ grep -rc "print(" src --include=*.py | grep -v ':0' → main.py:32  fetcher.py:5  grouper.py:4
$ grep -rn "logging" src                               → 0
```

`main.py` 的 32 处属于 CLI 正常输出，可以接受；**`fetcher.py`/`grouper.py` 的 9 处是库层日志**（`fetcher.py:53,71,76,82,85`、`grouper.py:38,47,59,84`），无法定级、无法重定向、CI 里只能靠 `grep` 日志文本判断阶段。

### 1.6 运行时实测（这是判断 CI 时间的依据）

用当前配置真实抓 20 个源（今天 3 个源坏：`raw.gh.registry.cyou` DNS 无法解析 ×2、`t.freetv.fun` 403）：

| 阶段 | 实测 | 备注 |
|---|---:|---|
| `Fetcher.fetch_all()` | **8.5s** | 16,859 频道 / 20 源（含 3 源 × 3 次重试） |
| `Grouper.group()` (Py3.14) | **122.3s** | 16,859 → 合并后 12,469 → 53 组 |
| `Grouper.group()` (Py3.11) | **217.4s** | 同数据，CI 用的就是 3.11 |
| `Generator.generate_hk_and_all()` | 1.3s | |
| `Validator.validate()` | **10.8~13.7 url/s** | conc=20 / timeout=10s（当前默认）；四次实测：200 条 14.6s（13.7 url/s）、400 条 33.4s（12.0）、400 条 34.8s（11.5）、600 条 55.7s（10.8） |
| 全流程（`--skip-validation` 冷跑） | 242s | 首次冷 DNS |

**验证（validation）阶段外推：16,859 条 URL ÷ 10.8~13.7 url/s ≈ 20.5~26.0 分钟。** 四次实测呈明显趋势：**样本越大吞吐越低**（200 条 13.7 / 400 条 12.0、11.5 / 600 条 10.8 url/s），因为小样本更容易落在"响应快"的那一段 URL 上。取 10.8~11.5 为悲观侧，加 3.11 下的分组 3.6 分钟 + 抓取约 0.2 分钟 ≈ **24.5~30 min —— 悲观侧已经顶到 30 分钟上限**（详见 §2.6）。

### 1.7 仓库体积与历史形态

```
$ git count-objects -vH
in-pack: 1137   size-pack: 1.18 MiB
$ git ls-files -z | xargs -0 du -cb | tail -1
373398  total
$ git log --oneline | wc -l
185
```

`output/` 占了工作树 373 KB 的 **72%**（258,998 + 8,454 + 1,118）。压缩后整个历史 1.18 MiB，182 次每日提交 → **平均每次提交只增约 6.6 KB**。

结论：**"git 历史被撑爆"这个担心在当前规模下不成立**（一年约 2.3 MB）。真正的代价是历史语义被淹没：`git log` 里 98% 是 `Update IPTV <时间戳>`，`git blame` 对 `output/` 无意义，人工提交被埋在 182 条噪音里。

---

## 二、CI 质量分析（逐条回答）

### 2.1 step 逐条审读

| # | step（行号） | 问题 |
|---|---|---|
| 1 | `Checkout` `update.yml:32-36` | `fetch-depth: 1`（够用，工作树 diff 不需要历史）；`persist-credentials: true` 显式写死（本就是默认） |
| 2 | `setup-python` `:38-41` | **无 `cache: pip`**；**无版本矩阵**；版本来自 `env.PYTHON_VERSION: "3.11"` 硬编码（`:22`） |
| 3 | `安装依赖` `:43-46` | `pip install --upgrade pip`（版本也不 pin） + `pip install -r requirements.txt`（无 lock、无 hash）；实测全新安装 **17s** |
| 4 | `抓取数据` `:48-56` | `--no-cache`；**注意这一步其实把整条流水线跑完了**（`main.py:16-123` 的 `run()` 无条件执行验证/分组/生成），不只是"抓取" |
| 5 | `生成播放列表` `:58-64` | `--skip-fetch`：**这一步必然是空转失败**，见 §2.3 |
| 6 | `检查是否有更新` `:66-76` | 判断条件写反，见 §2.2 |
| 7 | `提交并推送` `:78-87` | 用 `GITHUB_TOKEN`（默认凭证）；无 `permissions` 声明；无 concurrency 保护 |
| 8 | `上传产物` `:89-95` | `if: always()` + `retention-days: 7` → 失败也保留（✅），但只传 `output/` |

顺带两条：`workflow_dispatch` 声明了 `skip_validation` 输入（`:15-19`）**但从未传给命令**，是个纯装饰输入，手动触发时勾"跳过验证"没有任何效果；`fetch_timeout` 默认 300 而代码默认 90，两个默认值不一致。

### 2.2 P0：变更检测条件写反 → 无变化的那天必然红

```yaml
# update.yml:69
if git diff --stat output/ | grep -q "0 files changed"; then
  changed=false
```

`git diff --stat` 在**没有变化时输出空字符串，永远不会输出 "0 files changed"**。实测（当前工作树 `output/` 干净）：

```
$ git diff --stat output/
[空]
$ if git diff --stat output/ | grep -q "0 files changed"; then echo false; else echo true; fi
BRANCH: changed=true        ← 走了 else 分支
```

于是流程变成：无变化 → `changed=true` → `git add output/`（没有可加的东西）→ `git commit -m ...` → `nothing to commit` → **exit 1 → job 失败**。

后果是**反直觉的**：只要当天抓取结果和昨天逐字节一致（源站挂了、全部超时返回旧数据、或者干脆什么都没抓到），CI 就报红；而有变化的日子反而是绿的。真正的失败（抓取超时）会被当成"无变化 → commit 失败"来报告，日志里看不到根因。

正确写法（3 行）：

```bash
if git status --porcelain output/ | grep -q .; then
  echo "changed=true" >> "$GITHUB_OUTPUT"
else
  echo "changed=false" >> "$GITHUB_OUTPUT"
fi
```

`git status --porcelain` 还能覆盖 `git diff` 漏掉的**新增未跟踪文件**（`output/` 里将来多一个文件，现在的实现判断不出来）。

### 2.3 P0：第二步是空转，且失败不产生退出码

`update.yml:52` 的第一步带 `--no-cache`；`src/main.py:62-70` 走 `else` 分支抓取，**但这条路径不调用 `cache.set()`**：

```python
# main.py:46-61   use_cache=True 的分支才有 cache.set
        if channels_data: ...
        else:
            channels = await asyncio.wait_for(fetcher.fetch_all(), ...)
            cache.set(cache_key, [ch.__dict__ for ch in channels])   # ← 只有这里写缓存
# main.py:62-70   use_cache=False（--no-cache）分支
    else:
        channels = await asyncio.wait_for(fetcher.fetch_all(), ...)   # ← 没有 cache.set
```

所以第二步 `--skip-fetch` 永远读不到缓存。实测复现（清空缓存后）：

```
$ python -m src.main --skip-fetch --output /tmp/livetv_audit_out
[Step 1/4] 抓取频道...
  ❌ 跳过抓取但无缓存数据，请先正常运行一次抓取
❌ 运行失败
EXIT_CODE=0        ← 注意：失败，但退出码 0
```

两处工程缺陷叠加：

1. **`main()` 在失败时返回而不 `sys.exit(1)`**（`main.py:147-149`，全仓 `grep -n "sys.exit"` → 0 命中）。任何"运行失败"在 CI 里都是**绿色**的——包括真正致命的 `asyncio.TimeoutError`（`main.py:58-60`、`:68-70` 同样只 print 后 return）。
2. 第二步既然必然失败又退出 0，就成了**永久的假步骤**：它让 workflow 看起来"两阶段"（抓取 / 生成解耦），实际生成早在第一步做完了。这是"拆分缓存与生成"设计没做完留下的壳。

修法二选一：**（a）删掉第二步**（最小改动，立刻消除误解）；**（b）做真**——第一步 `--dump-raw raw.json`，第二步 `--from-raw raw.json`，中间用 `actions/cache` 或 artifact 传递，别依赖路径隐式约定的 `.cache`。无论哪种，`main()` 必须 `raise SystemExit(1)`。

另外缓存目录本身也是错的：

```
$ python -c "from src.lib.cache import SimpleCache; print(SimpleCache().cache_dir)"
/home/hermes/.hermes/projects/live-tv/src/.cache
```

`src/lib/cache.py:13` 用 `Path(__file__).parent.parent / ".cache"`，但 `cache.py` 在 `src/lib/` 里，`parent.parent` 是 **`src/`**，不是仓库根（`config.py:13`、`grouper.py:22`、`main.py:29` 同样的写法因为文件在 `src/` 下才碰巧正确）。于是缓存落在 `src/.cache/`，而 `.gitignore`（3 行）里没有 `.cache`，任何人本地跑一次都会得到 `?? src/.cache/`。

### 2.4 权限、并发、缓存、矩阵

| 检查项 | 现状 | 风险 |
|---|---|---|
| `permissions:` | **完全缺失** | 依赖仓库级默认设置。2023 年后新建仓库默认 `GITHUB_TOKEN` 只读，push 会 403；这个仓库显然是放宽到了可写，但**"能跑"是靠仓库设置而不是靠 workflow 声明**，改个设置就静默失效 |
| `concurrency:` | **缺失** | 定时触发 + `workflow_dispatch` 可同时跑两个 run：两个 run 各自 `git push origin HEAD:main`，后到者 non-fast-forward 失败；更糟的是**两个 run 交错写同一批产物**，先启动的慢 run 后推送，会用旧数据覆盖新数据 |
| pip 缓存 | 无 `cache: 'pip'` | 每次重下 aiohttp 等 wheel，实测 17s；属可优化但非致命 |
| 版本矩阵 | 无，单版本 3.11 硬编码 | 无法发现 3.12/3.13 的兼容问题；也无 `python-version-file` 与 `pyproject` 联动 |
| 步骤级 `timeout-minutes` | 无（只有 job 级 30） | 任一步骤挂起都会吃满 30 分钟后被整体 kill |

### 2.5 失败会不会有人知道

- **没有失败通知步骤**（无 issue 自动创建、无 webhook、无 Discord/Slack 推送）。
- GitHub 对 scheduled workflow 失败会给"最后修改 cron 的人"发邮件——依赖这个：一旦 `yy-niuma` 改了通知设置或邮箱过滤，失败就彻底静默。
- **没有连续失败检测**：不会因为"连续 5 天红"而升级告警。
- 结合 §2.3 的退出码问题，**可以让 job 变红的原因和真正的故障原因不是一回事**：真实故障（抓取超时）报成 commit 失败；而"什么都没抓到"这种情况可能连红都不会红（若上一次产物被覆盖成空文件，commit 反而成功）。

最低成本的补救（不增加外部依赖）：在 job 末尾加 `if: failure()` 的 step，用 `gh issue create`（或 `actions/github-script`）开一个带 `ci-failure` 标签的 issue，若同类 issue 已打开则追加评论。

### 2.6 `timeout-minutes: 30` 够吗（实测）

用**CI 的 Python 3.11** + 今天的真实数据（16,859 频道）：

| 阶段 | 3.11 实测 / 外推 |
|---|---:|
| 抓取 20 源 | ≈ 8.5s（网络稳定时） |
| 验证 16,859 URL（conc=20, timeout=10s） | **≈ 20.5~26.0 min**（10.8~13.7 url/s 四次实测外推） |
| 分组 | **217.4s（3.6 min）** |
| 生成 + 统计 | ≈ 2s |
| pip 安装 | ≈ 17s |
| **合计** | **≈ 24.5~30 min**（取验证 20.5~26.0 min） |

余量 **0~5.5 分钟**。这已经不是"够不够"的问题：**600 条样本外推的 26 分钟 + 分组 3.6 分钟 = 29.6 分钟，等于正好卡在 30 分钟上限**，而 GitHub 托管 runner 只有 2 vCPU（分组阶段单线程纯 CPU，会更慢）、出网质量更差。任一条件稍差当天就被 kill。**当前配置是"赌网络好"，不是"够用"。**

而且验证吞吐在四次同条件实测里从 13.7 掉到 10.8 url/s（差 27%），说明乐观侧完全不可依赖；每 100 条 URL 里约 58 条是超时/非 200，验证阶段就是纯串等网络。

而且一旦超时被 kill，产物推送可能停在半路（`git add` 已完成、`commit` 未执行等），第二天 checkout 会带着脏状态重来。

两个实测的提速手段（都不需要改业务逻辑）：

| 改动 | 验证吞吐 | 外推 16,859 条 | 依据 |
|---|---:|---:|---|
| 现状 conc=20 / timeout=10s | 10.8~13.7 url/s | 20.5~26.0 min | 实测（四次） |
| conc=50 / timeout=10s | 12.5 url/s | 22.5 min | 实测 |
| **conc=50 / timeout=5s** | **21.4 url/s** | **13.1 min** | 实测 |
| 分组正则预编译 | 122s → **1.0s**（同一 1,379 条样本，3.14） | 分组从 3.6 min → ~10s | 实测，见 §3.4 |

即：把 `Validator` 默认 `timeout` 从 10 降到 5、`max_concurrent` 20→50，加上正则预编译，整条流水线可从 24.5~30 min 压到 **~14 min**，30 分钟上限才有真实余量。

### 2.7 失败时的 artifact

有，且是有意的：

```yaml
# update.yml:89-95
- name: 上传产物（保留7天）
  uses: actions/upload-artifact@v4
  if: always()
```

但**调试价值很低**：它传的是 `output/`，而失败时 `output/` 里往往是 checkout 出来的**上一次的产物**（第一步没跑完就没写入），看起来像"成功产物"。要能调试，至少还应包含：`src/.cache/`（原始抓取快照）、`stats.json` 之外的阶段日志、以及一份 `git status --porcelain` 快照。理想做法是让 `output/` 在 step 开始时先被清空（或写到临时目录，最后再原子替换），这样 artifact 里"空"就等于"失败"，不会误导。

---

## 三、结构与工程规范问题

### 3.1 没有 `pyproject.toml` 的具体代价（不是抽象抱怨）

| 后果 | 具体表现 |
|---|---|
| **不可安装** | `pip install -e .` 直接失败；下游想复用 `categorize()` 只能 `sys.path.insert` 或复制代码 |
| **无法声明 entry point** | 只能用 `python -m src.main`；`src/__init__.py:3` 已经有 `__version__ = "1.0.0"`，但这个版本号无处可读、无 tag 对应 |
| **无法声明 `requires-python`** | 本地 venv 3.14.4、CI 3.11，中间差 3 个 minor，无任何机器可读约束 |
| **工具配置散落** | ruff/mypy/pytest 现在是"命令行参数"级别，无 repo 内配置 → 每个开发者跑出的结果不同（我这次就是靠临时 `--select` 拼出来的） |
| **无依赖单一来源** | 运行时依赖在 `requirements.txt`，开发/测试依赖**根本不存在**（连 pytest 都没声明），新人无从知道"要装什么才能跑测试" |
| **不可打包/发布** | 无 sdist/wheel，也无法被 Dependabot 的 `pip` 生态完整覆盖（每次 `pip install` 都在变） |

实证：

```
$ cd /tmp && /home/hermes/.hermes/projects/live-tv/.venv/bin/python -m src.main --help
Error while finding module specification for 'src.main' (ModuleNotFoundError: No module named 'src')
```

`python -m src.main` 只在**仓库根目录**可用。CI 能跑是因为 `actions/checkout` 后 `cwd` 正好在根目录——**"能跑"是路径巧合**。

### 3.2 `src/` 当包名：能跑，但不是标准做法

现在：`src/__init__.py` 存在（3 行）、`src/group/`、`src/lib/`，入口 `python -m src.main`。问题不在"能不能跑"，在于：

- 包名 `src` 是**布局名**而不是**项目名**，一旦 `pip install` 就会往 site-packages 里塞一个叫 `src` 的顶级包——和任何其它用裸 `src` 布局的项目冲突；
- `src/` 布局（src-layout）的标准形态是 `src/<真实包名>/`，即 `src/livetv/`，`pyproject` 里 `[tool.setuptools.packages.find] where=["src"]`；
- 没有 `__main__.py`，所以 `python -m src` 也不可用。

推荐形态（改动可控，`git mv` 即可）：

```
live-tv/
├── pyproject.toml
├── src/livetv/
│   ├── __init__.py        # __version__
│   ├── __main__.py        # from .cli import main; main()
│   ├── cli.py             # 原 main.py 的 argparse 部分
│   ├── pipeline.py        # 原 main.py 的 run()
│   ├── config.py
│   ├── fetcher/…
│   └── group/…
└── tests/
```

### 3.3 导入风格：三种写法并存

```
相对导入：  src/fetcher.py:9      from .config import Config
            src/validator.py:9-10 from .config import Config / from .fetcher import Channel
绝对导入：  src/main.py:8-13      from src.config import Config …
            src/grouper.py:5-7    from src.fetcher import Channel …
            src/generator.py:7-8  from src.logo_map import … / from src.group.categorizer import …
函数内导入：src/group/normalize.py:247  from src.lib.whitelist import is_hk_cdn_whitelisted（带 try/except ImportError 兜底）
            src/fetcher.py:158        import yaml
            src/main.py:40,50         from src.fetcher import Channel（在分支里重复导入两次）
```

同一个包里 `fetcher.py` 用相对、`grouper.py` 用绝对，结果是：**这套代码既不能 `import livetv`，也不能被 `pip install` 后正常使用**——`from src.xxx` 把它钉死在"仓库根目录 + 包名 src"这个特定布局上。

**循环导入**：目前**没有**（模块级依赖图是单向的）
`main → {config, fetcher, validator, grouper, generator, lib.cache}`、`grouper → {fetcher, group.categorizer, group.normalize}`、`generator → {logo_map, group.categorizer}`、`normalize → lib.whitelist`（函数内，规避了循环）。但有两处结构隐患：

1. `generator.py:8` 从 `group.categorizer` 导入 `is_hk_region`：**输出层依赖分类层内部判定**。分类规则一改，产物生成跟着变——这正是 `audit-a` 里"hk 列表混进 `🇨🇳 中国源` 分类"的根源之一（同一个判定函数在两处被不同方式调用）。
2. `normalize.py:246-251` 用 `try/except ImportError` 兜底一个**同仓模块**：这等于给"导入失败"写了一条静默降级路径（失败时所有 URL 优先级判定退化为 False），而且 import 失败这个事实不会有任何日志。同仓依赖不该需要兜底。

### 3.4 性能结构：一处 40 倍、一处白忙

**(a) 正则全部以字符串形式交给 `re.search`，命中率靠 re 的 512 条内部缓存——实际在狂编译。** cProfile（1,379 频道，3.14）：

```
ncalls      tottime  cumtime  function
     1        0.016   40.169   grouper.py:36(group)
  1371        0.007   39.884   grouper.py:87(_match_group)
  1371        0.076   39.877   categorizer.py:466(categorize)
792245        0.873   38.811   re/__init__.py:174(search)
795153        4.621   37.460   re/__init__.py:330(_compile)     ← 79 万次 search 里 30 万次触发重新编译
307458        1.529   27.487   re/_compiler.py:757(compile)
 80039        0.296   22.258   categorizer.py:48(_match)
```

`categorizer.py:56` 的 `any(re.search(p, full, re.IGNORECASE) for p in patterns)` 每次传字符串；`re` 的模块级缓存只有 512 条，而这个文件里正则字面量的规模是（AST 统计）：`categorize()` 265 个字符串字面量、`is_hk_region()` 207 个、`recategorize_others()` 133 个，外加 `PROVINCE_KEYWORDS` 的 **32 组 / 217 条** —— 实测去重后共 **634 个不同 (pattern, flags)**。交替访问把 512 条缓存冲干净，于是 97% 的时间花在**编译正则**上，不在匹配。

我用 monkeypatch（不改源码，只替换 categorizer 手里的 `re` 引用）验证修法效果：

```
without cache:  1,379 channels in 40.2s   (3.14)
with precompiled: 1,379 channels in  1.0s  ← 40×
distinct (pattern,flags) compiled: 634     ← 全项目其实只有 634 个不同模式
```

对应到 16,859 频道：3.14 下 122.3s → **约 3s**；3.11 下 217.4s → **约 5s**。修法是纯机械的：把模式表在模块加载时 `re.compile` 成 `Pattern` 对象（或写一个 `_rx_cache` 包一层），634 个模式一次性编完不到 50ms。

**(b) `Validator` 每条 URL 新建一个 `ClientSession`**（`validator.py:69`，在 `_check_url` 内部）。这看着像明显瓶颈（每次都要 TCP+TLS 握手），但**我实测了，不需要改**：

```
per-request session (current)    120 urls in 13.6s -> 8.8 url/s
shared session (proposed)        120 urls in 14.0s -> 8.6 url/s   ← 无收益
```

原因：瓶颈是远端不响应（等 timeout），不是握手。所以正确结论是：**这条是代码整洁度问题（P2），不是性能问题；真正的旋钮是 `timeout` 和 concurrency**（§2.6 的 13.1 min 就是这么来的）。写在这里是为了避免后续有人"优化"了这里却以为解决了 CI 超时。

**(c) `logo_map.get_logo_fuzzy()` 对未命中的频道做线性全表扫描**（`logo_map.py:294-301`，300+ 键，每个还判 `is_cjk` 逐字符），由 `generator.build_extinf()`（`generator.py:89`）对**每条输出记录**调用。生成阶段实测只有 1.3s，暂不构成问题，但一旦放开 §P0-1 的 100/组截断（把 8,450 条全写出），这一步会线性放大 7 倍。

### 3.5 死代码与不可达逻辑（都实测确认）

| 位置 | 内容 | 判定 |
|---|---|---|
| `categorizer.py:59-95` | `_excluded()` 37 行，`grep -rn "_excluded" src` 只有定义本身 | **完全无人调用** |
| `categorizer.py:222-236` | `is_hk_region()` 尾部：`for p in hk_exact+tw_exact+mo_exact: return True` 之后的所有分支最终都 `return False` | **不可达**（无论条件如何结果都是 False），这段 `non_hk_groups` 判定的存在只制造"这里做了排除"的错觉 |
| `categorizer.py:141,143,396` | `r"\\bttv\\b"`、`r"\\\\bmacau\\\\b"` 等**双反斜杠**模式 | **永不匹配**。正则里 `\\b` 是"字面反斜杠 + b"。实测 `re.search(r"\\bmacau\\b", "Macau TV", re.I) → None`；后果是 `Macau TV` 这种频道 `categorize()` 判成 `🇲🇴 澳门`，而 `is_hk_region()` 返回 `False` → **不进 hk_merged.m3u**（同一个频道两套判定打架） |
| `normalize.py:126-134` | `_SPECIAL_MAPPING` 字典在函数体内每次调用重建 | 每频道一次；顺便这 6 条特例是硬编码在代码里的业务规则 |
| `normalize.py:84` | `re.compile(r'\s+')` 的 sub 目标是 `''`（`strip_noise` 内 `pat.sub('', result)`） | **把所有内部空格删掉**：`strip_noise("TVB 翡翠台") → "TVB翡翠台"`、`"CCTV5 体育 1080P" → "CCTV5体育"`。`logo_map` 里同时存在 `"tvb翡翠台"` 和 `"tvb 翡翠台"` 两套键、`get_logo_fuzzy` 里额外的 `norm_nospace` 分支，都是在给这个 bug 打补丁 |
| `grouper.py:48-73` | Channel → dict → `normalize_channels` → 再 dict → Channel 的空转往返 | 只为了复用 `merge_duplicate_channels(dict[])` 的签名；中间丢失 `raw_attrs`（`_source`/`_priority` 在合并后全部消失） |
| `fetcher.py:15-22` | `Channel.__init__` 里 `self.raw_attrs = kwargs` 之后又 `kwargs.pop("_normalized_name", ...)` | 两行操作同一个 dict，靠顺序耦合；`**kwargs` 里塞私有字段是隐式契约（`grouper` 依赖它） |

### 3.5b 异常被当成"有效"：验证器最危险的一处写法

`validator.py:26-27`：

```python
results = await asyncio.gather(*tasks, return_exceptions=True)
return [ch for ch, valid in zip(channels, results) if valid]     # ← valid 可能是异常对象
```

`return_exceptions=True` 让异常作为**返回值**留在 `results` 里，而 `if valid` 对异常对象恒为 `True`——于是"验证过程报错"被解释成"验证通过"。实测（真实入口 `validate()`，7 条畸形 URL）：

```
  bad-ipv6-bracket   result=ValueError     kept_by_validate()=True   Invalid IPv6 URL
  bad-port           result=bool           kept_by_validate()=False
  space-in-url       result=bool           kept_by_validate()=False
  no-scheme          result=bool           kept_by_validate()=False
  ctrl-char          result=bool           kept_by_validate()=False
  empty-host         result=bool           kept_by_validate()=False
  rtmp-scheme        result=bool           kept_by_validate()=False

validate() 实际保留: ['bad-ipv6-bracket'] (1/7)
```

触发条件是 `urlparse()` 抛异常（未闭合的 IPv6 方括号是最典型的一条，`_is_proxy_domain` 里第一步就调它，`_validate_one` 的 `try` 只覆盖了 `_check_url`，`try/except (aiohttp.ClientError, asyncio.TimeoutError)` 也不含 `ValueError`）。所以产物里能出现 `http://[::1/list.m3u8` 这种非法 URL。

修法（两行）：

```python
    return [ch for ch, valid in zip(channels, results) if valid is True]
```

外加把 `_validate_one` 的整段包进 `except (aiohttp.ClientError, asyncio.TimeoutError, ValueError)`。

顺带一个同类隐患（mypy 已经报了）：`validator.py:20` / `fetcher.py:40` 的 `self._semaphore = None`，只在 `validate()` / `fetch_all()` 开头赋真实值。单独调 `_validate_one()` / `_fetch_url()` 会得到

```
TypeError: 'NoneType' object does not support the asynchronous context manager protocol
```

——这是"必须先调 A 才能调 B"的隐式时序契约，没有断言、没有文档，测试里一碰就炸。

### 3.6 复杂度（AST 统计，前 6）

| 函数 | 行数 | 分支数 | 位置 |
|---|---:|---:|---|
| `categorize` | 205 | 26 | `categorizer.py:466` |
| `is_hk_region` | 136 | 15 | `categorizer.py:101` |
| `run` | 108 | 9 | `main.py:16` |
| `recategorize_others` | 96 | 28 | `categorizer.py:365` |
| `normalize_channel_name` | 82 | 15 | `normalize.py:102` |
| `generate_hk_and_all` | 78 | 11 | `generator.py:105` |

`categorize()` 205 行、13 个顺序 if 块、265 个字符串字面量（去重后全文件 634 个不同正则）——**没有任何单元测试覆盖**。这是"零测试"代价最高的一处：它是全项目唯一决定产物正确性的函数，也是唯一没法用类型或 lint 保护的部分（`audit-a` 已证明它的 13 个分类里有 13 个死分类）。

### 3.7 `.gitignore` 只有 3 行

```
__pycache__/
*.pyc
.venv/
```

缺：`.cache/`（当前 bug 会写到 `src/.cache/`）、`.ruff_cache/`、`.mypy_cache/`、`.pytest_cache/`、`*.egg-info/`、`build/`、`dist/`。我这次审计跑完 `compileall`+`ruff`+`mypy` 之后，工作树里多出了 `.ruff_cache/`、`.mypy_cache/`、`src/.cache/`、3 个 `__pycache__/`——全部 `untracked`，只因为 `.gitignore` 只挡了其中一种。

### 3.8 文档

| 项 | 状态 |
|---|---|
| `README.md` | 2,162 字节 / 52 行。有：简介、播放列表地址、频道统计表、免责声明。**没有**：安装、运行命令、参数说明、配置格式（`sources.yaml` 每个字段什么意思）、产物说明、CI 说明、贡献方式 |
| 播放列表 URL | **404**（实测）：README 写 `yy-niuma/iptv`，仓库实际是 `yy-niuma/live-tv` |
| `CHANGELOG.md` | 无 |
| `LICENSE` | 无（README 只有"仅供个人学习研究"的免责声明，不构成授权） |
| `CONTRIBUTING.md` | 无 |
| 配置说明 | `config/sources.yaml` 有注释（`priority: 1=最高优先…`），`alias.txt` 168 行**无任何格式说明**（代码支持 `->` 和 `=` 两种分隔符，`grouper.py:28-31`，文档里没写） |

README 数字与实际（我实测）：`all_merged.m3u` 头行写 `# Total: 8168 channels, 51 categories`，文件里 `#EXTINF` 实际 **1168** 条（100/组截断，见 `audit-d`/基线 P0-1）；`stats.json` 51 组 / 8,450；README 写 "52 个分组 / 14,224 频道 / hk 162 个频道"，hk 实际 33。**同一件事四个数字，全部不一致。**

---

## 四、缺陷清单

### P0（阻断性：让质量无法保证 / 让 CI 说假话）

| ID | 缺陷 | 证据 | 影响 |
|---|---|---|---|
| **C-P0-1** | **零测试 + 零回归基线**，核心分类/合并/生成逻辑 672 行无任何断言 | `find -name 'test*'` 空；`git shortlog` 仅 3 个人类提交 | 任何改动都无法判断是否回归；产物数量在 18~39 间漂移无人知 |
| **C-P0-2** | **失败不产生非零退出码**，CI 无法感知"运行失败" | `main.py:147-149` 只 print+return；全仓 0 处 `sys.exit`；实测 `--skip-fetch` 无缓存 → `EXIT_CODE=0` | 抓取超时/无数据在 CI 里是绿的 |
| **C-P0-3** | **CI 无任何质量门禁**（无 lint、无类型检查、无测试步骤） | `update.yml` 8 个 step 全是运行/提交/上传 | 106 个 ruff 问题、19 个 mypy 错误、9 个未用 import 长期存在 |
| **C-P0-4** | **变更检测条件写反**：无变化当天必然红 | `update.yml:69` + 实测 `BRANCH: changed=true`（diff 为空） | 真实故障被误报成 commit 失败，告警语义完全错位 |

### P1（显著影响稳定性/可维护性）

| ID | 缺陷 | 证据 | 影响 |
|---|---|---|---|
| **C-P1-1** | 30 分钟超时余量 0~5.5 分钟（3.11 实测外推 24.5~30 min，600 条样本悲观侧 29.6 min ≈ 顶满上限） | §2.6 实测表 | 网络抖动即被 kill，当天无产物 |
| **C-P1-2** | 4 个依赖无上界、无 lock、无 Dependabot、2 个依赖根本没用 | `requirements.txt`；`grep aiofiles/charset_normalizer src` → 0 | 上游 minor 变更可让每日 CI 长期红且难复现 |
| **C-P1-3** | CI 第二步永久空转（`--no-cache` 不写缓存 + `--skip-fetch` 必失败） | `main.py:62-70` 无 `cache.set`；实测输出 | 误导性流程结构，隐藏"生成只在第一步发生"的事实 |
| **C-P1-4** | 无 `concurrency`、无 `permissions` 声明 | `update.yml` 全文 | 并发 run 互踩 push / 依赖仓库默认权限才能推 |
| **C-P1-5** | 无失败通知、无连续失败检测 | `update.yml` 无 `if: failure()` step | 只能靠 GitHub 邮件，静默失败风险高 |
| **C-P1-6** | 分组正则未预编译：3.11 下 217s（占全流程 CPU 的 99%） | cProfile 79 万次 search / 30 万次 compile；预编译后 40.2s→1.0s | 直接吃掉 CI 超时余量 |
| **C-P1-7** | `README.md` 播放列表 URL 404 + 全部数字失真 | 实测 `404` vs `200`；`#EXTINF` 1168 vs 声称 14,224 | 用户按 README 订阅什么都拿不到 |
| **C-P1-8** | **`validate()` 把异常当成"有效"**：`[ch for ch, valid in zip(channels, results) if valid]`（`validator.py:27`）里 `valid` 可能是 `gather(return_exceptions=True)` 返回的异常对象，而异常对象恒为真 | 实测 `validate([7 条畸形 URL])` → 保留 `http://[::1/list.m3u8`：`urlparse` 抛 `ValueError: Invalid IPv6 URL`，未在 `_validate_one` 内捕获 → 异常被当 True → 频道保留 1/7 | 非法 URL 直接进入产物；且真正的 bug 会被"看起来验证过了"掩盖 |

### P2（工程规范/可维护性）

| ID | 缺陷 | 证据 |
|---|---|---|
| C-P2-1 | 无 `pyproject.toml`：不可安装、无 entry point、无 `requires-python`、工具配置散落 | `cd /tmp && python -m src.main` → ModuleNotFoundError |
| C-P2-2 | 导入风格三种并存（相对 2 文件 / 绝对 5 文件 / 函数内 4 处） | §3.3 清单 |
| C-P2-3 | 缓存目录算错：落在 `src/.cache/` 而非仓库根 | 实测 `cache_dir=…/src/.cache` |
| C-P2-4 | `.gitignore` 仅 3 行，缺 `.cache/ .ruff_cache/ .mypy_cache/ .pytest_cache/` | §3.7 |
| C-P2-5 | 死代码：`_excluded()` 37 行、`is_hk_region` 不可达尾部 15 行、`original` 未用、`_SPECIAL_MAPPING` 每次重建 | §3.5 |
| C-P2-6 | 双反斜杠正则永不匹配（`\\bmacau\\b` 等 **9 处**，分布在 `141 / 143 / 396` 三行），导致 `Macau TV` 判不进 HK | 实测 `re.search(r"\\\\bmacau\\\\b", "Macau TV", re.I) → None`；`categorize("Macau TV")="🇲🇴 澳门"` 但 `is_hk_region("Macau TV")=False` |
| C-P2-7 | `strip_noise` 删除所有内部空格（`\s+`→`''`），下游靠 `norm_nospace` 打补丁 | `normalize.py:84`；`TVB 翡翠台 → TVB翡翠台` |
| C-P2-8 | `logo_map.py:47` 重复键 `"viutv"` | ruff F601 |
| C-P2-9 | 库层用 `print`（9 处），全仓 0 处 logging | `fetcher.py`/`grouper.py` |
| C-P2-10 | 逐 URL 建 `ClientSession`（整洁度问题，实测无性能收益） | `validator.py:69`；8.8 vs 8.6 url/s |
| C-P2-11 | 输出层依赖分类层内部函数 `is_hk_region` | `generator.py:8` |
| C-P2-12 | `output/` 每日提交：历史噪音（182/185 是机器人）、无 `.gitattributes` | `git count-objects`：1.18 MiB，增长约 2.3 MB/年 |
| C-P2-13 | 无 LICENSE / CHANGELOG / CONTRIBUTING；README 无安装运行说明 | `git ls-files` 26 个文件 |
| C-P2-14 | 单文件 670 行、`categorize()` 205 行 26 分支 | AST 统计 §3.6 |
| C-P2-15 | `workflow_dispatch.skip_validation` 输入声明但从未使用 | `update.yml:15-19` vs 命令行 |

---

## 五、改进方案与落地顺序

原则：**先让"坏"能被发现（退出码 + 门禁 + 最小测试），再让它跑得更快/更干净。** 顺序按"每步都能独立合并、独立回滚"排。

### 第 1 步（0.5 天，P0）：让 CI 说真话

**(1) `main()` 失败必须非零退出**

```python
# src/main.py:147-149
    if result is None:
        print("\n❌ 运行失败", file=sys.stderr)
        raise SystemExit(1)
```

**(2) 修变更检测**（`update.yml:66-76`）

```yaml
      - name: 检查是否有更新
        id: changes
        run: |
          if [ -n "$(git status --porcelain output/)" ]; then
            echo "changed=true"  >> "$GITHUB_OUTPUT"
            git status --porcelain output/
          else
            echo "changed=false" >> "$GITHUB_OUTPUT"
            echo "📭 output/ 无变化"
          fi
```

**(3) 删掉空转的第二步**（`update.yml:58-64`），或按 §2.3(b) 改成显式 `--dump-raw/--from-raw`。最小改动是删。

**(4) 产物保险丝**：提交前校验，防"静默产出空文件"

```yaml
      - name: 产物体检
        run: |
          python - <<'EOF'
          import json, sys, pathlib
          d = json.load(open("output/stats.json"))
          total = sum(d.values())
          hk = sum(v for k, v in d.items() if any(x in k for x in ("TVB","ViuTV","RTHK","HOY","Now","台湾","澳门")))
          print(f"channels={total} hk={hk} groups={len(d)}")
          if total < 3000: sys.exit("频道总数异常 < 3000")
          if hk == 0:      sys.exit("港澳台频道为 0")
          EOF
```

### 第 2 步（1~2 天，P0）：最小可行测试集

**必须先有测试的函数**（按"改坏概率 × 影响面"排序）：

| 优先级 | 函数 | 位置 | 为什么先测它 | 建议用例数 |
|---|---|---|---|---:|
| 1 | `categorize` | `categorizer.py:466` | 唯一决定产物分类的函数，205 行 26 分支、13 个死分类（`audit-a`），历史上全是这里出问题 | 40~60（表驱动 golden） |
| 2 | `strip_noise` / `normalize_channel_name` | `normalize.py:88,102` | 每个频道都过；空格/繁简/别名三层叠加，改一行影响全量 | 20 |
| 3 | `merge_duplicate_channels` | `normalize.py:237` | 决定"同名合并 + 最多 2 备用 + HK CDN 优先"三条业务规则 | 12 |
| 4 | `is_hk_region` | `categorizer.py:101` | 决定 hk 列表内容；已确认与 `categorize` 判定不一致（`\\b` bug） | 20 |
| 5 | `is_clean_name` / `build_extinf` / `generate_hk_and_all` | `generator.py:69,83,105` | 决定输出文件字节；100/组截断、头部计数、EXTINF 格式 | 12 |
| 6 | `Fetcher._fetch_m3u` 的解析逻辑 | `fetcher.py:99` | 所有源的第一道关（`#EXTINF` 正则、属性名归一） | 10（需先重构，见下） |
| 7 | `Validator._is_valid_response` / `validate` 的异常语义 | `validator.py:80,22` | 决定删不删频道；`validate()` 现会把异常当有效（C-P1-8） | 8 |
| 8 | `SimpleCache` TTL | `cache.py:18` | 决定"跳过抓取"是否有效（CI 第二步就死在这里） | 4 |
| 9 | `Config` 加载 | `config.py:37-57` | 配置格式陷阱（空列表被当成"未加载"） | 4 |

**必须先做的一处小重构**：`_fetch_m3u()` 把 HTTP 和解析耦在一起（`fetcher.py:99-148`）。抽出纯函数即可测：

```python
# src/fetcher.py
def parse_m3u(text: str) -> list[Channel]:   # 纯函数，无 aiohttp
    ...

async def _fetch_m3u(self, url: str) -> list[Channel]:
    ...
    return parse_m3u(text)
```

**建议的测试文件（内容可直接落地，我在 scratch 目录用现有源码跑过其中 8 条全部通过）**：

`tests/test_categorize_golden.py` —— 表驱动，这是防回归的主力

```python
import pytest
from src.group.categorizer import categorize, is_hk_region

GOLDEN = [
    # (name, group, logo, 期望分类)
    ("CCTV-1 综合",      "",        "", "📺 央视频道"),
    ("CCTV5 体育",       "",        "", "📺 央视频道"),
    ("CETV-1",           "",        "", "📺 央视频道"),
    ("翡翠台",           "",        "", "📺 TVB"),
    ("TVB Plus",         "",        "", "📺 TVB"),
    ("ViuTV6",           "",        "", "📺 ViuTV"),
    ("RTHK 31",          "",        "", "📺 RTHK"),
    ("HOY TV",           "",        "", "📺 HOY TV"),
    ("凤凰卫视中文台",   "",        "", "📡 卫视频道"),
    ("TVBS新闻",         "",        "", "🇹🇼 台湾"),
    ("东森新闻",         "",        "", "🇹🇼 台湾"),
    ("澳门莲花卫视",     "",        "", "🇲🇴 澳门"),
    ("HBO",              "Movies",  "", "🎬 电影频道"),
    ("Discovery Channel","",        "", "📺 纪录片"),
    ("BBC World News",   "",        "", "🌐 国际频道"),
    ("Cartoon Network",  "",        "", "🧸 儿童频道"),
    ("ESPN",             "Sports",  "", "⚽ 体育频道"),
    ("MTV",              "Music",   "", "🎵 音乐频道"),
    ("广东卫视",         "",        "", "📺 广东"),
    ("湖南卫视",         "",        "", "📺 湖南"),
]

@pytest.mark.parametrize("name,group,logo,expected", GOLDEN)
def test_categorize_golden(name, group, logo, expected):
    assert categorize(name, group, logo) == expected

# 已知缺陷的"契约测试"：先标 xfail，修好后去掉标记。
# 这些不是猜测——\\b 被写成 \\\\b，正则在找字面反斜杠。
@pytest.mark.xfail(reason="C-P2-6: r'\\\\bmacau\\\\b' 永不匹配", strict=True)
def test_macau_latin_name_is_hk():
    assert is_hk_region("Macau TV", "Macau") is True

@pytest.mark.xfail(reason="C-P2-7: strip_noise 删除全部空格", strict=True)
def test_space_preserved():
    from src.group.normalize import strip_noise
    assert strip_noise("TVB 翡翠台") == "TVB 翡翠台"
```

`tests/test_generator.py`

```python
from src.fetcher import Channel
from src.generator import Generator, build_extinf, is_clean_name

def test_build_extinf_format():
    ch = Channel(name="翡翠台", url="http://x/1.m3u8", logo="http://l.png")
    line = build_extinf(ch, "📺 TVB")
    assert line == '#EXTINF:-1 tvg-name="翡翠台" tvg-logo="http://l.png" group-title="📺 TVB",翡翠台'

def test_is_clean_name():
    assert is_clean_name("Mozilla/5.0 Chrome/120") is False
    assert is_clean_name("") is False
    assert is_clean_name("翡翠台") is True

def test_generate_per_group_cap(tmp_path):
    chans = [Channel(name=f"CH{i}", url=f"http://x/{i}.m3u8") for i in range(150)]
    res = Generator().generate_hk_and_all({"🎬 电影频道": chans}, str(tmp_path))
    body = (tmp_path / "all_merged.m3u").read_text(encoding="utf-8")
    # 当前行为（缺陷 C-P0-1，见 00-controller-baseline）：文件里只有 100 条，
    # 头部却写 150。修掉截断后，下面两行应改为 == 150 / 无 "and ... more"。
    assert res["all"]["channels"] == 150
    assert body.count("#EXTINF") == 100
```

`tests/test_normalize.py`

```python
from src.group.normalize import convert_tc_to_sc, get_url_priority, merge_duplicate_channels

def test_tc_to_sc():
    assert convert_tc_to_sc("翡翠台新聞") == "翡翠台新闻"

def test_url_priority_order():
    assert get_url_priority("http://tvb.com/a.m3u8") == 1
    assert get_url_priority("http://jdshipin.com/a") == 2
    assert get_url_priority("http://example.com/a") == 3

def test_merge_keeps_best_and_two_backups():
    chans = [
        {"name": "翡翠台", "_normalized_name": "翡翠台", "url": "http://example.com/1"},
        {"name": "翡翠台", "_normalized_name": "翡翠台", "url": "http://tvb.com/a"},
        {"name": "翡翠台", "_normalized_name": "翡翠台", "url": "http://example.com/2"},
        {"name": "翡翠台", "_normalized_name": "翡翠台", "url": "http://example.com/3"},
        {"name": "翡翠台", "_normalized_name": "翡翠台", "url": "http://example.com/4"},
    ]
    merged = merge_duplicate_channels(chans)
    assert len(merged) == 1
    assert merged[0]["url"] == "http://tvb.com/a"          # HK CDN 优先
    assert len(merged[0]["_backup_urls"]) == 2             # 最多 2 个备用
```

`tests/test_validator.py`（挡住 C-P1-8；**第一条现在必然失败**——它断言的是正确行为，失败即复现缺陷）

```python
import pytest
from src.config import Config
from src.fetcher import Channel
from src.validator import Validator

def test_validate_drops_unparseable_url():
    """urlparse 抛异常的 URL 必须被判为无效，不能因为异常对象恒为真而保留。"""
    v = Validator(Config("config"))
    import asyncio
    kept = asyncio.run(v.validate([Channel(name="bad", url="http://[::1/list.m3u8")]))
    assert kept == []

@pytest.mark.parametrize("url,expected", [
    ("rtmp://example.com/live", False),
    ("example.com/a.m3u8",      False),
    ("http:///a.m3u8",          False),
])
def test_validate_rejects_malformed(url, expected):
    import asyncio
    v = Validator(Config("config"))
    kept = asyncio.run(v.validate([Channel(name="x", url=url)]))
    assert bool(kept) is expected
```

`tests/test_pipeline_snapshot.py`（**这条最重要，能一条挡住"hk 从 36 掉到 18"这类问题**）

```python
import json
from src.config import Config
from src.fetcher import parse_m3u            # 需先按上文抽出纯函数
from src.grouper import Grouper
from src.generator import Generator

FIXTURE = "tests/fixtures/sample.m3u"        # 30~50 条真实抓下来的片段，含港台/央视/省台/国际/脏名字

def test_pipeline_snapshot(tmp_path, monkeypatch):
    text = open(FIXTURE, encoding="utf-8").read()
    grouped = Grouper(Config("config")).group(parse_m3u(text))
    res = Generator().generate_hk_and_all(grouped, str(tmp_path))
    stats = json.loads((tmp_path / "stats.json").read_text()) if (tmp_path / "stats.json").exists() else {}
    assert res["hk"]["channels"] >= 8          # 港台不许无声掉下去
    assert res["all"]["channels"] >= 30
    assert (tmp_path / "all_merged.m3u").read_text().count("#EXTINF") == res["all"]["channels"]
```

配套 `pyproject.toml`（同时解决 C-P2-1）：

```toml
[project]
name = "live-tv"
version = "1.1.0"
requires-python = ">=3.11"
dependencies = [
  "pyyaml>=6.0,<7",
  "aiohttp>=3.9,<4",
]

[project.optional-dependencies]
dev = ["pytest>=8", "pytest-asyncio>=0.24", "ruff>=0.6", "mypy>=1.11"]

[project.scripts]
live-tv = "src.main:main"

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
addopts = "-q --strict-markers"

[tool.ruff]
target-version = "py311"
line-length = 110          # 现有代码 49 处 E501 里大半是长关键字表，110 更现实

[tool.ruff.lint]
select = ["E", "F", "W", "I", "B", "UP", "SIM", "ASYNC", "RUF"]
ignore = [
  "RUF001", "RUF002", "RUF003",  # 全角标点——中文项目必然误报
  "UP006", "UP035", "UP045",     # 本项目用 typing.List 风格，非 bug；要改另开 PR
  "EXE001",                      # 有 shebang 但无 x 位
]

[tool.mypy]
python_version = "3.11"
ignore_missing_imports = true
warn_unused_ignores = true
# 渐进：先只卡这几个最脏的文件
[[tool.mypy.overrides]]
module = ["src.lib.*", "src.config"]
disallow_untyped_defs = false
```

命令：

```bash
.venv/bin/pip install -e ".[dev]"
.venv/bin/ruff check src tests
.venv/bin/mypy src
.venv/bin/pytest
```

### 第 3 步（2 小时，P0/P1）：CI 重写

```yaml
name: Update IPTV Playlists

on:
  schedule: [{cron: "0 0 * * *"}]
  workflow_dispatch:
    inputs:
      fetch_timeout:
        description: "抓取超时秒数"
        default: "300"

permissions:
  contents: write          # 只给自己需要的权限（当前缺失）

concurrency:               # 防止定时 + 手动两个 run 互踩 push
  group: update-playlists
  cancel-in-progress: false

env:
  PYTHON_VERSION: "3.11"

jobs:
  check:
    name: 静态检查 + 测试
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
          cache: pip
      - run: pip install -e ".[dev]"
      - run: ruff check src tests --output-format=github
      - run: mypy src
      - run: pytest

  update:
    name: 抓取 → 验证 → 生成 → 推送
    needs: check
    runs-on: ubuntu-latest
    timeout-minutes: 40      # 实测 3.11 下 24.5~30 min，留 30% 以上余量
    steps:
      - uses: actions/checkout@v4
        with: {fetch-depth: 1}
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
          cache: pip
      - run: pip install .
      - name: 生成（单阶段，不再假装有第二阶段）
        run: python -u -m src.main --no-cache --fetch-timeout ${{ inputs.fetch_timeout || '300' }} --output ./output
      - name: 产物体检
        run: python scripts/check_output.py     # 见第 1 步 (4)
      - name: 检查是否有更新
        id: changes
        run: |
          if [ -n "$(git status --porcelain output/)" ]; then
            echo "changed=true" >> "$GITHUB_OUTPUT"
          else
            echo "changed=false" >> "$GITHUB_OUTPUT"
          fi
      - name: 提交并推送
        if: steps.changes.outputs.changed == 'true'
        run: |
          git config user.name  "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add output/
          git commit -m "chore(data): 更新播放列表 $(date -u +%Y-%m-%dT%H:%M:%SZ)"
          git push
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: iptv-output-${{ github.run_number }}
          path: |
            output/
            src/.cache/
          retention-days: 7
      - name: 失败开 issue
        if: failure()
        uses: actions/github-script@v7
        with:
          script: |
            await github.rest.issues.create({
              owner: context.repo.owner, repo: context.repo.repo,
              title: `CI 失败：${new Date().toISOString().slice(0,10)}`,
              labels: ['ci-failure'],
              body: `run: ${context.serverUrl}/${context.repo.owner}/${context.repo.repo}/actions/runs/${context.runId}`,
            })
```

要点：`permissions` 显式化、`concurrency` 防撞车、`cache: pip`、job 级 `needs: check`（门禁不过就不产出垃圾数据）、`timeout-minutes: 40`、单一生成阶段、产物体检、失败开 issue。

### 第 4 步（2 小时，P1）：依赖与超时

**依赖**：保留 2 个真依赖，加锁。

```
# requirements.in
pyyaml>=6.0,<7
aiohttp>=3.9,<4

# requirements-dev.in
-r requirements.in
pytest>=8
pytest-asyncio>=0.24
ruff>=0.6
mypy>=1.11
```

```bash
pip install pip-tools
pip-compile -o requirements.txt requirements.in          # 生成完整 pin（含传递依赖）
pip-compile -o requirements-dev.txt requirements-dev.in
pip install -r requirements.txt                          # CI 用这个
```

再删掉 `aiofiles`、`charset-normalizer`（当前 0 处 import），并开启 Dependabot：

```yaml
# .github/dependabot.yml
version: 2
updates:
  - package-ecosystem: pip
    directory: "/"
    schedule: {interval: weekly}
  - package-ecosystem: github-actions
    directory: "/"
    schedule: {interval: weekly}
```

**超时**（两处默认值，实测依据见 §2.6）：

```python
# src/validator.py:16
def __init__(self, config: Config = None, max_concurrent: int = 50, timeout: int = 5):
```

单独这一项就把验证阶段从 20.5~26.0 min 压到 13.1 min（实测 21.4 url/s）。

### 第 5 步（半天，P1）：正则预编译（40×）

在 `categorizer.py` 顶部加一层缓存，然后把所有模式表改成 `Pattern`：

```python
# src/group/categorizer.py 顶部
_RX: dict[tuple[str, int], re.Pattern] = {}

def rx(pattern: str, flags: int = 0) -> re.Pattern:
    key = (pattern, flags)
    p = _RX.get(key)
    if p is None:
        p = _RX[key] = re.compile(pattern, flags)
    return p

# 用法：把 _match()/_excluded()/is_hk_region() 里的
#     re.search(p, full, re.IGNORECASE)
# 改成
#     rx(p, re.IGNORECASE).search(full)

# 模块加载后一次性编完（634 个不同模式，<50ms）
def _warmup() -> None: ...
```

实测：1,379 频道 40.2s → 1.0s；16,859 频道 3.11 下 217s → 预计约 5s。**这一项单独把整个 CI 从 24.5~30 min 拉到 13~17 min。**

### 第 6 步（1~2 天，P2）：结构与文档

1. **包名归位**：`git mv src src/livetv`，配合 `[tool.setuptools.packages.find] where = ["src"]`，统一改成相对导入（`from .config import`），消除 `from src.xxx`。
2. **拆 `categorizer.py`（670 行）**：规则表移入 `rules/*.yaml` 或 `rules/*.py`（`province/geo/genre` 三张正交表），`categorize()` 变成"按优先级取第一条命中"，每张表可独立测试——`audit-a` 的重构方案可以直接接。
3. **清死代码**：删 `_excluded()`、`is_hk_region` 不可达尾部、`original`、`_SPECIAL_MAPPING` 上移；修 9 处 `\\b`（`categorizer.py:141,143,396`）；修 `strip_noise` 的 `\s+`（改成 `' '`），之后可以删掉 `logo_map` 里的 `norm_nospace` 补丁。
4. **缓存路径**：`cache.py:13` 改成 `Path(__file__).resolve().parents[2] / ".cache"`，或干脆由 `main.py` 显式传 `cache_dir`。
5. **`.gitignore`** 补齐 `.cache/ .ruff_cache/ .mypy_cache/ .pytest_cache/ *.egg-info/ build/ dist/`。
6. **日志**：`fetcher.py`/`grouper.py` 的 9 处 print 换 `logging.getLogger(__name__)`，`main()` 里 `logging.basicConfig(level=INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")`，这样 CI 日志能按级别过滤。
7. **文档**：README 补「安装 / 运行 / 参数 / 配置格式（`sources.yaml` 字段、`alias.txt` 的 `->` 与 `=` 两种分隔符）/ 产物说明 / CI 说明」；新增 `LICENSE`（MIT 或明确"数据仅索引，版权归原广播者"）、`CHANGELOG.md`（从 `1.1.0` 开始记）、`CONTRIBUTING.md`；README 里的数字改成**从 `stats.json` 自动生成**（用一个 `scripts/render_readme_stats.py`，别手写）。
8. **`output/` 发布方式**（P2，可选）：当前 1.18 MiB / 182 提交 / 年增约 2.3 MB，**不紧急**。若要清理：
   - 最省事：加 `.gitattributes` 标 `output/*.m3u linguist-generated=true -diff`，让 diff/统计里不显示噪音；
   - 更彻底：产物推到 **orphan branch `output`**（或 `gh-pages`），`main` 只留代码；消费者地址改成 `raw.githubusercontent.com/…/output/all_merged.m3u`。代价是 README 链接要换。
   - 不建议上对象存储（增加运维面，raw CDN 已经完全够用）。

### 落地顺序一览

| 顺序 | 内容 | 工作量 | 解决 |
|---|---|---|---|
| 1 | `sys.exit(1)` + 修变更检测 + 删空转步骤 + 产物体检 | 0.5 天 | C-P0-2/4, C-P1-3 |
| 2 | 最小测试集（先 golden categorize/normalize/generator 三件套） | 1~2 天 | C-P0-1 |
| 3 | CI 重写（门禁 + concurrency + permissions + 40 min + 失败 issue） | 2 小时 | C-P0-3, C-P1-4/5 |
| 4 | 依赖锁定 + 删无用依赖 + Dependabot；`timeout=5, conc=50` | 2 小时 | C-P1-1/2 |
| 5 | 正则预编译 | 半天 | C-P1-6 |
| 6 | 包名/规则表/死代码/日志/文档 | 1~2 天 | 全部 P2 |

前 3 步做完，这个项目就从"每天有人跑但没人知道对不对"变成"改坏了会红"。

---

## 六、我不确定 / 需要人工判断的点

1. **CI 实际耗时我无法直接观测**。我测的是本机（20 核、网络通畅）上的 `3.11` + 今天的数据：抓取 8.5s、分组 217s、验证外推 20.5~26.0 min（四次实测 10.8~13.7 url/s，**样本越大越慢**）。GitHub 托管 runner 是 2 vCPU，分组阶段可能更慢（单线程纯 CPU），验证阶段取决于 runner 出网质量。**建议第一次改造后加一步 `date +%s` 打点实测**，别直接信我的外推。另外今天 `raw.gh.registry.cyou` 两个源 DNS 挂了、`t.freetv.fun` 403，源存活情况每天都在变，验证阶段的 URL 数和超时率都会变——这也是"30 分钟够不够"没有稳定答案的原因，但它已经**没有安全侧**了：600 条样本算下来就是 29.6 分钟。

2. **`src/.cache` 的历史影响无法确认**。缓存路径落在 `src/` 下是确定的事实（实测），`--no-cache` 不写缓存也是确定的。但 CI 从 2026-04-25 起就是"第一步 `--no-cache`、第二步 `--skip-fetch`"，而 `output/` 确实每天都在变——说明**产物是第一步产出的**，第二步自始至终没起过作用。这与"第二步是空转"的结论一致，但我没有 CI 侧日志，无法 100% 排除某些历史版本的 `main.py` 在 `--no-cache` 下也写过缓存。要确认只能看 Actions 历史日志。

3. **"162 个频道"是笔误还是历史真实值**：全历史扫描最大 39，所以这个数字在本仓库从未成立。它可能来自另一个仓库（README 的 URL 指向 `yy-niuma/iptv`）。如果真有一个叫 `iptv` 的旧仓库，那里可能有别的数据——**需要仓库所有者确认**，我不猜。

4. **`output/` 是否必须留在 `main` 分支**：这取决于消费者是谁。如果有第三方播放列表在订阅 `raw.githubusercontent.com/yy-niuma/live-tv/main/output/all_merged.m3u`，迁到 orphan branch 会打断他们（虽然 raw 有 ~5 分钟 CDN 缓存）。**这是产品决策，不是工程决策**，我只提供了数据（1.18 MiB、年增 2.3 MB、182/185 提交是噪音）和三个选项。

5. **ruff 规则集的取舍需要团队定**：`--select E,F,W` 65 条里 49 条是 E501（长关键字表），把 `line-length` 设成 110 而不是 88 能让大部分消失。我给的是 110；如果你们偏好 88，就得接受重构 `PROVINCE_KEYWORDS` 的排版。`RUF001/002/003`（全角标点）对中文项目一定是纯噪音，我建议永久忽略——但这是团队口味。

6. **mypy 的 19 个错误值不值得修**：17 个是 `X | None` 注解写法，修起来机械但会产生大片 diff（`def f(x: T = None)` → `def f(x: T | None = None)`）。我建议**先只在 CI 卡 ruff，mypy 用 `--check-untyped-defs=false` 的非阻塞模式跑**，等测试体系建立后再收紧。是否现在就卡死，取决于你们对"注解当契约"的意愿。

7. **与 `audit-b-pipeline.md` 的一处结论冲突（我方实测占优，保留我方）**：`audit-b` 的 B-07 把验证器吞吐低归因于"每 URL 新建 `ClientSession`，无连接复用"，并建议共享 session。我用同一批 URL 直接对照测过：

   | 方案 | 耗时 | 吞吐 | 实建 session 数 |
   |---|---:|---:|---:|
   | 逐请求 session（当前实现） | 13.5s | 11.09 url/s | **150** |
   | 共享 session（audit-b 建议） | 14.0s | 10.71 url/s | 0 |

   共享 session **没有收益**（-3%），因为瓶颈是远端不响应（等 timeout），不是 TCP/TLS 握手。所以"共享 session"是代码整洁度改进（P2），**不是解决 CI 超时的手段**；真正的旋钮是 `timeout` 与 concurrency（§2.6：conc=50/timeout=5 → 21.4 url/s）。另外 audit-b 报的 "9.29 url/s" 与我的 10.8~13.7 url/s 属同区间，不冲突。

   冲突记录在此，避免后续合并方案时被两份报告带偏。

8. **`is_hk_region` 与 `categorize` 的判定不一致，哪个才是"对"的**：我确认了 `Macau TV` 被判 `🇲🇴 澳门` 但 `is_hk_region` 返回 `False`（`\\b` bug 导致）。修掉 bug 后 hk 列表会多出频道——**但"多"是不是"对"取决于业务意图**：hk 列表要不要收英文名的澳门台？这属于 `audit-a` 的规则设计范畴，我只提供机制证据。

9. **`charset-normalizer` 能不能删**：它是 `aiohttp` 的传递依赖，直接删 `requirements.txt` 不影响运行。但如果将来显式用它处理编码，又得加回来。我按"当前 0 处 import"判为可删。

---

## 附录：复现命令

```bash
cd /home/hermes/.hermes/projects/live-tv

# 规模 / 历史
git log --oneline | wc -l                       # 185
git shortlog -sn --all                          # 182 bot / 3 human
git count-objects -vH                           # size-pack 1.18 MiB
find . -name 'test*' -not -path './.venv/*'     # 空

# 静态检查
.venv/bin/python -m compileall -q src
.venv/bin/pip install ruff mypy pytest pytest-asyncio
.venv/bin/ruff check src                                    # 106
.venv/bin/ruff check src --select E,F,W                     # 65
.venv/bin/ruff check src --select E,F,W,B,UP,SIM,C4,RET,ARG,PL,PT   # 174
.venv/bin/mypy src --ignore-missing-imports                 # 19
grep -rn "print(" src --include=*.py | wc -l                # 41
grep -rn "logging" src | wc -l                              # 0
grep -rn "_excluded" src                                    # 只有定义
for m in aiofiles charset_normalizer; do grep -rn "$m" src | wc -l; done   # 0 0

# CI 逻辑缺陷
git diff --stat output/                                     # 空
if git diff --stat output/ | grep -q "0 files changed"; then echo false; else echo true; fi   # true（错）
.venv/bin/python -m src.main --skip-fetch --output /tmp/x    # 报失败但 EXIT_CODE=0
.venv/bin/python -c "from src.lib.cache import SimpleCache; print(SimpleCache().cache_dir)"   # …/src/.cache
cd /tmp && /home/hermes/.hermes/projects/live-tv/.venv/bin/python -m src.main --help          # ModuleNotFoundError

# 运行时基准（3.14）
.venv/bin/python /home/hermes/.hermes/cache/scratch/bench_fetch.py      # 8.5s / 16859 频道
.venv/bin/python /home/hermes/.hermes/cache/scratch/bench_cpu.py        # group 122s + gen 1.3s
.venv/bin/python /home/hermes/.hermes/cache/scratch/measure_validate.py 400   # 12 url/s
.venv/bin/python /home/hermes/.hermes/cache/scratch/bench_conc.py       # conc50/timeout5 → 21.4 url/s
.venv/bin/python /home/hermes/.hermes/cache/scratch/bench_precompile.py # 40.2s → 1.0s
.venv/bin/python /home/hermes/.hermes/cache/scratch/bench_session.py    # 共享 session 无收益

# 同上在 3.11（CI 版本）
/home/hermes/.local/bin/python3.11 -m venv /tmp/venv311
/tmp/venv311/bin/pip install -r requirements.txt
/tmp/venv311/bin/python /home/hermes/.hermes/cache/scratch/bench_cpu.py  # group 217.4s
```

基准脚本放在 `/home/hermes/.hermes/cache/scratch/`，并已归档到本报告的 `reports/bench/`（仓库外运行，未改动仓库任何源码）：

| 脚本 | 用途 |
|---|---|
| `bench_fetch.py` | 20 源抓取耗时 + 频道数 |
| `bench_cpu.py` | `Grouper.group()` / `Generator` 分阶段耗时（3.14 与 3.11 各跑一次） |
| `measure_validate.py N` | 验证 N 条 URL 的吞吐、外推到 16,859 条 |
| `bench_conc.py` | 不同 concurrency/timeout 组合对验证吞吐的影响 |
| `bench_session.py` | 逐请求 vs 共享 `ClientSession` 对比（结论：无收益） |
| `bench_precompile.py` | 正则预编译前后对比（40.2s → 1.0s） |
| `profile_group.py` | cProfile：定位 79 万次 `re.search` / 30 万次 `re.compile` |
| `test_probe_reference.py` | 建议测试的参考实现；其中 `test_strip_noise` 断言的是**期望行为**（空格保留），当前必然失败——那就是 C-P2-7 |
| `probe_malformed_urls.py` | 畸形 URL 走真实 `validate()` 入口，验证"异常被当有效"（C-P1-8）：1/7 被错误保留 |

脚本里用的是绝对路径（`/home/hermes/.hermes/projects/live-tv`），换机器需改两处 `sys.path.insert` 和输入文件路径。

审计过程产生的 `.ruff_cache/`、`.mypy_cache/`、`src/.cache/`、`__pycache__/` 已全部清理，`git status` 只剩未跟踪的 `reports/`。
