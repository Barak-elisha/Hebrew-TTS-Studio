import unicodedata
from datetime import datetime
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, 
                             QPushButton, QLineEdit, QHeaderView, QMessageBox, QDialog, QAbstractItemView, QTableWidgetItem, QComboBox)
from PyQt5.QtCore import Qt

# ייבוא הרכיבים והוורקרים
from src.ui.widgets.nikud_table import PasteableTableWidget
from src.ui.widgets.errors_table import ErrorsTableWidget
from src.ui.dialogs.nikud_editor import NikudEditorDialog
from src.workers.nikud_worker import NikudWorker

class DictionaryTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = parent  # גישה לחלון הראשי ולהגדרות
        self.init_ui()
        
        # טעינה ראשונית של הנתונים
        self.refresh_dictionary_table()
        self.refresh_errors_table()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # --- קבוצה עליונה: טבלת טעויות ---
        group_errors = QGroupBox("⚠️ מילים שסומנו כטעות (ערוך בטבלה כדי לתקן)")
        group_errors.setStyleSheet("""
            QGroupBox { border: 2px solid #E74C3C; border-radius: 6px; margin-top: 10px; padding-top: 14px; }
            QGroupBox::title { color: #E74C3C; font-weight: bold; }
        """)
        errors_layout = QVBoxLayout(group_errors)

        self.table_errors = ErrorsTableWidget(self.main_window)
        self.table_errors.setMinimumHeight(200)
        self.table_errors.setMaximumHeight(300)
        errors_layout.addWidget(self.table_errors)

        btn_clear_errors = QPushButton("נקה את כל רשימת הטעויות")
        btn_clear_errors.setStyleSheet("background-color: #95A5A6; font-size: 11px; padding: 4px;")
        btn_clear_errors.clicked.connect(self.clear_errors_list)
        errors_layout.addWidget(btn_clear_errors)

        layout.addWidget(group_errors)

        # --- קבוצה תחתונה: מילון ניקוד ---
        group_dict = QGroupBox("📚 מילון ניקוד פעיל")
        group_dict.setStyleSheet("""
            QGroupBox { border: 2px solid #2ECC71; border-radius: 6px; margin-top: 10px; padding-top: 14px; }
            QGroupBox::title { color: #2ECC71; font-weight: bold; }
        """)
        dict_layout = QVBoxLayout(group_dict)

        search_layout = QHBoxLayout()
        self.input_search_dict = QLineEdit()
        self.input_search_dict.setPlaceholderText("🔍 חפש במילון...")
        self.input_search_dict.setStyleSheet("background-color: #FFFFFF; color: #000; padding: 5px; border-radius: 4px;")
        search_layout.addWidget(self.input_search_dict)

        btn_add_manual = QPushButton("➕ הוסף מילה ידנית")
        btn_add_manual.setStyleSheet("background-color: #2980B9; color: white; padding: 5px; font-weight: bold;")
        btn_add_manual.clicked.connect(self.add_manual_word)
        search_layout.addWidget(btn_add_manual)

        dict_layout.addLayout(search_layout)

        self.table_nikud = PasteableTableWidget()
        self.table_nikud.setColumnCount(6)
        self.table_nikud.setHorizontalHeaderLabels(["מילה בטקסט", "🔊", "תיקון (מנוקד)", "🔊", "סוג התאמה", "תאריך"])
        
        # חיבור חיפוש
        self.input_search_dict.textChanged.connect(self.table_nikud.filter_rows)

        header = self.table_nikud.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Fixed); self.table_nikud.setColumnWidth(1, 40)
        header.setSectionResizeMode(3, QHeaderView.Fixed); self.table_nikud.setColumnWidth(3, 40)
        header.setSectionResizeMode(4, QHeaderView.Fixed); self.table_nikud.setColumnWidth(4, 140)
        header.setSectionResizeMode(5, QHeaderView.Fixed); self.table_nikud.setColumnWidth(5, 100)
        self.table_nikud.verticalHeader().setVisible(False)

        dict_layout.addWidget(self.table_nikud)

        # כפתורי פעולה למילון
        actions_layout = QHBoxLayout()
        btn_select_all = QPushButton("✅ סמן הכל"); btn_select_all.clicked.connect(self.table_nikud.selectAll)
        btn_clear_sel = QPushButton("תבטל סימון"); btn_clear_sel.clicked.connect(self.table_nikud.clearSelection)
        btn_delete_multi = QPushButton("🗑️ מחק מסומנים"); btn_delete_multi.setStyleSheet("background-color: #C0392B; color: white;")
        btn_delete_multi.clicked.connect(self.delete_selected_from_dict) # פונקציה מותאמת

        actions_layout.addWidget(btn_select_all)
        actions_layout.addWidget(btn_clear_sel)
        actions_layout.addWidget(btn_delete_multi)
        actions_layout.addStretch()
        dict_layout.addLayout(actions_layout)

        layout.addWidget(group_dict)

    # ==========================
    # Logic Methods
    # ==========================

    def refresh_dictionary_table(self):
        """טעינת המילון לטבלה"""
        if not self.main_window: return
        self.table_nikud.setRowCount(0)
        self.table_nikud.clearContents()
        
        # --- התיקון: שימוש במשתנה עזר שמצביע להגדרות בחלון הראשי ---
        settings = self.main_window.settings 
        
        # עכשיו כל הגישות הן דרך המשתנה settings התקין
        dictionary = settings.get("nikud_dictionary", {})
        metadata = settings.get("nikud_metadata", {}) 
        
        sorted_keys = sorted(dictionary.keys())
        
        for base in sorted_keys:
            vocalized = dictionary[base]
            # שימוש ב-metadata התקין
            data = metadata.get(base, {})
            date_added = data.get("date", "-")
            match_type = data.get("match_type", "partial")
            
            self.table_nikud.add_row_with_data(base, vocalized, date_added, match_type)

    def refresh_errors_table(self):
        """רענון טבלת הטעויות"""
        if not self.main_window: return
        # משתמשים בפונקציה המובנית של ErrorsTableWidget
        # אבל צריך לוודא שאנחנו מעבירים לה את הרשימה הנכונה
        errors_list = self.main_window.settings.get("nikud_errors", [])
        
        # הערה: ErrorsTableWidget מצפה ל-settings בתוך ה-main_window שהעברנו לה ב-init
        # אז אם בנינו אותה נכון, זה אמור לעבוד אוטומטית, או שנפעיל פונקציית עזר.
        # נניח שיש לה פונקציה load_data כפי שהגדרנו קודם.
        if hasattr(self.table_errors, 'load_data'):
            self.table_errors.load_data(errors_list)

    def clear_errors_list(self):
        if QMessageBox.question(self, "אישור", "האם לנקות את כל רשימת הטעויות?") == QMessageBox.Yes:
            self.main_window.settings["nikud_errors"] = []
            self.main_window.save_settings()
            self.refresh_errors_table()

    def add_manual_word(self):
        word, ok = QLineEdit.getText(self, "הוספה מהירה", "הקלד מילה (ללא ניקוד):") # נשתמש ב-InputDialog רגיל או QInputDialog
        # עדיף QInputDialog אבל צריך לייבא אותו. לשם הפשטות נשתמש ב-QInputDialog
        from PyQt5.QtWidgets import QInputDialog
        word, ok = QInputDialog.getText(self, "הוספה מהירה", "הקלד מילה (ללא ניקוד):")
        
        if ok and word:
            clean_word = word.strip()
            if not clean_word: return
            
            self.main_window.lbl_status.setText(f"מנקד את '{clean_word}'...")
            
            self.manual_worker = NikudWorker(clean_word)
            self.manual_worker.finished.connect(lambda res: self.finish_manual_add(clean_word, res))
            self.manual_worker.start()

    def finish_manual_add(self, base_word, vocalized_result):
        self.add_or_update_word(base_word, vocalized_result, "partial")
        self.highlight_word_in_table(self.clean_nikud_from_string(base_word))
        self.main_window.lbl_status.setText(f"✅ נוסף: {base_word}")

    def add_or_update_word(self, base_word, vocalized_word, match_type):
        """הוספה למילון ושמירה"""
        key = self.clean_nikud_from_string(base_word)
        if not key: return

        self.main_window.settings["nikud_dictionary"][key] = vocalized_word.strip()
        if "nikud_metadata" not in self.main_window.settings:
            self.main_window.settings["nikud_metadata"] = {}
            
        self.main_window.settings["nikud_metadata"][key] = {
            "date": datetime.now().strftime("%d/%m/%Y"),
            "match_type": match_type
        }
        self.main_window.save_settings()
        self.refresh_dictionary_table()

    def delete_selected_from_dict(self):
        """מחיקת שורות מסומנות מהמילון"""
        rows = sorted(set(item.row() for item in self.table_nikud.selectedItems()), reverse=True)
        if not rows: return
        
        if QMessageBox.question(self, "מחיקה", f"למחוק {len(rows)} מילים?") == QMessageBox.Yes:
            for r in rows:
                key_item = self.table_nikud.item(r, 0)
                if key_item:
                    key = key_item.text()
                    if key in self.main_window.settings["nikud_dictionary"]:
                        del self.main_window.settings["nikud_dictionary"][key]
                    if key in self.main_window.settings.get("nikud_metadata", {}):
                        del self.main_window.settings["nikud_metadata"][key]
            
            self.main_window.save_settings()
            self.refresh_dictionary_table()

    # --- Helpers ---
    def clean_nikud_from_string(self, text):
        if not text: return ""
        normalized = unicodedata.normalize('NFD', text)
        return "".join([c for c in normalized if not unicodedata.combining(c) and (c.isalnum() or c.isspace())]).strip()

    def highlight_word_in_table(self, key):
        items = self.table_nikud.findItems(key, Qt.MatchExactly)
        if items:
            item = items[0]
            self.table_nikud.selectRow(item.row())
            self.table_nikud.scrollToItem(item, QAbstractItemView.PositionAtCenter)

    # פונקציה זו נקראת על ידי ErrorsTableWidget בעת דאבל קליק או לחיצה על "תיקון"
    def open_fix_dialog_for_error(self, word_with_nikud):
        # כדי לאפשר לטבלה לקרוא לפונקציה, נוודא ש-ErrorsTableWidget קורא לזה
        dialog = NikudEditorDialog(word_with_nikud, self.main_window)
        dialog.chk_add_to_dict.setChecked(True)
        dialog.chk_add_to_dict.setEnabled(False)
        
        if dialog.exec_() == QDialog.Accepted:
            corrected = dialog.get_text().strip()
            match_idx = dialog.combo_match_type.currentIndex()
            match_type = "exact" if match_idx == 1 else "partial"
            
            # הוספה למילון
            self.add_or_update_word(corrected, corrected, match_type) # המפתח מחושב בפנים
            
            # הסרה מרשימת הטעויות
            errors = self.main_window.settings.get("nikud_errors", [])
            if word_with_nikud in errors:
                errors.remove(word_with_nikud)
                self.main_window.settings["nikud_errors"] = errors
                self.main_window.save_settings()
            
            self.refresh_errors_table()
            self.main_window.lbl_status.setText(f"✅ תוקן: {corrected}")