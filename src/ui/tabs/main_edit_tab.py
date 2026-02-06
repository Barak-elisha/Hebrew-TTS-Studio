import os
import re
import difflib
import PyPDF2
import fitz  # PyMuPDF
from datetime import datetime
from collections import Counter

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFrame, 
                             QPushButton, QLabel, QLineEdit, QComboBox, 
                             QCheckBox,QDialog, QApplication, QSplitter, QFileDialog, QMessageBox)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QTextBlockFormat, QTextCharFormat, QTextImageFormat, QTextCursor

# Imports from your project
from src.ui.widgets.pdf_viewer import PDFViewerWidget
from src.ui.widgets.text_editor import NikudTextEdit
from src.workers.tts_worker import TTSWorker
from src.workers.nikud_worker import NikudWorker
from src.workers.telegram_worker import TelegramWorker
from src.ui.dialogs.compare_dialog import AnalysisDialog
from src.ui.dialogs.split_dialog import SplitExportDialog
from src.ui.dialogs.advanced_import import AdvancedImportDialog
from src.utils.text_tools import advanced_cleanup, cleanup_pdf_page

class MainEditTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = parent  # הפניה לחלון הראשי כדי לגשת להגדרות ולסטטוס
        
        # נתונים מקומיים לטאב
        self.file_path = ""
        self.file_paths = []
        self.he_voices = {
            "Hila (אישה - עברית)": "he-IL-HilaNeural", 
            "Avri (גבר - עברית)": "he-IL-AvriNeural"
        }
        self.en_voices = {
            "Aria (אישה - ארה\"ב)": "en-US-AriaNeural", 
            "Guy (גבר - ארה\"ב)": "en-US-GuyNeural",
            "Brian (גבר - בריטי)": "en-GB-BrianNeural"
        }

        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(4)
        layout.setContentsMargins(6, 4, 6, 4)

        # --- סרגל כלים עליון ---
        compact_bar = QFrame()
        compact_bar.setStyleSheet("background-color: #1A3C59; border-radius: 6px; padding: 4px;")
        compact_bar.setFixedHeight(76)
        bar_layout = QVBoxLayout(compact_bar)
        bar_layout.setContentsMargins(8, 4, 8, 4)
        bar_layout.setSpacing(4)

        # שורה 1: טעינה וקבצים
        row1 = QHBoxLayout()
        self.btn_load = QPushButton("📂 PDF")
        self.btn_load.setFixedWidth(70)
        self.btn_load.clicked.connect(self.load_pdf)
        row1.addWidget(self.btn_load)

        self.btn_advanced_import = QPushButton("📑 ייבוא")
        self.btn_advanced_import.setFixedWidth(70)
        self.btn_advanced_import.setStyleSheet("background-color: #2980B9; color: white;")
        self.btn_advanced_import.clicked.connect(self.open_advanced_import)
        row1.addWidget(self.btn_advanced_import)

        self.lbl_file = QLabel("לא נבחר קובץ")
        self.lbl_file.setStyleSheet("color: #8899AA; font-style: italic; font-size: 11px;")
        self.lbl_file.setMaximumWidth(150)
        row1.addWidget(self.lbl_file)

        self.btn_extract = QPushButton("ייבא")
        self.btn_extract.setFixedWidth(50)
        self.btn_extract.setStyleSheet("background-color: #27AE60; color: white; font-weight: bold;")
        self.btn_extract.clicked.connect(self.extract_text)
        row1.addWidget(self.btn_extract)

        row1.addWidget(QLabel("עמודים:"))
        
        input_style = "background-color: #102A43; color: #FFFFFF; font-weight: bold; border: 1px solid #BDC3C7;"
        self.input_start = QLineEdit("1"); self.input_start.setFixedWidth(35); self.input_start.setStyleSheet(input_style)
        self.input_end = QLineEdit(); self.input_end.setFixedWidth(35); self.input_end.setStyleSheet(input_style)
        
        row1.addWidget(self.input_start)
        row1.addWidget(QLabel("-"))
        row1.addWidget(self.input_end)
        row1.addStretch()
        bar_layout.addLayout(row1)

        # שורה 2: קולות ומהירות
        row2 = QHBoxLayout()
        combo_style = "QComboBox { background-color: #102A43; color: #ffffff; padding: 2px; border: 1px solid #BDC3C7; }"
        
        row2.addWidget(QLabel("קול עברי:"))
        self.combo_he = QComboBox(); self.combo_he.addItems(list(self.he_voices.keys())); self.combo_he.setFixedWidth(150); self.combo_he.setStyleSheet(combo_style)
        # שחזור בחירה מהגדרות
        if self.main_window and "selected_he_voice" in self.main_window.settings:
             self.combo_he.setCurrentText(self.main_window.settings["selected_he_voice"])
        row2.addWidget(self.combo_he)

        row2.addWidget(QLabel("קול אנגלי:"))
        self.combo_en = QComboBox(); self.combo_en.addItems(list(self.en_voices.keys())); self.combo_en.setFixedWidth(150); self.combo_en.setStyleSheet(combo_style)
        row2.addWidget(self.combo_en)

        row2.addWidget(QLabel("מהירות:"))
        self.combo_speed = QComboBox(); self.combo_speed.addItems(["-25%", "-10%", "+0%", "+10%", "+25%"]); self.combo_speed.setFixedWidth(80); self.combo_speed.setStyleSheet(combo_style)
        self.combo_speed.setCurrentText("+0%")
        row2.addWidget(self.combo_speed)

        self.chk_dual = QCheckBox("EN"); self.chk_dual.setChecked(True)
        row2.addWidget(self.chk_dual)
        row2.addStretch()
        bar_layout.addLayout(row2)
        
        layout.addWidget(compact_bar)

        # --- Splitter (PDF + Editor) ---
        self.splitter = QSplitter(Qt.Horizontal)
        self.pdf_viewer = PDFViewerWidget()
        self.splitter.addWidget(self.pdf_viewer)

        right_container = QWidget()
        right_layout = QVBoxLayout(right_container); right_layout.setContentsMargins(0,0,0,0); right_layout.setSpacing(3)
        
        # סרגל כלים לעורך
        frame_tools = QFrame(); frame_tools.setStyleSheet("background-color: #2C3E50; border-radius: 4px;")
        toolbar_layout = QHBoxLayout(frame_tools); toolbar_layout.setContentsMargins(4,2,4,2)
        
        self.input_filename = QLineEdit(); self.input_filename.setPlaceholderText("שם קובץ"); self.input_filename.setFixedWidth(150)
        toolbar_layout.addWidget(QLabel("🏷️"))
        toolbar_layout.addWidget(self.input_filename)
        
        btn_rtl = QPushButton("RTL"); btn_rtl.setFixedWidth(35); btn_rtl.clicked.connect(lambda: self.set_text_direction(Qt.RightToLeft))
        btn_ltr = QPushButton("LTR"); btn_ltr.setFixedWidth(35); btn_ltr.clicked.connect(lambda: self.set_text_direction(Qt.LeftToRight))
        toolbar_layout.addWidget(btn_rtl); toolbar_layout.addWidget(btn_ltr)

        self.btn_nikud_auto = QPushButton("ניקוד"); self.btn_nikud_auto.setStyleSheet("background-color: #8E44AD; color: white;"); self.btn_nikud_auto.clicked.connect(self.start_auto_nikud)
        toolbar_layout.addWidget(self.btn_nikud_auto)

        self.btn_dict_only = QPushButton("נקד ממילון"); self.btn_dict_only.setStyleSheet("background-color: #8E44AD; color: white;"); self.btn_dict_only.clicked.connect(self.run_dictionary_only)
        toolbar_layout.addWidget(self.btn_dict_only)

        self.btn_split_export = QPushButton("פיצול")
        self.btn_split_export.setStyleSheet("background-color: #E67E22; color: white;")
        self.btn_split_export.clicked.connect(self.open_split_dialog)
        toolbar_layout.addWidget(self.btn_split_export)

        toolbar_layout.addStretch()
        self.input_search = QLineEdit(); self.input_search.setPlaceholderText("🔍 חפש..."); self.input_search.setFixedWidth(150); self.input_search.returnPressed.connect(self.search_text)
        toolbar_layout.addWidget(self.input_search)
        
        right_layout.addWidget(frame_tools)

        self.editor = NikudTextEdit(self.main_window) # חשוב: parent הוא החלון הראשי לדיאלוגים
        self.editor.setFont(QFont("Arial", 14))
        self.editor.setLayoutDirection(Qt.RightToLeft)
        self.editor.textChanged.connect(self.update_char_count)
        self.editor.cursorPositionChanged.connect(self.sync_pdf_to_cursor)
        right_layout.addWidget(self.editor)

        self.splitter.addWidget(right_container)
        self.splitter.setSizes([600, 600])
        layout.addWidget(self.splitter, 1)

        # כפתור המרה
        self.btn_convert = QPushButton("🚀 צור קובץ MP3")
        self.btn_convert.setFixedHeight(42)
        self.btn_convert.setStyleSheet("background-color: #F76707; font-size: 16px; font-weight: bold;")
        self.btn_convert.clicked.connect(self.start_export_process)
        layout.addWidget(self.btn_convert)

    # ==========================
    # LOGIC FUNCTIONS MOVED HERE
    # ==========================

    def load_pdf(self):
        # שימוש ב-getOpenFileNames (ברבים) במקום getOpenFileName
        last_dir = os.path.dirname(self.file_path) if self.file_path else ''
        fnames, _ = QFileDialog.getOpenFileNames(self, 'בחר קבצי PDF (ניתן לבחור כמה)', last_dir, "PDF Files (*.pdf)")

        if fnames:
            # הוספה לרשימה קיימת (לתמיכה בייבוא מתיקיות שונות)
            self.file_paths.extend(fnames)
            # הסרת כפילויות תוך שמירה על סדר
            seen = set()
            unique = []
            for f in self.file_paths:
                if f not in seen:
                    seen.add(f)
                    unique.append(f)
            self.file_paths = unique
            self.file_path = self.file_paths[0]

            # עדכון התצוגה למשתמש
            if len(self.file_paths) == 1:
                self.lbl_file.setText(os.path.basename(self.file_paths[0]))
            else:
                self.lbl_file.setText(f"נבחרו {len(self.file_paths)} קבצים")

            # חישוב סך העמודים מכל הקבצים יחד
            total_pages_count = 0
            for f in self.file_paths:
                try:
                    with open(f, 'rb') as pdf_file:
                        reader = PyPDF2.PdfReader(pdf_file)
                        total_pages_count += len(reader.pages)
                except: pass

            self.input_start.setText("1")
            self.input_end.setText(str(total_pages_count))
            clean_name = os.path.splitext(os.path.basename(self.file_paths[0]))[0]
            self.input_filename.setText(clean_name)

    def extract_text(self):
        """
        גרסה משופרת הכוללת ניקוי מתקדם של פיסוק, סוגריים ואיחוד פסקאות חכם.
        """
        if not hasattr(self, 'file_paths') or not self.file_paths:
            QMessageBox.warning(self, "שגיאה", "לא נבחרו קבצים.")
            return

        self.main_window.lbl_status.setText("מייבא טקסט ומבצע ניקוי מתקדם...")
        self.main_window.progress_bar.setValue(0)

        if hasattr(self, 'pdf_viewer'):
            self.pdf_viewer.load_pdf(self.file_paths[0])

        full_text_accumulator = ""
        total_files = len(self.file_paths)

        try:
            for idx, f_path in enumerate(self.file_paths):
                try:
                    doc = fitz.open(f_path)
                    total_pages = len(doc)
                except Exception as e:
                    print(f"Error reading PDF {f_path}: {e}")
                    continue

                txt_start = self.input_start.text().strip() or "1"
                txt_end = self.input_end.text().strip() or str(total_pages)
                start_p = max(1, int(txt_start))
                end_p = min(total_pages, int(txt_end))

                for i in range(start_p - 1, end_p):
                    page_num = i + 1
                    full_text_accumulator += f"\n\n[PAGE:{page_num}]\n"

                    page_text = doc[i].get_text()

                    if page_text:
                        # === שלב 1: ניקוי שורות זבל ===
                        lines = page_text.split('\n')
                        cleaned_lines = []
                        for line in lines:
                            stripped = line.strip()
                            if re.match(r'^\s*\d+\s*$', stripped):
                                continue
                            if len(stripped) < 2 and stripped not in ['.', '!', '?', ',', ')', '(']:
                                continue
                            cleaned_lines.append(stripped)

                        # === שלב 1.5: תיקון סימני פיסוק RTL ===
                        # ב-PDF עברי, PyMuPDF מחזיר לפעמים ".פינוייה" במקום "פינוייה."
                        # כלומר סימן הפיסוק מופיע בתחילת השורה דבוק למילה הראשונה
                        # התיקון מעביר את הסימן לסוף המילה שדבוקה אליו
                        for k in range(len(cleaned_lines)):
                            cleaned_lines[k] = re.sub(r'^([.!?,;:"\u05F4]+)(\S+)', r'\2\1', cleaned_lines[k])
                        # תיקון סדר גרשיים-נקודה: word." -> word". (בעברית הגרשיים סוגרות לפני הנקודה)
                        for k in range(len(cleaned_lines)):
                            cleaned_lines[k] = re.sub(r'\.(")', r'\1.', cleaned_lines[k])

                        # === שלב 1.6: איחוד שורות פיסוק/סוגריים בודדות לשורה הקודמת ===
                        merged_lines = []
                        for line in cleaned_lines:
                            if merged_lines and re.match(r'^[.!?,;:)(–\-\]\[]+$', line):
                                merged_lines[-1] += line
                            else:
                                merged_lines.append(line)
                        cleaned_lines = merged_lines

                        # === שלב 2: איחוד פסקאות חכם ===
                        smart_text = ""
                        for j, line in enumerate(cleaned_lines):
                            # אם השורה מתחילה בסימן פיסוק - אל תוסיף רווח לפניה
                            if j > 0:
                                prev_line = cleaned_lines[j-1]
                                current_starts_with_punct = line and line[0] in '.!?,;:'
                                
                                if current_starts_with_punct:
                                    # אל תוסיף רווח - הנקודה תידבק למילה הקודמת
                                    pass
                                elif prev_line.endswith(('.', '!', '?', ':', ';', '"')):
                                    smart_text += "\n"
                                else:
                                    smart_text += " "
                            
                            smart_text += line

                        full_text_accumulator += smart_text

                doc.close()
                self.main_window.progress_bar.setValue(int(((idx + 1) / total_files) * 100))

            # === שלב 3: פוליש סופי ===
            final_text = advanced_cleanup(full_text_accumulator)
            
            # תיקון: נקודה דבוקה למילה עברית - הוסף רווח אחרי הנקודה
            # דוגמה: "פינוייה.כלומר" → "פינוייה. כלומר"
            final_text = re.sub(r'\.([^\s\n])', r'. \1', final_text)
            
            # תיקון: פסיק דבוק למילה - הוסף רווח אחרי
            final_text = re.sub(r',([^\s\n])', r', \1', final_text)
            
            # תיקון: רווחים מרובים
            final_text = re.sub(r' {2,}', ' ', final_text)
            
            # תיקון: רווחים לפני סימני פיסוק
            final_text = re.sub(r'\s+([.,!?;:])', r'\1', final_text)

            # תיקון: רווחים מיותרים בתוך סוגריים
            final_text = re.sub(r'\(\s+', '(', final_text)
            final_text = re.sub(r'\s+\)', ')', final_text)

            self.editor.setPlainText(final_text.strip())
            self.main_window.lbl_status.setText("הייבוא הושלם! (טקסט עבר סידור וניקוי)")

            if hasattr(self, 'sync_pdf_to_cursor'):
                self.sync_pdf_to_cursor()

        except Exception as e:
            QMessageBox.critical(self, "שגיאה בייבוא", f"תקלה בחילוץ: {str(e)}")
            import traceback
            traceback.print_exc()

    def start_export_process(self):
        text = self.editor.toPlainText()
        if not text.strip():
            QMessageBox.warning(self, "שגיאה", "אין טקסט לייצוא.")
            return

        out_dir = os.path.dirname(self.file_path) if self.file_path else os.path.expanduser("~/Documents")
        file_name = self.input_filename.text().strip()
        if not file_name:
            file_name = f"Audio_{datetime.now().strftime('%H-%M')}"
        if not file_name.endswith(".mp3"): file_name += ".mp3"
        
        save_path = os.path.join(out_dir, file_name)
        
        self.btn_convert.setEnabled(False)
        self.btn_convert.setText("מייצא... (מעבד)")
        self.main_window.lbl_status.setText(f"שומר ל: {file_name}")
        
        voice_name = self.combo_he.currentText()
        voice_key = self.he_voices.get(voice_name, "he-IL-HilaNeural")
        rate = self.combo_speed.currentText()

        # Access settings via main_window
        current_dict = self.main_window.settings.get("nikud_dictionary", {})

        self.tts_worker = TTSWorker(
            text=text,
            output_file=save_path,
            voice=voice_key,
            rate=rate,
            volume="+0%",
            dicta_dict=current_dict,
            parent=self.main_window
        )

        self.tts_worker.finished_success.connect(self.on_tts_finished)
        self.tts_worker.progress_update.connect(self.main_window.progress_bar.setValue)
        self.tts_worker.error.connect(self.on_tts_error)
        self.tts_worker.start()

    def on_tts_finished(self, mp3_path, skipped, is_batch=False):
        # ... (Copy logic from original, adapt self.tab_karaoke access)
        print(f"Finished: {mp3_path}")
        self.btn_convert.setEnabled(True)
        self.btn_convert.setText("🚀 צור קובץ MP3")
        
        # Load in Karaoke (Accessing sibling tab via main_window)
        json_path = mp3_path.replace(".mp3", ".json")
        if os.path.exists(json_path) and hasattr(self.main_window, 'tab_karaoke'):
            self.main_window.tab_karaoke.load_project(json_path, mp3_path)
            self.main_window.tabs.setCurrentWidget(self.main_window.tab_karaoke)

        # Handle Telegram upload here if needed (using main_window settings)
        token = self.main_window.settings.get("tg_token", "")
        chat_id = self.main_window.settings.get("tg_chat_id", "")
        
        if token and chat_id:
             self.tg_worker = TelegramWorker(token, chat_id, [(mp3_path, 'audio')])
             self.tg_worker.finished.connect(self.on_telegram_upload_complete)
             self.tg_worker.start()

    def on_tts_error(self, msg):
        self.btn_convert.setEnabled(True)
        self.btn_convert.setText("🚀 צור קובץ MP3")
        QMessageBox.critical(self, "שגיאה", msg)

    def on_telegram_upload_complete(self):
        self.main_window.lbl_status.setText("נשלח לטלגרם!")

    # --- Nikud Logic ---
    def start_auto_nikud(self):
        self.stop_worker_safely('nikud_worker')
        text = self.get_text_safe()
        if not text.strip(): return
        
        self.btn_nikud_auto.setText("מנקד...")
        self.btn_nikud_auto.setEnabled(False)
        
        current_dict = self.main_window.settings.get("nikud_dictionary", {})
        self.nikud_worker = NikudWorker(text, current_dict)
        self.nikud_worker.finished.connect(self.on_nikud_success)
        self.nikud_worker.error.connect(self.on_nikud_error)
        self.nikud_worker.start()

    def on_nikud_success(self, vocalized_text):
        # שחזור מצב הכפתורים
        self.btn_nikud_auto.setEnabled(True)
        self.btn_nikud_auto.setText("✨ ניקוד אוטומטי (Dicta)")
        self.main_window.progress_bar.setValue(100)
        
        # 1. שליפת הטקסט המקורי בצורה בטוחה (כולל תגיות תמונה) לצורך השוואה
        original_text = self.get_text_safe()

        # בדיקת זהות מוחלטת (אם אין שום שינוי, חבל להריץ לוגיקה כבדה)
        if original_text == vocalized_text:
            self.main_window.lbl_status.setText("הניקוד הסתיים. לא נמצאו שינויים.")
            self.set_text_safe(vocalized_text) # משחזר את התמונות
            return

        self.main_window.lbl_status.setText("הניקוד הסתיים! אנא אשר שינויים.")

        # === לוגיקת השוואה (Diff) ===
        # פונקציה לפירוק למילים ששומרת על תגיות תמונה שלמות כדי לא לשבור אותן
        def tokenize(txt):
            return re.findall(r'\[IMG:.*?\]|[\u0590-\u05FF]+|[^\s\u0590-\u05FF]+', txt)

        orig_tokens = tokenize(original_text)
        new_tokens = tokenize(vocalized_text)
        
        changes_map = {} 
        all_orig_words = []
        
        # שימוש ב-difflib למציאת ההבדלים בין הטקסט הישן לחדש
        matcher = difflib.SequenceMatcher(None, orig_tokens, new_tokens)
        
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == 'replace':
                segment_orig = orig_tokens[i1:i2]
                segment_new = new_tokens[j1:j2]
                
                # ניסיון התאמה 1-על-1 במקרה של החלפה
                for k in range(min(len(segment_orig), len(segment_new))):
                    o_word = segment_orig[k]
                    n_word = segment_new[k]
                    
                    # מתייחסים רק למילים בעברית (ולא לתמונות או סימנים)
                    if any('א' <= c <= 'ת' for c in o_word) and "[IMG:" not in o_word:
                        all_orig_words.append(o_word)
                        if o_word != n_word:
                            changes_map[o_word] = n_word
            
            elif tag == 'equal':
                # גם במילים זהות, צריך לספור אותן לסטטיסטיקה
                for k in range(i1, i2):
                    w = orig_tokens[k]
                    if any('א' <= c <= 'ת' for c in w) and "[IMG:" not in w:
                        all_orig_words.append(w)

        # יצירת הרשימה הסופית לדיאלוג
        word_counts = Counter(all_orig_words)
        final_list = []
        
        for orig, new in changes_map.items():
            count = word_counts[orig]
            final_list.append((orig, new, count))
        
        # מיון: מילים נפוצות למעלה
        final_list.sort(key=lambda x: x[2], reverse=True)

        # === שלב ההכרעה: דיאלוג או עדכון ישיר ===
        if final_list:
            # אם יש שינויים, פותחים את הדיאלוג
            dialog = AnalysisDialog(final_list, self)
            dialog.pending_text = vocalized_text 
            dialog.exec_()
        else:
            # אם אין שינויים (או שרק סימני פיסוק השתנו), מעדכנים ישירות
            self.main_window.lbl_status.setText("לא נמצאו שינויים מהותיים במילים.")
            # === הפקודה החשובה ביותר: עדכון בטוח ששומר על התמונות ===
            self.set_text_safe(vocalized_text)

    def on_nikud_error(self, msg):
        self.btn_nikud_auto.setEnabled(True)
        self.btn_nikud_auto.setText("✨ הוסף ניקוד אוטומטי (Dicta)")
        self.main_window.lbl_status.setText("שגיאה בניקוד")
        QMessageBox.warning(self, "שגיאה", msg)

    # --- Text Tools ---
    def set_text_direction(self, direction):
        self.editor.setLayoutDirection(direction); 
        cursor = self.editor.textCursor(); 
        block_format = cursor.blockFormat(); 
        block_format.setLayoutDirection(direction); 
        cursor.setBlockFormat(block_format); 
        self.editor.setTextCursor(cursor); 
        self.editor.setFocus()
        

    def search_text(self):
        """מבצע חיפוש בתוך עורך הטקסט"""
        search_str = self.input_search.text()
        if not search_str:
            return
            
        # שימוש בפונקציית החיפוש המובנית של QTextEdit
        found = self.editor.find(search_str)
        
        if not found:
            # אם לא נמצא, ננסה לחפש שוב מתחילת המסמך (Loop)
            cursor = self.editor.textCursor()
            cursor.movePosition(QTextCursor.Start)
            self.editor.setTextCursor(cursor)
            
            # חיפוש נוסף מההתחלה
            found = self.editor.find(search_str)
            
            if not found:
                self.main_window.lbl_status.setText(f"❌ הביטוי '{search_str}' לא נמצא.")
            else:
                self.main_window.lbl_status.setText(f"🔍 נמצא: '{search_str}' (חיפוש מההתחלה)")
        else:
             self.main_window.lbl_status.setText(f"🔍 נמצא: '{search_str}'")

    def update_char_count(self):
        """מעדכן את מספר התווים בשורת הסטטוס"""
        text = self.editor.toPlainText()
        count = len(text)
        # מעדכן את הסטטוס בר (למשל: "תווים: 120")
        self.main_window.lbl_status.setText(f"תווים: {count}")

    def sync_pdf_to_cursor(self):
        """
        פונקציית סנכרון: מזהה את המיקום הנוכחי בעורך הטקסט,
        מוצאת את תגית העמוד האחרונה ([PAGE:X]) ומעדכנת את ה-PDF משמאל.
        """
        try:
            # אם אין צפיין PDF פעיל, אין מה לסנכרן
            if not hasattr(self, 'pdf_viewer'):
                return

            # 1. קבלת מיקום הסמן הנוכחי
            cursor = self.editor.textCursor()
            position = cursor.position()

            # 2. שליפת הטקסט מתחילת המסמך ועד למיקום הסמן
            # כך אנו מבטיחים שנמצא את התגית ששולטת על הקטע הנוכחי
            text_up_to_cursor = self.editor.toPlainText()[:position]

            # 3. חיפוש כל תגיות העמוד בקטע הטקסט הזה
            # מחפש תבנית כמו [PAGE:12] או [PAGE:5]
            matches = re.findall(r'\[PAGE:(\d+)\]', text_up_to_cursor)

            if matches:
                # 4. לוקחים את התוצאה האחרונה ברשימה
                # (האחרונה היא זו שהכי קרובה למיקום הסמן שלנו מלמעלה)
                last_page_str = matches[-1]
                target_page = int(last_page_str)

                # 5. עדכון הצפיין (רק אם העמוד באמת השתנה)
                # בדיקה זו מונעת ריצודים וטעינות חוזרות מיותרות
                if self.pdf_viewer.current_page != target_page:
                    print(f"[SYNC] Cursor at pos {position} -> Jump to PDF Page {target_page}")
                    self.pdf_viewer.show_page(target_page)
            
            else:
                # אם לא נמצאה שום תגית (למשל בתחילת המסמך), נלך לעמוד 1 או לעמוד ההתחלה שהוגדר
                start_page = 1
                if self.input_start.text().strip().isdigit():
                    start_page = int(self.input_start.text())
                
                if self.pdf_viewer.current_page != start_page:
                    self.pdf_viewer.show_page(start_page)

        except Exception as e:
            # תופסים שגיאות כדי לא לתקוע את התוכנה בזמן הקלדה
            print(f"[SYNC ERROR] Could not sync PDF: {e}")   

    # --- Safe Text (Images) ---
    def get_text_safe(self):
        """
        שואב את הטקסט מהעורך, וממיר את התמונות הוויזואליות 
        בחזרה לתגיות טקסט [IMG:path] כדי שהמנוע יוכל לעבוד איתן.
        """
        doc = self.editor.document()
        full_text = ""
        
        block = doc.begin()
        while block.isValid():
            iter_ = block.begin()
            # אם הבלוק ריק (רק ירידת שורה), נוסיף ירידת שורה
            if iter_.atEnd():
                full_text += "\n"
            
            while not iter_.atEnd():
                fragment = iter_.fragment()
                if fragment.isValid():
                    char_format = fragment.charFormat()
                    # בדיקה: האם זו תמונה?
                    if char_format.isImageFormat():
                        img_fmt = char_format.toImageFormat()
                        name = img_fmt.name()
                        # המרה לתגית טקסט עבור המנוע
                        full_text += f"\n[IMG:{name}]\n"
                    else:
                        # סתם טקסט
                        full_text += fragment.text()
                iter_ += 1
            
            # סוף בלוק = בדרך כלל ירידת שורה, אלא אם כן זו תמונה שכבר הוספנו לה
            if not full_text.endswith("\n") and not full_text.endswith("]\n"):
                 full_text += "\n"
                 
            block = block.next()
            
        return full_text.strip()

    def set_text_safe(self, text_with_tags):
        """
        לוקח טקסט עם תגיות [IMG:path] ומציג אותן כתמונות אמיתיות בעורך.
        """
        print(f"[DEBUG] set_text_safe called. Length: {len(text_with_tags)}")
        
        self.editor.clear()
        cursor = self.editor.textCursor()
        
        # איפוס פורמטים למניעת גלישת סגנונות
        cursor.setBlockFormat(QTextBlockFormat())
        cursor.setCharFormat(QTextCharFormat())

        # פיצול חכם: מפריד בין טקסט רגיל לתגיות תמונה
        parts = re.split(r'(\[IMG:.*?\])', text_with_tags)
        
        images_count = 0
        
        for part in parts:
            if part.startswith("[IMG:") and part.endswith("]"):
                # === זו תמונה! ===
                path = part[5:-1] # חילוץ הנתיב נטו
                
                print(f"[DEBUG] Found Image Tag: {path}")
                
                if os.path.exists(path):
                    cursor.insertBlock() # שורה חדשה לפני
                    
                    img_fmt = QTextImageFormat()
                    img_fmt.setName(path)
                    
                    # קביעת רוחב מקסימלי כדי שלא ישבור את המסך
                    img_fmt.setWidth(550) 
                    
                    cursor.insertImage(img_fmt)
                    cursor.insertBlock() # שורה חדשה אחרי
                    images_count += 1
                else:
                    print(f"[ERROR] Image path does not exist: {path}")
                    cursor.insertText(f"[תמונה חסרה: {os.path.basename(path)}]")
                
            else:
                # === זה טקסט רגיל ===
                if part:
                    cursor.insertText(part)
        
        print(f"[DEBUG] set_text_safe finished. Inserted {images_count} images.")
        self.editor.moveCursor(QTextCursor.Start)

    # --- Helpers ---
    def stop_worker_safely(self, worker_attr_name):
        """פונקציית עזר לעצירה בטוחה של תהליכונים למניעת קריסות"""
        if hasattr(self, worker_attr_name):
            worker = getattr(self, worker_attr_name)
            if worker and worker.isRunning():
                print(f"[DEBUG] Stopping active worker: {worker_attr_name}")
                worker.quit()
                worker.wait(2000) # מחכים עד 2 שניות לסיום מסודר
                if worker.isRunning(): # אם עדיין רץ - עצירה כפויה (למניעת קריסה)
                    worker.terminate()
                    worker.wait()

    def open_advanced_import(self):
        dialog = AdvancedImportDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            # כשהמשתמש לוחץ "בצע ייבוא", הטקסט מגיע לכאן
            if dialog.result_text:
                self.editor.setPlainText(dialog.result_text)
                self.main_window.lbl_status.setText("הייבוא המתקדם הושלם בהצלחה!")
            else:
                self.main_window.lbl_status.setText("הייבוא הסתיים ללא טקסט.")

    def run_dictionary_only(self):
        """
        עובר על הטקסט ומחליף רק מילים שקיימות במילון האישי.
        כל שאר הטקסט נשאר ללא ניקוד/שינוי.
        """
        # 1. בדיקה שיש מילון
        current_dict = self.main_window.settings.get("nikud_dictionary", {})
        metadata = self.main_window.settings.get("nikud_metadata", {})
        
        if not current_dict:
            QMessageBox.information(self, "המילון ריק", "אין מילים במילון האישי ליישום.")
            return

        self.main_window.lbl_status.setText("מחיל ניקוד לפי מילון בלבד...")
        QApplication.processEvents()

        # 2. שליפת הטקסט הבטוח (שומר על תגיות תמונה)
        text = self.get_text_safe()
        
        # 3. מיון המילון לפי אורך מילה (מהארוך לקצר)
        # זה קריטי כדי שלא נחליף בטעות חלק ממילה (למשל 'בצל' בתוך 'בצלם')
        sorted_keys = sorted(current_dict.keys(), key=len, reverse=True)
        
        processed_text = text
        count = 0

        # 4. ביצוע ההחלפות
        for base_word in sorted_keys:
            target_word = current_dict[base_word]
            
            # בדיקה אם צריך התאמה מדויקת או חלקית
            is_exact = False
            if base_word in metadata:
                 if metadata[base_word].get('match_type') == 'exact':
                     is_exact = True
            
            # אם הערך במילון זהה למילה בטקסט (בלי ניקוד), אין טעם להחליף סתם
            # אבל אנחנו מניחים שהערך במילון מנוקד.

            if is_exact:
                # החלפה רק אם זו מילה שלמה (גבולות מילה)
                # (?<!...) מוודא שאין אות עברית/אנגלית לפני
                # (?!...) מוודא שאין אות עברית/אנגלית אחרי
                pattern = r'(?<![\w\u0590-\u05FF])' + re.escape(base_word) + r'(?![\w\u0590-\u05FF])'
                processed_text, n = re.subn(pattern, target_word, processed_text)
                count += n
            else:
                # החלפה חלקית (פשוטה)
                if base_word in processed_text:
                    # שימוש ב-replace רגיל במקום regex לביצועים, אבל regex בטוח יותר למניעת לולאות
                    # נשתמש ב-regex פשוט להחלפה גלובלית
                    pattern = re.escape(base_word)
                    processed_text, n = re.subn(pattern, target_word, processed_text)
                    count += n

        # 5. החזרת הטקסט לעורך
        if count > 0:
            self.set_text_safe(processed_text)
            self.main_window.lbl_status.setText(f"בוצע! הוחלפו {count} מופעים מתוך המילון.")
            QMessageBox.information(self, "סיום", f"התהליך הסתיים.\nבוצעו {count} החלפות לפי המילון.")
        else:
            self.main_window.lbl_status.setText("לא נמצאו מילים מהמילון בטקסט.")
            QMessageBox.information(self, "סיום", "לא נמצאו בטקסט מילים שמופיעות במילון שלך.")

         
    def open_split_dialog(self):
        """פותח את חלון ההגדרות לפיצול"""
        # לוקח את שם הקובץ הנוכחי כברירת מחדל
        current_name = self.input_filename.text()
        
        dialog = SplitExportDialog(current_name, self)
        if dialog.exec_() == QDialog.Accepted:
            data = dialog.get_data()
            # קריאה לפונקציית העיבוד עם הנתונים מהדיאלוג
            self.start_split_export_process(data)
         
    def start_split_export_process(self, data):
        """מתחיל תהליך של פיצול הטקסט וייצוא סדרתי (מקבל נתונים מהדיאלוג)"""
        full_text = self.editor.toPlainText()
        
        # חילוץ הנתונים שהתקבלו מהדיאלוג
        split_word = data["split_word"]
        base_filename = data["filename"] or "Audio"
        use_number = data["use_number"]
        
        if not full_text.strip():
            QMessageBox.warning(self, "שגיאה", "העורך ריק.")
            return
            
        if not split_word:
            QMessageBox.warning(self, "שגיאה", "לא הוזנה מילה לפיצול.")
            return

        # 1. לוגיקת החיתוך (Regex)
        if use_number:
            # מחפש: מילה + רווחים + ספרות (לדוגמה: "הרצאה 5")
            pattern = rf'(?={re.escape(split_word)}\s+\d+)'
        else:
            # מחפש רק את המילה
            pattern = rf'(?={re.escape(split_word)})'
            
        segments = re.split(pattern, full_text)
        segments = [s.strip() for s in segments if s.strip()]
        
        if len(segments) < 2:
            QMessageBox.warning(self, "שים לב", f"לא נמצאה המילה '{split_word}' (או שלא בוצע פיצול).")
            return

        # 2. בניית התור (Queue)
        self.batch_queue = []
        
        # קביעת תיקיית יעד
        out_dir = ""
        if hasattr(self, 'file_paths') and self.file_paths:
            out_dir = os.path.dirname(self.file_paths[0])
        elif hasattr(self, 'file_path') and self.file_path:
            out_dir = os.path.dirname(self.file_path)
        if not out_dir: out_dir = os.path.expanduser("~/Documents")

        print(f"[DEBUG] Splitting into {len(segments)} parts based on '{split_word}'")

        for idx, segment_text in enumerate(segments):
            clean_first_line = segment_text.split('\n')[0].strip()
            safe_name_start = re.sub(r'[\\/*?:"<>|]', "", clean_first_line)
            
            # לוקחים רק את ה-3-4 מילים הראשונות לשם הקובץ
            name_words = safe_name_start.split()[:4]
            short_name = " ".join(name_words)
            
            if idx == 0 and not clean_first_line.startswith(split_word):
                final_name = f"{base_filename}_Start"
            else:
                final_name = f"{base_filename}_{short_name}"
            
            # מוודאים שאין רווחים מיותרים בשם הקובץ
            final_name = final_name.replace(" ", "_")
            full_path = os.path.join(out_dir, f"{final_name}.mp3")
            
            self.batch_queue.append({
                "text": segment_text,
                "path": full_path,
                "index": idx + 1,
                "total": len(segments)
            })

        self.total_batch_size = len(self.batch_queue)
        self.run_next_batch_task()
         
    def run_next_batch_task(self):
        """לוקח את המשימה הבאה בתור ומריץ אותה"""
        if not hasattr(self, 'batch_queue') or not self.batch_queue:
            self.main_window.lbl_status.setText("✅ כל הקבצים בתור עובדו בהצלחה!")
            self.btn_convert.setEnabled(True)
            self.btn_split_export.setEnabled(True)
            self.main_window.progress_bar.setValue(100)
            QMessageBox.information(self, "סיום", f"הסתיים עיבוד של {self.total_batch_size} קבצים.")
            return

        # שליפת המשימה הבאה
        task = self.batch_queue.pop(0)
        
        self.current_batch_task = task
        self.main_window.lbl_status.setText(f"מעבד חלק {task['index']}/{task['total']}: {os.path.basename(task['path'])}...")
        self.main_window.progress_bar.setValue(0)
        
        # נעילת כפתורים
        self.btn_convert.setEnabled(False)
        self.btn_split_export.setEnabled(False)

        # הרצת ה-Worker (כמו בייצוא רגיל)
        voice_key = "he-IL-HilaNeural"
        if hasattr(self, 'combo_he'):
            voice_name = self.combo_he.currentText()
            voice_key = self.he_voices.get(voice_name, "he-IL-HilaNeural")
        rate = self.combo_speed.currentText()
        current_dict = self.main_window.settings.get("nikud_dictionary", {})

        self.tts_worker = TTSWorker(
            text=task['text'],
            output_file=task['path'],
            voice=voice_key,
            rate=rate,
            volume="+0%",
            dicta_dict=current_dict,
            parent=self
        )

        # שים לב: אנחנו מחברים לפונקציה מיוחדת שיודעת להמשיך את התור
        self.tts_worker.finished_success.connect(self.on_batch_part_finished)
        self.tts_worker.progress_update.connect(self.main_window.progress_bar.setValue)
        self.tts_worker.error.connect(self.on_tts_error) # אפשר להוסיף טיפול שגיאות שממשיך הלאה
        
        self.tts_worker.start()
         
    def on_batch_part_finished(self, mp3_path, skipped):
        """נקרא כשחלק אחד בתור מסתיים"""
        print(f"[DEBUG] Finished part: {mp3_path}")
        
        # 1. לוגיקה רגילה של סיום (יצירת PDF חתוך, טלגרם וכו')
        # אנחנו קוראים לפונקציה המקורית כדי שתטפל בשמירה ובטלגרם עבור הקובץ הספציפי הזה
        self.on_tts_finished(mp3_path, skipped, is_batch=True)
        
        # 2. המשך לקובץ הבא בתור
        # השהייה קטנה כדי לתת למערכת לנשום
        QTimer.singleShot(1000, self.run_next_batch_task)
         
    def create_sliced_pdf(self, output_filename):
        """יוצר קובץ PDF זמני הכולל רק את העמודים הנבחרים"""
        if not hasattr(self, 'file_path') or not self.file_path or not os.path.exists(self.file_path):
            return None

        try:
            # שליפת טווח העמודים מהממשק
            try:
                start_page = int(self.input_start.text())
                end_page = int(self.input_end.text())
            except:
                return None # אם הקלט לא תקין

            reader = PyPDF2.PdfReader(self.file_path)
            writer = PyPDF2.PdfWriter()
            
            # בדיקת גבולות
            total_pages = len(reader.pages)
            start_idx = max(0, start_page - 1)
            end_idx = min(total_pages, end_page)

            # הוספת העמודים הרלוונטיים
            for i in range(start_idx, end_idx):
                writer.add_page(reader.pages[i])

            # שמירה
            with open(output_filename, "wb") as f:
                writer.write(f)
            
            print(f"[DEBUG] Created sliced PDF: {output_filename} (Pages {start_page}-{end_page})")
            return output_filename

        except Exception as e:
            print(f"[ERROR] Failed to slice PDF: {e}")
            return None