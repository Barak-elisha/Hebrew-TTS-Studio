import os
import re
import difflib
import PyPDF2
import fitz  # PyMuPDF
import unicodedata
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
        self.main_window = parent
        
        # נתונים מקומיים לטאב
        self.file_path = ""
        self.file_paths = []
        self.active_placeholders = {} # משתנה לשמירת התגיות המוסתרות
        
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

        self.editor = NikudTextEdit(self.main_window)
        self.editor.setFont(QFont("Arial", 14))
        self.editor.setLayoutDirection(Qt.RightToLeft)
        self.editor.textChanged.connect(self.update_char_count)
        self.editor.cursorPositionChanged.connect(self.sync_pdf_to_cursor)
        right_layout.addWidget(self.editor)

        self.splitter.addWidget(right_container)
        self.splitter.setSizes([600, 600])
        layout.addWidget(self.splitter, 1)

        self.btn_convert = QPushButton("🚀 צור קובץ MP3")
        self.btn_convert.setFixedHeight(42)
        self.btn_convert.setStyleSheet("background-color: #F76707; font-size: 16px; font-weight: bold;")
        self.btn_convert.clicked.connect(self.start_export_process)
        layout.addWidget(self.btn_convert)

    # ============================================
    # === פונקציית עזר לניקוי תגיות ל-TTS ===
    # ============================================
    def clean_tags_for_tts(self, text):
        """מסיר תגיות מערכת כדי שה-TTS לא יקריא אותן"""
        if not text: return ""
        # מסיר [FILE:...], [PAGE:...], [IMG:...]
        return re.sub(r'\[(?:FILE|PAGE|IMG):.*?\]', '', text).strip()

    def load_pdf(self):
        last_dir = os.path.dirname(self.file_path) if self.file_path else os.path.expanduser("~")
        fnames, _ = QFileDialog.getOpenFileNames(self, 'בחר קבצי PDF (ניתן לבחור כמה)', last_dir, "PDF Files (*.pdf)")
        if fnames:
            self.file_paths.extend(fnames)
            # הסרת כפילויות
            seen = set()
            unique = []
            for f in self.file_paths:
                if f not in seen:
                    seen.add(f)
                    unique.append(f)
            self.file_paths = unique
            
            self.file_path = self.file_paths[0]
            if len(self.file_paths) == 1:
                self.lbl_file.setText(os.path.basename(self.file_paths[0]))
            else:
                self.lbl_file.setText(f"נבחרו {len(self.file_paths)} קבצים")
            
            # טעינה ראשונית
            if hasattr(self, 'pdf_viewer'):
                self.pdf_viewer.load_pdf(self.file_path)
            
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
        if not hasattr(self, 'file_paths') or not self.file_paths:
            QMessageBox.warning(self, "שגיאה", "לא נבחרו קבצים.")
            return
        
        self.main_window.lbl_status.setText("מייבא טקסט ומבצע ניקוי מתקדם...")
        self.main_window.progress_bar.setValue(0)
        
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
                
                # הוספת תגית קובץ
                abs_path = os.path.abspath(f_path)
                full_text_accumulator += f"\n[FILE:{abs_path}]\n"

                for i in range(start_p - 1, end_p):
                    page_num = i + 1
                    full_text_accumulator += f"\n\n[PAGE:{page_num}]\n"
                    page_text = doc[i].get_text()
                    
                    if page_text:
                        # לוגיקת ניקוי (זהה ל-Advanced Import)
                        lines = page_text.split('\n')
                        total_lines = len(lines)
                        cleaned_lines = []
                        for line_idx, line in enumerate(lines):
                            stripped = line.strip()
                            if len(stripped) == 0: continue
                            # סינון מספרי עמודים: מספר בודד שמוקף בשורות ריקות
                            if re.match(r'^\s*\d+\s*$', stripped):
                                prev_empty = (line_idx == 0) or not lines[line_idx - 1].strip()
                                next_empty = (line_idx >= total_lines - 1) or not lines[line_idx + 1].strip()
                                if prev_empty or next_empty:
                                    continue
                            # שורות קצרות (תו אחד): לשמור רק אם הן פיסוק, אות או ספרה
                            if len(stripped) == 1 and not re.match(r'[.!?,;:)(a-zA-Z0-9\u0590-\u05FF]', stripped): continue
                            cleaned_lines.append(stripped)

                        for k in range(len(cleaned_lines)):
                            cleaned_lines[k] = re.sub(r'^([.!?,;:"\u05F4]+)(\S+)', r'\2\1', cleaned_lines[k])
                        for k in range(len(cleaned_lines)):
                            cleaned_lines[k] = re.sub(r'\.(")', r'\1.', cleaned_lines[k])

                        merged_lines = []
                        for line in cleaned_lines:
                            if merged_lines and re.match(r'^[.!?,;:)(–\-\]\[]+$', line):
                                merged_lines[-1] += line
                            else:
                                merged_lines.append(line)
                        cleaned_lines = merged_lines

                        smart_text = ""
                        for j, line in enumerate(cleaned_lines):
                            if j > 0:
                                prev_line = cleaned_lines[j-1]
                                current_starts_with_punct = line and line[0] in '.!?,;:'
                                if current_starts_with_punct: pass
                                elif prev_line.endswith(('.', '!', '?', ':', ';', '"')): smart_text += "\n"
                                else: smart_text += " "
                            smart_text += line

                        # === פוליש סופי לעמוד זה ===
                        smart_text = advanced_cleanup(smart_text)
                        smart_text = re.sub(r'\.([^\s\n\d])', r'. \1', smart_text)
                        smart_text = re.sub(r',([^\s\n])', r', \1', smart_text)
                        smart_text = re.sub(r' {2,}', ' ', smart_text)
                        smart_text = re.sub(r'\s+([.,!?;:])', r'\1', smart_text)
                        smart_text = re.sub(r'\(\s+', '(', smart_text)
                        smart_text = re.sub(r'\s+\)', ')', smart_text)

                        full_text_accumulator += smart_text
                
                doc.close()
                self.main_window.progress_bar.setValue(int(((idx + 1) / total_files) * 100))
            
            # אין צורך בפוליש נוסף שמסכן את התגיות
            self.editor.setPlainText(full_text_accumulator.strip())
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
        
        # --- בניית שם קובץ ייחודי ---
        base_name = self.input_filename.text().strip()
        if not base_name: base_name = "Audio"
        
        # הסרת סיומת אם המשתמש הקליד אותה ידנית
        if base_name.lower().endswith(".mp3"):
            base_name = base_name[:-4]
            
        # 1. הוספת טווח עמודים לשם הקובץ
        min_p, max_p = self.extract_pages_from_text(text)
        page_suffix = ""
        if min_p is not None:
            if min_p == max_p:
                page_suffix = f"_p{min_p}"
            else:
                page_suffix = f"_p{min_p}-{max_p}"
                
        # 2. הוספת חותמת זמן (למניעת דריסה)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        final_filename = f"{base_name}{page_suffix}_{timestamp}.mp3"
        save_path = os.path.join(out_dir, final_filename)
        # ---------------------------
        
        self.btn_convert.setEnabled(False)
        self.btn_convert.setText("מייצא... (מעבד)")
        self.main_window.lbl_status.setText(f"שומר ל: {final_filename}")
        
        voice_name = self.combo_he.currentText()
        voice_key = self.he_voices.get(voice_name, "he-IL-HilaNeural")
        rate = self.combo_speed.currentText()
        current_dict = self.main_window.settings.get("nikud_dictionary", {})
        
        # ניקוי תגיות לפני שליחה ל-TTS
        text_for_tts = self.clean_tags_for_tts(text)

        # שמירת הקול האנגלי בהגדרות
        self.main_window.settings["selected_en_voice"] = self.combo_en.currentText()

        dual_mode = self.chk_dual.isChecked()
        
        # יצירת ה-Worker עם הנתיב החדש והייחודי
        self.tts_worker = TTSWorker(text_for_tts, save_path, voice_key, rate, "+0%", current_dict, parent=self.main_window, dual_mode=dual_mode)
        self.tts_worker.finished_success.connect(self.on_tts_finished)
        self.tts_worker.progress_update.connect(self.main_window.progress_bar.setValue)
        self.tts_worker.error.connect(self.on_tts_error)
        self.tts_worker.start()

    def on_tts_finished(self, mp3_path, skipped, is_batch=False):
        print(f"Finished: {mp3_path}")
        if not is_batch:
            self.btn_convert.setEnabled(True)
            self.btn_convert.setText("🚀 צור קובץ MP3")

        # === יצירת PDF חתוך לפרויקט ===
        relevant_text = ""
        if is_batch and hasattr(self, 'current_batch_task') and self.current_batch_task:
            relevant_text = self.current_batch_task['text']
        else:
            relevant_text = self.editor.toPlainText()

        pdf_output_name = mp3_path.replace(".mp3", ".pdf")
        created_pdf = None
        try:
            min_page, max_page = self.extract_pages_from_text(relevant_text)
            # חילוץ קובץ מקור PDF מתוך תגית [FILE:...]
            source_pdf = self._extract_source_pdf(relevant_text)
            created_pdf = self.create_sliced_pdf(pdf_output_name, min_page, max_page, source_pdf)
        except Exception as e:
            print(f"[PDF] Failed to create sliced PDF: {e}")

        # === רישום התיקייה, רענון רשימת הפרויקטים וטעינה לנגן ===
        json_path = mp3_path.replace(".mp3", ".json")
        if hasattr(self.main_window, 'tab_karaoke'):
            try:
                # רישום התיקייה שבה נשמר הקובץ כדי שתופיע ברשימת הפרויקטים
                mp3_dir = os.path.dirname(mp3_path)
                self.main_window.tab_karaoke.track_directory(mp3_dir)
                self.main_window.tab_karaoke.refresh_file_list()
            except Exception as e:
                print(f"[ERROR] Failed to refresh sidebar: {e}")

            if os.path.exists(json_path):
                self.main_window.tab_karaoke.load_project(json_path, mp3_path)
                if not is_batch:
                    self.main_window.tabs.setCurrentWidget(self.main_window.tab_karaoke)

        # === שליחה לטלגרם עם PDF ===
        token = self.main_window.settings.get("tg_token", "")
        chat_id = self.main_window.settings.get("tg_chat_id", "")

        if token and chat_id:
            files_to_send = [(mp3_path, 'audio')]
            if created_pdf and os.path.exists(created_pdf):
                files_to_send.append((created_pdf, 'document'))

            self.tg_worker = TelegramWorker(token, chat_id, files_to_send)
            self.tg_worker.finished.connect(self.on_telegram_upload_complete)
            self.tg_worker.start()

    def _extract_source_pdf(self, text):
        """מחלץ את נתיב ה-PDF המקורי מתוך תגית [FILE:...] בטקסט"""
        file_matches = re.findall(r'\[FILE:(.*?)\]', text)
        if file_matches:
            # לוקחים את הראשון (או האחרון, תלוי בהקשר)
            raw_path = file_matches[0]
            clean_path = raw_path.replace('\u200e', '').replace('\u200f', '').replace('\u202a', '').replace('\u202c', '').strip()
            clean_path = clean_path.replace('. pdf', '.pdf')
            if os.path.exists(clean_path):
                return clean_path
        return None

    def on_tts_error(self, msg):
        self.btn_convert.setEnabled(True)
        self.btn_convert.setText("🚀 צור קובץ MP3")
        QMessageBox.critical(self, "שגיאה", msg)

    def on_telegram_upload_complete(self):
        self.main_window.lbl_status.setText("נשלח לטלגרם!")

    # ============================================
    # === פונקציות הניקוד עם הגנת תגיות ===
    # ============================================

    def mask_tags(self, text):
        """מחליפה תגיות קובץ/עמוד/תמונה בפלייסהולדרים מוגנים"""
        placeholders = {}
        
        def replace_callback(match):
            key = f"__PROTECTED_TAG_{len(placeholders)}__"
            placeholders[key] = match.group(0)
            return key

        # תבנית שתופסת את כל התגיות הרגישות
        pattern = r'(\[(?:FILE|PAGE|IMG):.*?\])'
        masked_text = re.sub(pattern, replace_callback, text)
        return masked_text, placeholders

    def unmask_tags(self, text, placeholders):
        """מחזירה את התגיות המקוריות במקום הפלייסהולדרים"""
        result = text
        for key, val in placeholders.items():
            result = result.replace(key, val)
        return result

    def start_auto_nikud(self):
        self.stop_worker_safely('nikud_worker')
        text = self.get_text_safe()
        if not text.strip(): return
        
        # 1. הסוואה (Masking)
        masked_text, self.active_placeholders = self.mask_tags(text)
        
        self.btn_nikud_auto.setText("מנקד...")
        self.btn_nikud_auto.setEnabled(False)
        
        current_dict = self.main_window.settings.get("nikud_dictionary", {})
        
        self.nikud_worker = NikudWorker(masked_text, current_dict)
        self.nikud_worker.finished.connect(self.on_nikud_success)
        self.nikud_worker.error.connect(self.on_nikud_error)
        self.nikud_worker.start()

    def on_nikud_success(self, vocalized_masked_text):
        self.btn_nikud_auto.setEnabled(True)
        self.btn_nikud_auto.setText("✨ ניקוד אוטומטי (Dicta)")
        self.main_window.progress_bar.setValue(100)
        
        # 2. חשיפת התגיות (Unmasking)
        vocalized_text = self.unmask_tags(vocalized_masked_text, self.active_placeholders)
        self.active_placeholders = {} # ניקוי

        original_text = self.get_text_safe()

        if original_text == vocalized_text:
            self.main_window.lbl_status.setText("הניקוד הסתיים. לא נמצאו שינויים.")
            self.set_text_safe(vocalized_text) 
            return

        self.main_window.lbl_status.setText("הניקוד הסתיים! אנא אשר שינויים.")

        # לוגיקת השוואה
        def tokenize(txt):
            return re.findall(r'\[IMG:.*?\]|[\u0590-\u05FF]+|[^\s\u0590-\u05FF]+', txt)

        orig_tokens = tokenize(original_text)
        new_tokens = tokenize(vocalized_text)
        
        changes_map = {} 
        all_orig_words = []
        
        matcher = difflib.SequenceMatcher(None, orig_tokens, new_tokens)
        
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == 'replace':
                segment_orig = orig_tokens[i1:i2]
                segment_new = new_tokens[j1:j2]
                for k in range(min(len(segment_orig), len(segment_new))):
                    o_word = segment_orig[k]
                    n_word = segment_new[k]
                    if any('א' <= c <= 'ת' for c in o_word) and "[IMG:" not in o_word:
                        all_orig_words.append(o_word)
                        if o_word != n_word:
                            changes_map[o_word] = n_word
            elif tag == 'equal':
                for k in range(i1, i2):
                    w = orig_tokens[k]
                    if any('א' <= c <= 'ת' for c in w) and "[IMG:" not in w:
                        all_orig_words.append(w)

        word_counts = Counter(all_orig_words)
        final_list = []
        for orig, new in changes_map.items():
            count = word_counts[orig]
            final_list.append((orig, new, count))
        final_list.sort(key=lambda x: x[2], reverse=True)

        if final_list:
            dialog = AnalysisDialog(final_list, self)
            dialog.pending_text = vocalized_text 
            dialog.exec_()
        else:
            self.main_window.lbl_status.setText("לא נמצאו שינויים מהותיים במילים.")
            self.set_text_safe(vocalized_text)

    def run_dictionary_only(self):
        """
        עובר על הטקסט ומחליף רק מילים שקיימות במילון האישי.
        גרסה מוגנת לתגיות.
        """
        current_dict = self.main_window.settings.get("nikud_dictionary", {})
        metadata = self.main_window.settings.get("nikud_metadata", {})
        
        if not current_dict:
            QMessageBox.information(self, "המילון ריק", "אין מילים במילון האישי ליישום.")
            return

        self.main_window.lbl_status.setText("מחיל ניקוד לפי מילון בלבד...")
        QApplication.processEvents()

        text = self.get_text_safe()
        
        # 1. הסוואה
        masked_text, placeholders = self.mask_tags(text)
        
        sorted_keys = sorted(current_dict.keys(), key=len, reverse=True)
        processed_text = masked_text
        count = 0

        for base_word in sorted_keys:
            target_word = current_dict[base_word]
            is_exact = False
            if base_word in metadata:
                 if metadata[base_word].get('match_type') == 'exact':
                     is_exact = True

            if is_exact:
                pattern = r'(?<![\w\u0590-\u05FF])' + re.escape(base_word) + r'(?![\w\u0590-\u05FF])'
                processed_text, n = re.subn(pattern, target_word, processed_text)
                count += n
            else:
                if base_word in processed_text:
                    pattern = re.escape(base_word)
                    processed_text, n = re.subn(pattern, target_word, processed_text)
                    count += n

        # 2. חשיפה
        final_text = self.unmask_tags(processed_text, placeholders)

        if count > 0:
            self.set_text_safe(final_text)
            self.main_window.lbl_status.setText(f"בוצע! הוחלפו {count} מופעים מתוך המילון.")
            QMessageBox.information(self, "סיום", f"התהליך הסתיים.\nבוצעו {count} החלפות לפי המילון.")
        else:
            self.main_window.lbl_status.setText("לא נמצאו מילים מהמילון בטקסט.")
            QMessageBox.information(self, "סיום", "לא נמצאו בטקסט מילים שמופיעות במילון שלך.")

    def on_nikud_error(self, msg):
        self.btn_nikud_auto.setEnabled(True)
        self.btn_nikud_auto.setText("✨ הוסף ניקוד אוטומטי (Dicta)")
        self.main_window.lbl_status.setText("שגיאה בניקוד")
        QMessageBox.warning(self, "שגיאה", msg)

    def set_text_direction(self, direction):
        self.editor.setLayoutDirection(direction)
        cursor = self.editor.textCursor()
        block_format = cursor.blockFormat()
        block_format.setLayoutDirection(direction)
        cursor.setBlockFormat(block_format)
        self.editor.setTextCursor(cursor)
        self.editor.setFocus()

    def search_text(self):
        search_str = self.input_search.text()
        if not search_str: return
        found = self.editor.find(search_str)
        if not found:
            cursor = self.editor.textCursor()
            cursor.movePosition(QTextCursor.Start)
            self.editor.setTextCursor(cursor)
            found = self.editor.find(search_str)
            if not found:
                self.main_window.lbl_status.setText(f"❌ הביטוי '{search_str}' לא נמצא.")
            else:
                self.main_window.lbl_status.setText(f"🔍 נמצא: '{search_str}' (חיפוש מההתחלה)")
        else:
             self.main_window.lbl_status.setText(f"🔍 נמצא: '{search_str}'")

    def update_char_count(self):
        text = self.editor.toPlainText()
        count = len(text)
        self.main_window.lbl_status.setText(f"תווים: {count}")

    def sync_pdf_to_cursor(self):
        try:
            if not hasattr(self, 'pdf_viewer'): return
            cursor = self.editor.textCursor()
            position = cursor.position()
            start_pos = max(0, position - 3000)
            text_chunk = self.editor.toPlainText()[start_pos:position]
            
            # --- זיהוי קובץ ---
            file_matches = re.findall(r'\[FILE:(.*?)\]', text_chunk)
            if file_matches:
                raw_path = file_matches[-1]
                # ניקוי לכלוך (RTL) ותיקון רווחים
                clean_path = raw_path.replace('\u200e', '').replace('\u200f', '').replace('\u202a', '').replace('\u202c', '').strip()
                clean_path = clean_path.replace('. pdf', '.pdf')
                
                current_loaded = os.path.normpath(self.file_path) if self.file_path else ""
                
                # נרמול למק (NFC/NFD)
                target_candidates = [
                    os.path.normpath(clean_path),
                    unicodedata.normalize('NFC', clean_path),
                    unicodedata.normalize('NFD', clean_path)
                ]
                
                found_path = None
                for candidate in target_candidates:
                    if os.path.exists(candidate):
                        found_path = candidate
                        break
                        
                if found_path and current_loaded != os.path.normpath(found_path):
                    print(f"[SYNC] Switching PDF to: {found_path}")
                    self.file_path = found_path
                    self.pdf_viewer.load_pdf(found_path)
                    self.lbl_file.setText(os.path.basename(found_path))
                    if found_path not in self.file_paths:
                        self.file_paths.append(found_path)
            
            # --- זיהוי עמוד ---
            page_matches = re.findall(r'\[PAGE:(\d+)\]', text_chunk)
            if page_matches:
                target_page = int(page_matches[-1])
                if self.pdf_viewer.current_page != target_page:
                    self.pdf_viewer.show_page(target_page)
            elif not page_matches and not file_matches:
                start_page = 1
                if self.input_start.text().strip().isdigit():
                    start_page = int(self.input_start.text())
                if self.pdf_viewer.current_page != start_page:
                    self.pdf_viewer.show_page(start_page)
        except Exception as e:
            print(f"[SYNC ERROR]: {e}")

    def get_text_safe(self):
        doc = self.editor.document()
        full_text = ""
        block = doc.begin()
        while block.isValid():
            iter_ = block.begin()
            if iter_.atEnd(): full_text += "\n"
            while not iter_.atEnd():
                fragment = iter_.fragment()
                if fragment.isValid():
                    char_format = fragment.charFormat()
                    if char_format.isImageFormat():
                        img_fmt = char_format.toImageFormat()
                        name = img_fmt.name()
                        full_text += f"\n[IMG:{name}]\n"
                    else:
                        full_text += fragment.text()
                iter_ += 1
            if not full_text.endswith("\n") and not full_text.endswith("]\n"):
                 full_text += "\n"
            block = block.next()
        return full_text.strip()

    def set_text_safe(self, text_with_tags):
        print(f"[DEBUG] set_text_safe called. Length: {len(text_with_tags)}")
        self.editor.clear()
        cursor = self.editor.textCursor()
        cursor.setBlockFormat(QTextBlockFormat())
        cursor.setCharFormat(QTextCharFormat())
        
        parts = re.split(r'(\[IMG:.*?\])', text_with_tags)
        
        for part in parts:
            if part.startswith("[IMG:") and part.endswith("]"):
                path = part[5:-1]
                if os.path.exists(path):
                    cursor.insertBlock()
                    img_fmt = QTextImageFormat()
                    img_fmt.setName(path)
                    img_fmt.setWidth(550) 
                    cursor.insertImage(img_fmt)
                    cursor.insertBlock()
                else:
                    cursor.insertText(f"[תמונה חסרה: {os.path.basename(path)}]")
            else:
                if part: cursor.insertText(part)
                
        self.editor.moveCursor(QTextCursor.Start)

    def stop_worker_safely(self, worker_attr_name):
        if hasattr(self, worker_attr_name):
            worker = getattr(self, worker_attr_name)
            if worker and worker.isRunning():
                worker.quit()
                worker.wait(2000)
                if worker.isRunning():
                    worker.terminate()
                    worker.wait()

    def open_advanced_import(self):
        start_dir = ""
        # קביעת תיקייה חכמה
        if self.file_path: start_dir = os.path.dirname(self.file_path)
        elif self.file_paths: start_dir = os.path.dirname(self.file_paths[0])
        
        dialog = AdvancedImportDialog(start_dir, self) 
        
        if dialog.exec_() == QDialog.Accepted:
            if dialog.result_text:
                self.editor.setPlainText(dialog.result_text)
                self.main_window.lbl_status.setText("הייבוא המתקדם הושלם בהצלחה!")
                
                imported_files = getattr(dialog, 'files_list', [])
                if imported_files and len(imported_files) > 0:
                    self.file_paths = imported_files
                    self.file_path = imported_files[0]
                    if hasattr(self, 'pdf_viewer'):
                        self.pdf_viewer.load_pdf(self.file_path)
                    self.lbl_file.setText(os.path.basename(self.file_path))
                    self.sync_pdf_to_cursor()
            else:
                self.main_window.lbl_status.setText("הייבוא הסתיים ללא טקסט.")

    def open_split_dialog(self):
        current_name = self.input_filename.text()
        dialog = SplitExportDialog(current_name, self)
        if dialog.exec_() == QDialog.Accepted:
            data = dialog.get_data()
            self.start_split_export_process(data)
         
    def start_split_export_process(self, data):
        print("\n=== [DEBUG] Starting Split Process (Fixed Logic) ===")
        full_text = self.editor.toPlainText()
        split_word = data["split_word"]
        base_filename = data["filename"] or "Audio"
        use_number = data["use_number"]
        
        if not full_text.strip():
            QMessageBox.warning(self, "שגיאה", "העורך ריק.")
            return

        # 1. יצירת ה-Regex
        if use_number:
            pattern = rf'(?={re.escape(split_word)}\s+\d+)'
        else:
            pattern = rf'(?={re.escape(split_word)})'
            
        # 2. פיצול
        raw_segments = re.split(pattern, full_text)
        segments = [s for s in raw_segments if s.strip()] # סינון סגמנטים ריקים לגמרי

        self.batch_queue = []
        
        # בחירת נתיב
        out_dir = ""
        if hasattr(self, 'file_paths') and self.file_paths:
            out_dir = os.path.dirname(self.file_paths[0])
        elif hasattr(self, 'file_path') and self.file_path:
            out_dir = os.path.dirname(self.file_path)
        if not out_dir: out_dir = os.path.expanduser("~/Documents")
        
        # === ניהול זיכרון (State Tracking) ===
        
        # קובץ התחלתי
        last_seen_file_tag = None
        if self.file_path:
            abs_p = os.path.abspath(self.file_path)
            last_seen_file_tag = f"[FILE:{abs_p}]"

        # עמוד התחלתי (למשל 1, או מה שנקבע בתיבה למעלה)
        current_tracker_page = "1"
        if self.input_start.text().strip().isdigit():
             current_tracker_page = self.input_start.text().strip()

        print(f"[DEBUG] Initial Page Tracker: {current_tracker_page}")

        valid_counter = 0

        for i, segment_text in enumerate(segments):
            print(f"\n--- Processing Segment {i} ---")
            
            # === שלב קריטי 1: שמירת המצב הנוכחי לשימוש בסגמנט הזה ===
            # זה העמוד שצריך להופיע בתחילת הקטע הנוכחי, לפני שמעדכנים אותו לפי מה שכתוב בפנים
            start_page_for_this_segment = current_tracker_page
            
            # === שלב 2: סריקה ועדכון הזיכרון לעתיד (לסגמנט הבא) ===
            
            # עדכון קובץ
            file_match = re.search(r'\[FILE:(.*?)\]', segment_text)
            if file_match:
                last_seen_file_tag = file_match.group(0)
            
            # עדכון עמוד: אם יש עמודים בתוך הטקסט, העמוד האחרון יהיה נקודת ההתחלה של הקטע הבא
            page_matches = re.findall(r'\[PAGE:(\d+)\]', segment_text)
            if page_matches:
                current_tracker_page = page_matches[-1] # עדכון לשימוש עתידי
                print(f"[DEBUG] Pages found inside text: {page_matches}. Next segment will start at: {current_tracker_page}")
            else:
                print(f"[DEBUG] No pages found inside. Next segment continues from: {current_tracker_page}")

            # === שלב 3: בדיקה אם הסגמנט הוא "תוכן" או סתם תגיות ===
            clean_content = re.sub(r'\[(?:FILE|PAGE|IMG):.*?\]', '', segment_text).strip()
            
            if not clean_content:
                print(f"[DEBUG] Skipping empty segment. (Context updated: Page {start_page_for_this_segment} -> {current_tracker_page})")
                continue

            # === שלב 4: בניית הטקסט והזרקת התגיות ===
            final_segment_text = segment_text
            
            # הזרקת תגית עמוד: משתמשים ב-start_page_for_this_segment (הישן) ולא ב-tracker המעודכן!
            if not re.match(r'^\s*\[PAGE:', segment_text):
                injected_page = f"[PAGE:{start_page_for_this_segment}]"
                print(f"[DEBUG] Injecting start page: {injected_page}")
                final_segment_text = f"{injected_page}\n{final_segment_text}"
            
            # הזרקת תגית קובץ
            if not re.match(r'^\s*\[FILE:', segment_text) and last_seen_file_tag:
                 final_segment_text = f"{last_seen_file_tag}\n{final_segment_text}"

            # === שלב 5: שמירת הקובץ ===
            clean_first_line = clean_content.split('\n')[0].strip()
            safe_name_start = re.sub(r'[\\/*?:"<>|]', "", clean_first_line)
            name_words = safe_name_start.split()[:4]
            short_name = " ".join(name_words)
            
            if valid_counter == 0 and not clean_first_line.startswith(split_word):
                final_name = f"{base_filename}_Start"
            else:
                final_name = f"{base_filename}_{short_name}"
            
            final_name = final_name.replace(" ", "_")
            full_path = os.path.join(out_dir, f"{final_name}.mp3")
            
            self.batch_queue.append({
                "text": final_segment_text,
                "path": full_path,
                "index": valid_counter + 1,
                "total": 0 
            })
            valid_counter += 1
            
        # סיום
        total_items = len(self.batch_queue)
        for item in self.batch_queue:
            item['total'] = total_items

        self.total_batch_size = total_items
        
        if self.total_batch_size > 0:
            self.run_next_batch_task()
        else:
            QMessageBox.warning(self, "שגיאה", "לא נותר טקסט לייצוא לאחר הסינון.")


    def run_next_batch_task(self):
        if not hasattr(self, 'batch_queue') or not self.batch_queue:
            self.main_window.lbl_status.setText("✅ כל הקבצים בתור עובדו בהצלחה!")
            self.btn_convert.setEnabled(True)
            self.btn_split_export.setEnabled(True)
            self.main_window.progress_bar.setValue(100)

            # === רענון רשימת הפרויקטים ומעבר לטאב הנגן ===
            if hasattr(self.main_window, 'tab_karaoke'):
                try:
                    self.main_window.tab_karaoke.refresh_file_list()
                    self.main_window.tabs.setCurrentWidget(self.main_window.tab_karaoke)
                    print("[DEBUG] Project list refreshed and switched to karaoke tab.")
                except Exception as e:
                    print(f"[ERROR] Failed to refresh project list: {e}")
            # ==================================

            QMessageBox.information(self, "סיום", f"הסתיים עיבוד של {self.total_batch_size} קבצים.")
            return
            
        task = self.batch_queue.pop(0)
        self.current_batch_task = task
        self.main_window.lbl_status.setText(f"מעבד חלק {task['index']}/{task['total']}: {os.path.basename(task['path'])}...")
        self.main_window.progress_bar.setValue(0)
        
        self.btn_convert.setEnabled(False)
        self.btn_split_export.setEnabled(False)
        
        voice_key = "he-IL-HilaNeural"
        if hasattr(self, 'combo_he'):
            voice_name = self.combo_he.currentText()
            voice_key = self.he_voices.get(voice_name, "he-IL-HilaNeural")
        
        rate = self.combo_speed.currentText()
        current_dict = self.main_window.settings.get("nikud_dictionary", {})
        
        # === התיקון: ניקוי תגיות לפני שליחה ל-TTS ===
        text_for_tts = self.clean_tags_for_tts(task['text'])
        # ============================================

        dual_mode = self.chk_dual.isChecked() if hasattr(self, 'chk_dual') else False
        self.tts_worker = TTSWorker(text_for_tts, task['path'], voice_key, rate, "+0%", current_dict, parent=self, dual_mode=dual_mode)
        self.tts_worker.finished_success.connect(self.on_batch_part_finished)
        self.tts_worker.progress_update.connect(self.main_window.progress_bar.setValue)
        self.tts_worker.error.connect(self.on_tts_error)
        self.tts_worker.start()
         
    def on_batch_part_finished(self, mp3_path, skipped):
        print(f"[DEBUG] Finished part: {mp3_path}")
        self.on_tts_finished(mp3_path, skipped, is_batch=True)
        QTimer.singleShot(1000, self.run_next_batch_task)

    def extract_pages_from_text(self, text):
        """מחלץ את מספרי העמודים (מינימום ומקסימום) מתוך טקסט נתון"""
        matches = re.findall(r'\[PAGE:(\d+)\]', text)
        if matches:
            pages = [int(p) for p in matches]
            return min(pages), max(pages)
        return None, None
         
    def create_sliced_pdf(self, output_filename, start_page=None, end_page=None, source_pdf=None):
        """
        יוצר קובץ PDF הכולל רק את העמודים הרלוונטיים.
        source_pdf - נתיב ל-PDF מקור (אם None, משתמש ב-self.file_path).
        אם start_page/end_page לא מסופקים, משתמש בערכים מה-GUI.
        """
        # קביעת קובץ מקור
        pdf_source = source_pdf if source_pdf and os.path.exists(source_pdf) else None
        if not pdf_source:
            if hasattr(self, 'file_path') and self.file_path and os.path.exists(self.file_path):
                pdf_source = self.file_path
            else:
                return None

        try:
            # קביעת טווח העמודים (אם לא סופק, לוקחים מהממשק)
            if start_page is None:
                try:
                    start_page = int(self.input_start.text())
                except: start_page = 1

            if end_page is None:
                try:
                    end_page = int(self.input_end.text())
                except: end_page = 1000

            reader = PyPDF2.PdfReader(pdf_source)
            writer = PyPDF2.PdfWriter()

            total_pages = len(reader.pages)

            # התאמה לאינדקס 0-based
            start_idx = max(0, start_page - 1)
            end_idx = min(total_pages, end_page)

            if start_idx >= end_idx:
                return None

            for i in range(start_idx, end_idx):
                writer.add_page(reader.pages[i])

            with open(output_filename, "wb") as f:
                writer.write(f)

            print(f"[PDF] Created sliced PDF: {output_filename} (pages {start_page}-{end_page} from {os.path.basename(pdf_source)})")
            return output_filename

        except Exception as e:
            print(f"[ERROR] Failed to slice PDF: {e}")
            return None