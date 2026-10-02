from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QLabel,
                               QTextEdit, QVBoxLayout)

from screen_translator.runtime_terms import RuntimeTerms


class RuntimeTermsDialog(QDialog):
    """First-run consent, with no preselected acceptance and a safe default."""

    def __init__(self, terms: RuntimeTerms) -> None:
        super().__init__()
        self.setWindowTitle("本地屏幕翻译器 · 首次使用确认")
        self.setMinimumSize(420, 320)
        available = self.screen().availableGeometry()
        # Qt coordinates are logical pixels: keep the buttons on screen on
        # small displays using 150% or 200% Windows scaling.
        self.resize(min(720, max(420, available.width() - 48)),
                    min(600, max(320, available.height() - 48)))
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self.setStyleSheet("QWidget { font-family: 'Microsoft YaHei UI'; font-size: 13px; }")
        layout = QVBoxLayout(self)
        introduction = QLabel("请阅读微软运行库使用条款。确认前不会注册全局快捷键、截屏或开启翻译。\n"
                              "本确认仅适用于微软组件，不限制 Qt、GEOS、Eigen 等组件各自许可证赋予的权利。")
        introduction.setTextFormat(Qt.TextFormat.PlainText)
        introduction.setWordWrap(True)
        layout.addWidget(introduction)
        self.document = QTextEdit()
        self.document.setReadOnly(True)
        self.document.setPlainText(terms.text)
        layout.addWidget(self.document, 1)
        self.confirmation = QCheckBox("我已阅读并同意上述微软运行库使用条款")
        self.confirmation.setChecked(False)
        layout.addWidget(self.confirmation)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                        | QDialogButtonBox.StandardButton.Cancel)
        self.accept_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.accept_button.setText("同意并启动")
        self.accept_button.setEnabled(False)
        self.accept_button.setAutoDefault(False)
        reject_button = self.buttons.button(QDialogButtonBox.StandardButton.Cancel)
        reject_button.setText("不同意，退出")
        reject_button.setDefault(True)
        reject_button.setFocus()
        self.confirmation.toggled.connect(self.accept_button.setEnabled)
        self.buttons.accepted.connect(self._accept_if_confirmed)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def _accept_if_confirmed(self) -> None:
        if self.confirmation.isChecked():
            self.accept()


def prompt_runtime_terms(terms: RuntimeTerms) -> bool:
    dialog = RuntimeTermsDialog(terms)
    return dialog.exec() == QDialog.DialogCode.Accepted
