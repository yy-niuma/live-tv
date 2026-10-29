# live-tv 整改工作计划（第 2 轮 fan-out）

**Controller**: Hermes 主 bot
**执行**: 小弟（opencode-go / deepseek-v4.1-flash）
**基准 commit**: `f75575a`（+ 第 1 轮未提交改动）
**制定时间**: 2026-10-29
**依据**: `reports/audit-c-engineering.md` §5 + 本轮新发现

---

## 0. 当前工作树状态（所有 lane 必须遵守）

```
M  src/main.py                        ← 第 1 轮已改并验证，勿回退
M  .github/workflows/update.yml       ← 第 1 轮已改并验证，Lane B 在其上继续
?? scripts/check_output.py            ← 第 1 轮新增，Lane C 修正
?? reports/                           ← 审计产出，不提交
```

**硬约束（写进每个 lane 的 brief）**：
- **不 commit / 不 push**
- **不执行** `git checkout --` / `git stash` / `git reset` / `git restore`
- 只碰「文件所有权表」里属于自己的文件
- 每个结论必须贴「实际命令 + 实际输出」，数字自己核
- 测试只能报全量结果，不许把子集当全量

---

## 1. 本轮新发现（P0，必须修）

### N-01 产物保险丝校验错对象

| 项 | 实测值 | 命令 |
|---|---|---|
| `output/stats.json` 频道总数 | **8450** | `python3 -c "import json;print(sum(json.load(open('output/stats.json')).values()))"` |
| `output/all_merged.m3u` 实际 `#EXTINF` | **1168** | `grep -c '^#EXTINF' output/all_merged.m3u` |
| `output/hk_merged.m3u` 实际 `#EXTINF` | **33** | `grep -c '^#EXTINF' output/hk_merged.m3u` |
| `stats.json` 港澳台合计 | **44** | TVB6+ViuTV1+NowTV1+RTHK3+HOY1+台湾30+澳门2 |

`src/generator.py:167-172` 有**设计内**的每分组上限：

```python
for ch in channels[:100]:          # ALL 播放列表每个分组最多 100 个
    ...
if len(channels) > 100:
    all_lines.append(f"# ... and {len(channels) - 100} more")
```

截断补算：`国际 3870→100`、`综艺 1005→100`、`新闻 679→100`、`音乐 673→100`、`电影 603→100`、
`卫视 403→100`、`儿童 371→100`、`记录 292→100`、`体育 282→100` ⇒ 共丢 **7278** 条，`8450-7278=1172` ≈ 实测 1168。

**结论**：
1. `[:100]` 上限**是有意的**，不是缺陷 —— 不要动 `generator.py`。
2. 但 `stats.json` 记的是**截断前**计数，而 `check_output.py` 只校验 `stats.json`。
   于是把 `[:100]` 误改成 `[:1]`，保险丝**照样通过**，交付物只剩 51 条。**保险丝对本轮要防的失效完全无效。**
3. `hk_merged.m3u` 33 条 vs 港澳台计数 44，差 11 条，成因未定（Lane C 查，勿预设结论）。

### N-02 `requirements.txt` 含两个零引用依赖

| 包 | 引用 | 命令 |
|---|---|---|
| `aiofiles>=23.0.0` | **0 处** | `grep -rn "aiofiles" src/ scripts/` → 空 |
| `charset-normalizer>=3.3.0` | **0 处** | `grep -rn "charset" src/ scripts/` → 空 |

实际第三方 import 只有 `aiohttp` 和 `yaml`。

---

## 2. 文件所有权表（核心：一条路径只能有一个 lane）

| Lane | 独占文件/路径 | 任务 | 预估 |
|---|---|---|---|
| **A** 测试集 | `tests/**`（全新目录）、`pytest.ini` | audit-c §5 第 2 步 | 大 |
| **B** CI+依赖 | `pyproject.toml`、`requirements.in`、`requirements-dev.in`、`requirements.txt`、`requirements-dev.txt`、`.github/workflows/update.yml`、`.github/dependabot.yml`、`docs/ci.md` | 第 4 步 + CI 门禁 | 中 |
| **C** 保险丝加固 | `scripts/check_output.py` | N-01 | 小 |
| **D** 文档 | `README.md`、`CHANGELOG.md`、`LICENSE`、`docs/architecture.md`、`docs/getting-started.md` | 第 6 步文档部分 | 中 |
| **E** 咖啡豆加固 | `~/.config/systemd/user/coffee-tracker.service.d/override.conf`（新文件，另一项目） | systemd 加固草案，**不 reload / 不 restart** | 小 |

**冲突自检**：无路径重复。`tests/` 仅 A 写；`docs/` 下 B 与 D 分属不同文件名，不重叠；
`update.yml` 仅 B 写（且必须在第 1 轮未提交改动之上继续，不许回退）。

---

## 3. 排队中（第 3 轮，等本轮落地后再派）

| 顺序 | 任务 | 前置条件 | 理由 |
|---|---|---|---|
| 3-1 | **正则预编译**（`src/group/categorizer.py`，3.11 下 217.4s → 约 5s） | **A 的测试必须已落地并绿** | 改动 `categorizer.py` 属行为敏感文件，必须有 golden 测试当护栏；与 A 同轮会造成「测试错还是重构错」无法区分 |
| 3-2 | 修 `\\b` 双反斜杠正则（9 处，`categorizer.py:141,143,396`） | 同上 | 属**行为变更**，会改变分类结果，须在 golden 测试就位后做，并同步更新 golden |
| 3-3 | 修 `strip_noise` 空格被误删 | 同上 | 同上 |
| 3-4 | `src/` → `src/livetv/` 包名归位 + 拆 `categorizer.py` | 3-1~3-3 完成 | 大 diff，必须测试全绿才动 |
| 3-5 | `validator.py` `if valid is True` 修复 | 无（可与 A 并行，但 A 要写它的回归测试） | 1 行改动 + 回归测试 |

---

## 4. 整合与验收清单（Controller 执行，不派给小弟）

本轮全部返回后，由 Controller 串行执行：

1. `git diff --name-only` 核对无 lane 越权写入
2. 运行**全量** `pytest tests/ -v`（唯一 runner，避免并行写测）
3. `ruff check src/ scripts/ tests/` + `mypy src/`，与审计基线（106 / 19）对比，不许变差
4. 在 **Python 3.11**（CI 版本）下复跑：`/home/hermes/.hermes/cache/scratch/venv311/bin/python`
5. 保险丝双向验证：真产物 EXIT 0，4 类人造损坏各 EXIT 1
6. `git status --porcelain output/` 两种分支复验
7. 清理 `src/.cache`、`__pycache__`、`.ruff_cache`、`.mypy_cache`
8. 分 commit 提交（`reports/` 不入库）
9. 更新 `reports/audit-c-engineering.md` 的修复状态表

---

## 5. 不做什么（明确出界）

- 不碰 `src/group/categorizer.py`、`src/validator.py`、`src/generator.py`、`src/fetcher.py`（第 3 轮再动）
- 不改 `[:100]` 上限
- 不动 `reports/` 下除本文件外的任何报告
- 不改线上 coffee-tracker 服务（Lane E 只写 override 草案，由 Controller 复核后再 reload）
