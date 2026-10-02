# Microsoft Visual C++ 运行库发行依据

核验日期：2026-10-02。本目录保存微软官方许可及 REDIST 页面证据，和本应用
面向外部用户/分销商的保护条款。它不是微软对本项目的背书，也不是法律意见。

## 资格与必须完成的发布条件

开发者已在本项目对话中明确确认是个人独立开发，并明确授权安装免费
Visual Studio Community 的最小 C++ 组件及 Windows SDK。Community 2022
`Individual License` 允许个人开发自己的应用，包括销售或其他目的，不以应用
先选择 OSI 开源许可证为个人资格条件。安装时应接受适用正式许可；成功取得
并安装有效许可的 Community 后，才可据此行使第 4 节的发行权。

发行者必须同时满足：

- 本应用为运行库增加实质主要功能；截图、OCR、本地中英翻译及字幕功能满足
  技术事实上的独立应用功能，不是单独转售运行库。
- 仅发行 REDIST 范围中未修改的正式运行库，不发行 debug_nonredist、Preview、
  Pre-release 或 Beta 组件；保留版权和许可声明。
- 要求外部分销商和最终用户同意至少同等保护微软可再分发代码的条款。
  本包应在首次普通启动时显示 `final-user-terms.txt`，由用户明确同意后再启用
  截屏、快捷键和后台翻译；拒绝则退出。该保护文本只约束微软运行库。
- 发行包、程序名称和说明不得暗示 Microsoft 制作、担保或认可本应用。
- 不把微软组件源码改成要求公开源码或赋予修改权的排除许可证；不要把
  应用开源许可或 Qt/GEOS/Eigen 的许可套在微软二进制上。
- 合法分销商只有在应用发行者或其独立适用许可授权时，才可完整随应用
  发行未修改运行库，并向后续接收者传递保护条款。独立终端运行库 EULA
  不是再分发许可。

有效签名证明二进制身份/完整性，但不单独证明发行资格。免费工具本身也
不意味着任意人均已取得所有运行库的发行权。请保存安装版本和最终文件清单。

2026-10-02 旧候选包中的 9 个 PySide6/shiboken6 运行库副本由 Qt Company
签名，并非 Microsoft 签名原件。本次不推断重签名满足 REDIST 未修改条件；
最终便携包应使用已许可正式 VC\\redist 或微软明确列出的正式来源中的
未修改 Microsoft 签名文件，并重新测试，不能手工删改签名。

已从微软官方下载 14.51.36247.0 x64 正式包并静态提取原件，全部校验为
Microsoft 签名 Valid。精确包/CAB/DLL 来源与哈希见
[官方运行库原件来源记录](OFFICIAL_RUNTIME_PROVENANCE.md)。这解决原件来源，
不代替 Community 有效安装资格、外部用户接受或最终替换后的应用验收。

## 本目录原文

以下 TXT 是从对应 Microsoft 官方 DOCX 的 `word/document.xml` 中按段落
顺序提取的文本：未改写正文；Word 自动列表编号及排版不在纯文本中保留。
本地原始 DOCX 也予以留存，但公开导出工具只导出原文 TXT 和网页文本，
不导出 Word 元数据。若需要核对编号或格式，可从下列官方链接取得 DOCX。

| 文件 | 官方依据 |
| --- | --- |
| `Visual-Studio-2022-Community-License-EN.txt` | Community 2022 软件许可；EULAID `VS_Comm_2022_ENU.1033`；个人资格及第 4 节 Distributable Code |
| `Visual-Studio-2022-REDIST-official.html` | 正式 VS 2022 REDIST，含 `VC\redist`、排除 `debug_nonredist`，以及官方 latest VC 运行库来源 |
| `Visual-Cpp-redistribution-guide-official.html` | 微软部署说明：发行资格、应用本地 DLL 与中央安装的区别 |
| `Visual-Cpp-latest-supported-redist-official.html` | v14 为 VS 2017/2019/2022/2026 共用运行库；目标机运行库不得低于编译工具链版本 |
| `Visual-C-Runtime-2015-2022-License-EN.txt` | 2015–2022 终端运行库许可；EULA ID `Cpp_2015-2022_ENU.1033` |
| `Visual-C-V14-License-Redistributable-and-Runtime-2026-EN.txt` | v14 正式终端许可，原文更新 2025-10-01；EULA ID `Cpp_v14_ENU.1033`，用于 v14 最新版本核对 |
| `final-user-terms.txt` | 本应用的外部用户/分销商保护条款；不是微软原文或应用开源许可证 |

本项目可能随不同上游依赖带多份 v14 DLL；终端运行库许可应与实际版本
及其上游授权对应。保存两个正式运行库许可原文是为覆盖本项目现有的
2015–2022 和较新 v14 组件，不代表可以任选一个许可取代其真实适用条件。

### 官方来源

- Community 2022 许可页面：
  https://visualstudio.microsoft.com/license-terms/vs2022-ga-community/
- Community 2022 原始 DOCX：
  https://visualstudio.microsoft.com/wp-content/uploads/2021/11/Visual-Studio-2022-Community-License-EN.docx
- REDIST：
  https://learn.microsoft.com/en-us/visualstudio/releases/2022/redistribution
- 发行指引：
  https://learn.microsoft.com/en-us/cpp/windows/redistributing-visual-cpp-files?view=msvc-170
- 最新 v14 正式运行库：
  https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist?view=msvc-170
- 2015–2022 运行库许可页面：
  https://visualstudio.microsoft.com/license-terms/vs2022-cruntime/
- 2015–2022 原始 DOCX：
  https://visualstudio.microsoft.com/wp-content/uploads/2021/09/Visual-C-Runtime-2015-2022-License-1.docx
- 最新 v14 正式运行库许可页面：
  https://visualstudio.microsoft.com/license-terms/vs2026-ga-visualcpp-v14-redist-runtime/
- 最新 v14 原始 DOCX：
  https://visualstudio.microsoft.com/wp-content/uploads/2025/10/Visual-C-V14-License-Redistributable_and_Runtime_ENU.docx

### 获取时 SHA-256

网页带动态元数据，再次抓取其哈希可能不同；以下哈希固定本次保存的证据。

| 原文文件 | SHA-256 |
| --- | --- |
| Community 原始 DOCX | `41a207b10c8ab91d0d2f10a854715f73dca54509581692d2fe179aa3ffcb8540` |
| 2015–2022 Runtime 原始 DOCX | `f1e3d56ceb2ad68aae0711b910375009e651ac5530fa0760f0dea6e81e54fae1` |
| 最新 v14 Runtime 原始 DOCX | `08651651a7602fc7c0e2763de0fde1ff9f868df2780597cd1775ee9d6441c783` |
| 2022 REDIST 官方 HTML | `a616275981c776f997eb518e8ca9de55c7d51b0f490f5487f01798134810b62c` |
| 发行指引官方 HTML | `1d77f40cb7db5467e7bb9d6d66dbf20fdfff3c06ab52494c020d6b8bc4fa630b` |
| latest v14 官方 HTML | `e789b23ad81537a66924bf7ed5db72bac7f9fe4fdb424cc2181fcfd6679ddc2e` |

Qt/PySide6/Shiboken、GEOS、Eigen 和其他组件仍适用各自许可证。为修改 LGPL
组件调试而需要的替换、重新链接或许可允许的逆向权利，不能被本说明取消。
应用作者仍需单独决定自己的应用源码许可证；本文件没有作这个选择。
