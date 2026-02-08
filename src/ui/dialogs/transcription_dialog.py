from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
                             QLabel, QComboBox, QPushButton, QGroupBox)
from PyQt5.QtCore import Qt


class TranscriptionDialog(QDialog):
    """דיאלוג הגדרות תמלול לפני תחילת התהליך"""

    MODELS = [
        ("large (מומלץ - איכות גבוהה)", "large"),
        ("medium (מאוזן)", "medium"),
        ("small (מהיר)", "small"),
        ("base (מהיר מאוד)", "base"),
        ("tiny (הכי מהיר, איכות נמוכה)", "tiny"),
    ]

    LANGUAGES = [
        ("עברית", "he"),
        ("אנגלית", "en"),
        ("זיהוי אוטומטי", "auto"),
    ]

    def __init__(self, default_model="large", default_language="he", parent=None):
        super().__init__(parent)
        self.setWindowTitle("🎙️ תמלול אודיו")
        self.resize(400, 250)
        self.setLayoutDirection(Qt.RightToLeft)

        layout = QVBoxLayout(self)

        # כותרת
        lbl_title = QLabel("הגדרות תמלול MP3 → טקסט")
        lbl_title.setStyleSheet("font-weight: bold; font-size: 14px; margin-bottom: 10px;")
        layout.addWidget(lbl_title)

        # קבוצת הגדרות
        group = QGroupBox("הגדרות")
        form = QGridLayout(group)
        form.setVerticalSpacing(12)

        # בחירת מודל
        form.addWidget(QLabel("מודל:"), 0, 0)
        self.combo_model = QComboBox()
        for display, value in self.MODELS:
            self.combo_model.addItem(display, value)
        # בחירת ברירת מחדל
        for i, (_, val) in enumerate(self.MODELS):
            if val == default_model:
                self.combo_model.setCurrentIndex(i)
                break
        form.addWidget(self.combo_model, 0, 1)

        # בחירת שפה
        form.addWidget(QLabel("שפה:"), 1, 0)
        self.combo_language = QComboBox()
        for display, value in self.LANGUAGES:
            self.combo_language.addItem(display, value)
        for i, (_, val) in enumerate(self.LANGUAGES):
            if val == default_language:
                self.combo_language.setCurrentIndex(i)
                break
        form.addWidget(self.combo_language, 1, 1)

        layout.addWidget(group)

        # הערה
        lbl_note = QLabel("💡 המודל large נותן תוצאות טובות לעברית.\nהתמלול עשוי לקחת מספר דקות.")
        lbl_note.setStyleSheet("color: #BDC3C7; font-size: 11px; margin-top: 5px;")
        lbl_note.setWordWrap(True)
        layout.addWidget(lbl_note)

        layout.addStretch()

        # כפתורים
        btn_layout = QHBoxLayout()
        self.btn_start = QPushButton("🎙️ התחל תמלול")
        self.btn_start.setStyleSheet(
            "background-color: #27AE60; color: white; font-weight: bold; padding: 8px; border-radius: 4px;"
        )
        self.btn_start.clicked.connect(self.accept)

        btn_cancel = QPushButton("ביטול")
        btn_cancel.setStyleSheet("padding: 8px;")
        btn_cancel.clicked.connect(self.reject)

        btn_layout.addWidget(self.btn_start)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)

    def get_settings(self):
        """מחזיר את ההגדרות שנבחרו"""
        return {
            "model": self.combo_model.currentData(),
            "language": self.combo_language.currentData()
        }
