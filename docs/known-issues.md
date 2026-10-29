# 已知限制与缺陷（带证据）

README 只列一句话摘要，这里是完整版。每条都注明证据来源：**本机实测**、或**报告实测（未复测）**、或**代码事实**。

想快速核对数字，见文末「数字核实」。

---

## 1. 每分组 100 条上限（设计内，非缺陷）

`src/generator.py:182` 附近：

```python
for ch in channels[:100]:
    ...
if len(channels) > 100:
    all_lines.append(f"# ... and {len(channels) - 100} more")
```

后果：交付量与 `stats.json` 永久不一致。**这是刻意的体积控制**，要全量输出需改 `generator.py`（属行为变更）。

---

## 2. 文件头 `# Total:` 不是实际条数

`# Total: 8056 channels, 51 categories` 里的 8,056 是「截断前、脏名过滤后」的数，
文件里实际只有 1,164 条 `#EXTINF`。两个数字差 6,892，正好等于 9 行 `# ... and N more` 之和。

三口径完整推导见 [`getting-started.md`](getting-started.md) 的 FAQ 1/2/3。

---

## 3. `--skip-fetch` 在无缓存时必然失败

`--no-cache` 分支（`src/main.py:67-79`）**不调用** `cache.set()`，所以「先 `--no-cache` 抓取、
再 `--skip-fetch` 生成」的两步流程读不到缓存。

**实测**：`python -m src.main --skip-fetch` 在 `[Step 1/4]` 就中止。HEAD 版与工作区版行为一致。

---

## 4. 失败退出码 —— 已修（`871e32d`）

现在「运行失败」会写 stderr 并 `raise SystemExit(1)`（**实测 `EXIT=1`**）。
`871e32d` 之前的版本（含数据提交 `074c677`）只 `print` 后 `return`，退出码 0，CI 会把失败当成功。

校验：`git show 871e32d:src/main.py | grep -c SystemExit` → `1`。

---

## 5. 缓存目录位置不对

`src/lib/cache.py:13` 用 `Path(__file__).parent.parent / ".cache"`，实际落在 `src/.cache`
（**实测打印该路径**）。`.gitignore` 已补 `src/.cache/`（`7ff4be1`），
但缓存路径本身仍算错，缓存不会落到仓库根的 `.cache/`。

---

## 6. 验证器把异常当成「有效」

`src/validator.py:27` 的 `if valid` 对 `asyncio.gather(return_exceptions=True)` 返回的异常对象恒为真。

**实测**：`http://[::1/list.m3u8`（`urlparse` 抛 `ValueError`）仍被保留。

---

## 7. `strip_noise` 删除所有内部空格

`src/group/normalize.py:84` 把 `\s+` 替换成空串。**实测** `strip_noise("TVB 翡翠台")` → `"TVB翡翠台"`，
下游 `logo_map` 只能靠额外分支打补丁。

---

## 8. 分类与港澳台过滤判定不一致 —— 已修（2026-10-29 重构）

原缺陷：`categorizer.py` 的 `hk_exact`/`tw_exact`/`mo_exact` 三张表与 `categorize()` 各自维护一套关键词，
其中若干正则写成双反斜杠（如 `\\bmacau\\b`，实际匹配字面反斜杠 + `b`）永不命中，
于是 `categorize("Macau TV")` = `🇲🇴 澳门` 而 `is_hk_region("Macau TV")` = `False`。

修复后两者共用同一套 `HK_TW_MO_RULES` + `_region_category()`，
**实测** `is_hk_region("Macau TV")` → `True`、`is_hk_region("TTV")` → `True`。

**残留**：`is_hk_region()` 的 `cat` 参数仍可绕过地区判定，调用方需保持一致
（`src/generator.py:136` 已按生产路径传入 `cat`）。

详见 [`categorize-rework.md`](categorize-rework.md)。

---

## 9. 测试覆盖（代码事实）

`3020583` 起仓库里有 `tests/`（7 个文件）。此前 189 个历史提交里没有任何测试
（`git rev-list --count 3020583^` → 189）。

| 时点 | `pytest` |
|---|---|
| 重构前 | 283 passed, 23 xfailed |
| 重构后第一版 | 305 passed, 7 xfailed |
| 当前 | **323 passed, 7 xfailed**（330 例，1.0s） |

差额主要是真正修好的缺陷（xfail 守卫按 `strict=True` 报 XPASS，删掉标记后转为正向回归测试），
以及新增的 `CATEGORY_ORDER` 契约（11 例）与 logo 契约（7 例）。

剩下 7 个 xfail 是**刻意固化的、仍然坏着的**已知缺陷（`tests/test_known_defects.py`），
修好后去掉标记即变成契约测试。

---

## 10. 可安装性

`python -m src.main` 是唯一入口，**必须在仓库根目录执行**，否则
`ModuleNotFoundError: No module named 'src'`（包名就是 `src`）。

`pyproject.toml`（`7ff4be1`）只声明 `requires-python = ">=3.11"` 与 ruff/mypy 配置，
**有意不写 `[build-system]`**，所以仍然不能 `pip install -e .`（原因见该文件开头注释）。

---

## 11. 分组很慢

`categorizer.py` 里几百个正则都以**字符串**形式传给 `re.search`，`re` 的 512 条内部缓存被反复冲掉，
时间主要花在重新编译正则上。

> **报告实测（未复测）**：审计报告 `audit-c-engineering.md` §3.4 的 cProfile ——
> 1,379 频道 40.2s，预编译后 1.0s，约 40×。**这个 40× 是那份报告的数字，本项目文档更新时未复测。**
>
> 参考量级：本机一次完整运行（含抓取 16,991 条、合并 12,578 条、分类、生成）约 4 分钟，
> 时间几乎全在「合并同名 + 分类」上（`--skip-validation` 口径）。

---

## 12. 数字每天漂移

同一份代码在不同日期产出量差别很大：

| 口径 | 仓库快照（`074c677`） | 2026-10-29 全新运行 |
|---|---:|---:|
| 抓取到手 | — | 16,901 / 16,994 / 16,991（三次） |
| 同名合并后 | 8,371 | 12,505 / 12,578 / 12,578 |
| `all_merged` `#EXTINF` | 1,164 | 1,378 / 1,702 / 1,706 |
| `hk_merged` `#EXTINF` | 33 | 58 / 103 / 107 |

**任何写死的数字都只是当日快照**，引用前请自己跑 `grep -c`。

---

## 分组相关的残留（另见 `docs/categorize-rework.md` §9）

- `DetetivesMedicos` 判 `🌐 国际`，期望 `📺 纪录片`（评测集唯一不达标项，`eval_categorize.py` 因此退出码 1）。
- `ATV`（亚洲电视，香港）分类 `📡 卫视频道` 且 `is_hk_region('ATV')=False` → 不进 `hk_merged.m3u`。
- `CNNInternational` 连写落 `🌐 国际频道`，`CNN International` 带空格落 `📰 新闻财经`，确切分支未定位。
- `CHANNEL_REGION_PATTERNS`（25 条）全仓零引用，是死数据（`categorizer.py:386`）。

---

## 数字核实

```bash
git remote -v                                            # 仓库真实地址

# 订阅地址可达性
curl -s -o /dev/null -w '%{http_code} %{size_download}\n' \
  https://raw.githubusercontent.com/yy-niuma/live-tv/main/output/all_merged.m3u   # 200 257714

# 三个口径的频道数
python3 -c "import json;print(sum(json.load(open('output/stats.json')).values()))"  # 8371
python3 -c "import json;print(len(json.load(open('output/stats.json'))))"           # 51
grep -c '^#EXTINF' output/all_merged.m3u                 # 1164
grep -c '^#EXTINF' output/hk_merged.m3u                  # 33
grep -c '^#EXTGRP' output/hk_merged.m3u                  # 7
grep -c '^# \.\.\. and' output/all_merged.m3u            # 9
head -6 output/all_merged.m3u | tail -1                  # # Total: 8056 channels, 51 categories

# 配置与代码
python3 -c "import yaml;d=yaml.safe_load(open('config/sources.yaml'));print(len(d['sources']))"  # 20
python -m src.main --help                                # 6 个选项
.venv/bin/python -m ruff check src scripts               # All checks passed!
.venv/bin/python -m pytest                               # 323 passed, 7 xfailed
.venv/bin/python scripts/eval_categorize.py              # 50/51（退出码 1，见下）
```

`scripts/eval_categorize.py` 的退出码语义是「全部达标才 0」，当前有 1 条已知残留
（`DetetivesMedicos`），所以它**故意**退出 1。这个脚本没有接进 CI，
接进去之前要么先修掉那条残留、要么加个 `--allow-known-residuals` 开关。
