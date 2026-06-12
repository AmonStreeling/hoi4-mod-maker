"""
预览功能 — 把当前地图合成"游戏内观感"画面显示在画布上。

合成管线: domain/preview/compositor.py (游戏贴图 + 高度光影 + 气候色调
+ 海洋深度 + 河流)。游戏贴图来自用户本机的 HOI4 安装目录
(services/game_assets.py), 找不到时降级为大陆视图并在侧栏提示。

整图合成约 2~5 秒, 因此结果缓存、手动刷新, 不实时跟随编辑。
"""

from features.base import BaseFeature, FeatureContext


class PreviewFeature(BaseFeature):
    id = "map.preview"
    display_name = "预览"
    category = "map"

    def build_page(self, ctx: FeatureContext):
        from features.map.preview.page import PreviewPage
        return PreviewPage()

    def build_renderer(self, ctx: FeatureContext):
        from features.map.preview import renderer
        return renderer
