from PyQt5.QtWidgets import (QDialog, QSpinBox, QColorDialog, QGroupBox, QVBoxLayout,
                            QLabel, QGridLayout, QLineEdit, QCheckBox, QPushButton, QHBoxLayout)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor


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
    
class KaraokeStyleDialog(QDialog):
    def __init__(self, current_styles, parent=None):
        super().__init__(parent)
        self.setWindowTitle("עריכת עיצוב מתקדמת")
        self.resize(500, 600)
        self.setLayoutDirection(Qt.RightToLeft)
        
        self.styles = current_styles.copy()
        layout = QVBoxLayout(self)

        # === הגדרות כלליות ===
        group_general = QGroupBox("הגדרות כלליות")
        layout_gen = QGridLayout()
        
        self.spin_line_spacing = QSpinBox()
        self.spin_line_spacing.setRange(100, 300)
        self.spin_line_spacing.setSuffix("%")
        self.spin_line_spacing.setValue(self.styles.get('line_spacing', 100))
        self.spin_line_spacing.setToolTip("מרווח בין שורות (100% = רגיל)")
        
        layout_gen.addWidget(QLabel("מרווח בין שורות:"), 0, 0)
        layout_gen.addWidget(self.spin_line_spacing, 0, 1)
        group_general.setLayout(layout_gen)
        layout.addWidget(group_general)

        # === משפט פעיל ===
        layout.addWidget(self.create_style_group("עיצוב משפט פעיל (המוקרא כעת)", "active"))

        # === שאר הטקסט ===
        layout.addWidget(self.create_style_group("עיצוב שאר הטקסט", "inactive"))

        # כפתורים
        btn_box = QHBoxLayout()
        btn_save = QPushButton("שמור והחל"); btn_save.clicked.connect(self.accept)
        btn_cancel = QPushButton("ביטול"); btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(btn_save); btn_box.addWidget(btn_cancel)
        layout.addLayout(btn_box)

    def create_style_group(self, title, prefix):
        group = QGroupBox(title)
        grid = QGridLayout()
        
        # צבעים
        btn_fg = self.create_color_btn(self.styles.get(f'{prefix}_fg', '#000000'))
        btn_bg = self.create_color_btn(self.styles.get(f'{prefix}_bg', 'transparent'))
        
        # גודל
        spin_size = QSpinBox(); spin_size.setRange(8, 72)
        spin_size.setValue(self.styles.get(f'{prefix}_size', 12))
        
        # אפקטים
        chk_bold = QCheckBox("מודגש (Bold)")
        chk_bold.setChecked(self.styles.get(f'{prefix}_bold', False))
        
        chk_italic = QCheckBox("נטוי (Italic)")
        chk_italic.setChecked(self.styles.get(f'{prefix}_italic', False))
        
        chk_underline = QCheckBox("קו תחתון")
        chk_underline.setChecked(self.styles.get(f'{prefix}_underline', False))

        # שמירת רפרנסים כדי לשלוף נתונים אח"כ
        setattr(self, f"btn_{prefix}_fg", btn_fg)
        setattr(self, f"btn_{prefix}_bg", btn_bg)
        setattr(self, f"spin_{prefix}_size", spin_size)
        setattr(self, f"chk_{prefix}_bold", chk_bold)
        setattr(self, f"chk_{prefix}_italic", chk_italic)
        setattr(self, f"chk_{prefix}_underline", chk_underline)

        grid.addWidget(QLabel("צבע טקסט:"), 0, 0); grid.addWidget(btn_fg, 0, 1)
        grid.addWidget(QLabel("צבע רקע:"), 1, 0); grid.addWidget(btn_bg, 1, 1)
        grid.addWidget(QLabel("גודל גופן:"), 2, 0); grid.addWidget(spin_size, 2, 1)
        
        effects_layout = QHBoxLayout()
        effects_layout.addWidget(chk_bold)
        effects_layout.addWidget(chk_italic)
        effects_layout.addWidget(chk_underline)
        grid.addLayout(effects_layout, 3, 0, 1, 2)
        
        group.setLayout(grid)
        return group

    def create_color_btn(self, color_str):
        btn = QPushButton()
        btn.setStyleSheet(f"background-color: {color_str}; border: 1px solid #555;")
        btn.setFixedSize(50, 25)
        btn.setProperty("color_val", color_str)
        btn.clicked.connect(lambda: self.pick_color(btn))
        return btn

    def pick_color(self, btn):
        color = QColorDialog.getColor(QColor(btn.property("color_val")), self, "בחר צבע")
        if color.isValid():
            hex_c = color.name(QColor.HexArgb) # תמיכה בשקיפות
            btn.setStyleSheet(f"background-color: {hex_c}; border: 1px solid #555;")
            btn.setProperty("color_val", hex_c)

    def get_styles(self):
        new_styles = {'line_spacing': self.spin_line_spacing.value()}
        for prefix in ['active', 'inactive']:
            new_styles[f'{prefix}_fg'] = getattr(self, f"btn_{prefix}_fg").property("color_val")
            new_styles[f'{prefix}_bg'] = getattr(self, f"btn_{prefix}_bg").property("color_val")
            new_styles[f'{prefix}_size'] = getattr(self, f"spin_{prefix}_size").value()
            new_styles[f'{prefix}_bold'] = getattr(self, f"chk_{prefix}_bold").isChecked()
            new_styles[f'{prefix}_italic'] = getattr(self, f"chk_{prefix}_italic").isChecked()
            new_styles[f'{prefix}_underline'] = getattr(self, f"chk_{prefix}_underline").isChecked()
        return new_styles
