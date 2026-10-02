# 公开发布状态

<!-- release-status: approved -->

更新日期：2026-10-02。版本：0.1.0，Windows x64。

本轮完成纯 CPU 运行包构建、已识别第三方发行材料核验和本机核心功能验收，
可以生成并上传本轮完整便携 ZIP。**不要发布或重命名历史候选包。** 本记录
不是律师意见，也不保证所有 Windows 机器和硬件场景均已测试。

## 已完成的发行检查

- CTranslate2 4.8.2 与 Python 扩展从固定源码重建，关闭 CUDA/cuDNN/HIP/MKL；
  oneDNN 3.1.1 CPU INT8 启用。CPU 能力、构建缓存与普通/延迟导入检查一致。
- 新包不含 Intel OpenMP/MKL/CUDA/cuDNN/FFmpeg 二进制；旧组件声明仅作为
  历史核验资料保留，不代表其在新 CPU 包中使用。
- 作者确认个人独立开发，正式 Community 2022 17.14.41 安装成功；采用
  对应个人发行资格，而不是以 DLL 签名代替许可。
- 17 份 Microsoft v14 CRT/OpenMP 副本匹配官方未修改原件 14.51.36247.0，
  AMD64/哈希/离线签名通过；缓存式检查不声称已更新证书吊销信息。
- 首次条款默认不同意，明确勾选后才启动；拒绝、缺失、保存失败及内容
  改变重新确认的实现与测试通过，开发诊断不冒充外部用户已接受。
- 只面向 Windows 10/11，使用系统 UCRT，不重复分发 SDK 的 UCRT/API-set
  副本，不声称支持 Windows 7/8。
- Qt/PySide/Shiboken、GEOS、Eigen/tqdm/certifi 共 8 个对应源码档案实际
  随包保留，完整性与归档路径检查通过；原许可的替换、调试权利继续保留。
- 实际编译依赖、模型、Python 包、PyInstaller 的 Bootloader Exception/
  Apache 条款、FreeType/JPEG 致谢与 Noto OFL 原文保留。未据 PyInstaller
  GPL 文字强行为应用选择 GPL；没有分发或安装微软系统字体。
- 32 个模型文件（含 manifest）大小和哈希通过，中文兜底字体原件一致。

细节见 [原生构建哈希](CPU_BUILD_PROVENANCE.md)、[CPU 方案](CPU_ONLY_BUILD_PLAN.md)、
[微软核验](MICROSOFT_RUNTIME_TERMS.md)、[当前库与旧包历史证据](THIRD_PARTY_BINARY_NOTICES.md)
及 [LGPL/MPL 对应源码](COPYLEFT_SOURCE_NOTICES.md)。

## 本轮运行与隐私验收

完整开发环境 192 passed / 5 skipped；新 CPU 独立打包环境 190 passed /
7 skipped，无失败。额外 2 项为未打包 Transformers 的参考比较，另 5 项
为真实符号链接创建权限限制。

最终 exe 双向 OCR/翻译自检、UI/托盘/快捷键初始化退出 0；实际自建窗口
截图翻译、精确缓存键、字幕不抢焦点、原生窗口属性、捕获排除和快捷键
消息路由通过。稳定文字不重复推理、清空抑制同句、数字变化不过滤、停止
丢弃旧任务均通过。完整候选 ZIP CRC 通过，中文和空格路径完整解压后，
清除 Python/Qt/模型/配置开发变量并将 PATH 限为 Windows 目录，自检与
初始化仍退出 0。未接受或缺失条款时退出 3，不启动监控。

源码、应用字节码及原生文件未检出当前开发者路径、电脑名或凭据。上游
编译信息和厂商字符串保留；不为脱敏改写原生二进制。白名单导出不携带
测试已接受配置、缓存、日志、截图或原 Git 历史。最终导出 ZIP 还须复核
CRC、隐私和 exe 哈希；压缩文件摘要由交付清单固定。

最终 exe SHA-256：
`1974b547d5557a7b1fecb521b52af815e0bdbc6290f1f9e9e62aa6488c354241`。

## 未覆盖的场景与后续发布

实际测试为 Windows 11 x64 10.0.26100；虽清除了开发变量，但不是未安装
Python/Visual Studio 的干净虚拟机。Python 网络拦截无尝试，不是 OS
防火墙证明。computer-use 辅助工具未能初始化，未绕过它注入真实鼠标键盘；
鼠标实拖框选/物理 Esc、混合 DPI 多屏、游戏、长时间运行未做全面实机
覆盖，详见 [项目报告](项目说明报告.md)。程序未数字签名，核对来源和
校验码即可，不需要关闭安全软件。

导出默认 candidate；明确 `--final` 才生成本轮 Windows ZIP。状态标记是
防误发布措施，不是自动法律审查。源码内容放仓库，完整运行 ZIP 放 GitHub
Releases；GitHub 自动源码 ZIP 不能供普通用户运行。本轮运行包通过 GitHub Releases 发布，下载入口见仓库首页。
保留 `_internal/`、`models/`、`LICENSES/` 及对应源码。版本或工具链变更后
重新核验，不沿用本次哈希；发布者负责 app-local 运行库安全更新。应用
开源许可证仍由作者选择，公开源码不等于许可任意修改或再分发。
