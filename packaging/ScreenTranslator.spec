from pathlib import Path
from PyInstaller.utils.hooks import collect_dynamic_libs, collect_data_files, copy_metadata

project = Path(SPECPATH).parent
binaries = collect_dynamic_libs('onnxruntime') + collect_dynamic_libs('ctranslate2')
datas = collect_data_files('rapidocr', excludes=['**/models/**'])
for name in ('NotoSansCJKsc-Regular.otf', 'OFL.txt', 'README.md'):
    datas.append((str(project / 'packaging' / 'fonts' / name), 'fonts'))
for package in ('rapidocr', 'onnxruntime', 'ctranslate2', 'sentencepiece'):
    datas += copy_metadata(package)

a = Analysis([str(project / 'launcher.py')], pathex=[str(project / 'src')],
             binaries=binaries, datas=datas,
             hiddenimports=['rapidocr', 'rapidocr.inference_engine.onnxruntime',
                            'ctranslate2', 'sentencepiece', 'onnxruntime'],
             hookspath=[], hooksconfig={}, runtime_hooks=[],
             excludes=['torch', 'transformers', 'huggingface_hub', 'paddle', 'paddleocr',
                       'tensorflow', 'openvino', 'tensorrt', 'matplotlib', 'IPython',
                       'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets',
                       'PySide6.QtQml', 'PySide6.QtQuick', 'pytest'],
             noarchive=False)
# Qt's broad GUI hook collects optional PDF and virtual-keyboard plugins.
# This Widgets-only app uses neither; the keyboard is a GPL-only Qt module.
# Remove the optional plugins together with their unused DLL dependencies.
# Windows 10/11 always use the OS UCRT/API-set implementation. Do not ship
# redundant SDK/downlevel compatibility copies or broaden the OS target.
unused_binaries = {
    'qt6pdf.dll', 'qt6virtualkeyboard.dll', 'qt6qml.dll', 'qt6qmlmeta.dll',
    'qt6qmlmodels.dll', 'qt6qmlworkerscript.dll', 'qt6quick.dll',
    'qpdf.dll', 'qtvirtualkeyboardplugin.dll', 'opengl32sw.dll', 'cudnn64_9.dll',
}
a.binaries = [item for item in a.binaries
              if Path(item[0]).name.lower() not in unused_binaries
              and Path(item[0]).name.lower() != 'ucrtbase.dll'
              and not Path(item[0]).name.lower().startswith('api-ms-win-')
              and not Path(item[0]).name.lower().startswith('opencv_videoio_ffmpeg')]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='ScreenTranslator',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=False, disable_windowed_traceback=False,
          icon=str(project / 'packaging' / 'icon.ico'),
          version=str(project / 'packaging' / 'version_info.txt'),
          manifest=str(project / 'packaging' / 'app.manifest'))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='ScreenTranslator')
