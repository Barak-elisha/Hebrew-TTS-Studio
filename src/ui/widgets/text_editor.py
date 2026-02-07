from PyQt5.QtWidgets import QTextEdit, QDialog
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QTextCursor
from src.ui.dialogs.nikud_editor import NikudEditorDialog
from PyQt5.QtGui import QTextCursor, QTextCharFormat

class NikudTextEdit(QTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent 

    # ביטלנו את contextMenuEvent כדי שלא יפתח תפריט ברירת מחדל
    def contextMenuEvent(self, event):
        pass

    def mousePressEvent(self, event):
        # זיהוי לחיצה ימנית
        if event.button() == Qt.RightButton:
            # מציאת המילה מתחת לסמן העכבר
            cursor = self.cursorForPosition(event.pos())
            cursor.select(QTextCursor.WordUnderCursor)
            selected_text = cursor.selectedText().strip()
            
            if selected_text:
                # בדיקה האם המילה כבר מסומנת כטעות (אדום)
                fmt = cursor.charFormat()
                is_error = (fmt.foreground().color() == Qt.red)
                
                # ביצוע הפעולה (Toggle)
                self.toggle_error_state_direct(cursor, selected_text, not is_error)
            
            # לא קוראים ל-super() כדי למנוע את התפריט הרגיל
            return

        # לחיצה שמאלית (או אחרת) ממשיכה כרגיל
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            cursor = self.textCursor()
            cursor.select(QTextCursor.WordUnderCursor)
            selected_text = cursor.selectedText()
            
            if selected_text.strip():
                dialog = NikudEditorDialog(selected_text, self.parent_window)
                if dialog.exec_() == QDialog.Accepted:
                    new_text = dialog.get_text()
                    if dialog.chk_add_to_dict.isChecked():
                        self.add_to_dictionary_direct(selected_text, new_text, dialog.combo_match_type.currentIndex())
                    cursor.insertText(new_text)
        else:
            super().mouseDoubleClickEvent(event)

    def toggle_error_state_direct(self, cursor, text, make_error):
        """פונקציה שמבצעת את השינוי הויזואלי והלוגי"""
        fmt = cursor.charFormat()
        
        if make_error:
            # === סימון כטעות (אדום) ===
            fmt.setForeground(Qt.red)
            fmt.setUnderlineStyle(QTextCharFormat.WaveUnderline)
            fmt.setUnderlineColor(Qt.red)
            fmt.setFontUnderline(True)
            cursor.setCharFormat(fmt)
            
            if self.parent_window and hasattr(self.parent_window, 'add_error_to_review'):
                self.parent_window.add_error_to_review(text)
        else:
            # === ביטול טעות (חזרה לרגיל) ===
            # אנחנו לוקחים את הפורמט של הטקסט הכללי (לא אדום)
            default_fmt = QTextCharFormat()
            default_fmt.setForeground(self.palette().color(self.foregroundRole()))
            default_fmt.setFontUnderline(False)
            
            cursor.setCharFormat(default_fmt)
            
            if self.parent_window and hasattr(self.parent_window, 'remove_error_from_review'):
                self.parent_window.remove_error_from_review(text)

    def add_to_dictionary_direct(self, original, new_val, match_index):
        print(f"[DEBUG-EDITOR] add_to_dictionary_direct called for '{original}'")
        if not self.parent_window: return
        
        match_type = "exact" if match_index == 1 else "partial"
        
        if hasattr(self.parent_window, 'add_or_update_word'):
            # העורך שולח את המילה המקורית (מהטקסט) ואת התיקון
            # הפונקציה המרכזית תדאג לנקות את המפתח
            self.parent_window.add_or_update_word(original, new_val, match_type)
        else:
            print("[ERROR] Parent window missing add_or_update_word function!")
