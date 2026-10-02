# GitHub 发布与隐私检查

公开源码与公开运行包是两件事。仓库只应包含经过检查的源码导出目录；大型程序包和模型适合单独作为 Release 附件。不要上传整个开发目录、原便携包或旧压缩包来代替净化后的文件。

## 准备公开文件

从项目根目录运行以下命令，路径均是项目内的通用示例：

```powershell
python tools/prepare_public_release.py --portable dist/ScreenTranslator --output build/public-export --candidate
```

工具会生成：

- `repo/`：用于创建 GitHub 仓库的干净源码，不携带原 `.git` 历史。
- `ScreenTranslator-0.1.0-source.zip`：同一份公开源码的压缩包。
- `ScreenTranslator-0.1.0-Windows-x64-candidate.zip`：默认候选包；审核通过且明确 `--final` 时，名称为 `ScreenTranslator-0.1.0-Windows-x64.zip`。实际验收范围见 [发布状态](RELEASE_STATUS.md)，不要混用历史候选压缩包。

不提供参数时也默认生成候选包。只有完成剩余项、验收并将发布状态的
机器标记明确改为 `approved` 后，才可使用 `--final` 生成最终 Release 文件。
`--final` 与 `--candidate` 不能同时使用。状态标记是防误发布检查，不是自动法律审核。

阅读导出工具的检查结果和报告。任何未解决的检查失败都应先处理，再发布。仅上传新的导出文件；不要混入原测试目录或用户数据。工具处理的是本地文件，不会替你创建仓库、修改账号或向 GitHub 上传内容。

## 哪些内容不能上传

原始测试报告、运行日志和异常堆栈可能包含本机绝对路径、显示器布局、测试时间和进程标识，不应直接公开。`config.json` 及其备份包含用户选区和设置；SQLite 缓存及其 WAL/SHM 文件可能明文保存译文，也不能公开。真实截图、录屏、环境文件、访问凭据、虚拟环境、构建缓存和原 Git 历史同样不属于发布源码。

便携导出还排除 wheel 安装元数据的 `*.dist-info/direct_url.json`，避免
泄露本地构建文件 URL；版本、许可、运行二进制和公开固定来源记录继续保留。

默认运行不会保存截图，磁盘译文缓存必须由用户主动开启。不过，“默认不保存”不代表已有日志、配置或缓存可以放心上传。关闭磁盘缓存不会自动删除已有数据库。向他人提供故障日志前，应再次检查内容并脱敏。

`.gitignore` 是防止误加入文件的辅助规则，不是隐私证明。已经被 Git 跟踪的文件不会因为增加忽略规则而自动消失；已提交或已发布的私人内容，也不能仅靠删除当前文件来消除旧历史。若敏感凭据曾公开，应先撤销或轮换凭据，再按托管平台指引处理历史与已有公开副本。导出的干净目录不会继承原历史，适合尚未发布的新仓库。

## GitHub 账号和提交信息仍会公开

公开仓库会关联发布它的 GitHub 账号。Git 提交还包含作者及提交者名称、邮箱和时间；净化项目文件无法隐藏这些账号与提交元数据，也不意味着匿名发布。

发布前，请在 GitHub 的邮箱隐私设置中启用 `Keep my email address private` 和 `Block command line pushes that expose my email`，并将这个仓库的 Git 提交邮箱设为 GitHub 为你提供的准确 `noreply` 地址。不要猜测地址，也不要把真实邮箱写入示例配置。网页操作的邮箱隐私设置不会自动修改本机 Git 配置；邮箱拦截也不能代替逐次检查提交信息。详见 [GitHub 邮箱隐私说明](https://docs.github.com/en/account-and-profile/concepts/email-addresses) 和 [阻止暴露邮箱的命令行推送](https://docs.github.com/en/account-and-profile/how-tos/email-preferences/blocking-command-line-pushes-that-expose-your-personal-email-address)。

只在新的 `repo/` 目录内建立发布仓库。首次提交前核对暂存文件清单和提交作者信息；不要将原开发目录的 `.git` 复制过去。本文不会读取或修改你的 Git 全局配置。

## 隐私通过不等于许可通过

第三方作者、版权声明、许可证与官方来源链接不是用户隐私，应原样保留。应用自身尚未由作者选定开源许可证；公开源文件不等于授予他人任意使用、修改或再分发的权利。正式声明“开源”前，作者需要选择并添加适合自己的应用许可证。

模型、Qt/PySide6、推理组件等各有自己的许可条件。本轮以同版本纯 CPU 重建代替旧 Intel/MKL/CUDA wheel，使用 oneDNN CPU 与官方未修改 Microsoft OpenMP/CRT 原件。具体构建配置和原生哈希见 [CPU 构建记录](CPU_BUILD_PROVENANCE.md)，旧 Intel 核验保留为历史证据而非当前使用清单。详细边界见 [原生二进制核验记录](THIRD_PARTY_BINARY_NOTICES.md)。

已识别的 MPL 组件对应源码与获取说明已补齐，详见 [对应源码核验](COPYLEFT_SOURCE_NOTICES.md)。作者已确认个人独立开发并安装正式 Community；用户须明确接受随包微软保护条款，实际 DLL 与验收记录见 [微软核验](MICROSOFT_RUNTIME_TERMS.md)。最终发布时保留完整 `LICENSES/`、模型声明和对应源码；不要修改上游二进制。应用自身是否采用 MIT 等开源许可证仍由作者决定。

## 发布前最后检查

- 上传内容只来自新导出目录或新生成的净化包，没有旧压缩包、真实用户数据和历史。
- 隐私检查报告无未解决项；报告本身也没有本机身份或路径。
- 仓库和便携包中的第三方署名及许可文本保留完整；自建 CPU 库与微软原件哈希和核验记录一致；实际对应源码档案随包保留；应用许可由作者主动决定。
- 提交使用预期的公开作者名和 GitHub `noreply` 邮箱；理解账号仍可被关联。
- 在解压后的净化程序包上完成离线自检，并在 Release 说明中准确列出尚未人工验证的硬件场景。
