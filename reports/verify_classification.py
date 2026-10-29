#!/usr/bin/env python3
"""只读验证脚本：复现 reports/audit-a-classification.md 中的所有关键结论。
用法: cd <repo> && .venv/bin/python reports/verify_classification.py
不修改任何 src/ 文件，不联网。
"""
import json
import re
import sys
import time
from collections import Counter

sys.path.insert(0, ".")
import src.group.categorizer as C                      # noqa: E402
from src.generator import CATEGORY_ORDER               # noqa: E402


def hdr(t):
    print(f"\n{'='*68}\n{t}\n{'='*68}")


# ---------------------------------------------------------------- 1. 三个总数
hdr("1. 三个互相矛盾的总数")
stats = json.load(open("output/stats.json", encoding="utf-8"))
m3u = open("output/all_merged.m3u", encoding="utf-8").read().splitlines()
print(f"  stats.json 合计      : {sum(stats.values())}  ({len(stats)} 个分类)")
print(f"  m3u 头部自我声明     : {m3u[5].strip()}")
print(f"  m3u 实际 #EXTINF 条数: {sum(1 for l in m3u if l.startswith('#EXTINF'))}")
print(f"  stats - 8168 (脏名丢弃): {sum(stats.values()) - 8168}")

# ------------------------------------------------- 2. 解析 m3u 得到真实分类
hdr("2. 各分类真实计数（从 m3u 重算，每类被截断到 100）")
cur, groups = None, {}
for ln in m3u:
    if ln.startswith("#EXTINF"):
        m = re.search(r'group-title="([^"]*)"', ln)
        cur = m.group(1) if m else ""
        groups.setdefault(cur, []).append(ln.split(",", 1)[1])
for g, v in sorted(groups.items(), key=lambda x: -len(x[1])):
    cap = "  <= 被截断到 100" if len(v) == 100 and stats.get(g, 0) > 100 else ""
    print(f"  {len(v):4d}  {g:14s}(stats={stats.get(g,0)}){cap}")

# --------------------------------------------- 3. 国际桶 = 大陆地方台？
hdr("3. 「🌐 国际」可见样本 100 条：逐个打印，人工判断")
intl = groups["🌐 国际"]
print("  " + " | ".join(intl))
CJK = re.compile(r"[\u4e00-\u9fff]")
latin = [n for n in intl if not CJK.search(n)]
print(f"\n  含中文的条目: {len(intl)-len(latin)}/{len(intl)}")
print(f"  纯拉丁（可能真是境外台）: {latin if latin else '无'}")

# --------------------------------------------- 4. 卫视频道 = r"atv" 误判？
hdr('4. 「📡 卫视频道」= 裸子串 r"atv" 的产物')
sv = groups["📡 卫视频道"]
hit = [n for n in sv if "atv" in n.lower()]
print(f"  可见 {len(sv)} 条，含子串 'atv' 的 {len(hit)} 条 ({len(hit)/len(sv)*100:.0f}%)")
print(f"  样本: {hit[:10]}")
print(f"  其中真正的「XX卫视」: {[n for n in sv if n.endswith('卫视')]}")

# --------------------------------------------- 5. 历史 BUG 是否复发
hdr("5. 历史 BUG 回归（categorize(name, 'Others')）")
for n, expect in [
    ("NovaTV Brasov", "不应是 卫视频道"),
    ("AdrenalinaPuraTV", "不应是 卫视频道"),
    ("东方卫视", "不应是 国际"),
    ("东南卫视", "不应是 国际"),
    ("三沙卫视", "不应是 国际"),
    ("浙江经视", "不应是 国际"),
    ("浙江教科", "不应是 国际"),
    ("五星体育", "不应是 国际"),
    ("四川体育", "不应是 国际"),
    ("XinjiangTV5", "不应是 国际频道"),
    ("TheWildWildWest", "不应是 国际频道"),
    ("电影_赛车", "不应是 体育"),
    ("TVB 星河", "TVB 且 hk=True"),
    ("TVB 娱乐新闻", "TVB 且 hk=True"),
]:
    got = C.categorize(n, "Others")
    hk = C.is_hk_region(n, "Others", got)
    print(f"  {n:16s} -> {got:10s} hk={hk!s:5s}  ({expect})")

# --------------------------------------------- 6. 死正则
hdr("6. 双反斜杠死正则（源码字节原样 r\"\\\\bttv\\\\b\"）")
dead = [("C:141", r"\\bttv\\b", "ttv"), ("C:143", r"\\bmacau\\b", "macau"),
        ("C:396", r"ttv\\b", "ttv")]
for where, pat, probe in dead:
    print(f"  {where} {pat!r}: match({probe!r}) = {bool(re.search(pat, probe, re.I))}")

hdr("7. hk_exact 大小写敏感（文本已 lower）")
for p in [r"TVB生活台", r"\bVIUTV\b", r"TVB星河"]:
    print(f"  {p!r}: 无I={bool(re.search(p,'tvb生活台 tvb星河 viutv'))}  "
          f"有I={bool(re.search(p,'tvb生活台 tvb星河 viutv',re.I))}")

# --------------------------------------------- 8. 幂等 / group 污染
hdr("8. 幂等性与 group 污染")
names = [n for v in groups.values() for n in v]
bad = [n for n in names if C.categorize(n, "Others") != C.categorize(n, C.categorize(n, "Others"))]
print(f"  单次幂等 f(n,g) vs f(n,f(n,g)): {len(bad)}/{len(names)} 不一致")
dm = sum(1 for n in names if C.categorize(n, "Others") != C.categorize(n, "Movies"))
dn = sum(1 for n in names if C.categorize(n, "Others") != C.categorize(n, "News"))
print(f"  group 从 Others 换成 Movies: {dm}/{len(names)} ({dm/len(names)*100:.1f}%) 分类改变")
print(f"  group 从 Others 换成 News  : {dn}/{len(names)} ({dn/len(names)*100:.1f}%) 分类改变")
print(f"  分类名回灌成 group: {C.categorize('测试','📺 北京')} / {C.categorize('测试','📡 卫视频道')}")
print(f"  :441 音乐分裂: {C.categorize('hkdtmb','Music')!r} vs {C.categorize('hkdtmb','MTV')!r}")

# --------------------------------------------- 9. 缓存与耗时
hdr("9. _match 无显式缓存，re._cache 饱和")
allp = set()
for v in C.PROVINCE_KEYWORDS.values():
    allp |= set(v)
allp |= set(re.findall(r'r"([^"]*)"', __import__("inspect").getsource(C)))
print(f"  distinct pattern 约 {len(allp)} 个 / re._MAXCACHE = {re._MAXCACHE}")
t = time.perf_counter()
for n in names:
    C.categorize(n, "Others")
el = time.perf_counter() - t
print(f"  {len(names)} 条耗时 {el:.2f}s ({el/len(names)*1000:.2f} ms/条)  re._cache={len(re._cache)}")
print(f"  外推 8450 条 ≈ {el/len(names)*8450:.0f}s")

# --------------------------------------------- 10. 生产/排序表一致性
hdr("10. 代码可产出的分类 vs CATEGORY_ORDER")
produced = set(re.findall(r'return "([^"]+)"', __import__("inspect").getsource(C)))
produced |= set(C.GROUP_TITLE_EN_MAPPING.values()) | set(C.PROVINCE_KEYWORDS)
print(f"  可产出 {len(produced)} 个分类")
print(f"  不在 CATEGORY_ORDER: {sorted(produced - set(CATEGORY_ORDER))}")
print(f"  CATEGORY_ORDER 永不产出: {sorted(set(CATEGORY_ORDER) - produced)}")

# --------------------------------------------- 11. 死代码
hdr("11. 死代码确认")
import subprocess
for fn in ["_excluded(", "CHANNEL_REGION_PATTERNS"]:
    out = subprocess.run(["grep", "-rn", fn, "--include=*.py", "src/"],
                         capture_output=True, text=True).stdout.strip().splitlines()
    print(f"  {fn} 引用点 {len(out)} 处: {out}")
