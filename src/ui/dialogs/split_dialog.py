from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel, QGridLayout, QLineEdit, QCheckBox, QPushButton, QHBoxLayout
from PyQt5.QtCore import Qt

class SplitExportDialog(QDialog):
    def __init__(self, default_filename="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("הגדרות פיצול וייצוא")
        self.resize(400, 250)
        self.setLayoutDirection(Qt.RightToLeft)
        
        layout = QVBoxLayout(self)
        
        # כותרת והסבר
        lbl_info = QLabel("הגדר כיצד לחלק את הטקסט לקבצים נפרדים:")
        lbl_info.setStyleSheet("font-weight: bold; font-size: 14px; margin-bottom: 10px;")
        layout.addWidget(lbl_info)

        # קבוצת הגדרות
        form_layout = QGridLayout()
        form_layout.setVerticalSpacing(15)
        
        # 1. שם בסיס לקובץ
        form_layout.addWidget(QLabel("שם בסיס לקבצים:"), 0, 0)
        self.input_filename = QLineEdit(default_filename)
        self.input_filename.setPlaceholderText("לדוגמה: פרק_א")
        form_layout.addWidget(self.input_filename, 0, 1)
        
        # 2. מילת פיצול
        form_layout.addWidget(QLabel("מילה מפרידה:"), 1, 0)
        self.input_split_word = QLineEdit()
        self.input_split_word.setPlaceholderText("לדוגמה: הרצאה")
        form_layout.addWidget(self.input_split_word, 1, 1)
        
        layout.addLayout(form_layout)
        
        # 3. אפשרויות נוספות
        self.chk_include_number = QCheckBox("המפריד כולל מספר? (למשל: 'הרצאה 1', 'הרצאה 2')")
        self.chk_include_number.setChecked(True)
        layout.addWidget(self.chk_include_number)
        
        layout.addStretch()
        
        # כפתורים
        btn_layout = QHBoxLayout()
        self.btn_ok = QPushButton("✂️ פצל וייצא")
        self.btn_ok.setStyleSheet("background-color: #E67E22; color: white; font-weight: bold; padding: 8px;")
        self.btn_ok.clicked.connect(self.accept)
        
        btn_cancel = QPushButton("ביטול")
        btn_cancel.clicked.connect(self.reject)
        
        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(self.btn_ok)
        layout.addLayout(btn_layout)

    def get_data(self):
        return {
            "filename": self.input_filename.text().strip(),
            "split_word": self.input_split_word.text().strip(),
            "use_number": self.chk_include_number.isChecked()
        }
    