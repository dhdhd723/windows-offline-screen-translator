# 本地屏幕翻译器

> 新增 [2026-10-20 聊天修补测试预发布](https://github.com/dhdhd723/windows-offline-screen-translator/releases/tag/v0.1.1-chat-core-20261020)：改进消息分行、部分多词昵称保护和短回复组合。复杂游戏口语仍可能错译，尚未完成 Roblox 实机验收，详见[候选说明](docs/聊天候选说明.md)。

[![聊天修补测试版](https://img.shields.io/badge/release-0.1.1%20Chat%20Core-orange?style=flat-square)](https://github.com/dhdhd723/windows-offline-screen-translator/releases/tag/v0.1.1-chat-core-20261020)
[![Windows](https://img.shields.io/badge/platform-Windows%20x64-0078D4?style=flat-square)](#兼容与限制)
[![Downloads](https://img.shields.io/github/downloads/dhdhd723/windows-offline-screen-translator/total?style=flat-square&label=Downloads)](https://github.com/dhdhd723/windows-offline-screen-translator/releases)
[![Stars](https://img.shields.io/github/stars/dhdhd723/windows-offline-screen-translator?style=flat-square&label=Stars)](https://github.com/dhdhd723/windows-offline-screen-translator/stargazers)

**框选屏幕上的文字，在本机识别并翻译成悬浮字幕。**
适用于 Windows 上的游戏聊天、菜单和网页文字。支持中英互译，以及手动选择日语转简体中文。开启持续翻译后，程序监控固定区域，文字变化时更新译文；截图、OCR 和翻译都在本机完成。
*Offline screen translator for Windows: Chinese ↔ English, Japanese → Simplified Chinese.*

完整运行包自带模型和运行依赖，无需安装 Python、配置显卡或使用付费 API。项目署名 **dhdhd723**。
当前提供 **2026-10-20 聊天修补测试预发布版**，完整包约 792.9 MB，保留中英和日语模型，没有加入试验性大模型。已完成本机离线自检，但不保证所有游戏、全屏模式或文字都能正确识别和翻译，详见[兼容与限制](#兼容与限制)。

- 框选固定区域，持续监控文字变化，结合相似度与缓存减少重复处理。
- 中英双向翻译，另可选择“日语 → 简体中文”；不依赖在线翻译服务。
- 半透明置顶字幕默认鼠标穿透、不抢焦点，支持隐藏、复制译文及托盘操作。
- 内置 58 项聊天缩写，独立消息 `ty`、`np` 等可直接得到中文短回复；支持自定义词表和逐行对话模式。
- 点击“修改”后直接按下快捷键组合，无需手动输入名称；清空键同时停止监控，启停键可恢复原选区。
- 保存不同情境的设置为场景预设，可选带上选区和字幕位置，最多 20 项。

## 下载与运行

| 下载 | 内容 |
| --- | --- |
| [完整 Windows 测试运行包（7z，约 792.9 MB）](https://github.com/dhdhd723/windows-offline-screen-translator/releases/download/v0.1.1-chat-core-20261020/ScreenTranslator-0.1.1-Chat-Core-Candidate-20261020-Windows-x64.7z) | **含 EXE**、中英和日语模型、运行依赖、许可及对应源码，普通用户下载这一项 |
| [本次发布页与文件校验](https://github.com/dhdhd723/windows-offline-screen-translator/releases/tag/v0.1.1-chat-core-20261020) | 更新说明、验收报告、对应源码 ZIP 与 SHA256SUMS.txt |
| [上一版日语增强完整包](https://github.com/dhdhd723/windows-offline-screen-translator/releases/tag/v0.1.1-japanese-20261016) | 2026-10-16 版本，7z 约 791 MB，保留供回退 |
| [只需中英的旧场景预设版](https://github.com/dhdhd723/windows-offline-screen-translator/releases/tag/v0.1.1-scene-presets-20261016) | 不含日语模型，ZIP 约 379 MB；属于之前的预发布版 |
| [全部历史版本](https://github.com/dhdhd723/windows-offline-screen-translator/releases) | 保留旧预发布与正式 v0.1.0，不覆盖原附件 |

1. 从托盘退出旧版，将新 Windows 7z **完整解压到新目录**；系统无法打开时可使用 [7-Zip 官方工具](https://www.7-zip.org/download.html)。
2. 进入 `ScreenTranslator` 文件夹，双击 `ScreenTranslator.exe`。
3. 首次启动阅读并确认随包微软运行库条款；不同意会退出，不会启动监控。
4. 正常手动启动显示约 2 秒启动卡片，结束后打开设置。关闭该选项后直接进入托盘。

请保留 exe 同目录的 `_internal`、`models` 和 `LICENSES` 文件夹，不要只复制 exe。
GitHub 自动生成的 **Source code ZIP 不是运行包**；仓库源码不含 exe 和模型权重。“无需 Python”只适用于完整运行包。
本次运行包为 792,893,185 字节，使用无损压缩；711 个文件重新解压后逐项校验一致。保留原有模型、运行依赖和许可文件，不通过删减运行组件或降低模型精度压缩体积；解压后约 1.095 GB，运行内存不会因压缩而下降。之前日语版的 695 文件、791.1 MB 数据只适用于历史包。

## 使用

以下是新配置的默认快捷键。升级会保留旧配置，以设置页显示的实际按键为准。

| 操作 | 默认按键 | 行为 |
| --- | --- | --- |
| 框选区域 | `Ctrl+Alt+R` | 拖动选择文字所在区域，一个选区须在同一显示器内 |
| 开启 / 停止 | `Alt+T` | 开始持续翻译；再次按下停止，保留最后字幕 |
| 清空并停止 | `Alt+C` | 清空字幕并停止监控；再按启停键可翻译原选区，同一句也能重新翻译 |
| 隐藏 / 恢复 | `Esc` | 只改变字幕可见性，不改变监控状态；可在设置中禁用 |

右下角托盘菜单提供同样的操作、设置、复制译文和退出。双击托盘图标也可启停。
Esc 会继续传给当前应用；框选层和设置窗口需要正常接受输入，不属于字幕的鼠标穿透范围。
更改快捷键时，点击对应行的“修改”，按下组合键并全部松开，再保存；录入中的 Esc 用于取消。
快捷键被系统或其他软件占用时会提示，请更换组合键或使用托盘菜单。

字幕放在翻译选区外，避免反复识别自己的译文。尽量框选一两行清晰文字；首次翻译需要加载模型，字号小、运动背景和大选区都会增加识别时间。

### 日语转简体中文

设置 →“显示与翻译”→“翻译方向”选择“日语 → 简体中文（需日语模型包）”，保存后框选清晰横排文字，再按启停键翻译。
可以把日语方向和排版保存为场景预设。原“自动判断中英方向”仍只处理中英；不含中文转日语、日语转英文或三语自动识别。

日语模型在首次使用时加载；切换语言会在后台释放另一类模型，再切回时可能重新等待加载。没有模型时会明确提示，不会自动联网补包。
竖排、注音小字、艺术字、姓名与混合语言尚无可靠支持承诺；普通短句也可能错译，见[日语使用与模型说明](docs/日语支持说明.md)。

### 场景预设

在游戏聊天和网页段落之间切换时，可以分别保存排版、方向、词表、字幕样式、性能和快捷键。

1. 调整设置并先点击“保存”。有未保存草稿或正在录入快捷键时，预设入口会提示先处理。
2. 打开托盘“场景预设…”或设置中的同名页，选择“保存当前设置为新预设…”。按需要勾选保存选区及字幕位置。
3. 选中预设并应用，程序清空旧字幕、暂停监控；确认区域合适后，按当前启停键恢复。

支持更新、重命名和确认后删除，最多 20 项，名称最多 40 个可见字符。
开机启动、启动动画和许可确认记录不随预设切换。未保存空间坐标时保留当前区域；保存的区域失效时会清除并提示重选。
预设不按游戏进程自动切换，也不会自动开始抓屏。游戏窗口、文字布局或缩放改变后仍应检查选区。
详见[场景预设说明](docs/场景预设说明.md)。

### 聊天与段落

两条独立消息选择“逐行对话（聊天／Roblox）”，一句话自动换行则使用“连续文本（段落／长句）”。
明确的 `昵称: 正文` 会保留昵称；逐行模式还可保护部分两到三个首字母大写的英文显示名。连续模式遇到两条明确带单词昵称的消息也会保留独立行。只有 OCR 位置明确支持的缩进续行才合并，不猜测左对齐或位置不明的换行。

内置词表默认启用，无需逐条添加：独立的 `ty` / `tys` → `谢谢`、`np` → `没问题`；长句中的缩写先展开为英文，再交给模型。
数字 `2` 只在 `want 2 play` 等明确短语中按 `to` 处理。TYTL 是用户确认的“回头聊”兼容写法；MDFK、ASF 含粗俗语气。
本轮支持短回复组合，例如 `ty np lol` → `谢谢，没问题，哈哈`。关闭词表时，逐行昵称保护仍可生效，但不展开缩写。
多义缩写仍有风险；词表不为未知缩写编造释义，但后续模型仍可能自行猜错。设置 →“聊天词表”可查看、关闭或覆盖规则，详见[58 项内置词表与来源](docs/聊天内置词表.md)。

## 兼容与限制

- 目标系统为 Windows 10 2004 及以上 / Windows 11，64 位。仅支持单个固定区域，可在任一显示器内框选，不支持跨屏选区。
- 普通窗口或无边框窗口优先。真独占全屏、受保护内容和安全桌面可能无法捕获，或无法叠加普通悬浮字幕；当前没有全屏覆盖保证。
- “录屏兼容”默认开启，允许其他录屏或共享软件记录字幕；关闭时才尝试排除本应用字幕。它不修改 NVIDIA 或游戏，也不是绕过内容保护。
- 本次完整源码回归为 4,247 项通过、10 项跳过；跳过不计为通过。实际 OCR 使用生成图片，另有 52 条构造文本的真实轻量模型对照，不是代表性准确率测试。
- 新 EXE 通过本机隔离启动、中英与日语离线翻译、聊天处理自检；711 个文件重新解压并逐项核对一致，解压后的 EXE 再次通过聊天自检。这些不是实时游戏验收。
- **本轮尚未完成 Roblox 实时聊天、NVIDIA 录制、真独占全屏、物理多屏混合 DPI 和干净 Windows 系统的实机验收。** 离屏 Qt 控件、临时数据和合成图像测试不能替代这些检查。
- 普通长句仍可能重复、漏译或错译，扩展语义关键词检查仍为 4/8；`l8r` 可能被 OCR 误识别。简体字形转换不等于语义润色，已知专名规则也不覆盖未知名称。
- 日语仍有已记录错译，例如“ここで待ってください。”得到“请等到这里。”，不能把“返回中文”当作“意思正确”。本轮也没有完成真实日文游戏验收。
- 程序未数字签名，Windows 可能提示未识别发布者。可用发行页的 `SHA256SUMS.txt` 核对文件，不需要关闭安全软件。

本轮完整验证、哈希和测试边界见[聊天修补验收报告](docs/releases/CHAT_CORE_ACCEPTANCE_20261020.md)与[完整包交付验证](docs/releases/CHAT_CORE_DELIVERY_20261020.md)。报告及包内说明记录的是发布前验收状态；其中“尚未发布”不表示当前发布页没有附件。运行包保持验收时的原始字节，不为更新这句话重新打包。
旧版日语数据见[2026-10-16 日语测试报告](docs/releases/JAPANESE_TEST_REPORT_20261016.md)与[无损精简说明](docs/releases/LOSSLESS_PACKAGE_REPORT_20261016.md)，不能当成本轮新增测试。
历史实机片段只说明当时的菜单或窗口，不自动作为本版通过证据。

## 本地数据与隐私

设置位于 `%LOCALAPPDATA%\ScreenTranslator\config.json`，场景预设单独保存在同目录的 `presets.json`。
预设只包含设置，不包含截图、识别原文、译文或缓存内容；写入失败不会切换配置，损坏或未知版本的预设文件不会被空白内容覆盖。

默认不保存截图、不记录识别原文，译文缓存仅在内存中。可选磁盘缓存会保存译文，关闭选项不会删除已有数据库。
公开运行包和源码过滤个人配置、预设、缓存、真实截图与原始测试日志；分享诊断文件前仍需检查内容。
README 顶部徽章使用外部图片，只用于 GitHub 页面展示，不参与应用运行。

## 从源码运行与构建

开发环境为 Python 3.12 x64，使用 PySide6 Widgets、Win32 API、MSS、RapidOCR / ONNX Runtime、CTranslate2 INT8 和 SentencePiece。
运行时不使用 PyTorch 或 Transformers。模型准备和开发依赖安装需要联网，完成后应用可以离线运行。

```powershell
python -m pip install -e ".[build,models]"
python tools/prepare_models.py
python -m pytest
python launcher.py
python launcher.py --self-test --report build/self-test.json
python -m PyInstaller packaging/ScreenTranslator.spec --distpath dist --workpath build/pyinstaller
```

以上默认准备中英模型。日语模型需另外按[日语构建说明](docs/日语支持说明.md#构建与来源)使用 `tools/prepare_japanese_model.py` 准备，并将固定哈希与模型许可纳入清单；不要将开发转换环境复制进运行包。

这些命令不自动生成与发行包一致的纯 CPU 原生库。正式重建须按[纯 CPU 构建方案](docs/CPU_ONLY_BUILD_PLAN.md)编译并安装本地 CTranslate2 wheel，再复制模型、收集许可及对应源码，并重新核验新 exe。
不要将包索引中的 CUDA-enabled wheel 当作本项目已核验构建；打包、许可与净化步骤见[开发与构建完整记录](README-HISTORY.md#开发与构建)和[发布与隐私说明](docs/PUBLISHING.md)。

OCR 使用 RapidAI 转换的 PP-OCRv5 mobile ONNX 模型及匹配字库，复用其日语识别能力；中英翻译使用 Helsinki-NLP `opus-mt-zh-en`、`opus-mt-en-zh`，日语转中文使用固定版本 `facebook/m2m100_418M`，均转换为 CTranslate2 INT8。
模型来源、固定版本与哈希在完整包 `models/manifest.json`；英中模型为 Apache-2.0，中英模型为 CC-BY-4.0。
新增 M2M100 模型保留独立 MIT 通知；日语原文不做繁简转换，最终中文译文按既有策略统一简体字形。
英中输出按固定 OpenCC 官方词典做一次简体字形转换，不改昵称或模型权重。当前没有 DXGI、跨屏选区、高质量模型包或字幕历史功能。

## 文档

| 文档 | 内容 |
| --- | --- |
| [本次发布说明](docs/releases/v0.1.1-chat-core-20261020.md) | 聊天结构与短回复修补、附件与下载说明 |
| [聊天验收报告](docs/releases/CHAT_CORE_ACCEPTANCE_20261020.md) | 本轮源码、EXE、模型检查与未解决问题 |
| [完整包交付验证](docs/releases/CHAT_CORE_DELIVERY_20261020.md) | 711 文件校验及解压后 EXE 自检 |
| [旧版日语测试报告](docs/releases/JAPANESE_TEST_REPORT_20261016.md) | 2026-10-16 日语模型验证、已知错译及未测范围 |
| [无损精简说明](docs/releases/LOSSLESS_PACKAGE_REPORT_20261016.md) | 体积对比、逐文件哈希与解压后 exe 自检 |
| [日语支持](docs/日语支持说明.md) | 方向选择、识别范围与模型构建 |
| [使用说明](docs/使用说明.md) | 操作、排版与常见问题 |
| [场景预设](docs/场景预设说明.md) | 保存范围、应用行为和坐标校验 |
| [游戏兼容](docs/游戏兼容说明.md) | 捕获、字幕、录屏与诊断边界 |
| [发布状态](docs/RELEASE_STATUS.md) | 候选状态及历次验收记录，当前仍为 pending |
| [历史介绍与开发记录](README-HISTORY.md) | 原首页完整记录、诊断参数、模型与许可证说明 |
| [技术方案](docs/技术方案.md) | 模块、线程与实现方案 |

## 署名与许可

项目原始开发者署名为 **dhdhd723**，源码元数据与 exe 备注保留来源标记；这不是防复制机制。
应用自身尚未选定开源许可证，公开源码不等于授权任意复用；第三方组件仍适用各自许可。

第三方组件保留各自许可：Qt / PySide6 / Shiboken 使用 LGPLv3，GEOS 使用 LGPLv2.1；对应源码、替换和调试权利及其他依赖通知随完整包 `LICENSES/` 提供。
微软运行库使用已核验的个人 Community 发行路径；本包不混入旧 Intel OpenMP、MKL、CUDA 或 cuDNN 候选二进制。
本软件部分基于 [FreeType Team](https://freetype.org) 的工作。This software is based in part on the work of the Independent JPEG Group.
详见[第三方材料](docs/THIRD_PARTY_BINARY_NOTICES.md)、[对应源码说明](docs/COPYLEFT_SOURCE_NOTICES.md)与[微软运行库条款](docs/MICROSOFT_RUNTIME_TERMS.md)。
