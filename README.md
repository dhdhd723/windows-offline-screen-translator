# 本地屏幕中英翻译器

## 下载聊天缩写增强版（预发布）

[完整 Windows 运行 ZIP，含 exe 和本地模型](https://github.com/dhdhd723/windows-offline-screen-translator/releases/download/v0.1.1-chat-glossary-20261015/ScreenTranslator-0.1.1-Windows-x64-candidate.zip)
· [发布页与文件校验](https://github.com/dhdhd723/windows-offline-screen-translator/releases/tag/v0.1.1-chat-glossary-20261015)
· [更新说明](docs/releases/v0.1.1-chat-glossary-20261015.md)
· [测试报告与已知限制](docs/releases/CHAT_GLOSSARY_TEST_REPORT_20261015.md)

内置词表已扩展为 58 项，无需手填；TYTL 兼容“回头聊”，数字 2 仅在明确短语中展开。
此包还包含快捷键按键录入、清空并暂停、简体输出及保守 OCR 修补。
3,476 项源码回归与新 exe 离线自检通过，但小写 l8r 仍可能识别失败，长句仍可能重复或错译。
**尚未完成 Roblox 实时聊天、NVIDIA 录制、真独占全屏和全新 Windows 环境的本轮验收。**
退出旧版，完整解压新包，运行 `ScreenTranslator/ScreenTranslator.exe`；不要只复制 exe。
普通用户不需要安装 Python，不要下载 GitHub 自动生成的 Source code ZIP 来运行。
旧[聊天修补预发布](https://github.com/dhdhd723/windows-offline-screen-translator/releases/tag/v0.1.1-roblox-chat-fix-20261013)
和[正式 v0.1.0](https://github.com/dhdhd723/windows-offline-screen-translator/releases/tag/v0.1.0)保留，不覆盖原附件。
下文的本地候选记录是开发历史；本次包的实际验证范围以上述发布说明为准。

项目原始开发者署名：`dhdhd723`。源码元数据和后续构建的 Windows exe 备注保留此标记；
它用于核对来源，不是防复制或不可删除的保护机制，也不替代第三方组件的署名与许可证。

2026-10-15 OCR 局部重识别候选：真实 Windows 自绘窗口抓屏复现了相邻检测框重叠导致的多余字母、数字问题。新方案只对有几何证据的小范围联合图像重新识别，保留原始框和置信度，保护真实数字、否定词与消息边界；不确定则保留原文。未更换模型，仍有保守回退残留和旧模型错译。新 exe 构建及最终验收另行记录，不代表游戏、NVIDIA 录制或悬浮字幕实机验收完成。详见[OCR 局部重识别说明](docs/2026-10-15-OCR局部重识别说明.md)。

2026-10-14 本地翻译输出修补候选：英文→中文的新译文使用固定版本 OpenCC 1.1.9 官方词典统一字形；长段落按完整句子分别处理，再按原段落与消息行顺序组合；已确认的部分游戏名称、开发商名和一条游戏语境习语采用受控规则。未更换翻译模型，未增加大型运行组件，聊天昵称和 OCR 原文保持原样。新策略隔离旧译文缓存。源代码回归和真实离线模型固定文本检查已通过，Windows 完整包仍需独立构建核验；不代表普通长句已达到人工翻译质量，也不代表游戏或 NVIDIA 实机验收完成。详见[翻译输出修补说明](docs/翻译输出修补说明.md)。

此前的术语试验仍保留：完整、独立的 `Stardew Valley`、`Hollow Knight`、`Slay the Spire` 标题行使用已核对中文名称；明确的已知作者署名保持原名。本轮仅在明确语境下扩展少量行内专名，不对任意名称或未知专名做猜测。连续布局会合并 OCR 换行，建议单独框选标题，或使用逐行布局。普通菜单和对话仍使用原模型，仍有错译；这项修复不代表全屏显示问题解决。历史范围、语料及质量观察见[翻译质量试验语料](docs/翻译质量试验语料.md)。

当前源码版本为 **0.1.1 候选版，待验收**，不要将它当作已经验证的正式版本。
2026-10-08 本地候选增加持续抓屏异常后的低频自动恢复；主动停止仍会取消恢复，
确认显示器或选区改变时仍需重新框选。不代表 NVIDIA 同时录制已验收，见
[捕获恢复修订说明](docs/捕获恢复修订说明.md)。

2026-10-04 本地 R3 修订修复设置纠正后字幕恢复与暂时捕获错误的有限恢复，
增加不保存截图和文字的捕获健康诊断；须重新构建并验收，不沿用旧 exe 或哈希。
见 [R3 变更与测试边界](docs/0.1.1-R3变更说明.md) 和 [游戏兼容说明](docs/游戏兼容说明.md)。
《星露谷物语》已有一个菜单的显示与清空证据，其他游戏正确文字、
NVIDIA 实际录制和真独占全屏仍需验收。

已公开的旧版是 [v0.1.0](https://github.com/dhdhd723/windows-offline-screen-translator/releases/tag/v0.1.0)，
其中 [Windows 完整运行 ZIP](https://github.com/dhdhd723/windows-offline-screen-translator/releases/download/v0.1.0/ScreenTranslator-0.1.0-Windows-x64.zip)
不是本次 0.1.1 候选包。原版本和附件保持不变。

Windows 10 2004 及以上 / Windows 11，64 位。截图、OCR 和中英互译全部在本机完成。发布包自带模型，不需要 Python，不需要付费 API，也不需要显卡环境。

本仓库是开发源码，不包含 exe 或模型权重；“无需 Python”仅指完整便携运行包。[项目说明报告](docs/项目说明报告.md)记录 0.1.0 的历史构建与测试边界，不作为 0.1.1 已通过的证据；本轮状态以[发布状态](docs/RELEASE_STATUS.md)为准。

## 普通用户使用

快捷键修改：打开设置的“快捷键”页，点击对应行的“修改”，直接按下组合键并全部松开，然后点击“保存”。
无需手动输入快捷键名称。录入时按 Esc、点击取消、切换标签或离开设置窗口，会取消尚未完成的录入并保留原值。
录入期间仅暂停本程序的全局快捷键；其他软件或 Windows 占用的组合键不会被强行抢占，保存后的占用提示仍需留意。

完整解压便携包，在 ScreenTranslator 文件夹内双击 ScreenTranslator.exe。请保留同目录的 `_internal`、`models` 和 `LICENSES` 文件夹，不要只复制 exe。下载的是完整 Windows 运行包，不是 GitHub 自动生成的源码 ZIP。

首次正常启动须阅读并明确同意随包微软运行库条款，然后才会注册快捷键和
开启监控。不同意会退出；确认只存于本机设置，条款内容变化后会重新询问。
该条款不限制 Qt/GEOS/Eigen 等组件原许可证授予的源码、替换和调试权利。

1. 新配置按 Ctrl+Alt+R，拖动鼠标框选文字所在区域。可选择任意显示器，当前版本要求一个选区位于同一显示器内。旧配置会保留已保存的快捷键，请在托盘设置中手动修改，以实际显示的按键为准。
2. 按 Alt+T，开启持续翻译。首次翻译需加载本地模型，后续译文在文字变化后更新。
3. 再按 Alt+T 停止监控。停止后保留最后一条字幕。
4. Alt+C 清空字幕并停止持续翻译；Alt+T 恢复原选区，无需重新框选，同一句也可重新翻译。
5. 按 Esc 隐藏字幕，再按恢复。停止翻译后仍可隐藏保留的字幕。隐藏不会改变监控开关。Esc 也会传递给当前应用，可在设置中禁用全局 Esc。
6. 右下角托盘图标提供相同操作、设置、复制译文和退出。双击托盘图标开启/停止翻译。

字幕默认鼠标穿透、不抢焦点。框选时会暂时获取输入，以便拖动和 Esc 取消；设置窗口也正常接受输入。

手动启动后会显示约 2 秒的轻量启动卡片，正常播放完毕后自动打开设置窗口。
托盘与快捷键不等待动画结束才启用，也不因动画预加载模型。
可在托盘“设置”→“快捷键”取消“手动启动时显示 2 秒启动动画，结束后打开设置”，
此后直接进入托盘，不自动打开设置。
卡片不置顶、不接受输入；设置窗口正常接受输入和焦点，便于直接调整。
开始框选、启停、清空、隐藏、操作托盘、手动打开设置或退出会立即关闭卡片，
并取消本次自动打开设置，避免打断正在进行的操作。
前台窗口覆盖整个显示器或无法安全查询时保守跳过；这不是独占全屏兼容修复。
自动打开设置前会再次检查前台窗口；在动画期间切到全屏窗口也不会额外弹窗。
系统关闭动画时改为约 2 秒静态提示，正常结束后仍打开设置（查询失败也不播放动效），
无需更改 Windows 设置。
`--background` 和 `--no-startup-animation` 都可省略本次卡片及自动打开设置，
诊断模式不播放普通启动动画。
新设置的登录自启命令包含 `--background`；升级不会自行修改已有的注册表启动项，
已有自启项如需无动画，须在设置中先关闭并保存，再开启并保存以更新命令。
具体启动与取消行为见[启动界面说明](docs/启动界面说明.md)。

Roblox 等聊天场景中，若上下两行是两条独立对话，可在托盘“设置”→
“显示与翻译”→“文字排版”选择“逐行对话（聊天／Roblox）”，分别翻译并保留行顺序。
同一句话自动折行则保留默认“连续文本（段落／长句）”，避免切断上下文。
此修订需重新构建运行包，不会改变旧 exe；不代表已通过 Roblox 实机验收。
详见[逐行对话使用说明](docs/使用说明.md#聊天与-roblox-的逐行对话)。

聊天缩写词表默认启用，英文 → 中文时两种排版均生效，不需先切换逐行模式。
独立消息 `ty` / `tys` → `谢谢`、`np` → `没问题` 使用确定中文，不再只把英文缩写交给模型猜；
更长句中的缩写先展开为英文再翻译。明确的 `昵称: 正文` 保留昵称，仅翻译正文。
连续排版遇到两条带明确昵称前缀的 OCR 消息时自动保留独立行，普通段落软换行仍合并。
已内置 58 项，可在“内置词表”分页查看，无需逐条添加；“自定义（可选）”可以保持空白。
新增 sm1、l8r、cya/cyaa、prolly、cuz/bc、ppl、pic、rn、fr、hbu、yk、def、istg、tytl、mdfk、asf。
数字 2 仅在 want 2 play、talk 2 you 等明确短语中按 to 处理，裸数字和数量不替换。
TYTL 为用户确认的兼容写法；MDFK、ASF 含粗俗语气。RN、FR、BC、DEF 等按聊天选义，非通用缩写识别。
托盘“设置”→“聊天词表”可关闭或填写 `缩写 = 英文展开` 来覆盖、补充特殊用法。
常见词义及核对限制见[聊天内置词表](docs/聊天内置词表.md)。
原文保留，自定义英文规则优先于内置中文短回复；旧错误缓存不会用于新策略。
未命中仍交给本地模型；例如未知缩写 `oms` 尚无可靠词义，没有擅自添加释义。
普通口语长句仍可能错译，这项修订不是模型整体质量提升。详见[聊天修订说明](docs/聊天修订说明.md)。

“录屏兼容”默认开启（`recording_compatibility=true`）：不对本应用字幕启用
Windows 捕获排除，因此字幕允许被其他截图、录像或共享屏幕记录。关闭该
选项才尝试排除本应用字幕；它不是 DRM 绕过，也不修改游戏或 NVIDIA。
字幕应位于翻译选区外，避免程序反复识别自己的译文。

尽量只框选一两行清晰字幕或菜单，不要选择艺术字标题。区域过大、字号太小、运动背景、淡入和逐字字幕会增加识别时间。游戏优先使用普通窗口或无边框窗口。切换游戏、模式、分辨率后重新框选。已有菜单测试不代表全屏对白已通过；受保护的内容、真独占全屏和安全桌面可能无法捕获或无法叠加普通字幕窗。

配置保存在 `%LOCALAPPDATA%\ScreenTranslator\config.json`。默认不保存截图、不记录识别原文，翻译缓存仅存在内存。设置中可开启磁盘译文缓存，缓存数据库会保存译文；关闭选项不会删除已有数据库。

新配置的框选默认键改为 Ctrl+Alt+R，避免继续优先使用容易与其他工具冲突的 Alt+R；并不保证新按键在所有机器上空闲。升级不会自动覆盖旧配置中的键值，请在托盘设置中查看并手动修改。占用或注册失败时按托盘提示处理，也可先用托盘菜单操作；程序不修改其他软件的快捷键。显示器位置或分辨率变化后，需重新框选。

## 本地自检

发布程序支持 `--self-test --report 报告路径.json`。自检使用程序生成的中英文字图像，验证本地 OCR 与两个翻译方向，同时阻止并记录 Python 网络连接尝试。自检不读取用户屏幕；这不是操作系统级防火墙测试。

`--smoke-test --report 报告路径.json` 初始化 UI 和 Windows 集成后自动退出。自检结果不能代替具体游戏、显示器和 DPI 的实际验收。

`--startup-self-test --report 报告路径.json` 检查程序自己绘制的启动卡片、两秒自然结束、
资源清理及排队打开测试专用设置窗口的衔接，
不读取屏幕、不注册全局快捷键、不加载 OCR/翻译模型。无界面自动测试需设置
`QT_QPA_PLATFORM=offscreen`；该模式验证的是窗口标志和绘制生命周期，不代表实际焦点、游戏或 NVIDIA 录制验收。

`--capture-test --report 报告路径.json` 使用已保存选区有限检查真实 MSS、OCR 和本地翻译；不保存截图、原文或译文，不改选区和缓存。它不验收字幕显示或文字正确性。运行条件、字段和边界见[游戏兼容说明](docs/游戏兼容说明.md)。

诊断也需要先接受相同的随包条款；未接受时会返回退出码 3，而不是隐式同意。
明确读过条款并授权自动验收后，可对上述诊断模式增加
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

英文→中文默认输出按 OpenCC 官方 `t2s` 词典做一次字形转换，不修改模型权重，不转换聊天昵称；中文→英文不使用该转换。它不是语义润色，也不承诺解决地区用语或所有专名问题。固定词典版本、转换边界和第三方许可见[离线简体字形统一说明](docs/OpenCC词典说明.md)；新增名称与习语的正反例边界见[受控翻译术语](docs/受控翻译术语.md)。

当前交付的功能范围为单固定区域、任意显示器内框选、持续翻译、快捷键、悬浮字幕、托盘、持久配置和缓存。DXGI、跨屏选区、高质量模型包和字幕历史属于后续扩展。

## GitHub 发布与隐私

不要直接上传整个开发目录或原始便携包。先阅读 [发布与隐私说明](docs/PUBLISHING.md)，再从项目根目录生成干净源码和净化运行包：

```powershell
python tools/prepare_public_release.py --portable dist/ScreenTranslator --output build/public-export-0.1.1-candidate --candidate
```

导出器只读解析 source 的 pyproject 与应用版本字面量，二者不一致时拒绝导出，不执行待导出源码；ZIP 名称自动使用一致的版本。输出目录必须是新的，不能覆盖旧包。上述命令生成 `ScreenTranslator-0.1.1-Windows-x64-candidate.zip` 与 `ScreenTranslator-0.1.1-source.zip`。版本声明不证明输入 exe 是新构建；还须检查实际 exe 自检的版本和本轮哈希。

检查通过后，只将 `build/public-export-0.1.1-candidate/repo/` 的内容作为仓库源码；源码压缩包和净化便携包由同一工具生成。原始日志、测试报告、用户配置、译文缓存、真实截图和 Git 历史不能混入。GitHub 账号及提交作者信息仍可能公开，第三方版权声明必须保留。保留已核验的[纯 CPU 构建材料](docs/CPU_BUILD_PROVENANCE.md)，不混入旧 Intel/MKL/CUDA 候选二进制；微软运行库继续采用正式个人 Community 许可发行路径和官方原件。版本变更后重新核验，新 exe 不沿用旧摘要。实际发布及验收范围见[发布状态](docs/RELEASE_STATUS.md)，第三方材料见[核验记录](docs/THIRD_PARTY_BINARY_NOTICES.md)。导出默认是候选包，正式 `--final` 需要该源版本的唯一 approved 与 release-version 标记；目前 pending，不允许正式导出。导出工具不自动上传 GitHub。应用自身尚未选定开源许可证。

本程序使用 LGPLv3 许可的 Qt / PySide6 / Shiboken 6.9.3。便携包的 `LICENSES/Qt/` 包含 GPL/LGPL 全文及对应源码档案。关闭程序后，可在 `_internal/PySide6/` 与 `_internal/shiboken6/` 中替换接口兼容的库；允许为调试这些库的修改而进行逆向工程。详情见随包 Qt 声明，微软保护条款不限制这些原许可权利。

Shapely 使用 LGPLv2.1 的 GEOS 3.13.1 动态库。便携包的 `LICENSES/upstream/GEOS-3.13.1/` 提供对应源码与构建配方，完整许可在 `LICENSES/Shapely/`。兼容修改库可替换，允许为调试这些库的修改而进行逆向工程。

本软件部分基于 [FreeType Team](https://freetype.org) 的工作，FreeType 采用 FreeType License (FTL)；Pillow 的完整第三方文本保留在 `LICENSES/Pillow/`。This software is based in part on the work of the Independent JPEG Group.

ONNX Runtime 内嵌 Eigen、tqdm 和 certifi 的 MPL 对应源码、原许可和获取说明位于便携包 `LICENSES/upstream/` 的对应目录，详见 [对应源码核验](docs/COPYLEFT_SOURCE_NOTICES.md)。这些源码保持原许可权利，不受应用附加限制。
