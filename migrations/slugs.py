"""中文昵称 → 拼音/英文 slug 映射

避免每次加新博主都要手动起 slug。P0 期手工维护。
"""
from __future__ import annotations

# 已知中文博主 → slug 映射
# 新增博主可以：1) 在这里加映射；2) 或者直接用中文 slug（保留可读性）
DISPLAY_NAME_TO_SLUG: dict[str, str] = {
    "九栢米电商": "jiubaimi",
    "芭乐电商生活": "bale",
    "小贵子服装电商": "xiaoguizi",
    "天祥": "tianxiang",
    "狼教授电商": "langjiaoshou-shop",
    "狼教授": "langjiaoshou",
    "无招讲抖店": "wuzhao",
}
