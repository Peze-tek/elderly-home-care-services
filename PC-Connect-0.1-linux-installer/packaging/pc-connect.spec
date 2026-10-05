from PyInstaller.utils.hooks import collect_submodules

hiddenimports = collect_submodules("pc_connect")

analysis = Analysis(
    ["src/pc_connect/main.py"],
    pathex=["src"],
    hiddenimports=hiddenimports,
    datas=[],
    binaries=[],
)

pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    name="PC Connect",
    console=False,
)
