# Chinese display fallback font

This directory contains the unmodified, single-weight, static OpenType font
`NotoSansCJKsc-Regular.otf`, Noto Sans CJK SC Regular version 2.004. It is not a
variable font. It is loaded only into this application's process, never
installed into Windows or copied into the user's system font directory.

Copyright notice, as embedded in the original font's name table:

© 2014-2021 Adobe (http://www.adobe.com/).

The font is licensed under the SIL Open Font License, Version 1.1. The exact
upstream license is retained in `OFL.txt`. The font retains its original name,
metadata and bytes. It is a bundled component, not a separately sold font.
The application's license and the Microsoft runtime terms do not replace or
restrict the font's OFL rights.

Official source: https://github.com/notofonts/noto-cjk/releases/tag/Sans2.004

Pinned commit: `523d033d6cb47f4a80c58a35753646f5c3608a78`

Font download:
https://raw.githubusercontent.com/notofonts/noto-cjk/523d033d6cb47f4a80c58a35753646f5c3608a78/Sans/OTF/SimplifiedChinese/NotoSansCJKsc-Regular.otf

License download:
https://raw.githubusercontent.com/notofonts/noto-cjk/523d033d6cb47f4a80c58a35753646f5c3608a78/LICENSE

The 2026-10-02 download was checked against the font's internal version,
copyright and license metadata, and opened successfully by Pillow.

| File | Size (bytes) | SHA-256 |
| --- | ---: | --- |
| NotoSansCJKsc-Regular.otf | 16437364 | 2c76254f6fc379fddfce0a7e84fb5385bb135d3e399294f6eeb6680d0365b74b |
| OFL.txt | 4301 | 6a73f9541c2de74158c0e7cf6b0a58ef774f5a780bf191f2d7ec9cc53efe2bf2 |

The portable package places this font and both notices together in
`_internal/fonts/`. Qt keeps working system Chinese fonts in preference to this
fallback. On a Windows installation with no usable Chinese font, the bundled
font supplies Chinese text, including the first-run terms. The synthetic
offline OCR test also falls back to this file instead of rendering Chinese
using a Latin-only Windows font.
