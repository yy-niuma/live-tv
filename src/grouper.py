"""分组模块：频道去重、名称标准化、分类"""
from pathlib import Path
from typing import List, Dict, Optional

from src.fetcher import Channel
from src.group.categorizer import categorize
from src.group.normalize import normalize_channel_name, normalize_channels


class Grouper:
    """频道分组器"""

    def __init__(self, config=None, health: Optional[Dict[str, bool]] = None):
        self.config = config
        self._aliases: Dict[str, str] = {}
        # {url: bool} 实测可播快照，用于合并同名频道时优先挑能播的链路。
        # None / {} 时行为与旧版一致。见 src/lib/stream_health.py 的说明。
        self.health: Dict[str, bool] = health or {}

    def _load_aliases(self) -> Dict[str, str]:
        """加载别名映射"""
        if self._aliases:
            return self._aliases

        alias_file = Path(__file__).parent.parent / "config" / "alias.txt"
        if alias_file.exists():
            for line in alias_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    # 支持 "->" 和 "=" 分隔符
                    if "->" in line:
                        parts = line.split("->", 1)
                    else:
                        parts = line.split("=", 1)
                    if len(parts) == 2:
                        self._aliases[parts[0].strip()] = parts[1].strip()
        return self._aliases

    def group(self, channels: List[Channel]) -> Dict[str, List[Channel]]:
        """对频道列表进行分组"""
        print(f"[Grouper] 开始分组，共 {len(channels)} 个频道")

        # 1. 标准化频道名称
        aliases = self._load_aliases()
        for ch in channels:
            raw_name = ch.name or ""
            ch._normalized_name = normalize_channel_name(raw_name, aliases)

        # 2. 合并同名频道
        print("[Grouper] 合并同名频道...")
        channels_dict = []
        for ch in channels:
            channels_dict.append({
                "name": ch.name,
                "url": ch.url,
                "logo": ch.logo,
                "group": ch.group,
                # tvg-id 是 EPG 主键：产物头部声明了 x-tvg-url，没有这个键
                # 播放器绑不上节目表。这趟「Channel -> dict」必须带着它走，
                # 否则解析层抓到的 id 在这里被丢掉。
                "id": getattr(ch, "id", ""),
                "_normalized_name": ch._normalized_name,
            })

        merged = normalize_channels(channels_dict, aliases, health=self.health)
        print(f"[Grouper] 合并后剩余 {len(merged)} 个频道")

        # 转换回 Channel 对象，并使用标准化名称
        channels = []
        for ch_dict in merged:
            normalized = ch_dict.get("_normalized_name", "")
            display_name = normalized if normalized else ch_dict.get("name", "")
            ch = Channel(
                name=display_name,
                url=ch_dict.get("url", ""),
                logo=ch_dict.get("logo", ""),
                group=ch_dict.get("group", ""),
                id=ch_dict.get("id", ""),
            )
            ch._normalized_name = normalized
            # 备选链路（normalize.py 合并同名频道时算出）随频道一起交到产出层，
            # 由 src/generator.py 渲染成主 URL 之后的 #EXTBACKUP: 注释行。
            # 用动态属性而不是改 Channel 字段：Channel 属采集层文件，不归本改动。
            # setattr 只为绕开静态检查（Channel.__init__ 未声明该属性）；
            # 运行期与 `ch._backup_urls = [...]` 完全等价。
            setattr(ch, "_backup_urls", list(ch_dict.get("_backup_urls") or []))
            channels.append(ch)

        # 3. 分组
        result: Dict[str, List[Channel]] = {}
        for ch in channels:
            group_name = self._match_group(ch)
            if group_name:
                if group_name not in result:
                    result[group_name] = []
                result[group_name].append(ch)

        print(f"[Grouper] 分组完成，共 {len(result)} 个分组")
        return result

    def _match_group(self, channel: Channel) -> Optional[str]:
        """匹配频道所属分组"""
        name = channel._normalized_name or channel.name or ""
        group = channel.group or ""
        logo = channel.logo or ""
        return categorize(name, group, logo)
