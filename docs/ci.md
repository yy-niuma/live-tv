# CI 与依赖锁定

> 本文引用的 `audit-c-engineering.md` / `work-plan.md` 是只读审计产出，**不入库**（见 `.gitignore`），只存在于本地磁盘。

本文对应 本地工作计划 `work-plan.md` 第 2 步（Lane B：CI + 依赖），
问题依据是 本地审计报告 `audit-c-engineering.md` §1.4（CI 里没有任何一步跑 lint / 类型 / 测试）、
§1.5（静态检查实测 106 / 19）、§3.1（没有 pyproject.toml 的代价）。

改动前的状态一句话：**CI 只验证了「脚本没崩」，代码质量、类型、测试一样都没管。**
改动后：`ruff` 与 `pytest` 是红就行不通的阻断门禁，`mypy` 是带编号的提示基线，
依赖从 4 条范围声明变成 23 个精确锁定的包。

---

## 1. 两个 job 各干什么

`.github/workflows/update.yml` 现在有两个 job，触发条件不同：

| job | 何时跑 | 干什么 | 失败会怎样 |
|---|---|---|---|
| `check` | `pull_request`、`workflow_dispatch`、`schedule` | 静态检查 → 类型检查 → 测试 | ruff / pytest 失败 = 红；mypy 失败 = 黄（不阻断） |
| `update` | `schedule`、`workflow_dispatch`（**PR 上被 `if` 挡掉**） | 抓取 → 生成 → 保险丝 → 提交推送 → 上传 artifact | 红，产物不提交 |

两个关键约束：

1. **`update` 在 PR 上必须不跑。** 它的最后一步是 `git push origin HEAD:main`，
   一个外部 PR 就能借它改主干。所以它带 `if: github.event_name != 'pull_request'`。
2. **两个 job 之间没有 `needs`。** 这是刻意的：`check` 是代码质量闸门，
   `update` 是每日生产任务，两者目标不同。若让 `update` 依赖 `check`，
   一次测试抖动（新测试集刚落地）就会让当天产物停更 —— 对使用播放列表的人来说，
   "因为 ruff 红了所以今天没有新播放列表"是比"代码风格不好"更严重的故障。
   代价是：主干上的代码即使 `check` 红，`update` 照样跑。这个取舍在
   测试集稳定、`check` 连续绿一周之后可以重新评估（改成 `needs: check`）。

### `check` 的 step 顺序（顺序就是逻辑）

```
Checkout → Set up Python 3.11 (pip cache) → 安装 requirements.txt + requirements-dev.txt
        → ruff check src/ scripts/          （阻断）
        → mypy src/                          （continue-on-error）
        → pytest tests/ -q                   （阻断）
```

- 先 lint 后测试：ruff 是秒级，能在 pytest 之前拦住"根本不该进测试"的问题（未使用导入、
  未定义名、重复字典键）。
- 两个 requirements 文件都装：`tests/` 会 `import src/`，而 `src/` 依赖 `aiohttp` / `yaml`。
  只装 `requirements-dev.txt` 会让 pytest 在 collection 阶段报 `ModuleNotFoundError`。
- `pytest tests/ -q` 不加 `-x` / `--maxfail`：要看到全量失败分布，不是一个失败就停。

### `update` 的 step 顺序

```
Checkout → Set up Python 3.11 (pip cache) → 安装 requirements.txt
        → 抓取（python -m src.main --no-cache）
        → 产物体检（python scripts/check_output.py output/stats.json）   ← 保险丝
        → git status --porcelain output/（变更检测）
        → 提交并推送（仅 changed=true）
        → 上传 artifact（always()，保留 7 天）
```

`timeout-minutes`：`check` 10 分钟，`update` 45 分钟。
（`update` 原为 30 分钟；`audit-c-engineering.md` §2.6 有实测耗时依据。）

`permissions` 一律写在 job 级（`check: contents: read`、`update: contents: write`），
**没有全局 permissions** —— 全局放宽等于给 `check` 也发写令牌，而它不需要。

`concurrency.group` = `${{ github.workflow }}-${{ github.ref }}`，
`cancel-in-progress: false`。定时任务本来就该排队；而 `update` 会 push，
运行到一半被取消会留下"提交了但 artifact 没上传"的半截状态。

---

## 2. 保险丝（`scripts/check_output.py`）为什么存在

它不属于本 lane（所有权见 本地工作计划 `work-plan.md` §2，加固任务 N-01），但它决定了
`update` job 的可信度，所以这里写清它防的是什么：

**没有它的时候，`update` 的失败模式是静默的。** `python -m src.main` 即使产出了空列表、
或者只输出几十条频道，只要退出码是 0，`update` 就会把这份坏产物当成正常结果提交推送上主干。
用户第二天打开播放列表，看到的是一份几乎空的 m3u，而 CI 是全绿的。
`audit-b-pipeline.md` §3.1、`audit-d-output.md` §1.2 记录过三套互相矛盾的数字，
正是"没人校验产物"的直接后果。

保险丝的作用就是在**提交之前**把产物打开、数一遍、对一遍，不达标就非零退出。
它和 `check` job 是两种不同的防线：

- `check` 保证**代码**没问题（能过 lint、能过测试）；
- 保险丝保证**这一次跑出来的产物**没问题（条数够、分组对得上、港澳台没被清空）。

两者互补，不能相互替代：代码全绿也可能因为上游源全挂而产出空列表。

---

## 3. 依赖锁定怎么维护

四个文件，职责不重叠：

| 文件 | 内容 | 谁改 |
|---|---|---|
| `requirements.in` | 直接运行时依赖的范围（`aiohttp>=3.9`、`pyyaml>=6.0`） | 人 |
| `requirements.txt` | 上述依赖的**完整传递闭包**，11 个包，全部 `==` 精确锁定 | dependabot 提 PR，人合 |
| `requirements-dev.in` | 直接开发依赖范围（pytest / pytest-asyncio / ruff / mypy） | 人 |
| `requirements-dev.txt` | 开发依赖闭包，13 个包，全部 `==` | dependabot 提 PR，人合 |

- **不写 hash**：CI 不是高安全场景，hash 锁会让每次 dependabot PR 变成几十行 diffs，
  维护成本远大于收益。防供应链的更强手段（`pip --require-hashes` + 内部索引）不在本轮范围。
- **闭包来源**：`.venv`（Python 3.14.4）的 `pip freeze`，23 个包全部在其中且版本一致；
  再用 Python 3.11.15（CI 版本）跑 `pip install --dry-run --report` 复算，解析结果逐条相同。
  这一点必须验，因为 `multidict 7.2.1` 的 `requires-python` 是 `>=3.11` ——
  这也正是 `requires-python = ">=3.11"` 不是随便写的原因。
- **删掉的两个包**：`aiofiles`、`charset-normalizer`。证据在 §5。
  `charset-normalizer` 尤其值得记一笔：它是 `requests` 的传递依赖，
  而本仓库从不 import `requests`（本地审计脚本 `bench/` 里也没有），所以它连"间接用到"都不成立 ——
  它只是从别处的 requirements 复制过来的。

`dependabot.yml`：pip 与 github-actions 都是 weekly（周一 09:00 Asia/Shanghai）。
pip 的 minor/patch 按 `production` / `development` 分成两组提 PR（运行时依赖要看行为，
工具链只看报告变化，审查成本不同）；大版本不分组，单独一个 PR 由人判断。

**改依赖的正确顺序**：改 `.in` → 重出闭包 → 本地跑 §4 的三条命令 → 提交。
不要只改 `.txt` 而不改 `.in`，否则下次谁按 `.in` 重算都会把你的改动覆盖掉。

---

## 4. mypy 为什么是提示而不是门禁

现状（2026-10-29 实测，`mypy src/`，配置见 `pyproject.toml`）：

```
Found 19 errors in 7 files (checked 14 source files)
```

分布（与 `audit-c-engineering.md` §1.5 的基线一致，一个没多一个没少）：

| 错误码 | 数量 | 性质 |
|---|---:|---|
| `assignment` | 11 | 其中 9 条是隐式 Optional（`def f(x: str = None)`），2 条是 `Path` 赋给 `str` |
| `union-attr` | 2 | `fetcher.py:90` `self._semaphore` 可能是 `None` |
| `arg-type` | 2 | `fetcher.py:55`（`list[Channel] \| BaseException`）、`normalize.py:181` |
| `var-annotated` | 1 | `fetcher.py:50` 缺注解 |
| `attr-defined` | 1 | `main.py:31` `"str" has no attribute "mkdir"` |
| `operator` | 1 | `main.py:116` `str / str` |
| `misc` | 1 | `normalize.py:250` 条件定义的两个同名函数签名不一致 |

**这些错误全部要改 `src/` 才能修**（把 `str = None` 改成 `str | None`、把 `output_dir`
的注解从 `str` 改成 `Path`、在 `fetch_all()` 之前给 `_semaphore` 加断言……），
而本轮的文件所有权明确禁止本 lane 触碰 `src/`（本地工作计划 `work-plan.md` §5）。

所以只有两个诚实选项：

1. 把 mypy 当门禁 → CI 从第一天就是红的，红着几天之后所有人开始无视它，门禁形同不存在；
2. 把 mypy 设成 `continue-on-error: true`，**同时把数字写死在这里当基线**。

选了 2，并且明确它的代价：**类型注解目前是装饰性的，不是契约**（audit-c §1.5 原话）。
`continue-on-error` 只影响 job 的结论，不影响日志 —— 每个 PR 的类型错误仍然会打印在
Actions 日志里，仍然可见，只是不拦合并。

**升级成门禁的条件**（写清楚，免得"临时"变成永久）：

1. 上述 19 条清零（或只剩有明确 `# type: ignore` 理由的条目）；
2. 清掉之后再收紧一档：`warn_unused_ignores = true`，防止 ignore 腐烂；
3. 然后才删掉 `continue-on-error: true`。

注意 `pyproject.toml` 里 `ignore_missing_imports = true` 是必需的，不是图省事：
`aiohttp` / `yaml` 都没有 `py.typed`，也没装 `types-PyYAML` 这类 stub 包，
不忽略的话会产生一批"找不到类型"的纯噪音错误。

---

## 5. 依赖裁剪的证据

两个依赖的零引用证明（本轮实际执行，输出为空、退出码 1 表示 grep 无匹配）：

```
$ grep -rn "aiofiles" src/ scripts/
（无输出，exit 1）

$ grep -rn "charset" src/ scripts/
（无输出，exit 1）
```

第三方 import 的真实清单（用 `ast` 扫全部 `.py` 的 `Import` / `ImportFrom`，
按 `sys.stdlib_module_names` 过滤标准库）：

```
src/config.py: yaml
src/fetcher.py: aiohttp
src/fetcher.py: yaml
src/validator.py: aiohttp
```

即只有 `aiohttp` 与 `yaml`。闭包的交叉验证也一致：`.venv` 的 `pip freeze` 有 25 个包，
而 `aiohttp + PyYAML` 的闭包是 23 个 —— 差的两个正好是 `aiofiles` 与 `charset-normalizer`。
换句话说，这两个包从来没有出现在任何依赖路径上，只是躺在 `requirements.txt` 里。

---

## 6. per-file-ignores 清账计划

`pyproject.toml` 的 `[tool.ruff.lint.per-file-ignores]` 是**逐文件、逐规则**的记账式豁免，
没有任何全局 `ignore`。当前总账：**11 个文件、83 处**（E501 ×61、F401 ×9、I001 ×6、
W293 ×3、F541 ×2、F601 ×1、F841 ×1）。

为什么要有这张表：`ruff check src/ scripts/` 必须退出码 0（门禁才有意义），
但 69 处问题必须改 `src/` 才能修，而本轮不许改 `src/`。**豁免可以，遗忘不行** ——
所以每一处都写清"几处 / 什么性质 / 归哪一节 / 什么时候清"。

| 文件 | 忽略规则 | 处数 | 原因（性质） | 清账计划 |
|---|---|---:|---|---|
| `src/group/categorizer.py` | E501 | 35 | 关键词/正则**数据表写成单行**，90~230 字符（最长在 524 行） | work-plan 3-4 拆 `rules/*.yaml`（audit-a §4.2）时自然消解 |
| `src/group/categorizer.py` | F401 / I001 / W293 | 2 / 1 / 3 | 未使用导入、导入未排序、空行含空格 | 3-4 时 `ruff check --fix` 一次清掉（可自动修） |
| `src/validator.py` | E501 / F401 | 3 / 2 | 长行（最长 126 字符）+ 未使用导入 | 3-4 折行 + `--fix` |
| `src/main.py` | E501 / F401 / I001 / F541 | 4 / 1 / 1 / 2 | 长提示串、`import os` 未用、导入未排序、无占位符 f-string | 3-4 时 `--fix` + 折行 |
| `src/fetcher.py` | F401 / I001 / E501 | 2 / 1 / 2 | 同性质；`typing.Any`、`dataclass` 未用 | 3-4（work-plan §5 点名第 3 轮才允许动） |
| `src/generator.py` | F401 / I001 / E501 | 1 / 1 / 1 | `import re` 未用、导入未排序、长表达式 | 3-4；`[:100]` 上限不动（N-01） |
| `src/group/normalize.py` | F401 / E501 / F841 | 1 / 1 / 1 | `typing.Tuple` 未用、长行、`original = name` 赋值后未用 | F841 是残留逻辑，优先级最高，3-1 之后由 src lane 判"是否恢复回退原名" |
| `src/grouper.py` | I001 | 1 | 导入未排序 | 3-4 `--fix` |
| `src/lib/cache.py` | I001 | 1 | 导入未排序 | 3-4 `--fix` |
| `src/config.py` | E501 | 1 | 57 行长常量 92 字符 | 3-4 折行 |
| `src/logo_map.py` | **F601** | 1 | **真 bug**：42 行与 47 行都定义 `"viutv"`，后者静默覆盖前者 | **唯一"忽略了一条能抓 bug 的规则"的地方**。在修掉之前，新增 logo 映射若重复键不会被发现。需人工确认哪个扩展名映射是对的，故不归本 lane，src lane 修 |
| `scripts/check_output.py` | E501 | 14 | 长中文提示串 / 函数签名，89~96 字符 | **不归本 lane**：该文件归 Lane C（保险丝加固），正在频繁改动；数字会漂移。Lane C 交付后由 Controller 在 work-plan §4 整合环节删除本条并折行 |

清账主线是 本地工作计划 `work-plan.md` 3-4（`src/` → `src/livetv/` 包名归位 + 拆
`categorizer.py`）—— 那一次 `ruff check --fix` 可以一次性消掉 I001 / F401 / F541 / W293
共 20 处，E501 折行后再消 47 处。剩下 2 处（F601、F841）是行为判断，必须人工。

---

## 7. 本地怎么跑这套检查

前置：Python 3.11+，`pyproject.toml` 在仓库根，命令都在仓库根执行。
（`.venv` 是 Python 3.14，也能跑，ruff/mypy 的结果与 3.11 一致；
CI 目标版本是 3.11 —— 这里命令用 `python`，按需换成 `python3.11` 或 `.venv/bin/python`。）

```bash
# 0) 装依赖（一次性）
python -m pip install -r requirements.txt -r requirements-dev.txt

# 1) 静态检查（阻断门禁，必须 exit 0）
ruff check src/ scripts/

# 2) 类型检查（提示，当前 19 个错误是已知基线，不许变多）
mypy src/

# 3) 测试（阻断门禁）
pytest tests/ -q

# 4) 保险丝（本地复现 update job 的最后一道关）
python scripts/check_output.py output/stats.json
```

三条命令连跑（等价于 CI 的 check job）：

```bash
ruff check src/ scripts/ && mypy src/ && pytest tests/ -q
```

注意 `&&`：mypy 在 CI 里是 `continue-on-error`，本地这样连会因为它非零退出而挡住 pytest。
本地复现 CI 语义请分开跑，或用：

```bash
ruff check src/ scripts/ && { mypy src/ || echo "mypy 非阻断，见 docs/ci.md §4"; } && pytest tests/ -q
```

### 校验配置真的生效了

```bash
ruff check --show-settings src/config.py | grep -E "Settings path|line-length|target-version"
# Settings path: ".../pyproject.toml"   ← 证明读的是 pyproject，不是默认值
```

### 改完 per-file-ignores 后必做

```bash
ruff check src/ scripts/ --statistics     # 看还剩什么
ruff check src/ scripts/                  # 必须 exit 0
```

如果 `--statistics` 里出现你刚加白名单的规则之外的新规则，说明你的改动让门禁变松了。

---

## 8. 踩过的坑（写给下一个改这个文件的人）

1. **PyYAML 把顶层 `on:` 解析成布尔 `True`。** 校验 workflow 时用 `yaml.safe_load`，
   `data` 的 key 会是 `True` 而不是字符串 `"on"`（YAML 1.1 里 `on`/`off`/`yes`/`no`
   都是布尔的同义词）。**这不是文件坏了。** 校验脚本必须同时检查 `True` 与 `"on"` 两个键，
   否则会误判成一个健康的工作流"缺少触发条件"。
2. **`cache: pip` 找不到依赖文件会直接报错。** `actions/setup-python` 的 pip 缓存需要能定位
   `requirements.txt`（或用 `cache-dependency-path` 明确指定）。本仓库两个 job 都显式写了
   `cache-dependency-path`，改文件名时要同步改这里。
3. **`permissions` 不要提到顶层。** 提到顶层会让 `check` job 也拿到 `contents: write`，
   而它一个写操作都没有。
4. **`continue-on-error` 只改结论，不改日志**，但它会让 step 显示为黄色通过；
   如果哪天有人把 `mypy` 的 `continue-on-error` 删了，`check` 会立刻变红 19 条 ——
   那是预期行为，不是新引入的 bug。
