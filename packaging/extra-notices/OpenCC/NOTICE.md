# OpenCC official t2s dictionary attribution

This application includes dictionary data derived from [BYVoid/OpenCC](https://github.com/BYVoid/OpenCC), released under the Apache License, Version 2.0. A complete, unmodified copy of the upstream license is supplied in `LICENSE.txt`.

Upstream version: `ver.1.1.9`.
Pinned commit: `556ed22496d650bd0b13b6c163be9814637970ae`.

Included upstream works:

- `data/dictionary/TSCharacters.txt`
- `data/dictionary/TSPhrases.txt`

Modified representation: the original dictionary rows have been mechanically converted into immutable Python tuples in `screen_translator.core._opencc_t2s_data`. Where an upstream row provides multiple conversion candidates, this application keeps the first candidate, in original order. The dictionary keys have not been added, removed, or rewritten. The application supplies its own lightweight longest-phrase-first converter; it does not include OpenCC's native engine, segmentation implementation, DLLs, or third-party native dependencies.

This integration is accurately described as “OpenCC 官方 t2s 词典驱动的轻量转换”, not the complete OpenCC engine, regional conversion profiles, or a translation-quality model.

## Upstream AUTHORS attribution (verbatim)

```text
Author:
Carbo Kuo <byvoid@byvoid.com>

Contributors:
Peng Huang <shawn.p.huang@gmail.com>
Kefu Chai <tchaikov@gmail.com>
LI Daobing <lidaobing@gmail.com>
Asias <asias.hejun@gmail.com>
Peng Wu <alexepico@gmail.com>
Xiaojun Ma <damage3025@gmail.com>
佛振 <chen.sst@gmail.com>
```

These are the upstream authors' already-published attribution details; they are not end-user identifiers or application telemetry.

## Pinned source integrity

| File | SHA-256 |
|---|---|
| `TSCharacters.txt` | `6b5a0a799bea2bb22c001f635eaa3fc2904310f0c08addbff275477a80ecf09a` |
| `TSPhrases.txt` | `504169029c43f7f234b8e2ae470720af3657675c5574ff8aa0feb257e1dc5ce2` |
| upstream `LICENSE` / bundled `LICENSE.txt` | `b534e465949558eec2597b04f5092b5e161236a68dfbfd04d547592ac3964308` |
| upstream `AUTHORS` | `cb34e252fa994679bcbfc8355581e821ceda44bd857875e2cfe15b7ec4eec006` |

The derived pairs consist of 4,113 character rows and 278 phrase rows. The SHA-256 of the UTF-8 JSON representation `[TS_CHARACTERS, TS_PHRASES]`, with `ensure_ascii=False` and separators `(',', ':')`, is `72f97b4327c93bdd767896bab5f3f78b380ab77d84ebf3112011e6bb29100d61`.
