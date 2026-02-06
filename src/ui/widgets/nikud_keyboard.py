from PyQt5.QtWidgets import QDialog, QGridLayout, QPushButton, QVBoxLayout, QLabel, QApplication
from PyQt5.QtCore import Qt, QEvent
from PyQt5.QtGui import QKeyEvent

class NikudKeyboard(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("מקלדת ניקוד")
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.Tool)
        self.resize(500, 350)  # הגדלתי את החלון
        self.setLayoutDirection(Qt.RightToLeft)
        
        layout = QGridLayout(self)
        
        # הוספתי את '◌' לתצוגה בלבד, כדי שיראו את הניקוד ברור
        # הרשימה מכילה: (תו להוספה, שם, תו לתצוגה)
        self.chars = [
            ('ְ', 'שְווא', '◌ְ'), ('ֱ', 'חטף סגול', '◌ֱ'), ('ֲ', 'חטף פתח', '◌ֲ'), ('ֳ', 'חטף קמץ', '◌ֳ'),
            ('ִ', 'חיריק', '◌ִ'), ('ֵ', 'צירה', '◌ֵ'), ('ֶ', 'סגול', '◌ֶ'), ('ַ', 'פתח', '◌ַ'),
            ('ָ', 'קמץ', '◌ָ'), ('ֹ', 'חולם', '◌ֹ'), ('ֻ', 'קובוץ', '◌ֻ'), ('ּ', 'דגש', '◌ּ'),
            ('ׁ', 'שין ימנית', 'שׁ'), ('ׂ', 'שין שמאלית', 'שׂ'), ('ֿ', 'רפה', 'בֿ'), ('\u05bd', 'מתג (הטעמה)', '◌ֽ')
        ]
        
        row, col = 0, 0
        for char, name, display in self.chars:
            # שימוש ב-HTML כדי להגדיל את הסימן ולהקטין את השם
            btn_text = f"<span style='font-size: 28pt;'>{display}</span><br><span style='font-size: 10pt; color: #BDC3C7;'>{name}</span>"
            btn = QPushButton()
            btn.setText(name) # Fallback
            # כאן אנחנו מגדירים את הטקסט העשיר
            lbl = QLabel(btn_text)
            lbl.setAlignment(Qt.AlignCenter)
            
            # בניית כפתור שמכיל את ה-Label (טריק כדי לעקוף מגבלות עיצוב בכפתורים רגילים)
            btn_layout = QVBoxLayout(btn)
            btn_layout.addWidget(lbl)
            btn_layout.setContentsMargins(0,0,0,0)
            
            btn.setFixedSize(90, 85) # כפתורים גדולים ונוחים
            btn.setCursor(Qt.PointingHandCursor)
            
            # שליחת התו האמיתי (char) ולא התצוגה
            btn.clicked.connect(lambda _, c=char: self.insert_char(c))
            
            layout.addWidget(btn, row, col)
            
            col += 1
            if col > 3: # 4 כפתורים בשורה
                col = 0
                row += 1

    def insert_char(self, char):
        widget = QApplication.focusWidget()
        if widget:
            event = QKeyEvent(QEvent.KeyPress, 0, Qt.NoModifier, char)
            QApplication.sendEvent(widget, event)
