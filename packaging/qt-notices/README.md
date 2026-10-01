# Qt / PySide6 notices and source

This application dynamically links unmodified Qt / PySide6 / Shiboken 6.9.3
libraries from the official PySide6 Windows wheels. Qt libraries are separate,
replaceable files under `_internal/PySide6`; compatible modified LGPL libraries
may be substituted. The application imposes no restriction on reverse engineering
for debugging modifications to these libraries. Application source and build
instructions are supplied in the portable package's `source` folder.

The applicable LGPLv3 and accompanying GPLv3 texts are in this directory.
Qt and PySide copyright notices and third-party license texts are also available
inside the corresponding source archives under `source-archives`.

Exact upstream sources (no Qt / PySide source modifications):

- [Qt Base 6.9.3](https://download.qt.io/archive/qt/6.9/6.9.3/submodules/qtbase-everywhere-src-6.9.3.tar.xz)
- [Qt SVG 6.9.3](https://download.qt.io/archive/qt/6.9/6.9.3/submodules/qtsvg-everywhere-src-6.9.3.tar.xz)
- [Qt Image Formats 6.9.3](https://download.qt.io/archive/qt/6.9/6.9.3/submodules/qtimageformats-everywhere-src-6.9.3.tar.xz)
- [PySide6 / Shiboken 6.9.3](https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.9.3-src/pyside-setup-everywhere-src-6.9.3.tar.xz)

References: [Qt third-party notices](https://doc.qt.io/qt-6.9/licenses-used-in-qt.html),
[Qt for Python third-party notices](https://doc.qt.io/qtforpython-6.9/licenses.html),
[Qt open-source obligations](https://www.qt.io/development/open-source-lgpl-obligations).

Unused Qt PDF and GPL-only Virtual Keyboard plugins are not distributed. This
program does not use Qt Quick/QML or OpenCV video input/output. Model licenses
and attributions are separate, under `models/ocr` and `models/translation`.
