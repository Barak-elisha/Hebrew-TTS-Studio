import hashlib
import os
import tempfile
import unicodedata
from datetime import datetime
from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
from PyQt5.QtWidgets import (
    QTableWidget,QDialog, QTableWidgetItem, QPushButton, QHBoxLayout, 
    QWidget, QComboBox, QHeaderView, QAbstractItemView
)
# ייבוא של הדיאלוג והוורקרים מהתיקיות החדשות שיצרנו
from src.ui.dialogs.nikud_editor import NikudEditorDialog
from src.workers.nikud_worker import NikudWorker
from src.workers.tts_worker import AudioPreviewWorker # אם השארת את ה-PreviewWorker שם

class PasteableTableWidget(QTableWidget):
    """טבלה משודרגת עם תיקון שמירה אוטומטית"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setLayoutDirection(Qt.RightToLeft)
        self.memory_cache = {}
        self.active_workers = [] 
        self.player = QMediaPlayer()
        
        # הגדרות בחירה
        self.setSelectionBehavior(QTableWidget.SelectRows)
        self.setSelectionMode(QTableWidget.ExtendedSelection)
        
        # חיבור לאירוע שינוי
        self.itemChanged.connect(self.on_item_changed)
        self.cellDoubleClicked.connect(self.open_big_editor)

    def find_main_window(self):
        """פונקציית עזר למציאת החלון הראשי"""
        parent = self.parent()
        while parent:
            if hasattr(parent, 'add_or_update_word'):
                return parent
            parent = parent.parent()
        return None

    def on_item_changed(self, item):
        # אם אנחנו באמצע עדכון תוכנתי - מתעלמים כדי לא ליצור לולאה
        if self.signalsBlocked(): return

        row = item.row()
        col = item.column()
        
        print(f"[DEBUG-TABLE] Change detected at Row {row}, Col {col}. Text: '{item.text()}'")

        base_item = self.item(row, 0)
        voc_item = self.item(row, 2)
        
        if not base_item: return
        base_word = base_item.text().strip()
        
        # 1. זיהוי מילה חדשה (עמודה 0) -> ניקוד אוטומטי
        if col == 0 and base_word:
            if not voc_item or not voc_item.text().strip():
                print(f"[DEBUG-TABLE] New word detected. Sending to Auto-Nikud...")
                self.auto_nikud_single_word(base_word, row)
                return

        # 2. זיהוי עריכת ניקוד (עמודה 2) -> שמירה
        if col == 2:
            vocalized_word = item.text().strip() # לוקחים את הטקסט העדכני מהתא שערכת
            
            # אם מחקת את הניקוד לגמרי, לא נשמור מילה ריקה
            if not vocalized_word: return

            print(f"[DEBUG-TABLE] Saving update for '{base_word}' -> '{vocalized_word}'")
            
            # בדיקת סוג ההתאמה
            match_type = "partial"
            cell_widget = self.cellWidget(row, 4)
            if cell_widget:
                combo = cell_widget.findChild(QComboBox)
                if combo: match_type = "exact" if combo.currentIndex() == 1 else "partial"
            
            # קריאה לחלון הראשי
            main_window = self.find_main_window()
            if main_window:
                # חשוב מאוד: update_table_ui=False
                # כי אנחנו כבר רואים את השינוי בטבלה (אנחנו כתבנו אותו!)
                main_window.add_or_update_word(base_word, vocalized_word, match_type, update_table_ui=False)
            else:
                print("[ERROR] Could not find Main Window to save settings!")

    def open_big_editor(self, row, column):
        if column == 2: # עריכת המילה המנוקדת
            item = self.item(row, column)
            current_text = item.text() if item else ""
            
            # הנחה: הדיאלוג מוגדר בקובץ
            # אנחנו צריכים להעביר את החלון הראשי כהורה או למצוא אותו בתוך הדיאלוג
            main_win = self.find_main_window()
            dialog = NikudEditorDialog(current_text, self) 
            
            # "הזרקת" החלון הראשי לדיאלוג כדי שהשמע יעבוד
            dialog.parent_window = main_win 
            
            if dialog.exec_() == QDialog.Accepted:
                new_text = dialog.get_text()
                self.blockSignals(True) # חוסמים כדי ש-on_item_changed לא יקפוץ כפול
                self.setItem(row, column, QTableWidgetItem(new_text))
                self.blockSignals(False)
                
                # עכשיו קוראים ידנית לשמירה
                # אנחנו מדמים כאילו ItemChanged קרה
                self.on_item_changed(self.item(row, column))

    def auto_nikud_single_word(self, word, row):
        # מניח ש-NikudWorker קיים בקובץ
        worker = NikudWorker(word)
        self.active_workers.append(worker)
        worker.finished.connect(lambda res: self.fill_nikud_result(res, row))
        worker.finished.connect(lambda: self.cleanup_worker(worker))
        worker.start()

    def cleanup_worker(self, worker):
        if worker in self.active_workers:
            self.active_workers.remove(worker)

    def fill_nikud_result(self, result_text, row):
        # ממלא את התא ושומר
        self.blockSignals(True)
        self.setItem(row, 2, QTableWidgetItem(result_text))
        
        # וידוא כפתורים
        if self.cellWidget(row, 1) is None: self.set_play_button(row, 1)
        if self.cellWidget(row, 3) is None: self.set_play_button(row, 3)
        
        self.blockSignals(False)
        
        # שמירה אוטומטית אחרי שהניקוד הגיע
        self.on_item_changed(self.item(row, 2))

    # --- פונקציות עזר קיימות (ללא שינוי, רק מוודא שהן כאן) ---
    def delete_selected_rows(self):
        rows = sorted(set(index.row() for index in self.selectedIndexes()), reverse=True)
        if not rows: return
        
        # מחיקה מהזיכרון ומהקובץ
        main_win = self.find_main_window()
        if main_win:
            current_dict = main_win.settings.get("nikud_dictionary", {})
            for r in rows:
                item = self.item(r, 0)
                if item:
                    key = main_win.clean_nikud_from_string(item.text())
                    if key in current_dict:
                        del current_dict[key]
            
            main_win.save_settings() # שמירה אחרי המחיקה
            
        for r in rows:
            self.removeRow(r)

    def add_row_with_data(self, base_word, vocalized_word, date_str=None, match_type="partial"):
        self.blockSignals(True)
        row = self.rowCount()
        self.insertRow(row)
        
        self.setItem(row, 0, QTableWidgetItem(base_word))
        self.set_play_button(row, 1)
        self.setItem(row, 2, QTableWidgetItem(vocalized_word))
        self.set_play_button(row, 3)

        cmb_match = QComboBox()
        cmb_match.addItems(["חלקי (חכם)", "מדויק בלבד"])
        cmb_match.setCurrentIndex(1 if match_type == "exact" else 0)
        cmb_match.setStyleSheet("QComboBox { font-size: 13px; padding: 4px; margin: 2px; }")
        # חיבור לאירוע שינוי בקומבו בוקס לשמירה מיידית
        cmb_match.currentIndexChanged.connect(lambda: self.on_combo_changed(row))
        
        container = QWidget(); layout = QHBoxLayout(container); layout.setContentsMargins(5, 0, 5, 0); layout.setAlignment(Qt.AlignCenter)
        layout.addWidget(cmb_match)
        self.setCellWidget(row, 4, container)

        if not date_str: date_str = datetime.now().strftime("%d/%m/%Y")
        item_date = QTableWidgetItem(date_str)
        item_date.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        self.setItem(row, 5, item_date)
        
        self.blockSignals(False)

    def on_combo_changed(self, row):
        """שמירה כשמשנים את סוג ההתאמה בקומבו בוקס"""
        # מדמים שינוי בטבלה כדי להפעיל את מנגנון השמירה
        item = self.item(row, 2)
        if item: self.on_item_changed(item)

    def set_play_button(self, row, col):
        container = QWidget(); layout = QHBoxLayout(container); layout.setContentsMargins(0,0,0,0); layout.setAlignment(Qt.AlignCenter)
        btn = QPushButton("🔊"); btn.setFixedSize(30, 30); btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet("QPushButton { background-color: transparent; border: none; font-size: 16px; } QPushButton:hover { color: #27AE60; }")
        btn.clicked.connect(self.on_play_clicked)
        layout.addWidget(btn)
        self.setCellWidget(row, col, container)

    def on_play_clicked(self):
        btn = self.sender()
        if not btn: return
        index = self.indexAt(btn.parent().pos())
        if not index.isValid(): return
        
        # מנגן את הטקסט בעמודה המתאימה (0 או 2)
        text_col = 0 if index.column() == 1 else 2
        item = self.item(index.row(), text_col)
        if item: self.play_preview(item.text())

    def play_preview(self, text):
        if not text: return
        main_win = self.find_main_window()
        if not main_win: return
        
        try:
            voice_name = main_win.combo_he.currentText()
            voice_id = main_win.he_voices.get(voice_name, "he-IL-AvriNeural")
            speed = main_win.combo_speed.currentText()
            
            unique_str = f"{text}_{voice_id}_{speed}"
            cache_key = hashlib.md5(unique_str.encode('utf-8')).hexdigest()
            
            if cache_key in self.memory_cache:
                self.play_bytes(self.memory_cache[cache_key])
                return
            
            worker = AudioPreviewWorker(cache_key, text, voice_id, speed)
            self.active_workers.append(worker)
            worker.finished_data.connect(self.on_download_complete)
            worker.finished_data.connect(lambda: self.cleanup_worker(worker))
            worker.start()
        except: pass

    def on_download_complete(self, cache_key, data):
        self.memory_cache[cache_key] = data
        self.play_bytes(data)

    def play_bytes(self, data):
        try:
            temp_path = os.path.join(tempfile.gettempdir(), "tts_preview_table.mp3")
            with open(temp_path, "wb") as f: f.write(data)
            self.player.setMedia(QMediaContent(QUrl.fromLocalFile(temp_path)))
            self.player.setVolume(100)
            self.player.play()
        except: pass

    def filter_rows(self, query):
        query = query.strip()
        for row in range(self.rowCount()):
            if not query:
                self.setRowHidden(row, False); continue
            
            t1 = self.item(row, 0).text() if self.item(row, 0) else ""
            t2 = self.item(row, 2).text() if self.item(row, 2) else ""
            self.setRowHidden(row, not (query in t1 or query in t2))

