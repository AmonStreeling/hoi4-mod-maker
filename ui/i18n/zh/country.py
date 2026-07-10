"""
country — zh 翻译

本文件由 tools/migrate_i18n.py 生成。后续手动维护。
"""

STRINGS: dict[str, str] = {
    "country_show_names_label": "在地图上显示国家名字",
    "country_capital_label": "首都:",
    "country_capital_unset": "未设置",
    "country_color_label": "颜色:",
    "country_color_tip": "点击修改颜色",
    "country_create_btn": "创建国家（分步）",
    "country_create_tip": "分步骤：先弹窗输 TAG → 再弹窗输名称。颜色随机，党默认 neutrality。后续要改其他属性请用下方面板。",
    "country_search_placeholder": "🔍 搜索国家（TAG / 名称）…",
    "country_delete_btn": "🗑 删除当前国家",
    "country_delete_confirm_title": "删除国家",
    "country_delete_confirm_msg": "确定删除国家 {tag}? 该国所有 state 会变为无主 (state 本身不删)。可撤销 (Ctrl+Z)。",
    "country_assign_mode_btn": "分配领土模式",
    "country_assign_mode_tip": "开启后：点击地图上的州，把它分配给当前选中的国家（Ctrl+Z 撤销可归还原主）。\n关闭时（信息模式）：点击地图只查看该处国家的信息，不会改动归属。",
    "country_hint": "💡 平时是信息模式：点击地图查看该处国家，在上方面板编辑它的信息\n💡 分配领土：先选中国家 → 开启「分配领土模式」→ 点击州（Ctrl+Z 可撤销归还）\n💡 设置首都：右键地图上的省份 → 「设为首都」\n★ 推荐用「一键创建」按钮（一次填完所有字段）",
    "country_list_section": "国家列表",
    "country_name_label": "名称:",
    "country_name_placeholder": "国家名称",
    "country_party_label": "执政党:",
    "country_pick_color_title": "选择国家颜色",
    "country_props_section": "国家属性",
    "country_quick_create_btn": "★ 一键创建国家（推荐）",
    "country_quick_create_tip": "单对话框一次填完 TAG + 名称 + 执政党 + 颜色（可改）。创建后自动进入领土分配模式。",
    "country_quick_dlg_title": "快速创建国家",
    "country_tag_invalid": "TAG 必须是 3 个字母",
    "country_tag_placeholder": "如 KAR (3个大写字母)",
    "country_tag_row": "TAG:",
    "dlg_country_change_color": "修改 {tag} 的颜色",
    "dlg_country_create_failed": "创建国家失败",
    "dlg_country_name_prompt": "输入国家名称 (TAG: {tag}):",
    "dlg_country_pick_color": "选择 {tag} 的颜色",
    "dlg_country_tag_prompt": "输入国家 TAG (3个字母):",
}
