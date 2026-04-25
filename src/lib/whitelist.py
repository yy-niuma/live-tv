#!/usr/bin/env python3
"""CDN 白名单正则（供 normalize.py 合并频道时判断 URL 优先级）"""
import re
from typing import List, Pattern

# 香港/台湾/澳门 CDN 正则
HK_CDN_PATTERNS: List[Pattern] = [
    re.compile(r'^https?://([^/]+\.)*hkdtmb\.com/', re.IGNORECASE),
    re.compile(r'^https?://([^/]+\.)*tdm\.com\.mo/', re.IGNORECASE),
    re.compile(r'^https?://([^/]+\.)*viutv\.com/', re.IGNORECASE),
    re.compile(r'^https?://([^/]+\.)*now\.com/', re.IGNORECASE),
    re.compile(r'^https?://([^/]+\.)*tvb\.com/', re.IGNORECASE),
    re.compile(r'^https?://([^/]+\.)*rthk\.hk/', re.IGNORECASE),
    re.compile(r'^https?://([^/]+\.)*hkcable\.com\.hk/', re.IGNORECASE),
    re.compile(r'^https?://([^/]+\.)*cable-tvc\.com/', re.IGNORECASE),
    re.compile(r'^https?://61\.238\.\d+\.\d+/'),
    re.compile(r'^https?://116\.199\.\d+\.\d+'),
    re.compile(r'^https?://202\.181\.\d+\.\d+/'),
    re.compile(r'^https?://203\.186\.\d+\.\d+/'),
    re.compile(r'^https?://1\.32\.\d+\.\d+/'),
    re.compile(r'^https?://42\.2\.\d+\.\d+/'),
    re.compile(r'^https?://([^/]+\.)*163189\.xyz/'),
    re.compile(r'^https?://([^/]+\.)*jiduo\.me/'),
    re.compile(r'^https?://aktv\.top/'),
    re.compile(r'^https?://122\.152\.\d+\.\d+/'),
    re.compile(r'^https?://8\.138\.\d+\.\d+/'),
    re.compile(r'^https?://fm1077\.serv00\.net/'),
]

# 合并全局 CDN + 扩展 HK 源
EXTENDED_WHITELIST_PATTERNS: List[Pattern] = HK_CDN_PATTERNS + [
    re.compile(r'^https?://([^/]+\.)*rthktv\.com/', re.IGNORECASE),
    re.compile(r'^https?://hoytv\.com/', re.IGNORECASE),
    re.compile(r'^https?://php\.jdshipin\.com/'),
    re.compile(r'^https?://([^/]+\.)*akamaized\.net/', re.IGNORECASE),
    re.compile(r'^https?://([^/]+\.)*cloudfront\.net/', re.IGNORECASE),
    re.compile(r'^https?://([^/]+\.)*fastly\.net/', re.IGNORECASE),
    re.compile(r'^https?://([^/]+\.)*直播\.tv/', re.IGNORECASE),
    re.compile(r'^https?://([^/]+\.)*pstatic\.net/', re.IGNORECASE),
]


def is_hk_cdn_whitelisted(url: str) -> bool:
    """判断 URL 是否属于 HK/TW/MO CDN（normalize.py 合并频道时使用）"""
    for pattern in EXTENDED_WHITELIST_PATTERNS:
        if pattern.match(url):
            return True
    return False
