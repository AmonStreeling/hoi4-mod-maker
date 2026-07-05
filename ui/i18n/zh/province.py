"""
province — zh 翻译

本文件由 tools/migrate_i18n.py 生成。后续手动维护。
"""

STRINGS: dict[str, str] = {
    "btn_generate": "生成",
    "label_land_ratio": "陆地密度倍率:",
    "label_province_count": "省份数量:",
    "prov_bld_bunker": "陆防",
    "prov_bld_cancel": "取消",
    "prov_bld_coastal": "海防",
    "prov_bld_naval": "海军基地",
    "prov_bld_province_id": "省份 ID",
    "prov_bld_save": "保存",
    "prov_bld_tip": """为 state 内每个陆地省份单独配置防御建筑.
0 = 不建. bunker 适用所有陆地, coastal_bunker 和 naval_base 应只给沿海省份.""",
    "prov_bld_title_fmt": "省份建筑 — {0} (ID {1})",
    "province_btn_find": "定位",
    "province_btn_find_tip": "输入省份 ID，按 Enter 或点定位 — 地图自动跳到该省份并高亮显示。",
    "province_search_placeholder": "输入省份 ID …",
    "province_btn_expand": "扩张省份",
    "province_btn_expand_tip": "🖌 像素级笔刷：开启后选中一个省份，鼠标拖动经过的像素归入该省份。松手自动关闭。",
    "province_btn_merge": "合并省份",
    "province_btn_merge_tip": "开启后：点第一个省份，再点第二个省份 → 整省合并，自动关闭。",
    "province_btn_split": "切割选中省份",
    "province_btn_split_tip": "先点击选中一个省份 → 点此按钮 → 沿中线自动切成两半",
    "province_coastal_no": "否",
    "province_coastal_yes": "是",
    "province_hint_click_info": "点击省份查看信息",
    "province_hint_default": "💡 默认点击查看省份信息。下方按钮开启 合并 / 扩张（像素笔刷）/ 切割 / 局部重生 模式。",
    "province_hint_expand": "🟠 扩张（像素笔刷）— 1) 点选省份 2) 拖动笔刷，鼠标经过的像素归入该省份。",
    "province_hint_merge": "🟠 合并 — 1) 点第一个省份 2) 点第二个 → 自动整省合并。",
    "province_hint_split": "🟠 切割 — 在省份上画一条线，松手沿线切开。",
    "province_info_coastal": "沿海",
    "province_info_compact_default": "ID: — | — | — | 0px",
    "province_info_id": "省份 ID",
    "province_info_pixels": "像素数",
    "province_info_terrain": "地形",
    "province_info_type": "类型",
    "province_section_info": "省份信息",
    "province_section_tools": "省份操作",
}
