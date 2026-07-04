# PyInstaller spec — HOI4 MOD 制作工具打包配置.
# 用法: pyinstaller hoi4_map_maker.spec
# 产物: dist/HOI4MapMaker/HOI4MapMaker.exe

# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

# 动态扫描 ui/i18n/<lang>/*.py, 自动生成 hiddenimports
# 社区加新语言只要放 ui/i18n/<lang>/ 文件夹, 重打包自动识别, 不用改这个 spec
_I18N_DIR = Path('ui/i18n')
_i18n_hiddenimports = [
    f'ui.i18n.{p.parent.name}.{p.stem}'
    for p in _I18N_DIR.glob('*/*.py')
    if p.stem != '__init__' and p.parent.is_dir() and not p.parent.name.startswith('_')
]


a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('data/atlas_tiles', 'data/atlas_tiles'),
        ('ui/i18n', 'ui/i18n'),
        # qdarktheme 内部 .qss 模板/.svg 图标资源, 不显式列出运行时找不到
        *collect_data_files('qdarktheme'),
        # resources/ (图标等) 是未入库的本地目录, 丢失时不挡打包 —
        # 程序运行时不读它, 只影响 exe 图标 (icon= 行自带存在性判断)
        *([('resources', 'resources')] if os.path.exists('resources') else []),
    ],
    hiddenimports=[
        # features 是动态加载的, PyInstaller 抓不到, 显式列出
        'features.map.land',
        'features.map.province',
        'features.map.terrain',
        'features.map.height',
        'features.map.state',
        'features.map.country',
        'features.map.river',
        'features.map.continent',
        'features.content.tech_tree',
        'features.content.focus_tree',
        'features.content.events',
        'features.content.decisions',
        'features.content.characters',
        'features.content.portraits',
        'features.content.oob',
        'features.content.namelist',
        'features.content.flags',
        'features.content.ideas',
        'features.map.density',
        'features.map.density.page',
        'features.map.land.page',
        'features.map.province.page',
        'features.map.terrain.page',
        'features.map.height.page',
        'features.map.state.page',
        'features.map.country.page',
        'features.map.river.page',
        'features.map.land.renderer',
        'features.map.province.renderer',
        'features.map.terrain.renderer',
        'features.map.height.renderer',
        'features.map.state.renderer',
        'features.map.country.renderer',
        'features.map.river.renderer',
        'features.map.state.detail_dialog',
        'features.map.continent.dialog',
        'features.map.logistics',
        'features.map.logistics.page',
        'features.map.logistics.renderer',
        'features.map.strategic_region',
        'features.map.strategic_region.page',
        'features.map.colormap',
        'features.map.colormap.page',
        'features.map.default_map',
        'features.map.default_map.page',
        'scipy.ndimage',
        'scipy.spatial',
        # 包名 pyqtdarktheme != 模块名 qdarktheme, PyInstaller 静态分析在某些环境抓不到, 显式声明
        'qdarktheme',
        *_i18n_hiddenimports,
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 本项目只用 PyQt5 — 环境里混进其他 Qt 绑定会让 PyInstaller 拒绝打包
        # (2026-07-04: 3.10 环境被某依赖捎带装了 PySide6, 必须显式排除)
        'PySide6', 'PySide2', 'PyQt6', 'qt_material',
        'pytest', 'pytest_qt', 'tests',
        'torch', 'torchvision', 'torchaudio',
        'paddle', 'paddlepaddle',
        'cv2', 'opencv-python',
        'transformers', 'huggingface_hub',
        'onnxruntime', 'onnx',
        'llvmlite', 'numba',
        'av',
        'tensorflow', 'keras',
        'matplotlib', 'pandas',
        'IPython', 'jupyter', 'notebook',
        'tkinter',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='HOI4MapMaker',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,     # 发布版不显示控制台
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='resources/icon.ico' if os.path.exists('resources/icon.ico') else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='HOI4MapMaker',
)
