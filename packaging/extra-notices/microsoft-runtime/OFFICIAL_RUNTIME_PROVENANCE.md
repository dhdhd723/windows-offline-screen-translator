# 官方 v14 x64 运行库原件来源记录

获取及核验日期：2026-10-02。对象为 Microsoft Visual C++ v14 Redistributable
(x64) **14.51.36247.0**。本记录固定官方字节来源；发行资格仍须满足
本目录 README、Community 正式许可及外部用户保护条款，不由哈希或签名单独授予。

## 官方包

- 官方下载页面：
  https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist?view=msvc-170
- 该页面所列 x64 永久链接：
  https://aka.ms/vc14/vc_redist.x64.exe
- 本次解析后的官方地址：
  https://download.visualstudio.microsoft.com/download/pr/ebdab8e5-1d7b-4d9f-a11b-cbb1720c3b12/843068991DAAA1F73AD9F6239BCE4D0F6A07A51F18C37EA2A867E9BECA71295C/VC_redist.x64.exe
- 文件大小：18,731,856 字节。
- SHA-256：`843068991daaa1f73ad9f6239bce4d0f6a07a51f18c37ea2a867e9beca71295c`。
- 文件版本及产品版本：14.51.36247.0。
- Authenticode 状态：Valid；签名者 Microsoft Corporation，颁发者
  Microsoft Code Signing PCA 2024。

## 静态提取及完整性

没有安装运行库，也没有执行 MSI 的安装或自定义动作。官方 `/layout` 动作
返回 0；日志中三个运行库包的 execute 均为 None。由于材料内嵌于 Burn 包，
随后用 WiX 官方 portable `dark.exe` 只读提取：先提取 Burn 附加容器，再从
`vc_runtimeMinimum_x64.msi` 的 CAB 静态提取文件。按 MSI File 表中的 `Name`
将 `*.dll_amd64` 的字节副本复制成正式 DLL 名称，没有修改文件内容或签名。

| 载荷 | 大小 | SHA-256 | 签名 |
| --- | ---: | --- | --- |
| `AttachedContainer/packages/vcRuntimeMinimum_amd64/vc_runtimeMinimum_x64.msi` | 212,992 | `bab5d0257e6a18a4a008e683442e3077b38172dd61af3cb1c588b46724a714e2` | Microsoft Corporation / Valid |
| `AttachedContainer/packages/vcRuntimeMinimum_amd64/cab1.cab` | 1,065,893 | `6e8ee73933678c55973e83366e48e948b394c7a36743a36b7224c95de979b13f` | Microsoft Corporation / Valid |

解包工具仅是私有构建依赖，不随本应用发行：

- 官方 WiX 3.14.1 发布页：
  https://github.com/wixtoolset/wix3/releases/tag/wix3141rtm
- 便携工具来源：
  https://github.com/wixtoolset/wix3/releases/download/wix3141rtm/wix314-binaries.zip
- 工具 ZIP SHA-256：
  `6ac824e1642d6f7277d0ed7ea09411a508f6116ba6fae0aa5f2c7daa2ff43d31`。
- 实际 dark 工具版本：3.14.1.8722。

## 原始 DLL 清单

以下文件均从同一份官方 Minimum x64 CAB 提取，版本均为
**14.51.36247.0**，PE Machine 均为 AMD64 (`0x8664`)，Authenticode 均为
**Valid**，签名者均为 **Microsoft Windows Software Compatibility Publisher
(Microsoft Corporation)**。以下是可选原件材料清单，不表示每个文件都必须
随应用发行；最终只收集经依赖检查和测试确认需要的文件，并记录实际相对路径。

| DLL | 字节数 | SHA-256 |
| --- | ---: | --- |
| `msvcp140.dll` | 643,512 | `7c26614e1d733892c2deac7e245ce115504b1d80592dd0a01b08e3e5a55f89ca` |
| `msvcp140_1.dll` | 35,768 | `206c931bf90fdad8816de3b5e2ef80b2bcaa9406c89ecc05fe6fddffe251e982` |
| `msvcp140_2.dll` | 274,872 | `d50d7883f20d1dc6191768d3746f52dd9cac89c346ffaed5be1f110c2f34a838` |
| `msvcp140_atomic_wait.dll` | 57,792 | `3d0cbfaa1bf3eecf5a3f4491d2960ee803cb994f30292c6adc4a07c498f60e2b` |
| `msvcp140_codecvt_ids.dll` | 31,160 | `8a65c7596ef2e6938731f5a1058e7e40145b6d97967cc649231a076b9a608d78` |
| `vcruntime140.dll` | 178,616 | `d1f4225df2cd877dbf130d5668a021dce3f94118455ff5ec952061c30afc9ce7` |
| `vcruntime140_1.dll` | 50,112 | `a7146c08f89fe5b04541ab507cdb59ff7b44534d4ba3c668a426c6450a03434e` |
| `vcruntime140_threads.dll` | 38,840 | `40f39e8cee5f5a531b4010e18b807e8fe265b908dc58f959ecb7ebc6ea6cb11a` |
| `concrt140.dll` | 374,200 | `54716f0738af891f283d213b5c8d11b25896bb8ee3097d301eae718560cf974e` |
| `vcomp140.dll` | 212,920 | `95d4ce4a6802d1e18b5e0e1722cc30ea72ca7e033f83828f05c0b7b993fe7cbf` |
| `vccorlib140.dll` | 350,648 | `09f93d5ff96ae09767f3e1af3cdd43a5a58f2598654fc63089429bb6f9f4737f` |
| `vcamp140.dll` | 417,728 | `dc283ffb87e9b82e687ed4e899ae062a209aa338207abfc9a89d61407d678bd4` |

原始 `msvcp140.dll`、`vcruntime140.dll`、`vcruntime140_1.dll` 的 SHA-256 与
2026-10-02 旧候选包 `_internal/` 基础副本一致，补齐了这三个原有文件的
精确官方来源。Qt 重签副本可在新构建输出中替换为上述官方原件，但必须
在替换后的最终输出上重新执行应用、OCR、翻译和 UI 依赖测试。

`vcomp140.dll` 的常规 PE 导入表只依赖 `KERNEL32.dll`；其余原件的导入
为同包 MSVC 运行库及 Windows 10/11 提供的系统/API-set DLL。不得因此推断
无需实际启动测试，也不得把任意 Windows 系统 DLL 复制进应用来凑依赖。

## 发布边界

只将必要的未修改原始运行库和适用声明放入应用。不要公开私有布局日志、
工具目录、解包工作区或 MSI 反编译文件，它们可能含本机安装路径或已有
系统运行库的来源。不要把 `/layout` 或 dark 解包成功当成 Community 安装
完成、最终包通过验收或全部许可条件已满足。最终发布状态由主验收报告确认。
