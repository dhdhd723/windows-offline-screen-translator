# 本地屏幕中英翻译器

## 下载与运行（普通用户）

无需安装 Python。请下载 [完整 Windows 运行包：ScreenTranslator-0.1.0-Windows-x64.zip](https://github.com/dhdhd723/windows-offline-screen-translator/releases/download/v0.1.0/ScreenTranslator-0.1.0-Windows-x64.zip)，或进入 [v0.1.0 发布页](https://github.com/dhdhd723/windows-offline-screen-translator/releases/tag/v0.1.0) 查看说明和校验值。不要下载 GitHub 自动生成的 Source code 压缩包来运行程序。

1. 更新前，先从旧版托盘菜单选择“退出”，不要同时运行两个版本。
2. 完整解压 ZIP，在 `ScreenTranslator` 文件夹内双击 `ScreenTranslator.exe`。保留同目录的 `_internal`、`models`、`LICENSES`，不要只复制 exe。
3. 首次启动请按提示阅读并明确同意随包运行库条款，再使用 Alt+R 框选、Alt+T 开启／停止翻译。

快捷键冲突时，以托盘提示的实际按键为准。默认 Alt+R 被占用会依次尝试 Alt+Shift+R、Ctrl+Alt+R；其他冲突可从托盘菜单操作或在设置中修改。

Windows 10 2004 及以上 / Windows 11，64 位。截图、OCR 和中英互译全部在本机完成。发布包自带模型，不需要 Python，不需要付费 API，也不需要显卡环境。

本仓库是开发源码，不包含 exe 或模型权重；“无需 Python”仅指完整便携运行包。项目范围、使用方式、测试结果及隐私边界见 [项目说明报告](docs/项目说明报告.md)。

## 普通用户使用

完整解压便携包，在 ScreenTranslator 文件夹内双击 ScreenTranslator.exe。请保留同目录的 `_internal`、`models` 和 `LICENSES` 文件夹，不要只复制 exe。下载的是完整 Windows 运行包，不是 GitHub 自动生成的源码 ZIP。

首次正常启动须阅读并明确同意随包微软运行库条款，然后才会注册快捷键和
开启监控。不同意会退出；确认只存于本机设置，条款内容变化后会重新询问。
该条款不限制 Qt/GEOS/Eigen 等组件原许可证授予的源码、替换和调试权利。

1. 按 Alt+R，拖动鼠标框选文字所在区域。可选择任意显示器，当前版本要求一个选区位于同一显示器内。
2. 按 Alt+T，开启持续翻译。首次翻译需加载本地模型，后续译文在文字变化后更新。
3. 再按 Alt+T 停止监控。停止后保留最后一条字幕。
4. Alt+C 清空字幕；当前文字未变化前，不会立即重新显示同一句。
5. 按 Esc 隐藏字幕，再按恢复。停止翻译后仍可隐藏保留的字幕。隐藏不会改变监控开关。Esc 也会传递给当前应用，可在设置中禁用全局 Esc。
6. 右下角托盘图标提供相同操作、设置、复制译文和退出。双击托盘图标开启/停止翻译。

字幕默认鼠标穿透、不抢焦点。框选时会暂时获取输入，以便拖动和 Esc 取消；设置窗口也正常接受输入。

尽量只框选一两行字幕。区域过大、字号太小、运动背景、淡入和逐字字幕会增加识别时间。游戏建议使用无边框窗口模式。受 DRM 保护的内容、独占全屏和安全桌面可能无法捕获。

配置保存在 `%LOCALAPPDATA%\ScreenTranslator\config.json`。默认不保存截图、不记录识别原文，翻译缓存仅存在内存。设置中可开启磁盘译文缓存，缓存数据库会保存译文；关闭选项不会删除已有数据库。

默认 Alt+R 若被其他程序占用，程序会尝试改用 Alt+Shift+R，其次 Ctrl+Alt+R，并保存实际快捷键、更新托盘提示；不会修改其他程序。自定义快捷键若被占用，会提示用户从设置修改。显示器位置或分辨率变化后，需重新框选。

## 本地自检

发布程序支持 `--self-test --report 报告路径.json`。自检使用程序生成的中英文字图像，验证本地 OCR 与两个翻译方向，同时阻止并记录 Python 网络连接尝试。自检不读取用户屏幕；这不是操作系统级防火墙测试。

`--smoke-test --report 报告路径.json` 初始化 UI 和 Windows 集成后自动退出。自检结果不能代替具体游戏、显示器和 DPI 的实际验收。

诊断也需要先接受相同的随包条款；未接受时会返回退出码 3，而不是隐式同意。
明确读过条款并授权自动验收后，可对 `--self-test` 或 `--smoke-test` 增加
`--accept-runtime-terms`；该参数不能用于绕过普通 GUI 首次确认。

## 开发与构建

开发环境：Python 3.12 x64。项目使用 PySide6 Widgets、Win32 API、MSS、RapidOCR/ONNX Runtime、CTranslate2 INT8 和 SentencePiece。运行时不使用 PyTorch 或 Transformers。

可用 `requirements-lock.txt` 重建本次开发环境（包含测试与模型转换依赖）；也可只安装 pyproject.toml 中需要的依赖。执行：

以下依赖安装用于开发测试，并不自动得到本项目最终发行的纯 CPU 原生库。
正式重建须按 [纯 CPU 构建方案](docs/CPU_ONLY_BUILD_PLAN.md) 编译并安装本地
CTranslate2 wheel，再打包；不要把包索引中的 CUDA-enabled 官方 wheel
误当作本项目已核验的 CPU 构建。重新构建后必须重新完成发布核验。

```powershell
python -m pip install -e ".[build,models]"
python tools/prepare_models.py
python -m pytest
python launcher.py
python launcher.py --self-test --report build/self-test.json
python -m PyInstaller packaging/ScreenTranslator.spec --distpath dist --workpath build/pyinstaller
```

先在 Python 3.12 x64 的虚拟环境中执行以上步骤。依赖安装和首次模型准备需要联网；模型准备脚本会下载固定版本权重并在本机转换为 INT8。若已有经过校验的完整 `models/`，可直接放入项目目录，避免重复准备。完成后应用可以离线运行。

将 `models/` 复制到 `dist/ScreenTranslator/models/`，再运行 `tools/collect_licenses.py dist/ScreenTranslator/LICENSES`。把 `packaging/qt-notices` 中的 Qt 许可文本与源码说明复制到 `LICENSES/Qt`，同时保留交付包中的第三方源码档案。开发依赖下载缓存应放在有写权限的目录；PyInstaller 可通过 `PYINSTALLER_CONFIG_DIR` 指定构建缓存。

Windows 原生库和模型会随便携包交付。目录形式的打包避免每次启动解压大模型；当前发布使用 PyInstaller，后续可在同一模块结构下更换 Nuitka，不影响运行逻辑。

## 模型与边界

OCR 使用 PP-OCRv5 mobile 中英模型，由 RapidAI 提供 ONNX 转换版本；翻译使用 Helsinki-NLP 的 opus-mt-zh-en 与 opus-mt-en-zh，转换为 CTranslate2 INT8。来源、固定版本和 SHA-256 清单在 models/manifest.json。

英文到中文模型为 Apache-2.0；中文到英文模型为 CC-BY-4.0。分发时必须保留模型与第三方组件的许可证和署名。

翻译模型适合一般短句；专业术语、口语和孤立短词不保证准确。自动方向对中英混合文本使用汉字与拉丁字母比例，可手动指定方向。

当前交付的功能范围为单固定区域、任意显示器内框选、持续翻译、快捷键、悬浮字幕、托盘、持久配置和缓存。DXGI、跨屏选区、高质量模型包和字幕历史属于后续扩展。

## GitHub 发布与隐私

不要直接上传整个开发目录或原始便携包。先阅读 [发布与隐私说明](docs/PUBLISHING.md)，再从项目根目录生成干净源码和净化运行包：

```powershell
python tools/prepare_public_release.py --portable dist/ScreenTranslator --output build/public-export --candidate
```

检查通过后，只将 `build/public-export/repo/` 的内容作为仓库源码；源码压缩包和净化便携包由同一工具生成。原始日志、测试报告、用户配置、译文缓存、真实截图和 Git 历史不能混入。GitHub 账号及提交作者信息仍可能公开，第三方版权声明必须保留。本轮采用[同版本纯 CPU 重建](docs/CPU_BUILD_PROVENANCE.md)，不使用旧 Intel/MKL/CUDA 候选二进制；微软运行库采用正式个人 Community 许可发行路径和官方原件。实际发布及验收范围见[发布状态](docs/RELEASE_STATUS.md)，第三方证据见[核验记录](docs/THIRD_PARTY_BINARY_NOTICES.md)。导出默认是候选包，正式 `--final` 导出需要审核通过状态；导出工具不自动上传 GitHub。应用自身尚未选定开源许可证。

本程序使用 LGPLv3 许可的 Qt / PySide6 / Shiboken 6.9.3。便携包的 `LICENSES/Qt/` 包含 GPL/LGPL 全文及对应源码档案。关闭程序后，可在 `_internal/PySide6/` 与 `_internal/shiboken6/` 中替换接口兼容的库；允许为调试这些库的修改而进行逆向工程。详情见随包 Qt 声明，微软保护条款不限制这些原许可权利。

Shapely 使用 LGPLv2.1 的 GEOS 3.13.1 动态库。便携包的 `LICENSES/upstream/GEOS-3.13.1/` 提供对应源码与构建配方，完整许可在 `LICENSES/Shapely/`。兼容修改库可替换，允许为调试这些库的修改而进行逆向工程。

本软件部分基于 [FreeType Team](https://freetype.org) 的工作，FreeType 采用 FreeType License (FTL)；Pillow 的完整第三方文本保留在 `LICENSES/Pillow/`。This software is based in part on the work of the Independent JPEG Group.

ONNX Runtime 内嵌 Eigen、tqdm 和 certifi 的 MPL 对应源码、原许可和获取说明位于便携包 `LICENSES/upstream/` 的对应目录，详见 [对应源码核验](docs/COPYLEFT_SOURCE_NOTICES.md)。这些源码保持原许可权利，不受应用附加限制。
