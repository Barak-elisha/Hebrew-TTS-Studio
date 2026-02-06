import sys
import os
import io
import asyncio
import re
import json
import edge_tts
import tempfile
import PyPDF2
import difflib # חובה בשביל לתקן את הבאג של המילים הלא תואמות
import requests
import numpy as np
from pdf2image import convert_from_path
import shutil
import unicodedata
import hashlib
import time  # וודא שביצעת import time למעלה בקובץ
import asyncio
import random
from PIL import Image as PILImage
import concurrent.futures
from collections import Counter
from datetime import datetime
from pydub import AudioSegment, silence
from PyQt5.QtWidgets import QMenu, QAction, QSplitter, QScrollArea, QLabel, QSizePolicy  # וודא שזה מופיע ברשימת הייבוא מ-QtWidgets
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
from PyQt5.QtWidgets import QGridLayout, QAbstractItemView # וודא שזה קיים ב-import
from PyQt5.QtGui import QFont, QTextCursor, QTextCharFormat, QIcon, QTextBlockFormat, QKeyEvent, QColor, QTextImageFormat, QImage, QPixmap, QKeySequence

from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QTextEdit, QFileDialog, QLabel, QComboBox, 
                             QProgressBar, QLineEdit, QMessageBox, QFrame, QCheckBox, QGroupBox, 
                             QTabWidget, QSpinBox, QTableWidget, QTableWidgetItem, QHeaderView, 
                             QDialog, QInputDialog, QSlider, QListWidget, QListWidgetItem, QColorDialog,
                             QStyleOptionSlider, QStyle, QShortcut, QTreeWidget, QTreeWidgetItem) # <-- הוספנו את השניים האלו בסוף
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QUrl, QBuffer, QIODevice, QByteArray, QTime, QTimer, QEvent, QObject
from PyQt5.QtGui import QFont, QTextCursor, QTextCharFormat, QIcon, QTextBlockFormat
from src.workers.tts_worker import TTSWorker, AudioPreviewWorker
from src.workers.nikud_worker import NikudWorker
from src.utils.text_tools import remove_nikud, advanced_cleanup
from src.ui.dialogs.split_dialog import SplitExportDialog
from src.ui.tabs.karaoke_tab import KaraokeTab
from src.ui.widgets.pdf_viewer import PDFViewerWidget
from src.utils.settings_manager import SettingsManager
from src.workers.telegram_worker import TelegramWorker
from src.ui.widgets.text_editor import NikudTextEdit
from src.ui.dialogs.nikud_editor import NikudEditorDialog
from src.ui.dialogs.compare_dialog import AnalysisDialog
from src.utils.vision_tools import crop_illustration_only
from src.ui.widgets.nikud_table import PasteableTableWidget
from src.ui.widgets.errors_table import ErrorsTableWidget
from src.ui.widgets.jump_slider import JumpSlider
from src.ui.dialogs.advanced_import import ProgressFileReader, AdvancedImportDialog


class ProcessingWorker(QObject):
    finished = pyqtSignal()
    progress = pyqtSignal(str)  # חיווי טקסטואלי
    percent = pyqtSignal(int)   # חיווי למד התקדמות

    def process_files(self, files):
        for i, file in enumerate(files):
            # כאן נכנס הלוגיקה של ה-Trim וה-Decode
            msg = f"Processing sentence {i}..."
            self.progress.emit(msg) # שולח עדכון לממשק מבלי לעצור
            
            # ביצוע העיבוד בפועל...
            
            self.percent.emit(int((i+1)/len(files)*100))
        self.finished.emit()

# --- קובץ הגדרות ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")


# --- ברירת מחדל ---
DEFAULT_SETTINGS = {
    "pause_lang": 80,
    "pause_hyphen": 450,
    "pause_comma": 250,
    "pause_sentence": 600,
    "max_concurrent": 50,
    "custom_symbols": {"***": 1000},
    "nikud_dictionary": {}
}


    







# --- דיאלוג השוואה והשמעה ---
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


class HebrewTTSStudio(QMainWindow):

    def open_split_dialog(self):
        """פותח את חלון ההגדרות לפיצול"""
        # לוקח את שם הקובץ הנוכחי כברירת מחדל
        current_name = self.input_filename.text()
        
        dialog = SplitExportDialog(current_name, self)
        if dialog.exec_() == QDialog.Accepted:
            data = dialog.get_data()
            # קריאה לפונקציית העיבוד עם הנתונים מהדיאלוג
            self.start_split_export_process(data)

    def load_initial_values_to_ui(self):
        """מעדכנת את שדות הממשק בערכים שנטענו מההגדרות"""
        try:
            # עדכון שדות טלגרם
            self.input_tg_token.setText(self.settings.get("tg_token", ""))
            self.input_tg_chat_id.setText(self.settings.get("tg_chat_id", ""))
            
            # עדכון ערכי ה-SpinBoxes (השהיות)
            self.spin_lang.setValue(self.settings.get("pause_lang", 1000))
            self.spin_comma.setValue(self.settings.get("pause_comma", 400))
            self.spin_sentence.setValue(self.settings.get("pause_sentence", 600))
            
            # עדכון כמות תהליכים מקבילים
            if hasattr(self, 'spin_concurrent'):
                self.spin_concurrent.setValue(self.settings.get("max_concurrent", 15))
                
            print("[DEBUG] UI initial values loaded from settings")
        except Exception as e:
            print(f"[DEBUG] Note: Some UI elements were not ready during initial load: {e}")
    
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
            self.lbl_status.setText("✅ כל הקבצים בתור עובדו בהצלחה!")
            self.btn_convert.setEnabled(True)
            self.btn_split_export.setEnabled(True)
            self.progress_bar.setValue(100)
            QMessageBox.information(self, "סיום", f"הסתיים עיבוד של {self.total_batch_size} קבצים.")
            return

        # שליפת המשימה הבאה
        task = self.batch_queue.pop(0)
        
        self.current_batch_task = task
        self.lbl_status.setText(f"מעבד חלק {task['index']}/{task['total']}: {os.path.basename(task['path'])}...")
        self.progress_bar.setValue(0)
        
        # נעילת כפתורים
        self.btn_convert.setEnabled(False)
        self.btn_split_export.setEnabled(False)

        # הרצת ה-Worker (כמו בייצוא רגיל)
        voice_key = "he-IL-HilaNeural"
        if hasattr(self, 'combo_he'): voice_key = self.combo_he.currentText()
        rate = self.combo_speed.currentText()
        current_dict = self.settings.get("nikud_dictionary", {})

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
        self.tts_worker.progress_update.connect(self.progress_bar.setValue)
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

    def run_dictionary_only(self):
        """
        עובר על הטקסט ומחליף רק מילים שקיימות במילון האישי.
        כל שאר הטקסט נשאר ללא ניקוד/שינוי.
        """
        # 1. בדיקה שיש מילון
        current_dict = self.settings.get("nikud_dictionary", {})
        metadata = self.settings.get("nikud_metadata", {})
        
        if not current_dict:
            QMessageBox.information(self, "המילון ריק", "אין מילים במילון האישי ליישום.")
            return

        self.lbl_status.setText("מחיל ניקוד לפי מילון בלבד...")
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
            self.lbl_status.setText(f"בוצע! הוחלפו {count} מופעים מתוך המילון.")
            QMessageBox.information(self, "סיום", f"התהליך הסתיים.\nבוצעו {count} החלפות לפי המילון.")
        else:
            self.lbl_status.setText("לא נמצאו מילים מהמילון בטקסט.")
            QMessageBox.information(self, "סיום", "לא נמצאו בטקסט מילים שמופיעות במילון שלך.")

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

    def start_export_process(self):
        """
        מתחיל את תהליך הייצוא ל-MP3.
        הנתיב נגזר אוטומטית מתיקיית המקור ומשם הקובץ שהוגדר בשדה הטקסט.
        """
        text = self.editor.toPlainText()

        if not text.strip():
            QMessageBox.warning(self, "שגיאה", "אין טקסט לייצוא.")
            return

        # 1. קביעת תיקיית היעד (לפי קובץ המקור)
        out_dir = ""
        if hasattr(self, 'file_paths') and self.file_paths:
            out_dir = os.path.dirname(self.file_paths[0])
        elif hasattr(self, 'file_path') and self.file_path:
            out_dir = os.path.dirname(self.file_path)
        
        # גיבוי: אם לא נטען קובץ, נשמור בתיקיית המסמכים
        if not out_dir or not os.path.exists(out_dir):
            out_dir = os.path.expanduser("~/Documents")

        # 2. קביעת שם הקובץ (מהשדה בתוכנה)
        file_name = self.input_filename.text().strip()
        
        # אם המשתמש לא כתב כלום, ניצור שם ברירת מחדל עם תאריך
        if not file_name:
            base_name = "Audio_Output"
            if hasattr(self, 'file_paths') and self.file_paths:
                base_name = os.path.splitext(os.path.basename(self.file_paths[0]))[0]
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
            file_name = f"{base_name}_{timestamp}"

        # וידוא סיומת mp3
        if not file_name.lower().endswith(".mp3"):
            file_name += ".mp3"

        # הנתיב הסופי המלא
        save_path = os.path.join(out_dir, file_name)

        # עדכון ממשק והתחלת תהליך
        self.btn_convert.setEnabled(False)
        self.btn_convert.setText("מייצא... (מעבד)")
        
        self.progress_bar.setValue(0)
        self.lbl_status.setText(f"שומר לקובץ: {file_name}...")
        print(f"[DEBUG] Exporting to: {save_path}")

        # הגדרות לקריאה
        voice_key = "he-IL-HilaNeural"
        if hasattr(self, 'combo_he'): voice_key = self.combo_he.currentText()
        
        rate = self.combo_speed.currentText()
        current_dict = self.settings.get("nikud_dictionary", {})

        # יצירת ה-Worker
        self.tts_worker = TTSWorker(
            text=text,
            output_file=save_path,
            voice=voice_key,
            rate=rate,
            volume="+0%",
            dicta_dict=current_dict,
            parent=self
        )

        self.tts_worker.finished_success.connect(self.on_tts_finished)
        self.tts_worker.progress_update.connect(self.progress_bar.setValue)
        self.tts_worker.log_update.connect(self.lbl_status.setText)
        self.tts_worker.error.connect(self.on_tts_error)

        self.tts_worker.start()

    def on_tts_error(self, error_msg):
        # === תיקון: שימוש בשם הכפתור החדש ===
        self.btn_convert.setEnabled(True)
        self.btn_convert.setText("🚀 צור קובץ MP3")
        # ====================================
        
        self.progress_bar.setValue(0)
        self.lbl_status.setText("שגיאה בייצוא")
        QMessageBox.critical(self, "שגיאה בתהליך הייצוא", f"התרחשה שגיאה:\n{error_msg}")


    def on_tts_finished(self, mp3_path, skipped, is_batch=False):
        print(f"\n[DEBUG] === TTS FINISHED === Path: {mp3_path}")
        
        # חישוב הנתיב הסופי של ה-PDF (אותו שם כמו ה-MP3)
        target_pdf_path = mp3_path.replace(".mp3", ".pdf")
        pdf_created = False

        # --- שינוי: יצירת PDF חתוך ושמירתו כשם הקובץ הסופי ---
        if hasattr(self, 'file_path') and self.file_path and os.path.exists(self.file_path):
            # שימוש בפונקציית החיתוך כדי ליצור את הקובץ ישירות בתיקיית היעד
            # זה מחליף את ההעתקה של הקובץ המלא שהיתה כאן קודם
            created_file = self.create_sliced_pdf(target_pdf_path)
            
            if created_file:
                pdf_created = True
                print(f"[DEBUG] Sliced PDF saved permanently to: {target_pdf_path}")
            else:
                print("[DEBUG] Warning: Could not slice PDF. No PDF saved.")
        # -------------------------------------------------------

        self.progress_bar.setValue(100)
        
        # טעינה לנגן המקומי
        json_path = mp3_path.replace(".mp3", ".json")
        if os.path.exists(json_path):
            self.tab_karaoke.load_project(json_path, mp3_path)
            self.tabs.setCurrentWidget(self.tab_karaoke)

        # --- שליחה לטלגרם ---
        token = self.input_tg_token.text().strip()
        chat_id = self.input_tg_chat_id.text().strip()
        
        if token and chat_id:
            self.progress_bar.setValue(0)
            self.lbl_status.setText("מכין קבצים לשליחה...")
            
            files_to_send = []
            
            # 1. הוספת האודיו
            files_to_send.append((mp3_path, 'audio'))
            
            # 2. הוספת ה-PDF החתוך (אם נוצר בהצלחה)
            if pdf_created and os.path.exists(target_pdf_path):
                files_to_send.append((target_pdf_path, 'document'))
            
            self.tg_worker = TelegramWorker(token, chat_id, files_to_send)
            self.tg_worker.upload_progress.connect(self.progress_bar.setValue)
            self.tg_worker.log_update.connect(self.lbl_status.setText)
            self.tg_worker.finished.connect(self.on_telegram_upload_complete)
            
            # ביטול מחיקה אוטומטית - כי זה הקובץ הקבוע שלנו בתיקייה
            self.tg_worker.temp_pdf_to_delete = None 
            
            self.tg_worker.start()
            
            self.btn_convert.setText("מעלה לטלגרם...")
            self.btn_convert.setEnabled(False)
            
        else:
            self.on_telegram_upload_complete()

        if skipped:
            QMessageBox.warning(self, "הושלם עם דילוגים", f"דולגו {len(skipped)} משפטים.")

        if is_batch:
            print(f"[DEBUG] Batch part finished. Checking queue...")
            # לא מציגים MessageBox ולא משנים את כפתור Convert כאן
            # ה-run_next_batch_task יעשה את זה כשייגמר הכל
            return

        # --- הקוד המקורי לסיום בודד (נשאר למקרה של ייצוא רגיל) ---
        self.btn_convert.setEnabled(True)
        self.btn_convert.setText("🚀 צור קובץ MP3")
        
        if skipped:
            QMessageBox.warning(self, "הושלם עם דילוגים", f"דולגו {len(skipped)} משפטים.")

        if is_batch: return
        



    def on_telegram_upload_complete(self):
        self.lbl_status.setText("✅ כל הקבצים נשלחו לטלגרם!")
        self.btn_convert.setEnabled(True)
        self.btn_convert.setText("🚀 צור קובץ MP3")
        self.progress_bar.setValue(100)
        
        # ניקוי קובץ PDF חתוך זמני אם נוצר
        if hasattr(self, 'tg_worker') and hasattr(self.tg_worker, 'temp_pdf_to_delete'):
            f = self.tg_worker.temp_pdf_to_delete
            if f and os.path.exists(f):
                try:
                    os.remove(f)
                    print(f"[DEBUG] Deleted temp sliced PDF: {f}")
                except: pass


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
    
    def run_startup_sanitization(self):
        """
        ניקוי אגרסיבי בעלייה:
        1. מוחק מפתחות שהם רק פיסוק.
        2. מוחק מפתחות שמכילים את המילה "(שגיאה)".
        3. מוחק ערכים שמכילים את המילה "(שגיאה)".
        4. מוחק ספציפית את הפסיק אם הוא קיים כמפתח.
        """
        print("[STARTUP] Running AGGRESSIVE dictionary sanitization...")
        
        if "nikud_dictionary" not in self.settings:
            return

        dictionary = self.settings["nikud_dictionary"]
        metadata = self.settings.get("nikud_metadata", {})
        
        keys_to_delete = []

        # רשימת תווים ספציפיים למחיקה מיידית
        blacklist_chars = [",", ".", "-", "'", '"', ";", ":"]

        for key, val in dictionary.items():
            key_str = str(key).strip()
            val_str = str(val).strip()

            # בדיקה 1: האם המפתח הוא אחד מהתווים האסורים?
            is_blacklisted = key_str in blacklist_chars
            
            # בדיקה 2: האם המפתח עצמו מכיל את המילה "שגיאה"? (זה מה שקרה בתמונה)
            is_error_in_key = "(שגיאה)" in key_str or "(שגאולִיטֶריא)" in key_str

            # בדיקה 3: האם הערך מכיל שגיאה?
            is_error_in_val = "(שגיאה)" in val_str or "(שגאולִיטֶריא)" in val_str
            
            # בדיקה 4: האם המפתח הוא רק סימני פיסוק (ללא אותיות)?
            is_garbage = not any(c.isalnum() for c in key_str)

            if is_blacklisted or is_error_in_key or is_error_in_val or is_garbage:
                print(f"[SANITIZER] Marking for deletion: '{key}' -> '{val}'")
                keys_to_delete.append(key)

        # ביצוע המחיקה
        if keys_to_delete:
            for k in keys_to_delete:
                if k in dictionary: del dictionary[k]
                if k in metadata: del metadata[k]
            
            self.save_settings()
            print(f"[SANITIZER] DELETED {len(keys_to_delete)} bad entries successfully.")
            
            # רענון הטבלה אם התוכנה כבר רצה (לא תמיד רלוונטי ב-init אבל לא מזיק)
            if hasattr(self, 'refresh_dictionary_table'):
                try: self.refresh_dictionary_table()
                except: pass
        else:
            print("[SANITIZER] Dictionary looks clean.")

    def open_nikud_keyboard(self):
        if not hasattr(self, 'nikud_kb_window'):
            self.nikud_kb_window = NikudKeyboard(self)
        self.nikud_kb_window.show()
        # מביא את החלון לקדמה
        self.nikud_kb_window.raise_()
        self.nikud_kb_window.activateWindow()



    # --- פונקציות עזר לממשק (העתק את אלו לתוך HebrewTTSStudio) ---

    def update_char_count(self):
        """מעדכן את מספר התווים בשורת הסטטוס"""
        text = self.editor.toPlainText()
        count = len(text)
        # מעדכן את הסטטוס בר (למשל: "תווים: 120")
        self.lbl_status.setText(f"תווים: {count}")

    def set_text_direction(self, direction):
        """משנה את כיוון הטקסט באדיטור (RTL / LTR)"""
        self.editor.setLayoutDirection(direction)
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
                self.lbl_status.setText(f"❌ הביטוי '{search_str}' לא נמצא.")
            else:
                self.lbl_status.setText(f"🔍 נמצא: '{search_str}' (חיפוש מההתחלה)")
        else:
             self.lbl_status.setText(f"🔍 נמצא: '{search_str}'")

    # פונקציות לניהול טבלת הסמלים (במידה וחסרות לך גם אלו מההגדרות)
    def add_symbol_row(self):
        row = self.table_symbols.rowCount()
        self.table_symbols.insertRow(row)
    
    def delete_symbol_row(self):
        row = self.table_symbols.currentRow()
        if row >= 0:
            self.table_symbols.removeRow(row)
    # --- פונקציות חדשות לניהול טעויות ---

    # --- פונקציות לניהול טבלת טעויות ---

    def add_error_to_review(self, word):
        """הוספה חכמה לרשימת הטעויות (לחיצה ימנית באדיטור)"""
        print(f"[DEBUG] Adding error: '{word}'")
        errors_list = self.settings.get("nikud_errors", [])
        
        if word not in errors_list:
            errors_list.append(word)
            self.settings["nikud_errors"] = errors_list
            self.save_settings()
            
            # עדכון ויזואלי: הוספת שורה לטבלה הקיימת (בלי לטעון הכל מחדש)
            self.table_errors.add_row_ui(word)
            self.table_errors.scrollToBottom()
            
            self.lbl_status.setText(f"התווסף לטעויות: {word}")

    def remove_error_from_review(self, word):
        """הסרה חכמה מרשימת הטעויות (נקרא ע"י ביטול סימון בעורך)"""
        print(f"[DEBUG MAIN] Removing error requested: '{word}'")
        errors_list = self.settings.get("nikud_errors", [])
        
        # שלב 1: מחיקה מהנתונים (הקובץ והזיכרון)
        if word in errors_list:
            errors_list.remove(word)
            self.settings["nikud_errors"] = errors_list
            self.save_settings()
            print(f"[DEBUG MAIN] Removed '{word}' from settings.")
        else:
            print(f"[DEBUG MAIN] Warning: '{word}' not found in settings list.")

        # שלב 2: מחיקה ויזואלית מהטבלה (בעזרת הפונקציה החדשה והחכמה)
        if hasattr(self, 'table_errors'):
            # === התיקון כאן: שינוי השם ל-remove_row_by_text_smart ===
            self.table_errors.remove_row_by_text_smart(word)
        else:
            print("[DEBUG MAIN] Error: Table widget not found.")
            
        self.lbl_status.setText(f"הוסר מהטעויות: {word}")

    # =========================================================================
    # ניהול טבלת טעויות - גרסה מלאה (השמעה, עריכה, מחיקה)
    # =========================================================================

    def refresh_errors_table(self):
        """רענון טבלת הטעויות (משתמש בלוגיקה הפנימית של הטבלה החדשה)"""
        print("[DEBUG] Refreshing Errors Table...")
        
        # שליפת הרשימה מההגדרות
        errors_list = self.settings.get("nikud_errors", [])
        
        # קריאה לפונקציה המובנית של הטבלה שבונה הכל מאפס נכון
        self.table_errors.load_data(errors_list)

    def add_play_button_to_error_table(self, row, col, text):
        """מוסיף כפתור השמעה שעובד לטבלת הטעויות"""
        container = QWidget(); layout = QHBoxLayout(container); layout.setContentsMargins(0,0,0,0); layout.setAlignment(Qt.AlignCenter)
        btn = QPushButton("🔊")
        btn.setFixedSize(30, 25)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet("QPushButton { background-color: transparent; border: none; } QPushButton:hover { color: #27AE60; }")
        
        # שימוש בלמבדה שמפעילה את מנגנון ההשמעה הראשי
        btn.clicked.connect(lambda: self.play_preview_general(text))
        
        layout.addWidget(btn)
        self.table_errors.setCellWidget(row, col, container)

    def add_action_buttons_to_error_table(self, row, word_to_action):
        """מוסיף כפתורי פעולה לשורה בטבלת הטעויות"""
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(5)
        
        # כפתור עריכה/תיקון
        btn_fix = QPushButton("🛠️")
        btn_fix.setToolTip("תקן והעבר למילון")
        btn_fix.setStyleSheet("background-color: #27AE60; color: white; border-radius: 4px; font-weight: bold;")
        btn_fix.setFixedSize(30, 25)
        btn_fix.clicked.connect(lambda: self.open_fix_dialog(word_to_action))
        
        # כפתור מחיקה (Specific Delete)
        btn_del = QPushButton("🗑️")
        btn_del.setToolTip("מחק מרשימת הטעויות בלבד")
        btn_del.setStyleSheet("background-color: #C0392B; color: white; border-radius: 4px; font-weight: bold;")
        btn_del.setFixedSize(30, 25)
        
        # שימוש ב-word_to_action מבטיח שמוחקים את המילה הספציפית הזו
        btn_del.clicked.connect(lambda: self.delete_from_errors(word_to_action))
        
        layout.addWidget(btn_fix)
        layout.addWidget(btn_del)
        self.table_errors.setCellWidget(row, 4, container)

    def delete_from_errors(self, word):
        """מוחק מילה ספציפית מרשימת הטעויות"""
        print(f"[DEBUG] Deleting error: {word}")
        errors_list = self.settings.get("nikud_errors", [])
        
        if word in errors_list:
            errors_list.remove(word)
            self.settings["nikud_errors"] = errors_list
            self.save_settings()
            self.refresh_errors_table()
            self.lbl_status.setText(f"המילה '{word}' הוסרה מרשימת הטעויות.")
        else:
            print(f"[DEBUG] Error: Could not find '{word}' in list {errors_list}")

    def on_error_double_click(self, row, col):
        # אם לוחצים דאבל קליק על השורה, פותחים את העורך
        # המילה המנוקדת נמצאת בעמודה 1
        item = self.table_errors.item(row, 1) 
        if item:
            self.open_fix_dialog(item.text())

    # --- פונקציית השמעה כללית (לשימוש בכל הטבלאות) ---
    def play_preview_general(self, text):
        """מנגן אודיו מכל מקום בתוכנה"""
        if not text: return
        print(f"[DEBUG] Playing audio for: {text}")
        try:
            voice_name = self.combo_he.currentText()
            voice_id = self.he_voices.get(voice_name, "he-IL-AvriNeural")
            speed = self.combo_speed.currentText()
            
            unique_str = f"{text}_{voice_id}_{speed}"
            cache_key = hashlib.md5(unique_str.encode('utf-8')).hexdigest()
            
            self.general_audio_worker = AudioPreviewWorker(cache_key, text, voice_id, speed)
            self.general_audio_worker.finished_data.connect(self.on_general_audio_ready)
            self.general_audio_worker.start()
        except Exception as e:
            print(f"Audio Error: {e}")

    def on_general_audio_ready(self, key, data):
        try:
            path = os.path.join(tempfile.gettempdir(), "gen_preview.mp3")
            with open(path, "wb") as f: f.write(data)
            
            if not hasattr(self, 'gen_player'): self.gen_player = QMediaPlayer()
            self.gen_player.setMedia(QMediaContent(QUrl.fromLocalFile(path)))
            self.gen_player.play()
        except: pass

    # הוסף את פונקציית העזר הזו במחלקה הראשית אם אין לך אותה
    # בתוך HebrewTTSStudio

    def clean_nikud_from_string(self, text):
        """מנקה ניקוד ופיסוק ליצירת מפתח נקי"""
        if not text: return ""
        normalized = unicodedata.normalize('NFD', text)
        # משאיר רק אותיות ומספרים (בלי ניקוד ובלי פיסוק)
        clean_chars = [c for c in normalized if not unicodedata.combining(c) and (c.isalnum() or c.isspace())]
        clean = unicodedata.normalize('NFC', "".join(clean_chars)).strip()
        # print(f"[DEBUG-CLEAN] Input: '{text}' -> Output: '{clean}'") # דיבאג אופציונלי
        return clean

    def open_fix_dialog(self, original_word_with_nikud):
        """
        פותח דיאלוג לתיקון מילה מטבלת הטעויות.
        """
        print(f"\n[DEBUG] === Opening Fix Dialog ===")
        print(f"[DEBUG] Input Word (From Error Table): '{original_word_with_nikud}'")
        
        # הדפסת ייצוג Hex כדי לראות אם יש תווים נסתרים
        hex_repr = original_word_with_nikud.encode('utf-8').hex()
        print(f"[DEBUG] Hex representation: {hex_repr}")

        dialog = NikudEditorDialog(original_word_with_nikud, self)
        # ברירת מחדל: הוספה למילון מסומנת ונעולה
        dialog.chk_add_to_dict.setChecked(True)
        dialog.chk_add_to_dict.setEnabled(False) 
        
        if dialog.exec_() == QDialog.Accepted:
            # 1. הערך המתוקן
            corrected_word = dialog.get_text().strip()
            match_index = dialog.combo_match_type.currentIndex()
            print(f"[DEBUG] User corrected to: '{corrected_word}'")
            
            # 2. יצירת מפתח למילון (המילה המקורית ללא ניקוד)
            # אם המילה בטעות הייתה "אוֹטוֹאִימוּנִיוֹת", המפתח צריך להיות "אוטואימוניות"
            dict_key = self.clean_nikud_from_string(original_word_with_nikud)
            
            print(f"[DEBUG] Generated Dictionary Key (No Nikud): '{dict_key}'")
            
            if not dict_key:
                print("[ERROR] Dictionary Key is empty! Aborting add.")
                return

            # 3. הוספה למילון
            self.add_word_to_dictionary_logic(dict_key, corrected_word, match_index)
            
            # 4. הסרה מרשימת הטעויות
            errors_list = self.settings.get("nikud_errors", [])
            if original_word_with_nikud in errors_list:
                errors_list.remove(original_word_with_nikud)
                self.settings["nikud_errors"] = errors_list
                self.save_settings()
                print(f"[DEBUG] Removed '{original_word_with_nikud}' from error list.")
            else:
                print(f"[DEBUG] Warning: Could not find '{original_word_with_nikud}' in error list to remove.")

            # 5. רענון
            self.refresh_errors_table()
            self.refresh_dictionary_table()
            
            self.lbl_status.setText(f"✅ תוקן: {dict_key} -> {corrected_word}")

    def add_word_to_dictionary_logic(self, key, value, match_index):
        """מבצעת שמירה פיזית למילון ולקובץ"""
        print(f"[DEBUG] >>> add_word_to_dictionary_logic STARTED")
        print(f"[DEBUG] Key: '{key}' | Value: '{value}'")
        
        match_type = "exact" if match_index == 1 else "partial"
        
        # 1. עדכון בזיכרון
        self.settings["nikud_dictionary"][key] = value.strip()
        
        if "nikud_metadata" not in self.settings:
            self.settings["nikud_metadata"] = {}
            
        self.settings["nikud_metadata"][key] = {
            "date": datetime.now().strftime("%d/%m/%Y"),
            "match_type": match_type
        }
        
        # 2. שמירה לקובץ
        try:
            self.save_settings()
            print("[DEBUG] >>> Save settings called successfully.")
        except Exception as e:
            print(f"[DEBUG] >>> ERROR SAVING SETTINGS: {e}")


    def add_manual_word(self):
        """
        תהליך הוספה מהיר:
        1. המשתמש מקליד מילה.
        2. המערכת מנקדת אותה אוטומטית.
        3. המערכת מוסיפה למילון וגוללת אליה לבדיקה.
        """
        # 1. בקשת המילה מהמשתמש
        word, ok = QInputDialog.getText(self, "הוספה מהירה", "הקלד את המילה (ללא ניקוד):")
        
        if ok and word:
            clean_word = word.strip()
            if not clean_word: return

            self.lbl_status.setText(f"מנקד את '{clean_word}' מול שרתי דיקטה...")
            
            # 2. שליחה לניקוד ברקע
            # אנו שומרים את ה-Worker במשתנה מחלקה כדי שלא יימחק מהזיכרון
            self.manual_nikud_worker = NikudWorker(clean_word)
            
            # חיבור לפונקציית ההמשך
            self.manual_nikud_worker.finished.connect(lambda res: self.finish_manual_add(clean_word, res))
            self.manual_nikud_worker.start()

    def finish_manual_add(self, base_word, vocalized_result):
        """פונקציית ההמשך: מקבלת את הניקוד, שומרת וגוללת"""
        print(f"[DEBUG] Manual Add: Received '{vocalized_result}' for '{base_word}'")
        
        # 3. הוספה למילון ולטבלה
        # אנו משתמשים ב-partial כברירת מחדל, ו-True כדי לעדכן את הטבלה
        self.add_or_update_word(base_word, vocalized_result, "partial", update_table_ui=True)
        
        # 4. גלילה והדגשה לבדיקה
        # אנחנו מחפשים את המפתח הנקי בטבלה כדי לקפוץ אליו
        key = self.clean_nikud_from_string(base_word)
        self.highlight_word_in_table(key)
        
        self.lbl_status.setText(f"✅ המילה נוספה: {base_word} -> {vocalized_result}")
        
        # אופציונלי: פוקוס לטבלה כדי שתוכל מיד לנווט עם חצים
        self.table_nikud.setFocus()


    def refresh_errors_table(self):
        """טוען מחדש את טבלת הטעויות"""
        self.table_errors.setRowCount(0)
        errors_list = self.settings.get("nikud_errors", [])
        
        for i, word in enumerate(errors_list):
            self.table_errors.insertRow(i)
            
            # מילה
            item_word = QTableWidgetItem(word)
            item_word.setTextAlignment(Qt.AlignCenter)
            self.table_errors.setItem(i, 0, item_word)
            
            # כפתור השמעה
            self.add_play_button_to_table(self.table_errors, i, 1, word)
            
            # תאריך (היום)
            date_item = QTableWidgetItem(datetime.now().strftime("%d/%m/%Y"))
            date_item.setTextAlignment(Qt.AlignCenter)
            self.table_errors.setItem(i, 2, date_item)
            
            # כפתור תיקון
            btn_fix = QPushButton("🛠️ תקן והעבר למילון")
            btn_fix.setStyleSheet("background-color: #27AE60; color: white; border-radius: 4px;")
            btn_fix.clicked.connect(lambda _, w=word: self.open_fix_dialog(w))
            
            container = QWidget()
            layout = QHBoxLayout(container)
            layout.setContentsMargins(2, 2, 2, 2)
            layout.addWidget(btn_fix)
            self.table_errors.setCellWidget(i, 3, container)

    def on_error_double_click(self, row, col):
        """טיפול בדאבל קליק על שורה בטבלת הטעויות"""
        item = self.table_errors.item(row, 0)
        if item:
            self.open_fix_dialog(item.text())
    
    def open_fix_dialog(self, original_word_with_nikud):
        """פותח חלון תיקון לטעות"""
        print(f"\n[DEBUG] === Opening Fix Dialog ===")
        print(f"[DEBUG] Input: '{original_word_with_nikud}'")
        
        dialog = NikudEditorDialog(original_word_with_nikud, self)
        dialog.chk_add_to_dict.setChecked(True)
        dialog.chk_add_to_dict.setEnabled(False)
        
        if dialog.exec_() == QDialog.Accepted:
            corrected_word = dialog.get_text().strip()
            match_index = dialog.combo_match_type.currentIndex()
            
            # יצירת המפתח הנקי
            dict_key = self.clean_nikud_from_string(original_word_with_nikud)
            
            # בדיקה שהמפתח תקין
            if not dict_key:
                # ניסיון גיבוי: נקה ניקוד מהמילה המתוקנת
                dict_key = self.clean_nikud_from_string(corrected_word)
            
            print(f"[DEBUG] Final Dictionary Key: '{dict_key}'")
            
            # ביצוע ההוספה
            self.add_word_to_dictionary_logic(dict_key, corrected_word, match_index)
            
            # הסרה מטבלת הטעויות
            errors_list = self.settings.get("nikud_errors", [])
            if original_word_with_nikud in errors_list:
                errors_list.remove(original_word_with_nikud)
                self.settings["nikud_errors"] = errors_list
                self.save_settings()
            
            # רענון ממשק
            self.refresh_errors_table()
            self.refresh_dictionary_table()
            
            # === גלילה למילה החדשה בטבלה ===
            self.highlight_word_in_table(dict_key)
            
            self.lbl_status.setText(f"✅ נשמר למילון: {dict_key}")

    def highlight_word_in_table(self, key):
        """מוצא את המילה בטבלה, מסמן אותה וגולל אליה"""
        # מחפשים בעמודה 0 (המילה בטקסט/המפתח)
        items = self.table_nikud.findItems(key, Qt.MatchExactly)
        if items:
            item = items[0]
            row = item.row()
            self.table_nikud.selectRow(row)
            self.table_nikud.scrollToItem(item, QAbstractItemView.PositionAtCenter)
            print(f"[DEBUG] Scrolled to row {row} for key '{key}'")
        else:
            print(f"[DEBUG] Could not find key '{key}' in table visual items.")
    
    def add_word_to_dictionary_logic(self, original, new_val, match_index):
        """לוגיקה פנימית להוספה למילון"""
        normalized = unicodedata.normalize('NFD', original)
        key = "".join([c for c in normalized if not unicodedata.combining(c)])
        match_type = "exact" if match_index == 1 else "partial"
        
        self.settings["nikud_dictionary"][key] = new_val.strip()
        if "nikud_metadata" not in self.settings:
            self.settings["nikud_metadata"] = {}
        self.settings["nikud_metadata"][key] = {
            "date": datetime.now().strftime("%d/%m/%Y"),
            "match_type": match_type
        }
        self.save_settings()

    def clear_errors_list(self):
        if QMessageBox.question(self, "אישור", "האם לנקות את כל רשימת הטעויות?") == QMessageBox.Yes:
            self.settings["nikud_errors"] = []
            self.save_settings()
            self.refresh_errors_table()
            
    # פונקציית עזר להוספת כפתור ניגון לטבלאות רגילות
    def add_play_button_to_table(self, table, row, col, text):
        """פונקציית עזר להוספת כפתור השמעה לכל טבלה"""
        container = QWidget(); layout = QHBoxLayout(container); layout.setContentsMargins(0,0,0,0); layout.setAlignment(Qt.AlignCenter)
        btn = QPushButton("🔊")
        btn.setFixedSize(30, 25)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet("QPushButton { background-color: transparent; border: none; } QPushButton:hover { color: #27AE60; }")
        
        # חיבור לפונקציה הכללית
        btn.clicked.connect(lambda: self.play_preview_general(text))
        
        layout.addWidget(btn)
        table.setCellWidget(row, col, container)


    def open_advanced_import(self):
        dialog = AdvancedImportDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            # כשהמשתמש לוחץ "בצע ייבוא", הטקסט מגיע לכאן
            if dialog.result_text:
                self.editor.setPlainText(dialog.result_text)
                self.lbl_status.setText("הייבוא המתקדם הושלם בהצלחה!")
            else:
                self.lbl_status.setText("הייבוא הסתיים ללא טקסט.")

    def add_symbol_row(self):
        """פונקציה להוספת שורה לטבלת תווים מיוחדים"""
        row = self.table_symbols.rowCount()
        self.table_symbols.insertRow(row)
        self.table_symbols.setItem(row, 0, QTableWidgetItem("***")) # ברירת מחדל
        self.table_symbols.setItem(row, 1, QTableWidgetItem("1000")) # ברירת מחדל ב-ms

    def remove_symbol_row(self):
        """פונקציה למחיקת שורה מטבלת תווים מיוחדים"""
        curr = self.table_symbols.currentRow()
        if curr >= 0:
            self.table_symbols.removeRow(curr)

    def __init__(self):
        super().__init__()
        # 1. הגדרות חלון בסיסיות
        self.setWindowTitle("Hebrew PDF Studio - Ultimate Edition")
        self.setGeometry(100, 100, 1300, 950)
        
        # 2. אתחול מנהל ההגדרות (העברת הנתיב מה-config)
        # בהנחה ש-CONFIG_FILE מוגדר אצלך כקבוע
        self.settings_manager = SettingsManager(CONFIG_FILE)
        
        # 3. טעינת ההגדרות לתוך self.settings (שימוש ב-Manager במקום בפונקציה הפנימית)
        self.settings = self.settings_manager.load_settings(DEFAULT_SETTINGS)

        # 4. נתונים ומשתנים
        self.he_voices = {
            "Hila (אישה - עברית)": "he-IL-HilaNeural", 
            "Avri (גבר - עברית)": "he-IL-AvriNeural"
        }
        self.en_voices = {
            "Aria (אישה - ארה\"ב)": "en-US-AriaNeural", 
            "Guy (גבר - ארה\"ב)": "en-US-GuyNeural",
            "Brian (גבר - בריטי)": "en-GB-BrianNeural"
        }
        self.file_path = ""
        
        # 5. בניית הממשק והעיצוב
        self.init_ui()
        self.apply_styles()
        
        # בונוס: עדכון שדות ה-UI בערכים שנטענו
        self.load_initial_values_to_ui()

    def search_text(self):
        """פונקציית חיפוש מילים בתוך האדיטור"""
        target = self.input_search.text()
        if not target:
            return

        # ביצוע החיפוש
        # הפקודה self.editor.find מחזירה True אם נמצא ומסמנת את הטקסט
        found = self.editor.find(target)

        if not found:
            # אם לא נמצא, אולי הגענו לסוף הקובץ? ננסה מההתחלה
            # נזיז את הסמן להתחלה ונחפש שוב
            cursor = self.editor.textCursor()
            cursor.movePosition(QTextCursor.Start)
            self.editor.setTextCursor(cursor)
            
            # ניסיון שני מההתחלה
            found_again = self.editor.find(target)
            
            if not found_again:
                # אם עדיין לא נמצא - הודעה למשתמש
                QMessageBox.information(self, "חיפוש", f"המילה '{target}' לא נמצאה בטקסט.")
            else:
                # אם נמצא בסיבוב השני, נודיע שחזרנו להתחלה
                self.lbl_status.setText("החיפוש חזר לתחילת המסמך")
        else:
            self.lbl_status.setText(f"נמצא: {target}")
            self.editor.setFocus() # החזרת הפוקוס לעורך כדי שיראו את הסימון


    def load_settings(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f: return json.load(f)
            except: pass
        return DEFAULT_SETTINGS.copy()
    
    def handle_dictionary_update(self, base_word, vocalized_word):
        """מעדכן את הטבלה הוויזואלית ואת הזיכרון, אך לא שומר לקובץ"""
        # 1. ניקוי דגשים
        cleaner = NikudWorker("")
        vocalized_word = cleaner.clean_non_bgdkpt(vocalized_word)

        # 2. בדיקת כפילויות מול הזיכרון הקיים
        current_dict = self.settings.get("nikud_dictionary", {})
        if base_word in current_dict:
            existing_val = current_dict[base_word]
            if existing_val != vocalized_word:
                # קבלת הגדרות קול להשמעה
                current_he_voice_name = self.combo_he.currentText()
                voice_code = self.he_voices.get(current_he_voice_name, "he-IL-AvriNeural")
                speed = self.combo_speed.currentText()
                
                # דיאלוג השוואה
                dialog = CompareDialog(base_word, existing_val, vocalized_word, voice_code, speed, self)
                if dialog.exec_() != QDialog.Accepted:
                    return False # המשתמש ביטל

        # 3. עדכון הזיכרון
        self.settings["nikud_dictionary"][base_word] = vocalized_word
        
        # 4. === עדכון הטבלה הוויזואלית ישירות ===
        # אנחנו מחפשים אם השורה קיימת ומעדכנים, או מוסיפים חדשה
        table = self.table_nikud
        found = False
        for r in range(table.rowCount()):
            if table.item(r, 0).text() == base_word:
                table.setItem(r, 2, QTableWidgetItem(vocalized_word))
                found = True
                break
        
        if not found:
            table.add_row_with_buttons(base_word, vocalized_word)
            
        return True

    def save_settings(self):
        print("\n[DEBUG] >>> save_settings() CALLED")
        
        # 1. איסוף נתונים מהממשק לתוך המילון
        self.settings["tg_token"] = self.input_tg_token.text().strip()
        self.settings["tg_chat_id"] = self.input_tg_chat_id.text().strip()
        self.settings["pause_lang"] = self.spin_lang.value()
        self.settings["pause_comma"] = self.spin_comma.value()
        self.settings["pause_sentence"] = self.spin_sentence.value()
        self.settings["max_concurrent"] = self.spin_concurrent.value()

        # 2. שליחה ל-Manager לביצוע השמירה הפיזית
        success, info = self.settings_manager.save_to_disk(self.settings)
        
        # 3. עדכון סטטוס ב-UI
        if success:
            self.lbl_status.setText(f"✅ נשמר בהצלחה! ({info})")
            print(f"[DEBUG] Saving dictionary with {len(self.settings.get('nikud_dictionary', {}))} entries...")
        else:
            self.lbl_status.setText(f"❌ שגיאה בשמירה: {info}")
            print(f"[ERROR SAVE] {info}")


    def add_or_update_word(self, base_word, vocalized_word, match_type="partial", update_table_ui=True):
        """
        פונקציה מרכזית להוספה/עדכון מילה.
        update_table_ui: האם לעדכן את הטבלה הוויזואלית? 
                         True = כן (כשזה בא מבחוץ), False = לא (כשזה בא עריכה בטבלה עצמה).
        """
        print(f"\n[DEBUG] add_or_update_word called. Base='{base_word}', Voc='{vocalized_word}', UpdateUI={update_table_ui}")
        
        if not base_word or not vocalized_word: return
        if not any(c.isalnum() for c in base_word):
            print(f"[DEBUG] Blocked attempt to add punctuation '{base_word}' to dictionary.")
            return
        # 1. יצירת מפתח נקי
        key = self.clean_nikud_from_string(base_word)
        if not key: key = self.clean_nikud_from_string(vocalized_word)
        
        # 2. עדכון הזיכרון
        self.settings["nikud_dictionary"][key] = vocalized_word.strip()
        
        if "nikud_metadata" not in self.settings:
            self.settings["nikud_metadata"] = {}
            
        self.settings["nikud_metadata"][key] = {
            "date": datetime.now().strftime("%d/%m/%Y"),
            "match_type": match_type
        }

        # 3. שמירה לקובץ (תמיד קורה!)
        self.save_settings()

        # 4. עדכון הטבלה הוויזואלית (רק אם צריך)
        if update_table_ui:
            self.update_table_visuals_only(key, vocalized_word, match_type)
        else:
            print("[DEBUG] Skipping table visual update (assumed already updated by user).")

    def update_table_visuals_only(self, key, vocalized, match_type):
        """מעדכן שורה בטבלה אם קיימת, או מוסיף חדשה (ויזואלי בלבד)"""
        print(f"[DEBUG] Updating table visual for key: '{key}'")
        
        found_row = -1
        # חיפוש השורה בטבלה
        for row in range(self.table_nikud.rowCount()):
            item = self.table_nikud.item(row, 0)
            if item and self.clean_nikud_from_string(item.text()) == key:
                found_row = row
                break
        
        date_str = datetime.now().strftime("%d/%m/%Y")
        
        self.table_nikud.blockSignals(True) # מניעת לולאה חוזרת
        
        if found_row >= 0:
            print(f"[DEBUG] Found existing row {found_row}. Updating...")
            self.table_nikud.setItem(found_row, 2, QTableWidgetItem(vocalized))
            self.table_nikud.setItem(found_row, 5, QTableWidgetItem(date_str))
            
            # עדכון קומבו בוקס
            cell_widget = self.table_nikud.cellWidget(found_row, 4)
            if cell_widget:
                combo = cell_widget.findChild(QComboBox)
                if combo:
                    combo.setCurrentIndex(1 if match_type == "exact" else 0)
        else:
            print(f"[DEBUG] Row not found. Adding new row for '{key}'")
            self.table_nikud.add_row_with_data(key, vocalized, date_str, match_type)
            self.table_nikud.scrollToBottom()
            
        self.table_nikud.blockSignals(False)

    def update_table_row_visuals(self, key, vocalized, match_type):
        """עדכון שורה בודדת בטבלה או הוספה אם לא קיימת"""
        # חיפוש אם השורה קיימת
        found_row = -1
        for row in range(self.table_nikud.rowCount()):
            item = self.table_nikud.item(row, 0)
            if item and item.text() == key:
                found_row = row
                break
        
        date_str = datetime.now().strftime("%d/%m/%Y")
        
        if found_row >= 0:
            # עדכון שורה קיימת (רק את עמודת הניקוד, התאריך והסוג)
            self.table_nikud.blockSignals(True)
            self.table_nikud.setItem(found_row, 2, QTableWidgetItem(vocalized))
            self.table_nikud.setItem(found_row, 5, QTableWidgetItem(date_str))
            
            # עדכון הקומבו בוקס של סוג ההתאמה
            cell_widget = self.table_nikud.cellWidget(found_row, 4)
            if cell_widget:
                combo = cell_widget.findChild(QComboBox)
                if combo:
                    idx = 1 if match_type == "exact" else 0
                    combo.setCurrentIndex(idx)
            self.table_nikud.blockSignals(False)
        else:
            # הוספת שורה חדשה
            self.table_nikud.add_row_with_data(key, vocalized, date_str, match_type)
            # גלילה למילה החדשה
            self.table_nikud.scrollToBottom()


    def init_ui(self):
        self.setWindowTitle("Hebrew TTS Studio - עורך דיבור עברי מתקדם")
        self.setGeometry(100, 100, 1300, 850)
        
        # הגדרת עיצוב (StyleSheet)
        self.setStyleSheet("""
            QWidget { background-color: #102A43; color: #F0F4F8; font-family: 'Segoe UI', Arial; font-size: 14px; }
            QLabel { color: #D9E2EC; font-weight: bold; }
            QTextEdit { background-color: #243B53; color: #FFFFFF; border: 1px solid #486581; border-radius: 6px; padding: 12px; font-size: 16px; }
            QLineEdit, QComboBox, QSpinBox { background-color: #F0F4F8; padding: 6px; color: #102A43; border-radius: 4px; }
            QPushButton { background-color: #334E68; color: #FFFFFF; padding: 8px; font-weight: bold; border-radius: 5px; }
            QPushButton:hover { background-color: #486581; }
            QProgressBar { border: 2px solid #334E68; border-radius: 5px; text-align: center; background-color: #102A43; color: white; }
            QProgressBar::chunk { background-color: #F76707; }
            QTableWidget { background-color: #243B53; gridline-color: #486581; color: white; selection-background-color: #334E68; }
            QHeaderView::section { background-color: #102A43; color: white; padding: 5px; border: 1px solid #486581; }
            QGroupBox { border: 1px solid #486581; border-radius: 6px; margin-top: 20px; font-weight: bold; }
            QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top center; padding: 0 10px; color: #F76707; }
        """)
        # הגדרת פונט ספציפי לטאבים שתומך באימוג'י
        
        # פריסה ראשית
        main_layout = QVBoxLayout()
        container = QWidget()
        container.setLayout(main_layout)
        self.setCentralWidget(container)

        self.tabs = QTabWidget()
        self.tabs.setLayoutDirection(Qt.RightToLeft)
        self.tabs.setDocumentMode(True)
        # =================================================================
        # TAB 1: עריכה והמרה (תצוגה מפוצלת - קומפקטית)
        # =================================================================
        tab_main = QWidget()
        layout_main = QVBoxLayout(tab_main)
        layout_main.setSpacing(4)
        layout_main.setContentsMargins(6, 4, 6, 4)

        # --- סרגל כלים דו-שורתי ---
        compact_bar = QFrame()
        compact_bar.setStyleSheet("background-color: #1A3C59; border-radius: 6px; padding: 4px;")
        compact_bar.setFixedHeight(76)
        bar_main_layout = QVBoxLayout(compact_bar)
        bar_main_layout.setContentsMargins(8, 4, 8, 4)
        bar_main_layout.setSpacing(4)

        # --- שורה 1: טעינת קבצים + טווח עמודים (עם דיבאג) ---
        print("[DEBUG] Starting Row 1 initialization...") # DEBUG LOG
        row1 = QHBoxLayout()
        row1.setSpacing(6)

        self.btn_load = QPushButton("📂 PDF")
        self.btn_load.setFixedWidth(70)
        self.btn_load.setStyleSheet("padding: 4px; font-size: 12px;")
        self.btn_load.clicked.connect(self.load_pdf)
        row1.addWidget(self.btn_load)

        self.btn_advanced_import = QPushButton("📑 ייבוא")
        self.btn_advanced_import.setFixedWidth(70)
        self.btn_advanced_import.setStyleSheet("background-color: #2980B9; color: white; padding: 4px; font-size: 12px;")
        self.btn_advanced_import.clicked.connect(self.open_advanced_import)
        row1.addWidget(self.btn_advanced_import)

        self.lbl_file = QLabel("לא נבחר קובץ")
        self.lbl_file.setStyleSheet("color: #8899AA; font-style: italic; font-size: 11px;")
        self.lbl_file.setMaximumWidth(150)
        row1.addWidget(self.lbl_file)

        self.btn_extract = QPushButton("ייבא")
        self.btn_extract.setFixedWidth(50)
        self.btn_extract.setStyleSheet("background-color: #27AE60; color: white; padding: 4px; font-size: 12px; font-weight: bold;")
        self.btn_extract.clicked.connect(self.extract_text)
        row1.addWidget(self.btn_extract)

        # תווית "עמודים"
        lbl_pages = QLabel("עמודים:")
        lbl_pages.setStyleSheet("color: #FFFFFF; font-size: 11px; font-weight: bold;")
        row1.addWidget(lbl_pages)

        # === יצירת שדות הקלט (עם הדפסות דיבאג למציאת השגיאה) ===
        input_style = "background-color: #102A43; color: #FFFFFF; font-size: 11px; font-weight: bold; border-radius: 2px; padding: 2px; border: 1px solid #BDC3C7;"

        print("[DEBUG] Creating input_start...") # DEBUG LOG
        self.input_start = QLineEdit("1")
        self.input_start.setFixedWidth(35)
        self.input_start.setAlignment(Qt.AlignCenter)
        self.input_start.setStyleSheet(input_style) 
        
        print("[DEBUG] Creating input_end...") # DEBUG LOG
        self.input_end = QLineEdit() # <--- כאן הייתה הבעיה שלך (השורה הזו הייתה חסרה)
        self.input_end.setFixedWidth(35)
        self.input_end.setAlignment(Qt.AlignCenter)
        self.input_end.setStyleSheet(input_style) 
        
        row1.addWidget(self.input_start)
        
        lbl_dash = QLabel("-")
        lbl_dash.setStyleSheet("color: #FFFFFF; font-size: 11px; font-weight: bold;")
        lbl_dash.setFixedWidth(8)
        row1.addWidget(lbl_dash)
        
        print("[DEBUG] Adding input_end to layout...") # DEBUG LOG
        row1.addWidget(self.input_end) # <--- בשורה הזו הקוד קרס כי self.input_end לא היה קיים

        row1.addStretch()
        bar_main_layout.addLayout(row1)
        print("[DEBUG] Row 1 initialization complete.") # DEBUG LOG

        # --- שורה 2: הגדרות קול ומהירות (מתוקן) ---
        row2 = QHBoxLayout()
        row2.setSpacing(6)

        # סגנון ברור לתיבות הבחירה: רקע לבן, טקסט כהה, ורשימה נפתחת קריאה
        combo_style = """
            QComboBox { 
                background-color: #102A43; 
                color: #ffffff; 
                font-size: 11px; 
                padding: 2px; 
                border: 1px solid #BDC3C7;
                border-radius: 4px;
            }
            QComboBox QAbstractItemView {
                background-color: #102A43;
                color: #ffffff;
                selection-background-color: #2980B9;
                selection-color: white;
            }
        """

        # תווית קול עברי
        lbl_he_voice = QLabel("קול עברי:")
        lbl_he_voice.setStyleSheet("color: #FFFFFF; font-size: 11px; font-weight: bold;")
        row2.addWidget(lbl_he_voice)
        
        self.combo_he = QComboBox(); self.combo_he.addItems(list(self.he_voices.keys()))
        self.combo_he.setFixedWidth(150)
        self.combo_he.setStyleSheet(combo_style) # <--- שימוש בסגנון החדש
        if "selected_he_voice" in self.settings: self.combo_he.setCurrentText(self.settings["selected_he_voice"])
        row2.addWidget(self.combo_he)

        # תווית קול אנגלי
        lbl_en_voice = QLabel("קול אנגלי:")
        lbl_en_voice.setStyleSheet("color: #FFFFFF; font-size: 11px; font-weight: bold;")
        row2.addWidget(lbl_en_voice)
        
        self.combo_en = QComboBox(); self.combo_en.addItems(list(self.en_voices.keys()))
        self.combo_en.setFixedWidth(150)
        self.combo_en.setStyleSheet(combo_style) # <--- שימוש בסגנון החדש
        if "selected_en_voice" in self.settings: self.combo_en.setCurrentText(self.settings["selected_en_voice"])
        row2.addWidget(self.combo_en)

        # תווית מהירות
        lbl_speed = QLabel("מהירות:")
        lbl_speed.setStyleSheet("color: #FFFFFF; font-size: 11px; font-weight: bold;")
        row2.addWidget(lbl_speed)
        
        self.combo_speed = QComboBox(); self.combo_speed.addItems(["-25%", "-10%", "+0%", "+10%", "+25%"])
        self.combo_speed.setCurrentText(self.settings.get("selected_speed", "+0%"))
        self.combo_speed.setFixedWidth(80)
        self.combo_speed.setStyleSheet(combo_style) # <--- שימוש בסגנון החדש
        row2.addWidget(self.combo_speed)

        # צ'קבוקס EN
        self.chk_dual = QCheckBox("EN")
        self.chk_dual.setStyleSheet("font-size: 11px; color: #FFFFFF; font-weight: bold;")
        self.chk_dual.setChecked(self.settings.get("is_dual_mode", True))
        row2.addWidget(self.chk_dual)

        row2.addStretch()
        bar_main_layout.addLayout(row2)

        layout_main.addWidget(compact_bar)

        # --- חלק מרכזי: תצוגה מפוצלת (Split View) - תופס את רוב המסך ---
        
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(6)
        splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: #486581;
                border-radius: 3px;
            }
            QSplitter::handle:hover {
                background-color: #F76707;
            }
        """)
        
        # צד שמאל: PDF Viewer (חצי מסך)
        self.pdf_viewer = PDFViewerWidget()
        splitter.addWidget(self.pdf_viewer)
        
        # צד ימין: עורך טקסט + כלים
        right_container = QWidget()
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(3)
        
        # >> כלי עריכה (קומפקטיים)
        frame_tools = QFrame()
        frame_tools.setStyleSheet("background-color: #2C3E50; border-radius: 4px; padding: 4px;")
        frame_tools.setFixedHeight(50) # גובה מצומצם ונקי
        
        toolbar_layout = QHBoxLayout(frame_tools)
        toolbar_layout.setContentsMargins(4, 2, 4, 2)
        toolbar_layout.setSpacing(10)

        # 1. שם קובץ (כללי)
        lbl_file = QLabel("🏷️")
        self.input_filename = QLineEdit()
        self.input_filename.setPlaceholderText("שם קובץ כללי")
        self.input_filename.setStyleSheet("background-color: #ffffff")
        self.input_filename.setFixedWidth(150)
        
        # 2. כפתורי כיוון וניקוד
        btn_rtl = QPushButton("RTL"); btn_rtl.setFixedWidth(35); btn_rtl.clicked.connect(lambda: self.set_text_direction(Qt.RightToLeft))
        btn_ltr = QPushButton("LTR"); btn_ltr.setFixedWidth(35); btn_ltr.clicked.connect(lambda: self.set_text_direction(Qt.LeftToRight))
        
        self.btn_nikud_auto = QPushButton("ניקוד")
        self.btn_nikud_auto.setStyleSheet("background-color: #8E44AD; color: white; font-weight: bold;")
        self.btn_nikud_auto.setToolTip("נקד את כל הטקסט בעזרת Dicta")
        self.btn_nikud_auto.setFixedWidth(50)
        self.btn_nikud_auto.clicked.connect(self.start_auto_nikud)

        self.btn_dict_only = QPushButton("נקד ממילון")
        self.btn_dict_only.setStyleSheet("background-color: #8E44AD; color: white; font-weight: bold;")
        self.btn_dict_only.setToolTip("נקד רק מילים המופיעות במילון")
        self.btn_dict_only.setFixedWidth(80)
        self.btn_dict_only.clicked.connect(self.run_dictionary_only)
        
        # === 3. הכפתור החדש לפיצול (פותח Popup) ===
        btn_split_popup = QPushButton("פיצול")
        btn_split_popup.setStyleSheet("background-color: #E67E22; color: white; font-weight: bold;")
        btn_split_popup.setToolTip("פצל את הטקסט לקבצים נפרדים לפי מילה")
        btn_split_popup.setFixedWidth(50)
        btn_split_popup.clicked.connect(self.open_split_dialog)
        
        # ==========================================

        # הוספה לסרגל
        toolbar_layout.addWidget(lbl_file)
        toolbar_layout.addWidget(self.input_filename)
        toolbar_layout.addWidget(btn_rtl)
        toolbar_layout.addWidget(btn_ltr)
        toolbar_layout.addWidget(self.btn_nikud_auto)
        toolbar_layout.addWidget(self.btn_dict_only)
        toolbar_layout.addWidget(btn_split_popup) # הכפתור החדש
        
        # חיפוש (בצד שמאל של הסרגל)
        toolbar_layout.addStretch()
        self.input_search = QLineEdit()
        self.input_search.setPlaceholderText("🔍 חפש...")
        self.input_search.setFixedWidth(150)
        self.input_search.setStyleSheet("background-color: #ffffff")
        self.input_search.returnPressed.connect(self.search_text)
        toolbar_layout.addWidget(self.input_search)
        
        right_layout.addWidget(frame_tools)

        # >> העורך הראשי
        self.editor = NikudTextEdit(self)
        self.editor.setFont(QFont("Arial", 14))
        self.editor.setLayoutDirection(Qt.RightToLeft)
        self.editor.textChanged.connect(self.update_char_count)
        right_layout.addWidget(self.editor)
        
        splitter.addWidget(right_container)
        
        # הגדרת יחסים: PDF 50%, Editor 50% (ניתן להזזה עם המפצל)
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 5)
        splitter.setSizes([600, 600])

        layout_main.addWidget(splitter, 1)  # stretch=1 כדי שיתפוס את כל המקום הזמין

        # --- כפתור המרה (קומפקטי) ---
        self.btn_convert = QPushButton("🚀 צור קובץ MP3")
        self.btn_convert.setFixedHeight(42)
        self.btn_convert.setFont(QFont("Arial", 14, QFont.Bold))
        self.btn_convert.setStyleSheet("background-color: #F76707; font-size: 16px; border: 2px solid #D9480F;")
        self.btn_convert.clicked.connect(self.start_export_process) 
        
        layout_main.addWidget(self.btn_convert)
        
        # חיבור סנכרון בזמן אמת (קריטי!)
        self.editor.cursorPositionChanged.connect(self.sync_pdf_to_cursor)

        self.tabs.addTab(tab_main, "🎙️ עריכה והמרה")


        # =================================================================
        # TAB 2: מילון ניקוד וטעויות
        # =================================================================
        tab2 = QWidget()
        tab2_layout = QVBoxLayout(tab2)
        tab2_layout.setSpacing(8)

        # --- קבוצה עליונה: טבלת טעויות ---
        group_errors = QGroupBox("⚠️ מילים שסומנו כטעות (ערוך בטבלה כדי לתקן)")
        group_errors.setStyleSheet("""
            QGroupBox { border: 2px solid #E74C3C; border-radius: 6px; margin-top: 10px; padding-top: 14px; }
            QGroupBox::title { color: #E74C3C; font-family: 'Segoe UI Emoji', 'Segoe UI', Arial; }
        """)
        errors_layout = QVBoxLayout(group_errors)

        self.table_errors = ErrorsTableWidget(self)
        self.table_errors.setMinimumHeight(200)
        self.table_errors.setMaximumHeight(300)
        errors_layout.addWidget(self.table_errors)

        btn_clear_errors = QPushButton("נקה את כל רשימת הטעויות")
        btn_clear_errors.setStyleSheet("background-color: #95A5A6; font-size: 10px; padding: 4px;")
        btn_clear_errors.clicked.connect(self.clear_errors_list)
        errors_layout.addWidget(btn_clear_errors)

        tab2_layout.addWidget(group_errors)

        # --- קבוצה תחתונה: מילון ניקוד ---
        group_dict = QGroupBox("📚 מילון ניקוד פעיל")
        group_dict.setStyleSheet("""
            QGroupBox { border: 2px solid #2ECC71; border-radius: 6px; margin-top: 10px; padding-top: 14px; }
            QGroupBox::title { color: #2ECC71; font-family: 'Segoe UI Emoji', 'Segoe UI', Arial; }
        """)
        dict_layout = QVBoxLayout(group_dict)

        search_layout = QHBoxLayout()
        self.input_search_dict = QLineEdit()
        self.input_search_dict.setPlaceholderText("🔍 חפש במילון...")
        self.input_search_dict.setStyleSheet("background-color: #FFFFFF; color: #000; padding: 5px;")
        search_layout.addWidget(self.input_search_dict)

        btn_add_manual = QPushButton("➕ הוסף מילה ידנית")
        btn_add_manual.setStyleSheet("background-color: #2980B9; color: white;")
        btn_add_manual.clicked.connect(self.add_manual_word)
        search_layout.addWidget(btn_add_manual)

        dict_layout.addLayout(search_layout)

        self.table_nikud = PasteableTableWidget()
        self.table_nikud.setColumnCount(6)
        self.table_nikud.setHorizontalHeaderLabels(["מילה בטקסט", "🔊", "תיקון (מנוקד)", "🔊", "סוג התאמה", "תאריך"])
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
        btn_delete_multi.clicked.connect(self.table_nikud.delete_selected_rows)

        actions_layout.addWidget(btn_select_all)
        actions_layout.addWidget(btn_clear_sel)
        actions_layout.addWidget(btn_delete_multi)
        actions_layout.addStretch()
        dict_layout.addLayout(actions_layout)

        tab2_layout.addWidget(group_dict)

        self.tabs.addTab(tab2, "📖 מילון ניקוד")

        # =================================================================
        # TAB 3: הגדרות מתקדמות (הטאב החסר שחזר)
        # =================================================================
        tab_settings = QWidget()
        layout_settings = QVBoxLayout(tab_settings)
        layout_settings.setSpacing(12)

        # קבוצה: טלגרם
        group_tg = QGroupBox("🤖 הגדרות טלגרם")
        layout_tg = QGridLayout(group_tg)
        
        self.input_tg_token = QLineEdit(self.settings.get("tg_token", ""))
        self.input_tg_token.setPlaceholderText("הדבק כאן את הטוקן של הבוט")
        self.input_tg_chat_id = QLineEdit(self.settings.get("tg_chat_id", ""))
        self.input_tg_chat_id.setPlaceholderText("הדבק כאן את ה-Chat ID שלך")
        
        layout_tg.addWidget(QLabel("Bot Token:"), 0, 0)
        layout_tg.addWidget(self.input_tg_token, 0, 1)
        layout_tg.addWidget(QLabel("Chat ID:"), 1, 0)
        layout_tg.addWidget(self.input_tg_chat_id, 1, 1)
        layout_settings.addWidget(group_tg)

        # קבוצה: השהיות
        group_pauses = QGroupBox("⏱️ השהיות אוטומטיות")
        layout_pauses = QHBoxLayout(group_pauses)
        
        self.spin_lang = QSpinBox(); self.spin_lang.setRange(0, 2000); self.spin_lang.setValue(self.settings.get("pause_lang", 500)); self.spin_lang.setSuffix(" ms")
        self.spin_comma = QSpinBox(); self.spin_comma.setRange(0, 2000); self.spin_comma.setValue(self.settings.get("pause_comma", 300)); self.spin_comma.setSuffix(" ms")
        self.spin_sentence = QSpinBox(); self.spin_sentence.setRange(0, 5000); self.spin_sentence.setValue(self.settings.get("pause_sentence", 800)); self.spin_sentence.setSuffix(" ms")
        
        layout_pauses.addWidget(QLabel("חילוף שפה:"))
        layout_pauses.addWidget(self.spin_lang)
        layout_pauses.addSpacing(20)
        layout_pauses.addWidget(QLabel("פסיק:"))
        layout_pauses.addWidget(self.spin_comma)
        layout_pauses.addSpacing(20)
        layout_pauses.addWidget(QLabel("סוף משפט:"))
        layout_pauses.addWidget(self.spin_sentence)
        layout_settings.addWidget(group_pauses)

        # קבוצה: ביצועים
        group_perf = QGroupBox("ביצועים")
        layout_perf = QHBoxLayout(group_perf)
        self.spin_concurrent = QSpinBox()
        self.spin_concurrent.setRange(1, 50) # הגדלנו ל-50 כמו שביקשת קודם
        self.spin_concurrent.setValue(self.settings.get("max_concurrent", 5))
        
        # >>> שורת הקסם להוספה: <<<
        self.spin_concurrent.valueChanged.connect(self.save_settings)
        layout_perf.addWidget(QLabel("מספר המרות במקביל:"))
        layout_perf.addWidget(self.spin_concurrent)
        layout_perf.addStretch()
        layout_settings.addWidget(group_perf)

        # קבוצה: סמלים מיוחדים
        group_symbols = QGroupBox("🔣 החלפת סמלים והשהיות מיוחדות")
        layout_symbols = QVBoxLayout(group_symbols)
        
        self.table_symbols = QTableWidget(0, 2)
        self.table_symbols.setHorizontalHeaderLabels(["סמל בטקסט", "השהייה (ms)"])
        self.table_symbols.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout_symbols.addWidget(self.table_symbols)
        
        btn_add_sym = QPushButton("➕ הוסף סמל"); btn_add_sym.clicked.connect(self.add_symbol_row)
        btn_del_sym = QPushButton("🗑️ מחק סמל"); btn_del_sym.clicked.connect(self.delete_symbol_row)
        
        sym_btns = QHBoxLayout()
        sym_btns.addWidget(btn_add_sym); sym_btns.addWidget(btn_del_sym)
        layout_symbols.addLayout(sym_btns)
        layout_settings.addWidget(group_symbols)

        # טעינת סמלים קיימים
        custom_symbols = self.settings.get("custom_symbols", {"...": 500, "-": 300})
        for sym, dur in custom_symbols.items():
            r = self.table_symbols.rowCount()
            self.table_symbols.insertRow(r)
            self.table_symbols.setItem(r, 0, QTableWidgetItem(sym))
            self.table_symbols.setItem(r, 1, QTableWidgetItem(str(dur)))
        
        layout_settings.addStretch()
        self.tabs.addTab(tab_settings, "🔧 הגדרות מתקדמות")

        # סיום הבנייה
        main_layout.addWidget(self.tabs)

        status_frame = QFrame()
        status_frame.setStyleSheet("background-color: #1A3C59; border-top: 2px solid #486581; padding: 5px;")
        status_layout = QVBoxLayout(status_frame)
        self.progress_bar = QProgressBar(); self.progress_bar.setAlignment(Qt.AlignCenter)
        self.lbl_status = QLabel("מוכן"); self.lbl_status.setAlignment(Qt.AlignCenter)
        self.lbl_status.setStyleSheet("font-size: 14px; font-weight: bold; color: white;")
        status_layout.addWidget(self.progress_bar)
        status_layout.addWidget(self.lbl_status)
        main_layout.addWidget(status_frame)

        global TG_TOKEN, TG_CHAT_ID
        TG_TOKEN = self.settings.get("tg_token", "")
        TG_CHAT_ID = self.settings.get("tg_chat_id", "")
        
        self.refresh_dictionary_table()
        self.refresh_errors_table()


        # הגדרת נתיב ברירת מחדל לקבצים (Documents)
        output_dir = os.path.expanduser("~/Documents")
        
        # יצירת הטאב החדש
        self.tab_karaoke = KaraokeTab(output_dir, self) 
        self.tabs.addTab(self.tab_karaoke, "🎵 נגן וקבצים")

        # Tooltips עם קיצורי מקלדת
        self.tabs.setTabToolTip(0, "עריכה והמרה (Ctrl+1)")
        self.tabs.setTabToolTip(1, "מילון ניקוד (Ctrl+2)")
        self.tabs.setTabToolTip(2, "הגדרות מתקדמות (Ctrl+3)")
        self.tabs.setTabToolTip(3, "נגן וקבצים (Ctrl+4)")

        # קיצורי מקלדת לניווט בין טאבים
        for i in range(4):
            QShortcut(QKeySequence(f"Ctrl+{i+1}"), self, lambda idx=i: self.tabs.setCurrentIndex(idx))
        QShortcut(QKeySequence("Ctrl+Tab"), self, lambda: self.tabs.setCurrentIndex((self.tabs.currentIndex() + 1) % self.tabs.count()))
        QShortcut(QKeySequence("Ctrl+Shift+Tab"), self, lambda: self.tabs.setCurrentIndex((self.tabs.currentIndex() - 1) % self.tabs.count()))

        

    def add_row_to_table(self, table):
        table.insertRow(table.rowCount())

    def remove_row_from_table(self, table):
        current_row = table.currentRow()
        if current_row >= 0: table.removeRow(current_row)
        elif table.rowCount() > 0: table.removeRow(table.rowCount() - 1)

    def refresh_dictionary_table(self):
        """טעינת המילון לטבלה"""
        print("[DEBUG] Refreshing dictionary table...")
        self.table_nikud.setRowCount(0)
        self.table_nikud.clearContents() # ניקוי יסודי
        
        dictionary = self.settings.get("nikud_dictionary", {})
        metadata = self.settings.get("nikud_metadata", {}) 
        
        # מיון כדי שיהיה קל למצוא
        sorted_keys = sorted(dictionary.keys())
        
        for base in sorted_keys:
            vocalized = dictionary[base]
            data = metadata.get(base, {})
            date_added = data.get("date", "-")
            match_type = data.get("match_type", "partial")
            
            self.table_nikud.add_row_with_data(base, vocalized, date_added, match_type)
            
        print(f"[DEBUG] Table refreshed. Total words: {len(dictionary)}")

    def add_word_to_dict_externally(self, base_word, vocalized_word):
        self.settings["nikud_dictionary"][base_word] = vocalized_word
        row = self.table_nikud.rowCount()
        self.table_nikud.insertRow(row)
        self.table_nikud.setItem(row, 0, QTableWidgetItem(base_word))
        self.table_nikud.setItem(row, 1, QTableWidgetItem(vocalized_word))
        self.save_settings()

    def start_auto_nikud(self):
        # 1. עצירה בטוחה של תהליך קודם
        self.stop_worker_safely('nikud_worker')

        # === שינוי: קריאה בטוחה ששומרת על נתיבי התמונות כטקסט ===
        text = self.get_text_safe() 
        # =========================================================
        
        if not text.strip(): return
        
        # עדכון ממשק
        self.btn_nikud_auto.setEnabled(False)
        self.btn_nikud_auto.setText("מנקד...")
        
        # שליפת מילון
        current_dict = self.settings.get("nikud_dictionary", {})
        
        # יצירת ה-Worker
        self.nikud_worker = NikudWorker(text, current_dict)
        
        # חיבור לאירועים (הצלחה, שגיאה, התקדמות)
        self.nikud_worker.finished.connect(self.on_nikud_success)
        self.nikud_worker.error.connect(self.on_nikud_error)
        self.nikud_worker.progress.connect(self.lbl_status.setText) 
        self.nikud_worker.progress_percent.connect(self.progress_bar.setValue)
        
        # התחלה
        self.nikud_worker.start()

    def on_nikud_success(self, vocalized_text):
        # שחזור מצב הכפתורים
        self.btn_nikud_auto.setEnabled(True)
        self.btn_nikud_auto.setText("✨ ניקוד אוטומטי (Dicta)")
        self.progress_bar.setValue(100)
        
        # 1. שליפת הטקסט המקורי בצורה בטוחה (כולל תגיות תמונה) לצורך השוואה
        original_text = self.get_text_safe()

        # בדיקת זהות מוחלטת (אם אין שום שינוי, חבל להריץ לוגיקה כבדה)
        if original_text == vocalized_text:
            self.lbl_status.setText("הניקוד הסתיים. לא נמצאו שינויים.")
            self.set_text_safe(vocalized_text) # משחזר את התמונות
            return

        self.lbl_status.setText("הניקוד הסתיים! אנא אשר שינויים.")

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
            self.lbl_status.setText("לא נמצאו שינויים מהותיים במילים.")
            # === הפקודה החשובה ביותר: עדכון בטוח ששומר על התמונות ===
            self.set_text_safe(vocalized_text)

    # --- הפונקציה שהייתה חסרה! ---
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

    def start_conversion(self):
        # 1. עצירה בטוחה של תהליך קודם אם קיים
        self.stop_worker_safely('worker')

        text = self.editor.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "שגיאה", "העורך ריק!")
            return

        self.btn_convert.setEnabled(False)
        self.btn_convert.setText("מעבד...")
        self.progress_bar.setValue(0)
        self.save_settings()
        
        # ... (שאר איסוף הנתונים ללא שינוי) ...
        he_voice = self.he_voices[self.combo_he.currentText()]
        en_voice = self.en_voices[self.combo_en.currentText()]
        speed = self.combo_speed.currentText()
        is_dual = self.chk_dual.isChecked()
        
        # יצירת נתיב שמירה...
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
        if hasattr(self, 'file_paths') and self.file_paths:
            out_dir = os.path.dirname(self.file_paths[0])
        elif self.file_path and os.path.exists(self.file_path):
            out_dir = os.path.dirname(self.file_path)
        else:
            out_dir = os.path.expanduser("~/Documents")
            
        user_name = self.input_filename.text().strip()
        if user_name: original_name = re.sub(r'[\\/*?:"<>|]', "", user_name)
        elif hasattr(self, 'file_paths') and self.file_paths: original_name = os.path.splitext(os.path.basename(self.file_paths[0]))[0]
        else: original_name = "HebrewTTS_Output"
        
        if not os.path.exists(out_dir): out_dir = os.path.expanduser("~/Documents")
        final_path = os.path.join(out_dir, f"{original_name}_{timestamp}.mp3")
        
        # יצירת ה-Worker החדש
        self.worker = TTSWorker(text, he_voice, en_voice, speed, final_path, self.settings, dual_mode=is_dual)
        
        self.worker.progress_update.connect(self.progress_bar.setValue)
        self.worker.finished_success.connect(self.on_success)
        self.worker.finished_error.connect(self.on_error)
        if hasattr(self.worker, 'log_update'):
            self.worker.log_update.connect(self.lbl_status.setText)
            
        self.worker.start()

    def start_auto_nikud(self):
        # 1. עצירה בטוחה
        self.stop_worker_safely('nikud_worker')

        text = self.editor.toPlainText()
        if not text.strip(): return
        
        self.btn_nikud_auto.setEnabled(False)
        self.btn_nikud_auto.setText("מנקד...")
        
        current_dict = self.settings.get("nikud_dictionary", {})
        self.nikud_worker = NikudWorker(text, current_dict)
        
        self.nikud_worker.finished.connect(self.on_nikud_success)
        self.nikud_worker.error.connect(self.on_nikud_error)
        self.nikud_worker.progress.connect(self.lbl_status.setText) 
        self.nikud_worker.progress_percent.connect(self.progress_bar.setValue)
        self.nikud_worker.start()

    def on_success(self, path, skipped_list):
        print(f"[DEBUG] on_success called. Path: {path}")
        
        # שמירת רשימת הדילוגים לשימוש מאוחר יותר
        self.last_skipped_list = skipped_list 
        
        # וידוא שהקובץ קיים
        if not path or not os.path.exists(path):
            self.lbl_status.setText("שגיאה: הקובץ לא נוצר")
            self.btn_convert.setEnabled(True)
            self.btn_convert.setText("🚀 צור קובץ MP3")
            QMessageBox.critical(self, "שגיאה", "הקובץ לא נמצא על הדיסק.")
            return
        
        # שליפת פרטי טלגרם
        token = self.input_tg_token.text().strip()
        chat_id = self.input_tg_chat_id.text().strip()
        
        print(f"[DEBUG] Telegram Details -> Token: {'YES' if token else 'NO'} | ChatID: {'YES' if chat_id else 'NO'}")

        # אם יש פרטי טלגרם - מתחילים העלאה
        if token and chat_id:
            self.progress_bar.setValue(0)
            self.lbl_status.setText("מתחיל העלאה לטלגרם...")
            
            # יצירת ה-Worker
            self.tg_worker = TelegramWorker(token, chat_id, path)
            self.tg_worker.upload_progress.connect(self.progress_bar.setValue)
            self.tg_worker.log_update.connect(self.lbl_status.setText)
            self.tg_worker.finished.connect(self.on_telegram_finished)
            self.tg_worker.start()
        else:
            # אם אין טלגרם - נותנים הודעה קטנה בקונסול ומסיימים
            print("[DEBUG] No Telegram credentials found. Skipping upload.")
            self.on_telegram_finished()

    def on_telegram_finished(self):
        self.lbl_status.setText("התהליך הושלם!")
        self.btn_convert.setEnabled(True)
        self.btn_convert.setText("🚀 צור קובץ MP3")
        
        # --- בדיקה אם היו שגיאות (משפטים שדולגו) ---
        if hasattr(self, 'last_skipped_list') and self.last_skipped_list:
            skipped_count = len(self.last_skipped_list)
            details = ""
            for idx, text in self.last_skipped_list:
                display_text = text[:100] + "..." if len(text) > 100 else text
                details += f"• משפט {idx}:\n{display_text}\n\n"
            
            mbox = QMessageBox(self)
            mbox.setWindowTitle("דו\"ח משפטים חסרים")
            mbox.setText(f"התהליך הסתיים עם {skipped_count} שגיאות.")
            mbox.setDetailedText(details)
            mbox.setIcon(QMessageBox.Warning)
            
            # כפתורים
            btn_ok = mbox.addButton("אישור", QMessageBox.AcceptRole)
            btn_player = mbox.addButton("🎵 פתח בנגן", QMessageBox.ActionRole)
            
            mbox.exec_()
            
            if mbox.clickedButton() == btn_player:
                self.open_in_player_tab()
        
        else:
            # --- הצלחה מלאה ---
            mbox = QMessageBox(self)
            mbox.setWindowTitle("הצלחה")
            mbox.setText("התהליך הסתיים בהצלחה מלאה!\nהאם לעבור לנגן?")
            mbox.setIcon(QMessageBox.Information)
            
            btn_yes = mbox.addButton("כן, פתח נגן", QMessageBox.YesRole)
            btn_no = mbox.addButton("לא", QMessageBox.NoRole)
            
            mbox.exec_()
            
            if mbox.clickedButton() == btn_yes:
                self.open_in_player_tab()

        self.last_skipped_list = []

    def open_in_player_tab(self):
        """פונקציית עזר למעבר לנגן וטעינת הקובץ האחרון"""
        # מעבר לטאב הנגן
        self.tabs.setCurrentWidget(self.tab_karaoke)
        
        # איתור הקובץ האחרון שנוצר
        if hasattr(self, 'worker') and hasattr(self.worker, 'output_path'):
            mp3_path = self.worker.output_path
            json_path = mp3_path.replace(".mp3", ".json")
            
            if os.path.exists(json_path):
                # רענון הרשימה ובחירת הקובץ
                self.tab_karaoke.refresh_file_list()
                self.tab_karaoke.select_file_by_path(json_path)
            else:
                print("[DEBUG] JSON file not found for player auto-load.")


    def on_error(self, msg):
        self.btn_convert.setEnabled(True)
        self.btn_convert.setText("🚀 צור קובץ MP3")
        self.lbl_status.setText("שגיאה")
        QMessageBox.critical(self, "Error", msg)

    def on_nikud_error(self, msg):
        self.btn_nikud_auto.setEnabled(True)
        self.btn_nikud_auto.setText("✨ הוסף ניקוד אוטומטי (Dicta)")
        self.lbl_status.setText("שגיאה בניקוד")
        QMessageBox.warning(self, "שגיאה", msg)


    def set_text_direction(self, direction):
        self.editor.setLayoutDirection(direction); cursor = self.editor.textCursor(); block_format = cursor.blockFormat(); block_format.setLayoutDirection(direction); cursor.setBlockFormat(block_format); self.editor.setTextCursor(cursor); self.editor.setFocus()

    def load_pdf(self):
        # שימוש ב-getOpenFileNames (ברבים) במקום getOpenFileName
        fnames, _ = QFileDialog.getOpenFileNames(self, 'בחר קבצי PDF (ניתן לבחור כמה)', '', "PDF Files (*.pdf)")
        
        if fnames:
            # מיון הקבצים לפי השם כדי לשמור על סדר הגיוני (פרק 1, פרק 2...)
            self.file_paths = sorted(fnames)
            self.file_path = self.file_paths[0] # שומר על הקובץ הראשון כברירת מחדל לתאימות
            
            # עדכון התצוגה למשתמש
            if len(self.file_paths) == 1:
                self.lbl_file.setText(os.path.basename(self.file_paths[0]))
            else:
                self.lbl_file.setText(f"נבחרו {len(self.file_paths)} קבצים ברצף")
            
            # חישוב סך העמודים מכל הקבצים יחד (לא חובה, אבל נחמד לדעת)
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
        

    # החלף את הפונקציה extract_text הקיימת במחלקה HebrewTTSStudio בגרסה המשודרגת הזו:
    def extract_text(self):
        """
        גרסה משופרת הכוללת ניקוי מתקדם של פיסוק, סוגריים ואיחוד פסקאות חכם.
        """
        if not hasattr(self, 'file_paths') or not self.file_paths:
            QMessageBox.warning(self, "שגיאה", "לא נבחרו קבצים.")
            return

        self.lbl_status.setText("מייבא טקסט ומבצע ניקוי מתקדם...")
        self.progress_bar.setValue(0)
        
        if hasattr(self, 'pdf_viewer'):
            self.pdf_viewer.load_pdf(self.file_paths[0])

        full_text_accumulator = ""
        total_files = len(self.file_paths)

        try:
            for idx, f_path in enumerate(self.file_paths):
                try:
                    pdf_reader = PyPDF2.PdfReader(f_path)
                    total_pages = len(pdf_reader.pages)
                except Exception as e:
                    print(f"Error reading PDF {f_path}: {e}")
                    continue
                
                txt_start = self.input_start.text().strip() or "1"
                txt_end = self.input_end.text().strip() or str(total_pages)
                start_p = max(1, int(txt_start))
                end_p = min(total_pages, int(txt_end))

                for i in range(start_p - 1, end_p):
                    page_num = i + 1
                    # תגית עמוד לסנכרון
                    full_text_accumulator += f"\n\n[PAGE:{page_num}]\n"
                    
                    page_text = pdf_reader.pages[i].extract_text()
                    
                    if page_text:
                        # === שלב 1: ניקוי שורות זבל ===
                        lines = page_text.split('\n')
                        cleaned_lines = []
                        for line in lines:
                            stripped = line.strip()
                            # מסנן שורות שהן רק מספרים (כמו מספרי עמוד)
                            if re.match(r'^\s*\d+\s*$', stripped):
                                continue
                            if len(stripped) < 2 and stripped not in ['.', '!', '?']:
                                continue
                            cleaned_lines.append(stripped)

                        # === שלב 2: איחוד פסקאות חכם ===
                        # אם שורה לא נגמרת בנקודה/סימן שאלה/קריאה, נחבר אותה לשורה הבאה
                        smart_text = ""
                        for j, line in enumerate(cleaned_lines):
                            smart_text += line
                            # רשימת סיומות המעידות על סוף פסקה באמת
                            if line.endswith(('.', '!', '?', ':', ';', '"')):
                                smart_text += "\n" 
                            else:
                                smart_text += " " 

                        full_text_accumulator += smart_text

                self.progress_bar.setValue(int(((idx + 1) / total_files) * 100))

            # === שלב 3: פוליש סופי (Regex) - התיקון הגדול ===
            final_text = self.advanced_cleanup(full_text_accumulator)

            self.editor.setPlainText(final_text.strip())
            self.lbl_status.setText("הייבוא הושלם! (טקסט עבר סידור וניקוי)")
            
            if hasattr(self, 'sync_pdf_to_cursor'):
                self.sync_pdf_to_cursor()

        except Exception as e:
            QMessageBox.critical(self, "שגיאה בייבוא", f"תקלה בחילוץ: {str(e)}")
            import traceback
            traceback.print_exc()
            

    def apply_styles(self):
        self.setStyleSheet("""
            QMainWindow { background-color: #102A43; }
            QLabel, QCheckBox { color: #F0F4F8; font-size: 14px; font-family: Arial; }
            
            /* עיצוב הקבוצות החדש */
            QGroupBox {
                border: 1px solid #486581;
                border-radius: 6px;
                margin-top: 10px;
                color: #F0F4F8;
                font-weight: bold;
                background-color: #1A3C59; /* רקע טיפה שונה להפרדה */
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top center;
                padding: 0 5px;
                color: #62B0E8; /* צבע כותרת תכלת */
            }

            QTextEdit, QTableWidget { background-color: #243B53; color: #FFFFFF; border: 2px solid #486581; border-radius: 6px; padding: 12px; font-size: 16px; }
            QLineEdit, QComboBox, QSpinBox { background-color: #F0F4F8; padding: 6px; color: #102A43; border-radius: 4px; }
            
            QPushButton { background-color: #334E68; color: #FFFFFF; padding: 8px; font-weight: bold; border-radius: 5px; }
            QPushButton:hover { background-color: #486581; }
            
            QPushButton#PrimaryBtn { background-color: #F76707; font-size: 18px; border: 2px solid #D9480F; }
            QPushButton#PrimaryBtn:hover { background-color: #D9480F; }
            
            QPushButton#ActionBtn { background-color: #27AE60; }
            
            QFrame#Panel { background-color: #243B53; border-radius: 8px; border: 1px solid #334E68; }
            
            QProgressBar { border: 2px solid #334E68; border-radius: 5px; text-align: center; background-color: #102A43; color: white; }
            QProgressBar::chunk { background-color: #F76707; }
            
            QTabWidget::pane {
                border: 2px solid #334E68;
                border-top: none;
                background-color: #102A43;
                border-radius: 0 0 8px 8px;
            }
            QTabBar::tab {
                background: #1A3C59;
                color: #9FB3C8;
                padding: 12px 24px;
                margin-right: 3px;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                border: 2px solid transparent;
                border-bottom: none;
                font-family: 'Segoe UI Emoji', 'Segoe UI', Arial;
                font-size: 14px;
                font-weight: bold;
                min-width: 120px;
            }
            QTabBar::tab:hover {
                background: #243B53;
                color: #D9E2EC;
                border-color: #486581;
            }
            QTabBar::tab:selected {
                background: #102A43;
                color: #FFFFFF;
                border-color: #F76707;
                border-bottom: 3px solid #F76707;
            }
            QHeaderView::section { background-color: #334E68; color: white; padding: 4px; }
        """)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = HebrewTTSStudio()
    window.show()
    sys.exit(app.exec_())