import unicodedata
from datetime import datetime

from PyQt5.QtWidgets import (
    QTableWidget, QTableWidgetItem, QHeaderView, QPushButton, 
    QHBoxLayout, QWidget, QDialog
)
from PyQt5.QtCore import Qt

# ייבוא של הדיאלוג והוורקרים מהמיקומים החדשים שלהם
from src.ui.dialogs.nikud_editor import NikudEditorDialog
from src.workers.nikud_worker import NikudWorker


class ErrorsTableWidget(QTableWidget):
    """טבלת טעויות עם מנגנון מחיקה חכם ודיבאג מלא"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setLayoutDirection(Qt.RightToLeft)
        
        # 6 עמודות: מקור, רמקול, שגוי, רמקול, תאריך, פעולות
        headers = ["מקור (נקי)", "🔊", "מילה שגויה/מנוקדת", "🔊", "תאריך", "פעולות"]
        self.setColumnCount(len(headers))
        self.setHorizontalHeaderLabels(headers)
        
        self.setSelectionBehavior(QTableWidget.SelectRows)
        self.verticalHeader().setVisible(False)
        self.setAlternatingRowColors(True)
        
        # רוחב עמודות
        header = self.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Fixed); self.setColumnWidth(1, 35)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.Fixed); self.setColumnWidth(3, 35)
        header.setSectionResizeMode(4, QHeaderView.Fixed); self.setColumnWidth(4, 100)
        header.setSectionResizeMode(5, QHeaderView.Fixed); self.setColumnWidth(5, 90)

        self.itemChanged.connect(self.on_item_changed)
        self.cellDoubleClicked.connect(self.open_cell_editor)
        self.active_workers = []

    def remove_row_by_text_smart(self, word_to_remove):
        """מוחקת שורה ע"י חיפוש חכם בשתי העמודות (מקור ושגוי)."""
        print(f"\n[DEBUG TABLE] --- Starting Search for Deletion ---")
        input_clean = self.clean_string(word_to_remove).strip()
        rows_to_delete = []
        
        for r in range(self.rowCount()):
            item_src = self.item(r, 0)
            item_err = self.item(r, 2)
            
            txt_src = item_src.text().strip() if item_src else ""
            txt_err = item_err.text().strip() if item_err else ""
            
            # בדיקה כפולה: או התאמה למילה המנוקדת או למקור הנקי
            if txt_err == word_to_remove or txt_src == input_clean:
                rows_to_delete.append(r)

        for r in sorted(rows_to_delete, reverse=True):
            self.removeRow(r)
            
        self.save_changes_to_settings()

    # --- שאר הפונקציות הנדרשות למחלקה (העתק והדבק כדי שהכל יעבוד) ---

    def save_changes_to_settings(self):
        main = self.find_main_window()
        if main:
            new_errors = []
            for r in range(self.rowCount()):
                item = self.item(r, 2)
                if item and item.text().strip() and item.text() != "טוען...":
                    new_errors.append(item.text().strip())
            main.settings["nikud_errors"] = new_errors
            main.save_settings()

    def load_data(self, errors_list):
        self.blockSignals(True)
        self.setRowCount(0)
        for word in errors_list:
            if word: self.add_row_ui(word)
        self.blockSignals(False)

    def add_row_ui(self, vocalized_word):
        row = self.rowCount()
        self.insertRow(row)
        clean_word = self.clean_string(vocalized_word)
        
        item_clean = QTableWidgetItem(clean_word); item_clean.setTextAlignment(Qt.AlignCenter)
        self.setItem(row, 0, item_clean)
        self.add_audio_btn(row, 1, clean_word)
        
        item_error = QTableWidgetItem(vocalized_word); item_error.setTextAlignment(Qt.AlignCenter)
        self.setItem(row, 2, item_error)
        self.add_audio_btn(row, 3, vocalized_word)
        
        item_date = QTableWidgetItem(datetime.now().strftime("%d/%m/%Y"))
        item_date.setFlags(Qt.ItemIsEnabled); item_date.setTextAlignment(Qt.AlignCenter)
        self.setItem(row, 4, item_date)
        
        self.add_action_buttons(row)

    def add_action_buttons(self, row):
        container = QWidget(); layout = QHBoxLayout(container); layout.setContentsMargins(2,2,2,2); layout.setSpacing(4)
        btn_save = QPushButton("💾"); btn_save.setFixedSize(30, 25); btn_save.setStyleSheet("background-color: #27AE60; color: white; border-radius: 4px;")
        btn_save.setToolTip("העבר למילון"); btn_save.setCursor(Qt.PointingHandCursor)
        btn_save.clicked.connect(self.approve_error_to_dict)
        
        btn_del = QPushButton("✖"); btn_del.setFixedSize(30, 25); btn_del.setStyleSheet("background-color: #C0392B; color: white; border-radius: 4px;")
        btn_del.setToolTip("מחק"); btn_del.setCursor(Qt.PointingHandCursor)
        btn_del.clicked.connect(self.delete_row_btn_clicked)
        
        layout.addWidget(btn_save); layout.addWidget(btn_del)
        self.setCellWidget(row, 5, container)

    def get_row_from_button(self):
        btn = self.sender()
        if not btn: return -1
        index = self.indexAt(btn.parent().pos())
        return index.row()

    def approve_error_to_dict(self):
        row = self.get_row_from_button()
        if row < 0: return
        base = self.item(row, 0).text().strip()
        voc = self.item(row, 2).text().strip()
        main = self.find_main_window()
        if main and hasattr(main, 'add_or_update_word'):
            main.add_or_update_word(base, voc, "partial", update_table_ui=True)
            self.removeRow(row)
            self.save_changes_to_settings()
            if hasattr(main, 'lbl_status'): main.lbl_status.setText(f"✅ '{base}' הועברה למילון.")

    def delete_row_btn_clicked(self):
        row = self.get_row_from_button()
        if row >= 0:
            self.removeRow(row)
            self.save_changes_to_settings()

    def on_item_changed(self, item):
        if self.signalsBlocked(): return
        row, col = item.row(), item.column()
        text = item.text().strip()
        
        # אם שונה הניקוד (עמודה 2) - רק נעדכן את כפתור השמע וההגדרות (בלי לגעת במקור)
        if col == 2:
            self.blockSignals(True)
            # מחקנו את השורה שהייתה כאן: self.setItem(row, 0, QTableWidgetItem(new_clean))
            
            # עדכון כפתור שמע לעמודה של הניקוד
            self.add_audio_btn(row, 3, text)
            self.blockSignals(False)
            
            # שמירה לקובץ
            self.save_changes_to_settings()

        # אם שונה המקור (עמודה 0) - נשלח לניקוד אוטומטי מחדש
        elif col == 0:
            if not text: return
            self.blockSignals(True)
            self.setItem(row, 2, QTableWidgetItem("טוען..."))
            self.blockSignals(False)
            self.run_auto_nikud(text, row)

    def run_auto_nikud(self, text, row):
        worker = NikudWorker(text)
        self.active_workers.append(worker)
        worker.finished.connect(lambda res: self.apply_auto_nikud(res, row))
        worker.start()

    def apply_auto_nikud(self, result, row):
        self.blockSignals(True)
        self.setItem(row, 2, QTableWidgetItem(result))
        self.add_audio_btn(row, 3, result)
        self.blockSignals(False)
        self.save_changes_to_settings()

    def open_cell_editor(self, row, col):
        if col not in [0, 2]: return
        item = self.item(row, col)
        if not item: return
        main_win = self.find_main_window()
        dialog = NikudEditorDialog(item.text(), self)
        dialog.parent_window = main_win
        if dialog.exec_() == QDialog.Accepted:
            new_txt = dialog.get_text().strip()
            if new_txt:
                self.blockSignals(True); self.setItem(row, col, QTableWidgetItem(new_txt)); self.blockSignals(False)
                self.on_item_changed(self.item(row, col))

    def add_audio_btn(self, row, col, text):
        container = QWidget(); layout = QHBoxLayout(container); layout.setContentsMargins(0,0,0,0); layout.setAlignment(Qt.AlignCenter)
        btn = QPushButton("🔊"); btn.setFixedSize(25, 25); btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet("QPushButton { background-color: transparent; border: none; } QPushButton:hover { color: #27AE60; }")
        btn.clicked.connect(lambda: self.request_preview(text))
        layout.addWidget(btn)
        self.setCellWidget(row, col, container)

    def request_preview(self, text):
        main = self.find_main_window()
        if hasattr(main, 'play_preview_general'): main.play_preview_general(text)

    def find_main_window(self):
        p = self.parent()
        while p:
            if hasattr(p, 'settings') and hasattr(p, 'save_settings'): return p
            p = p.parent()
        return None

    def clean_string(self, text):
        if not text: return ""
        normalized = unicodedata.normalize('NFD', text)
        return "".join([c for c in normalized if not unicodedata.combining(c)])
