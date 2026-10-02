# certifi 2026.7.22 source and Mozilla CA data

certifi's CA certificate bundle carries an MPL-2.0 source notice. The release
preserves the original certifi `LICENSE` and the bundle's notices, and this
directory includes the full license as `MPL-2.0.txt`.

The accompanying release provides the unmodified upstream certifi source
distribution, including the exact CA data, at:
`LICENSES/upstream/certifi-2026.7.22/certifi-2026.7.22.tar.gz`.
It can be extracted without running the application. The source-only Git
repository retains this notice and the official retrieval URL, but deliberately
omits the dependency source archive. Use the accompanying portable release for
the included offline copy, or the fixed URL below. The application also carries
the readable PEM certificate data at `_internal/certifi/cacert.pem`.

- Official release: https://pypi.org/project/certifi/2026.7.22/
- PyPI source metadata: https://pypi.org/pypi/certifi/2026.7.22/json
- Source archive: https://files.pythonhosted.org/packages/a3/c2/24167ea9858356b47a87a50d39908bfdb72ceeefe0041586e704e5376b3a/certifi-2026.7.22.tar.gz
- Archive SHA-256: `741e2c3b351ddf169a738da9f2c048608ff7f2c5cc02f1ebc6b118bb090d5d55`.
- Shipped `cacert.pem` SHA-256:
  `9cc2a774b5198dcff14d9be1e66091f538975d867ce029a96bce15a55dfd730f`.

The archive hash matches the official PyPI release metadata. The shipped PEM
data and all five matching Python files in the packaging environment were
byte-for-byte identical to the source distribution when reviewed. The same six
files (five Python files and the PEM file) in the official
`certifi-2026.7.22-py3-none-any.whl` also matched the source distribution.
That wheel's SHA-256 is
`62f22742b58a1a33014a2b6b706588a8d7e2a88ae7bd1a6ebe8c992928483775`,
matching its PyPI metadata. No project patch to certifi or its certificate
data was identified.

The original license links Mozilla's certificate source tree. Do not replace
the version-matched data supplied here with the current moving `tip` version
and describe that different data as the application's exact certificate bundle.

MPL-covered data and source remain available under MPL-2.0. The application's
terms do not restrict those rights. Providing these materials does not certify
all licenses or all components of the application.
