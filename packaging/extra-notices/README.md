# Additional upstream licenses

These exact runtime wheels do not include a license file in their installed
distribution records. The unmodified license text in each subdirectory was
retrieved from its official repository at the matching release tag on 2026-10-01.
Keep this directory and its contents with the application's third-party notices.

| Component | Release | Official license source | SHA-256 of `LICENSE.txt` |
| --- | --- | --- | --- |
| CTranslate2 | 4.8.2 | https://raw.githubusercontent.com/OpenNMT/CTranslate2/v4.8.2/LICENSE | `54aa79d9fe3c09e67a16dcd95b9e88676405a6ec174efda31036983cf7672ecb` |
| SentencePiece | 0.2.2 | https://raw.githubusercontent.com/google/sentencepiece/v0.2.2/LICENSE | `cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30` |
| RapidOCR | 3.9.2 | https://raw.githubusercontent.com/RapidAI/RapidOCR/v3.9.2/LICENSE | `3e0af25fdd06aa9586ae97adb00ea927ebe5a3805ac77d2d3a81ce5f55693333` |
| FlatBuffers Python runtime | 25.12.19 | https://raw.githubusercontent.com/google/flatbuffers/v25.12.19/LICENSE | `cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30` |
| ANTLR4 Python runtime | 4.9.3 | https://raw.githubusercontent.com/antlr/antlr4/4.9.3/LICENSE.txt | `b1b379fcaf3219593a4c433feb1b35c780bed23fafaae440b1ae2771a9521e3a` |

CTranslate2's MIT text retains the original SYSTRAN and OpenNMT copyright
notices. RapidOCR's Apache text retains the RapidOCR / RapidAI notices.
ANTLR's upstream license retains the ANTLR copyright and accompanying notices.

Additional copyright attribution for the two Apache-licensed libraries whose
top-level license contains only the standard license text:

- SentencePiece: Copyright 2016 Google Inc. See the original source header at
  https://raw.githubusercontent.com/google/sentencepiece/v0.2.2/src/sentencepiece_processor.cc.
- FlatBuffers: Copyright 2014 Google Inc. All rights reserved. See the original
  Python runtime header at
  https://raw.githubusercontent.com/google/flatbuffers/v25.12.19/python/flatbuffers/__init__.py.

This directory covers these five upstream components. Notices for third-party
code embedded in native libraries are supplied separately by their distributors;
do not treat the component license as a replacement for such notices.
