import os
import re
import hashlib
import tempfile
import unicodedata
from datetime import datetime

# PyQt5 Imports
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, 
    QCheckBox, QTableWidget, QTableWidgetItem, QHeaderView, 
    QPushButton, QComboBox, QWidget
)
from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent

# ייבוא מהקבצים שפירקת בשלבים הקודמים
from src.ui.dialogs.nikud_editor import NikudEditorDialog
from src.workers.tts_worker import AudioPreviewWorker

class AnalysisDialog(QDialog):
    def __init__(self, data, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.pending_text = "" 
        self.setWindowTitle("אישור ניקוד ושינויים")
        self.resize(1200, 700) # הרחבתי את החלון
        self.setLayoutDirection(Qt.RightToLeft)
        self.player = QMediaPlayer()
        self.is_all_selected = False 
        
        layout = QVBoxLayout(self)
        
        # כותרת והסבר
        lbl_info = QLabel("להלן המילים שזוהו לניקוד.\n"
                          "לחיצה כפולה על 'הצעה' תפתח את חלון העריכה המורחב.")
        lbl_info.setStyleSheet("font-size: 14px; font-weight: bold; margin-bottom: 5px; color: #E0E0E0;")
        layout.addWidget(lbl_info)

        # === שורת חיפוש וסינון ===
        search_layout = QHBoxLayout()
        
        self.input_search = QLineEdit()
        self.input_search.setPlaceholderText("🔍 חפש מילה ברשימה (מקור או הצעה)...")
        self.input_search.setStyleSheet("""
            QLineEdit {
                padding: 6px;
                border: 1px solid #5DADE2;
                border-radius: 15px;
                background-color: #F0F4F8;
                color: #2C3E50;
                font-size: 14px;
            }
        """)
        # חיבור לשינוי טקסט - מפעיל את הסינון
        self.input_search.textChanged.connect(lambda: self.apply_filters())
        search_layout.addWidget(self.input_search)

        # --- הוספה: צ'קבוקס לסינון מילים קיימות ---
        self.chk_show_new_only = QCheckBox("הצג רק מילים חדשות (שלא במילון)")
        self.chk_show_new_only.setStyleSheet("font-weight: bold; color: #E0E0E0; margin-right: 10px;")
        self.chk_show_new_only.stateChanged.connect(lambda: self.apply_filters())
        search_layout.addWidget(self.chk_show_new_only)
        
        layout.addLayout(search_layout)

        # --- טבלה ---
        self.table = QTableWidget()
        # שיניתי ל-8 עמודות (הוספתי את "ערך במילון")
        self.table.setColumnCount(8) 
        self.table.setHorizontalHeaderLabels(["שמור?", "כמות", "מילה מקורית", "🔊", "הצעה (דאבל קליק לעריכה)", "🔊", "סוג התאמה", "קיים במילון?"])
        self.table.cellDoubleClicked.connect(self.open_editor_dialog)
        
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed); self.table.setColumnWidth(0, 50)
        header.setSectionResizeMode(1, QHeaderView.Fixed); self.table.setColumnWidth(1, 50)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.Fixed); self.table.setColumnWidth(3, 40)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        header.setSectionResizeMode(5, QHeaderView.Fixed); self.table.setColumnWidth(5, 40)
        header.setSectionResizeMode(6, QHeaderView.Fixed); self.table.setColumnWidth(6, 130)
        header.setSectionResizeMode(7, QHeaderView.Stretch) # העמודה החדשה
        
        layout.addWidget(self.table)

        if isinstance(data, list):
            self.load_changes_list(data)

        # --- כפתורים ---
        btn_layout = QHBoxLayout()
        btn_toggle = QPushButton("✅ סמן/בטל הכל"); btn_toggle.setStyleSheet("background-color: #34495E; color: white; padding: 8px;")
        btn_toggle.clicked.connect(self.toggle_all_checkboxes)
        btn_layout.addWidget(btn_toggle)
        btn_layout.addSpacing(20)

        btn_all = QPushButton("💾 הוסף למילון ואשר בטקסט"); btn_all.setStyleSheet("background-color: #27AE60; color: white; font-weight: bold; padding: 8px;")
        btn_all.clicked.connect(self.action_save_dict_and_text)
        btn_layout.addWidget(btn_all)
        
        btn_dict_only = QPushButton("📘 הוסף למילון בלבד"); btn_dict_only.setStyleSheet("background-color: #2980B9; color: white; padding: 8px;")
        btn_dict_only.clicked.connect(self.action_save_dict_only)
        btn_layout.addWidget(btn_dict_only)
        
        btn_text_only = QPushButton("📝 אשר טקסט בלבד"); btn_text_only.setStyleSheet("background-color: #E67E22; color: white; padding: 8px;")
        btn_text_only.clicked.connect(self.action_text_only)
        btn_layout.addWidget(btn_text_only)
        
        btn_layout.addStretch()
        btn_cancel = QPushButton("✖ בטל"); btn_cancel.setStyleSheet("background-color: #C0392B; color: white; padding: 8px;")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)
        
        layout.addLayout(btn_layout)

    # === פונקציית הסינון החדשה והמשולבת ===
    def apply_filters(self):
        """מסננת שורות לפי טקסט ולפי הצ'קבוקס של המילון"""
        search_text = self.input_search.text().strip().lower()
        show_new_only = self.chk_show_new_only.isChecked()
        
        for row in range(self.table.rowCount()):
            # שליפת נתונים
            item_orig = self.table.item(row, 2)
            item_sugg = self.table.item(row, 4)
            item_exist = self.table.item(row, 7) # העמודה החדשה
            
            orig_text = item_orig.text().lower() if item_orig else ""
            sugg_text = item_sugg.text().lower() if item_sugg else ""
            exist_text = item_exist.text() if item_exist else ""
            
            # בדיקת חיפוש טקסטואלי
            match_search = True
            if search_text:
                match_search = (search_text in orig_text or search_text in sugg_text)
            
            # בדיקת סינון מילון (אם מסומן "הצג רק חדשות", מסתירים אם יש ערך קיים)
            match_dict = True
            if show_new_only:
                # אם יש טקסט בעמודה 7 (והוא לא "-"), סימן שזה קיים. אז נסתיר.
                if exist_text and exist_text != "-":
                    match_dict = False
            
            # החלטה סופית
            if match_search and match_dict:
                self.table.setRowHidden(row, False)
            else:
                self.table.setRowHidden(row, True)

    # --- פונקציות עזר קודמות ---
    def normalize_text(self, text):
        if not text: return ""
        return unicodedata.normalize('NFC', text)

    def remove_nikud_local(self, text):
        normalized = unicodedata.normalize('NFD', text)
        return "".join([c for c in normalized if not unicodedata.combining(c)])

    def get_regex_pattern(self, word):
        pattern = ""
        for char in word:
            if 'א' <= char <= 'ת':
                pattern += re.escape(char) + r'[\u0591-\u05C7]*'
            else:
                pattern += re.escape(char)
        return pattern

    def open_editor_dialog(self, row, column):
        if column == 4:
            item = self.table.item(row, column)
            if not item: return
            current_text = item.text()
            dialog = NikudEditorDialog(current_text, self)
            if dialog.exec_() == QDialog.Accepted:
                new_text = dialog.get_text()
                self.table.item(row, column).setText(new_text)
                self.add_play_button(row, 5, new_text)

    def toggle_all_checkboxes(self):
        self.is_all_selected = not self.is_all_selected
        target_state = Qt.Checked if self.is_all_selected else Qt.Unchecked
        self.table.blockSignals(True)
        for row in range(self.table.rowCount()):
            if self.table.isRowHidden(row): continue 
            item = self.table.item(row, 0)
            if item: item.setCheckState(target_state)
        self.table.blockSignals(False)

    def load_changes_list(self, changes_list):
        self.table.setRowCount(len(changes_list))
        
        # טעינת המילון מהזיכרון כדי לבדוק כפילויות
        current_dict = {}
        if self.parent_window and hasattr(self.parent_window, 'settings'):
            current_dict = self.parent_window.settings.get("nikud_dictionary", {})

        for i, (original, vocalized, count) in enumerate(changes_list):
            chk = QTableWidgetItem(); chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled); chk.setCheckState(Qt.Unchecked)
            self.table.setItem(i, 0, chk)
            
            item_count = QTableWidgetItem(str(count)); item_count.setTextAlignment(Qt.AlignCenter); item_count.setFlags(Qt.ItemIsEnabled)
            self.table.setItem(i, 1, item_count)
            
            item_orig = QTableWidgetItem(original); item_orig.setFlags(Qt.ItemIsEnabled)
            self.table.setItem(i, 2, item_orig)
            
            self.add_play_button(i, 3, original)

            item_voc = QTableWidgetItem(vocalized)
            item_voc.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            normalized_voc = self.normalize_text(vocalized)
            item_voc.setData(Qt.UserRole, normalized_voc) 
            self.table.setItem(i, 4, item_voc)
            
            self.add_play_button(i, 5, vocalized)

            cmb = QComboBox(); cmb.addItems(["חלקי (חכם)", "מדויק בלבד"]); cmb.setStyleSheet("QComboBox { font-size: 12px; padding: 2px; }"); cmb.setCurrentIndex(0)
            container = QWidget(); layout = QHBoxLayout(container); layout.setContentsMargins(2,0,2,0); layout.setAlignment(Qt.AlignCenter); layout.addWidget(cmb)
            self.table.setCellWidget(i, 6, container)
            
            # === עמודה 7: ערך קיים במילון ===
            clean_key = self.remove_nikud_local(original)
            existing_val = current_dict.get(clean_key, "")
            
            display_val = existing_val if existing_val else "-"
            item_exist = QTableWidgetItem(display_val)
            item_exist.setFlags(Qt.ItemIsEnabled) # לקריאה בלבד
            
            if existing_val:
                # צבע בולט (כחול) למילים קיימות
                item_exist.setForeground(Qt.green)
                item_exist.setToolTip(f"המילה '{clean_key}' כבר קיימת במילון כ: {existing_val}")
                
                # אם המילה קיימת, אולי נרצה שהיא לא תהיה מסומנת לשמירה כברירת מחדל?
                # לשיקולך. כרגע זה unchecked בכל מקרה.
            else:
                item_exist.setForeground(Qt.gray)
                
            self.table.setItem(i, 7, item_exist)

    def add_play_button(self, row, col, text):
        old = self.table.cellWidget(row, col)
        if old: old.deleteLater()
        container = QWidget(); layout = QHBoxLayout(container); layout.setContentsMargins(0,0,0,0); layout.setAlignment(Qt.AlignCenter)
        btn = QPushButton("🔊"); btn.setFixedSize(30, 25); btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet("QPushButton { background-color: transparent; border: none; } QPushButton:hover { color: #3498DB; }")
        btn.clicked.connect(lambda: self.play_preview(text))
        layout.addWidget(btn)
        self.table.setCellWidget(row, col, container)

    def play_preview(self, text):
        if not text or not self.parent_window: return
        try:
            voice_name = self.parent_window.combo_he.currentText()
            voice_id = self.parent_window.he_voices.get(voice_name, "he-IL-AvriNeural")
            speed = self.parent_window.combo_speed.currentText()
            unique_str = f"{text}_{voice_id}_{speed}"
            cache_key = hashlib.md5(unique_str.encode('utf-8')).hexdigest()
            if hasattr(self.parent_window, 'table_nikud') and cache_key in self.parent_window.table_nikud.memory_cache:
                self.play_bytes(self.parent_window.table_nikud.memory_cache[cache_key])
                return
            worker = AudioPreviewWorker(cache_key, text, voice_id, speed)
            self.current_worker = worker 
            worker.finished_data.connect(self.on_audio_ready)
            worker.start()
        except: pass

    def on_audio_ready(self, key, data):
        if self.parent_window: self.parent_window.table_nikud.memory_cache[key] = data
        self.play_bytes(data)

    def play_bytes(self, data):
        try:
            path = os.path.join(tempfile.gettempdir(), "preview_dlg.mp3")
            with open(path, "wb") as f: f.write(data)
            self.player.setMedia(QMediaContent(QUrl.fromLocalFile(path)))
            self.player.play()
        except: pass

    def process_dictionary_updates(self):
        count = 0
        if self.parent_window:
            print("\n[DEBUG] --- Saving to Global Dictionary ---")
            for row in range(self.table.rowCount()):
                if self.table.item(row, 0).checkState() == Qt.Checked:
                    raw_orig = self.table.item(row, 2).text()
                    key = self.remove_nikud_local(raw_orig)
                    new_val = self.normalize_text(self.table.item(row, 4).text().strip())
                    match_type = "partial"
                    cell_widget = self.table.cellWidget(row, 6)
                    if cell_widget:
                        combo = cell_widget.findChild(QComboBox)
                        if combo and combo.currentIndex() == 1:
                            match_type = "exact"
                    
                    self.parent_window.settings["nikud_dictionary"][key] = new_val
                    if "nikud_metadata" not in self.parent_window.settings:
                        self.parent_window.settings["nikud_metadata"] = {}
                    
                    self.parent_window.settings["nikud_metadata"][key] = {
                        "date": datetime.now().strftime("%d/%m/%Y"),
                        "match_type": match_type
                    }
                    count += 1
            self.parent_window.refresh_dictionary_table()
            self.parent_window.save_settings()
        return count

    def apply_replacements(self):
        print("\n\n[DEBUG] ================= START APPLY REPLACEMENTS (TOKEN MODE) =================")
        try:
            current_text = self.normalize_text(self.pending_text)
            
            all_replacements = {} 
            
            # א. מילון גלובלי
            global_dict = self.parent_window.settings.get("nikud_dictionary", {})
            global_meta = self.parent_window.settings.get("nikud_metadata", {})
            
            for k, v in global_dict.items():
                m_type = global_meta.get(k, {}).get("match_type", "partial")
                all_replacements[k] = (self.normalize_text(v), m_type)

            # ב. דריסה עם הערכים בטבלה
            for row in range(self.table.rowCount()):
                raw_orig = self.table.item(row, 2).text()
                key = self.remove_nikud_local(raw_orig)
                val = self.normalize_text(self.table.item(row, 4).text().strip())
                match_type = "partial"
                cell_widget = self.table.cellWidget(row, 6)
                if cell_widget:
                    combo = cell_widget.findChild(QComboBox)
                    if combo.currentIndex() == 1: match_type = "exact"
                
                all_replacements[key] = (val, match_type)

            # מיון מפתחות
            sorted_keys = sorted(all_replacements.keys(), key=len, reverse=True)
            
            token_map = {}
            token_counter = 0
            
            # החלפה לטוקנים
            for base_word in sorted_keys:
                target, match_type = all_replacements[base_word]
                pattern_str = self.get_regex_pattern(base_word)
                
                token = f"__TOK_{token_counter}__"
                token_map[token] = target
                token_counter += 1
                
                try:
                    if match_type == "exact":
                        regex = r'(?<![\w\u0590-\u05FF])' + pattern_str + r'(?![\w\u0590-\u05FF])'
                        new_text, count = re.subn(regex, token, current_text)
                    else:
                        new_text, count = re.subn(pattern_str, token, current_text)
                    
                    if count > 0:
                        current_text = new_text
                except Exception as ex:
                    print(f"[DEBUG] Regex Error: {ex}")

            # שחזור טוקנים
            print("[DEBUG] Restoring tokens to final text...")
            for token, final_val in token_map.items():
                if token in current_text:
                    current_text = current_text.replace(token, final_val)
            
            # === התיקון הקריטי: שימוש ב-set_text_safe במקום setPlainText ===
            if self.parent_window:
                if hasattr(self.parent_window, 'set_text_safe'):
                    # הפונקציה הזו יודעת להפוך את תגיות [IMG:...] חזרה לתמונות
                    self.parent_window.set_text_safe(current_text)
                else:
                    # גיבוי למקרה שהפונקציה לא קיימת
                    if hasattr(self.parent_window, 'set_text_safe'):
                        print("[DEBUG] AnalysisDialog: Saving with set_text_safe (preserving images)")
                        self.parent_window.set_text_safe(current_text)
                    else:
                        self.parent_window.editor.setPlainText(current_text)
                print("[DEBUG] Editor updated successfully (Images Preserved).")
            # ================================================================

        except Exception as e:
            print(f"[ERROR] CRITICAL FAILURE: {e}")
            import traceback
            traceback.print_exc()

    def action_save_dict_and_text(self):
        added = self.process_dictionary_updates()
        self.apply_replacements()
        if self.parent_window:
            self.parent_window.lbl_status.setText(f"עודכן הטקסט ונוספו {added} מילים למילון.")
        self.accept()

    def action_save_dict_only(self):
        added = self.process_dictionary_updates()
        if self.parent_window:
            self.parent_window.lbl_status.setText(f"נוספו {added} מילים למילון. הטקסט לא שונה.")
        self.accept()

    def action_text_only(self):
        self.apply_replacements()
        if self.parent_window:
            self.parent_window.lbl_status.setText("הטקסט עודכן (לפי השינויים בטבלה בלבד).")
        self.accept()


class CompareDialog(QDialog):
    def __init__(self, base_word, old_val, new_val, voice, speed, parent=None):
        super().__init__(parent)
        self.setWindowTitle("בדיקת מילה והשוואת אודיו")
        self.resize(600, 400)
        self.player = QMediaPlayer()
        self.player.error.connect(lambda: print(f"Player Error: {self.player.errorString()}"))
        
        self.setLayoutDirection(Qt.RightToLeft)
        
        # נתונים לשמירה
        self.voice = voice
        self.speed = speed
        self.result_action = "CANCEL" # ברירת מחדל

        layout = QVBoxLayout(self)
        
        # כותרת
        msg = f"המילה '<b>{base_word}</b>' כבר קיימת במילון (או דורשת אישור)."
        if old_val:
            msg += f"<br>ערך נוכחי: {old_val}"
        
        lbl_info = QLabel(msg)
        lbl_info.setStyleSheet("font-size: 16px; margin-bottom: 10px;")
        layout.addWidget(lbl_info)

        # טבלת השוואה
        table = QTableWidget(2, 3)
        table.setHorizontalHeaderLabels(["תיאור", "טקסט", "בדיקת שמיעה"])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.verticalHeader().setVisible(False)
        
        # שורה 1: איך זה נשמע בלי ניקוד (המנוע מחליט לבד)
        table.setItem(0, 0, QTableWidgetItem("ללא ניקוד (מקור)"))
        table.setItem(0, 1, QTableWidgetItem(base_word))
        btn_raw = QPushButton("🔊 נגן בלי ניקוד")
        btn_raw.clicked.connect(lambda: self.play_preview(base_word))
        table.setCellWidget(0, 2, btn_raw)

        # שורה 2: איך זה נשמע עם הניקוד החדש
        table.setItem(1, 0, QTableWidgetItem("הצעה חדשה (עם ניקוד)"))
        table.setItem(1, 1, QTableWidgetItem(new_val))
        btn_new = QPushButton("🔊 נגן עם ניקוד")
        btn_new.setStyleSheet("background-color: #27AE60; color: white; font-weight: bold;")
        btn_new.clicked.connect(lambda: self.play_preview(new_val))
        table.setCellWidget(1, 2, btn_new)

        layout.addWidget(table)
        
        # סטטוס
        self.lbl_status = QLabel("לחץ על כפתורי הנגינה כדי לבדוק")
        self.lbl_status.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.lbl_status)

        # כפתורי פעולה
        btn_layout = QHBoxLayout()
        
        btn_update = QPushButton("✅ החלף לערך החדש")
        btn_update.setStyleSheet("background-color: #27AE60; color: white; padding: 8px;")
        btn_update.clicked.connect(self.approve_new)
        
        btn_keep = QPushButton("✋ השאר את הישן / בטל")
        btn_keep.clicked.connect(self.reject) # סוגר ב-Reject

        btn_layout.addWidget(btn_update)
        btn_layout.addWidget(btn_keep)
        layout.addLayout(btn_layout)

    def play_preview(self, text):
        self.lbl_status.setText("מייצר אודיו... אנא המתן")
        # יצירת worker זמני להשמעה
        self.worker = AudioPreviewWorker(text, self.voice, self.speed)
        self.worker.finished_url.connect(self.on_audio_ready)
        self.worker.start()

    def on_audio_ready(self, url):
        self.lbl_status.setText("מנגן...")
        self.player.setMedia(QMediaContent(QUrl.fromLocalFile(url)))
        self.player.play()

    def approve_new(self):
        self.accept() # סוגר ב-Accept
