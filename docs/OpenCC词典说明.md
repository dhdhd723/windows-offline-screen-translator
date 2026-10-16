# 离线简体字形统一说明

本项目采用“OpenCC 官方 t2s 词典驱动的轻量转换”。它用于英文→中文翻译的最终结果，不改动 OCR 原文，也不把中文→英文结果改写一遍。昵称、用户标识等身份文字由调用方单独保护，不应直接送入字形转换。

它解决的是繁简字形混用，不是语义翻译：例如“紅桶邀請你體驗”可以统一为“红桶邀请你体验”，但不会自动知道 Red Barrels 是开发商，也不能把直译的“保持脚趾”改成“保持警觉”。术语、专名和翻译模型质量需要另外处理。

## 来源与固定版本

- 官方仓库：[BYVoid/OpenCC](https://github.com/BYVoid/OpenCC)。
- 固定版本：[ver.1.1.9](https://github.com/BYVoid/OpenCC/releases/tag/ver.1.1.9)。
- 固定提交：`556ed22496d650bd0b13b6c163be9814637970ae`；不跟随 `master` 自动更新。
- 官方 [t2s.json](https://github.com/BYVoid/OpenCC/blob/556ed22496d650bd0b13b6c163be9814637970ae/data/config/t2s.json) 指定的转换词典是 `TSPhrases` 和 `TSCharacters`。
- 原始文件：[TSCharacters.txt](https://github.com/BYVoid/OpenCC/blob/556ed22496d650bd0b13b6c163be9814637970ae/data/dictionary/TSCharacters.txt)、[TSPhrases.txt](https://github.com/BYVoid/OpenCC/blob/556ed22496d650bd0b13b6c163be9814637970ae/data/dictionary/TSPhrases.txt)。

| 原始文件 | 字节数 | SHA-256 |
|---|---:|---|
| `TSCharacters.txt` | 34627 | `6b5a0a799bea2bb22c001f635eaa3fc2904310f0c08addbff275477a80ecf09a` |
| `TSPhrases.txt` | 5181 | `504169029c43f7f234b8e2ae470720af3657675c5574ff8aa0feb257e1dc5ce2` |
| `t2s.json` | 406 | `b818534194f27c2d95f01001edb0a5ec49b9050119892cb30a0504bb202cc07c` |
| `LICENSE` | 9165 | `b534e465949558eec2597b04f5092b5e161236a68dfbfd04d547592ac3964308` |

词典被机械转换为 Python 常量，编译进入 exe 的 Python 模块归档；不加载可被误删或替换的外部词典，不增加 DLL，不改变已审核的 CPU 推理运行时。源码形式为 `core/_opencc_t2s_data.py`，共 4113 条字符记录、278 条短语记录。若原始记录有多个候选，使用第一候选；不手工添加或删除官方词典项。

## 转换规则与边界

1. 在原文当前位置匹配最长官方短语；没有短语则逐字使用官方默认候选。短语结果不再递归逐字替换，避免把“乾隆”二次转成“干隆”。
2. 拉丁文字、数字、空格、换行、标点、emoji 和词典中不存在的字符保持不变。不改写大小写，不压缩空格。
3. 首次遇到汉字时才加载并构建只读转换器；加锁保证多线程只建立一份。纯英文、空字符串直接返回。
4. 首次加载校验固定提交、版本、条目数和转换对的 SHA-256。词典缺失、损坏或意外替换时明确报错，不静默回退为繁体输出。
5. `SCRIPT_POLICY_ID` 包含算法版本及词典转换对哈希。调用方必须纳入中文输出缓存策略，使旧繁体结果不再命中。
6. 仅对新鲜译文执行一次转换；缓存存储转换后的结果，读取后不再次转换。官方默认映射并不保证任意文本幂等，例如“乾清宮→乾清宫”，再次转换会成为“干清宫”。本模块没有擅自补充词典项来隐藏该边界；旧缓存通过策略版本隔离，而不是读取时反复加工。

“乾隆／乾坤”应保留“乾”；“乾燥”转为“干燥”；“理髮／頭髮／發展”分别转为“理发／头发／发展”；“皇后”保持不变，而“後面”转为“后面”。这些例子在自动测试中覆盖。

此实现不声称与全部 OpenCC 分词和区域配置逐项兼容。它未包含 `tw2sp`、`hk2s`、地区词汇转换、拼音或语义消歧。例如词典默认字形处理不能凭句意解决所有历史人名；也不应借此修改用户名。若以后要支持完整 OpenCC 区域配置，应另行评测、固定版本及核验新增运行时，而不是暗中扩大此模块职责。

## 许可证与署名

官方词典使用 Apache License 2.0。完整未修改许可证及作者署名随源码位于 `packaging/extra-notices/OpenCC/`，运行包必须携带对应的 `LICENSES/upstream/OpenCC/` 文件。上游作者的公开邮箱仅作为原有署名保留，不属于本项目用户隐私或联网遥测。

转换对哈希：`72f97b4327c93bdd767896bab5f3f78b380ab77d84ebf3112011e6bb29100d61`。这是 `[TS_CHARACTERS, TS_PHRASES]` 经 UTF-8、非 ASCII 转义关闭、无额外空白的 JSON 序列化后的 SHA-256；不混同于原始文件哈希。
