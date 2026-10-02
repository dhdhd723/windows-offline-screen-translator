# Microsoft 运行库的发布条款与验收

核验日期：2026-10-02。范围是此项目 Windows x64 便携包中的 Microsoft
C/C++ 运行时；本记录不是律师法律意见，也不是软件厂商背书。

## 发行资格结论

作者已明确确认本项目是个人独立开发，并明确授权安装最小 C++/SDK 组件。
微软 Community 2022 的个人许可允许个人开发自己的应用，无论销售或其他
用途，不要求先选定应用开源许可证。[Community 正式许可](https://visualstudio.microsoft.com/license-terms/vs2022-ga-community/)

安装有效正式许可的 Community 后，其第 4 节允许发行 REDIST 清单中的
未修改目标代码，并允许应用分销商随应用发行；要求应用提供实质主要功能、
外部用户/分销商同意保护微软代码的条款、不发行预览或调试非发行组件。
VC\redist 路径及官方下载页所得正式运行库在范围内。
[微软 REDIST](https://learn.microsoft.com/en-us/visualstudio/releases/2022/redistribution)

**因此本项目采用个人 Community 许可发行路径，而不是仅凭 DLL 签名、
Python 附带许可或“工具免费”推断已取得发行资格。** 安装完成版本、最终
DLL 清单与签名检查，必须由最终构建/验收记录固定；本文件单独不能证明
安装和最终发布步骤已经成功。

实际安装已于本轮完成：Community 2022 17.14.41（内部 17.14.37710.0）、
VisualStudio.17.Release 正式通道，完整、可启动、非预发布、无需重启；安装器
退出码 0。MSVC x64 cl 19.44.35229.0 / link 14.44.35229.0，SDK 10.0.26100.0
/ rc 10.0.26100.7705；三个工具均为 Microsoft Corporation 有效签名。
本公开记录不包含用户安装目录或原始日志。独立 CMake 3.31.10 用于构建，
没有将未安装 Visual Studio 的 CMake 可选组件误当作缺少 C++ 编译器。

## 用户接受要求

第三方原文与保护条款保存在：
`packaging/extra-notices/microsoft-runtime/`；便携版对应
`LICENSES/upstream/microsoft-runtime/`。

首次普通 GUI 启动应展示完整 `final-user-terms.txt`，版本标识为
`microsoft-runtime-2026-10-02-v1`；只有用户明确同意才继续，并在个人设置
中保存接受的版本/内容摘要。不同意或缺失/不能读取该文件则退出。
拒绝前不得开始区域截图、注册全局快捷键或启动翻译任务。更新保护条款
版本或内容摘要后重新请求接受。自检等开发者模式的验收不能冒充普通
外部最终用户已经接受；自动测试资料也不能带着“已经接受”设置公开发行。

该条款只保护 Microsoft 运行库。不得把禁止修改和逆向的要求套在整个
源码、Qt/PySide6、GEOS 或 Eigen 上。LGPL/MPL 组件的对应源码、动态替换、
重新链接、许可允许的调试逆向等权利继续保留；本说明不替作者选择
应用本身的开源许可证。

普通用户无需安装 Visual Studio 或 Python。安装编译工具是发行者构建和
取得发行依据的步骤；便携包应完整携带应用实际所需的未修改可发行 DLL。

## DLL 版本与来源核验

2026-10-02 的旧候选包扫描发现 15 个 Microsoft v14 DLL 副本，分布于
`_internal/`、`PySide6/`、`shiboken6/`、`numpy.libs/`、`rapidfuzz.libs/` 和
`Shapely.libs/`。所有扫描到的副本 Authenticode 状态均为 Valid；本次先前
签名检查只是身份证据，不单独等于许可结论。

| 来源组 | 旧候选包版本 | 说明 |
| --- | --- | --- |
| `_internal` 基础 MSVCP/VCRUNTIME | 14.51.36247.0 | 较新 v14，不能因为 Community 2022 编译器较旧就随意降级 |
| PySide6 / shiboken6 | 14.44.35211.0 | 上游 wheel 副本被 Qt Company 签名；不可只凭 Valid 推断是未修改微软原件 |
| NumPy / RapidFuzz | 14.40.33810.0 | 上游工具带哈希后缀名称，内容保持签名完整 |
| Shapely | 14.44.35215.0 | 上游工具带哈希后缀名称，内容保持签名完整 |

深入检查发现 9 个 PySide6/shiboken6 运行库副本的签名者是
`The Qt Company Oy`，其余 6 个运行库副本为 Microsoft。上游可能对这些
文件重新签名；本次核验不把 Qt 重签名等同于 REDIST 所要求的未修改微软
原始目标代码。最终包应从发行者已许可安装的正式 VC\\redist 或微软明确列出
的正式运行库来源收集未修改、Microsoft 签名的对应文件，替换这些候选包
副本，并重新测试。文件本身不能通过手工删改签名来“修复许可”。

最终 CPU 重建已引入 `vcomp140.dll`（MSVC OpenMP），已纳入实际清单。
只从已许可工具链的正式 VC\redist，或微软明确列出的正式运行库来源收集
未修改文件。不要使用编译器 bin 目录中的调试 DLL，也不要从任意 System32
副本推断具有发行授权。

当前微软文档说明 VS 2017/2019/2022/2026 共用 v14 正式运行库；版本不得低于
用于构建相应组件的工具链。若要统一 DLL，必须固定官方最新版包/安装
VC\redist 来源，并重新测试全部原生依赖，不能按文件名猜兼容。
[最新 v14 运行库说明](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist?view=msvc-170)

本轮准备的官方原件版本为 `14.51.36247.0`，12 个 DLL 的 AMD64、版本、
签名与精确 SHA-256 已记录在随包上游声明中的
`OFFICIAL_RUNTIME_PROVENANCE.md`。`tools/normalize_microsoft_runtime.py`
默认只预检，明确使用 `--apply` 才替换新停止运行的 staging 包；它固定原件
哈希，保留带上游哈希后缀的文件名，拒绝版本降级、目录交叠和文件链接，
将备份与相对路径清单保存在另外的新目录。只有指定原生 PE 的实际 import
需要时才补入 `vcomp140.dll`。旧候选包未执行该替换。

本轮新 CPU staging 的 16 份已有 v14 副本已以官方原件标准化，另新增
`_internal/vcomp140.dll`，共 17 份；Shiboken 原来就附有另一份 VCOMP。
所有实际目标的相对路径、官方映射、版本及 SHA-256 见随包
`LICENSES/upstream/microsoft-runtime/FINAL_RUNTIME_MANIFEST.md`，源码对应
`packaging/extra-notices/microsoft-runtime/FINAL_RUNTIME_MANIFEST.md`。
替换前备份及开发者原始测试报告不公开，不沿用 Qt 重签名副本作官方来源。

仅支持 Windows 10/11，打包排除重复 `ucrtbase.dll` 和 `api-ms-win-*`
转发 DLL。Microsoft 明确这些系统始终使用系统 UCRT；它们的 PE 导入仍
正常存在，依赖由操作系统提供和维护，而不是声称所有 Windows 系统文件
也装入便携包。[UCRT 部署说明](https://learn.microsoft.com/en-us/cpp/windows/universal-crt-deployment?view=msvc-170)

该工具的签名验证采用 Windows `WinVerifyTrust` 的离线缓存模式，不联网
获取证书或撤销信息；因此其通过不能冒充已检查最新撤销状态。签名主体
按实际证书记录，微软官方 DLL 为 Microsoft Corporation 或 Microsoft
Windows Software Compatibility Publisher；Qt 重签名只允许作为待替换
的现存目标，不允许作为微软原件来源。

便携本地 DLL 便于无需安装直接启动，但 Microsoft 不单独替应用更新这些
副本；发布者需跟踪安全更新并重新构建发行。正式安装器可采用微软中央
运行库安装程序，让运行库独立维护。两种部署方式都需有效发行资格。
[微软部署指引](https://learn.microsoft.com/en-us/cpp/windows/redistributing-visual-cpp-files?view=msvc-170)

## 最终验收清单

1. 保存成功安装的 Community 版本、正式通道、工具链及 SDK 版本。
2. 最终包每份微软 DLL 保存相对路径、版本、SHA-256、Authenticode 状态和
   正式来源；无 debug_nonredist、Preview、Pre-release 或 Beta 组件。
3. 保存官方许可与 REDIST 原文，并与便携包文件清单对应。
4. 普通首次启动显示保护条款；拒绝/关闭退出；同意后正常使用；已接受相同
   内容不重复提示；条款缺失或变化按设计阻止/重新请求。
5. 首次启动、OCR、中英双向本地翻译、UI/托盘/快捷键退出测试通过。
6. 在没有 Python、Visual Studio 或用户旧配置参与的测试条件下检查依赖
   是否自足；如没有干净系统测试条件，应明确实际验证范围，不作全 Windows
   版本/机器保证。

最终发布结论以完成后的发布状态与验收报告为准，不以本说明存在为准。
