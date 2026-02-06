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
import cv2
import numpy as np
from pdf2image import convert_from_path
import shutil
import unicodedata
import hashlib
import time  # וודא שביצעת import time למעלה בקובץ
import asyncio
import random
from pdf2image import convert_from_path  # <--- התיקון לשגיאה שלך
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
from src.workers.tts_worker import TTSWorker
from src.workers.nikud_worker import NikudWorker
from src.utils.text_tools import remove_nikud, advanced_cleanup

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

class PDFViewerWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True) # חשוב!
        self.scroll_area.setAlignment(Qt.AlignCenter)
        
        self.image_label = QLabel("טען קובץ PDF כדי לראות אותו כאן")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setStyleSheet("background-color: #525659; color: white; font-size: 16px;") 
        
        # הגדרת ה-Label בתוך ה-ScrollArea
        self.scroll_area.setWidget(self.image_label)
        self.layout.addWidget(self.scroll_area)
        
        self.current_pdf_path = None
        self.page_images = {} # מטמון: שומר את התמונות המקוריות (ברזולוציה גבוהה)
        self.current_page = 0

    def load_pdf(self, pdf_path):
        self.current_pdf_path = pdf_path
        self.page_images = {}
        self.show_page(1)

    def show_page(self, page_num):
        if not self.current_pdf_path: return
        
        # אם העמוד כבר בזיכרון, נשתמש בו
        if page_num in self.page_images:
            self.current_page = page_num
            self.update_display() # קריאה לפונקציית ההתאמה
            return

        try:
            # המרה
            images = convert_from_path(self.current_pdf_path, first_page=page_num, last_page=page_num, dpi=150)
            if images:
                pil_image = images[0]
                if pil_image.mode == "RGB":
                    r, g, b = pil_image.split()
                    pil_image = PILImage.merge("RGB", (b, g, r))
                elif pil_image.mode == "RGBA":
                    r, g, b, a = pil_image.split()
                    pil_image = PILImage.merge("RGBA", (b, g, r, a))
                
                im_data = pil_image.convert("RGBA").tobytes("raw", "RGBA")
                qim = QImage(im_data, pil_image.size[0], pil_image.size[1], QImage.Format_RGBA8888)
                pixmap = QPixmap.fromImage(qim)
                
                # שמירת המקור במטמון
                self.page_images[page_num] = pixmap
                self.current_page = page_num
                
                # הצגה מותאמת
                self.update_display()
                
        except Exception as e:
            print(f"Error loading PDF page {page_num}: {e}")
            self.image_label.setText(f"שגיאה בטעינת עמוד {page_num}")

    def update_display(self):
        """פונקציה שמתאימה את התמונה לרוחב החלון הנוכחי"""
        if self.current_page in self.page_images:
            original_pixmap = self.page_images[self.current_page]
            
            # חישוב הרוחב הזמין (פחות קצת שוליים לגלילה)
            available_width = self.scroll_area.width() - 25
            if available_width < 100: available_width = 100 # מינימום
            
            # שינוי גודל תוך שמירה על יחס גובה-רוחב
            scaled_pixmap = original_pixmap.scaledToWidth(available_width, Qt.SmoothTransformation)
            
            self.image_label.setPixmap(scaled_pixmap)

    def resizeEvent(self, event):
        """הופעל אוטומטית כשהמשתמש משנה את גודל החלון"""
        self.update_display()
        super().resizeEvent(event)
            
# --- העתק את פונקציית החיתוך החכם (מתוך app.py) ---
# אפשר להוסיף אותה לפני המחלקה HebrewTTSStudio
def crop_illustration_only(image_path):
    """
    גרסה v2: חיתוך כירורגי לגרפים ותמונות בלבד (מסנן טקסטים).
    """
    try:
        # 1. טעינה
        img = cv2.imread(image_path)
        if img is None: return False
        
        # המרה לגווני אפור
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        # 2. הפיכה לבינארי (הפוך: טקסט/קוים בלבן, רקע בשחור)
        # שימוש ב-OTSU לקביעת סף דינאמי וטוב יותר
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        # === שלב סינון הטקסט ===
        # יצירת "מסיכה" שתשמש רק לזיהוי המיקום (לא משנה את התמונה המקורית)
        detection_mask = thresh.copy()
        
        # זיהוי שורות טקסט: אלו בד"כ קווים אופקיים
        # אנחנו מחפשים דברים שהם רחבים אבל נמוכים
        contours, _ = cv2.findContours(detection_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        img_h, img_w = img.shape[:2]
        
        for c in contours:
            x, y, w, h = cv2.boundingRect(c)
            
            # לוגיקה: אם זה נראה כמו שורת טקסט - נצבע את זה בשחור (נמחוק מהזיהוי)
            # תנאי 1: גובה קטן (פחות מ-5% מהדף)
            # תנאי 2: רוחב משמעותי (יותר מ-10% מהדף) - כדי לא למחוק מקרא קטן בתוך גרף
            # תנאי 3: יחס רוחב/גובה קיצוני (טקסט הוא מלבן מאורך)
            
            aspect_ratio = w / float(h)
            is_text_line = (h < img_h * 0.05) and (aspect_ratio > 3)
            
            # מחיקת שורות טקסט מהמסיכה
            if is_text_line:
                cv2.drawContours(detection_mask, [c], -1, (0, 0, 0), -1)

        # === שלב איחוד הגרף ===
        # עכשיו שנשארנו (בתקווה) בלי פסקאות, נאחד את מה שנשאר (קווי הגרף)
        # משתמשים בקרנל קטן יותר (9,9) במקום (25,25) כדי לא לחבר בטעות כותרות קרובות
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9))
        dilated = cv2.dilate(detection_mask, kernel, iterations=4)

        # מציאת קווי המתאר הסופיים
        contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        if not contours: return False

        # מציאת הקונטור הגדול ביותר (הגרף עצמו)
        largest_contour = max(contours, key=cv2.contourArea)
        
        # סינון רעש: אם הגרף קטן מדי (פחות מ-5% משטח הדף), כנראה אין גרף אלא סתם לכלוך
        page_area = img_w * img_h
        if cv2.contourArea(largest_contour) < (page_area * 0.05):
            print(f"Skipping {image_path}: Largest object is too small (likely noise/text remains).")
            return False

        # קבלת המלבן החוסם
        x, y, w, h = cv2.boundingRect(largest_contour)

        # הוספת מעט "אוויר" (Padding), אבל בזהירות לא לצאת מהגבולות
        pad = 15
        x_start = max(0, x - pad)
        y_start = max(0, y - pad)
        x_end = min(img_w, x + w + pad)
        y_end = min(img_h, y + h + pad)

        # ביצוע החיתוך על התמונה המקורית הצבעונית
        cropped_img = img[y_start:y_end, x_start:x_end]
        
        if cropped_img.size == 0: return False

        cv2.imwrite(image_path, cropped_img)
        return True

    except Exception as e:
        print(f"Crop Error: {e}")
        return False
    



class ProgressFileReader:
    def __init__(self, filename, callback):
        self._file = open(filename, 'rb')
        self._total_size = os.path.getsize(filename)
        self._bytes_read = 0
        self._callback = callback
        self._start_time = time.time()
        print(f"[DEBUG-READER] Opened file: {filename} | Size: {self._total_size} bytes")

    def read(self, size=-1):
        # הדפסה רק בקריאה הראשונה כדי לא להציף את הלוג
        if self._bytes_read == 0:
            print(f"[DEBUG-READER] First read requested. Size arg: {size}")

        data = self._file.read(size)
        
        if data:
            self._bytes_read += len(data)
            if self._callback:
                self._callback(self._bytes_read, self._total_size)
        else:
            # הגענו לסוף הקובץ
            elapsed = time.time() - self._start_time
            print(f"[DEBUG-READER] Finished reading file. Time elapsed: {elapsed:.2f}s")
        
        return data

    def __len__(self):
        # requests משתמש בזה כדי לקבוע את ה-Content-Length
        return self._total_size

    def close(self):
        print("[DEBUG-READER] Closing file.")
        self._file.close()

    def __getattr__(self, attr):
        return getattr(self._file, attr)


class TelegramWorker(QThread):
    finished = pyqtSignal()
    upload_progress = pyqtSignal(int)
    log_update = pyqtSignal(str)

    def __init__(self, token, chat_id, files_list):
        """
        files_list: רשימה של טאפלים [(path, type), ...]
        type יכול להיות 'audio' או 'document'
        """
        super().__init__()
        self.token = token
        self.chat_id = chat_id
        self.files_list = files_list

    def run(self):
        print(f"\n--- [DEBUG] Starting Batch Telegram Upload ---")
        
        total_files = len(self.files_list)
        
        for index, (file_path, msg_type) in enumerate(self.files_list):
            if not file_path or not os.path.exists(file_path):
                continue

            filename = os.path.basename(file_path)
            self.log_update.emit(f"שולח לטלגרם ({index+1}/{total_files}): {filename}...")

            # הגדרת סוג השליחה (אודיו או מסמך)
            if msg_type == 'audio':
                endpoint = "sendAudio"
                field_name = "audio"
            else:
                endpoint = "sendDocument"
                field_name = "document"

            url = f"https://api.telegram.org/bot{self.token}/{endpoint}"
            boundary = '----WebKitFormBoundary7MA4YWxkTrZu0gW'
            
            # קידוד שם הקובץ
            filename_header = filename.replace('"', '\\"')
            
            # הכנת ה-Header
            part_boundary = f'--{boundary}\r\n'.encode('utf-8')
            end_boundary = f'\r\n--{boundary}--\r\n'.encode('utf-8')
            
            payload_meta = []
            payload_meta.append(part_boundary)
            payload_meta.append(f'Content-Disposition: form-data; name="chat_id"\r\n\r\n{self.chat_id}\r\n'.encode('utf-8'))
            
            # Caption (רק לקובץ הראשון או לכולם, לבחירתך. כאן שמנו רק לאודיו)
            if msg_type == 'audio':
                payload_meta.append(part_boundary)
                payload_meta.append(f'Content-Disposition: form-data; name="caption"\r\n\r\nHebrew TTS Studio\r\n'.encode('utf-8'))
            
            # File Header
            payload_meta.append(part_boundary)
            header_str = f'Content-Disposition: form-data; name="{field_name}"; filename="{filename_header}"\r\n'
            payload_meta.append(header_str.encode('utf-8'))
            
            # קביעת MIME Type
            mime_type = "audio/mpeg" if msg_type == 'audio' else "application/pdf"
            payload_meta.append(f'Content-Type: {mime_type}\r\n\r\n'.encode('utf-8'))
            
            header_bytes = b''.join(payload_meta)
            file_size = os.path.getsize(file_path)
            total_packet_size = len(header_bytes) + file_size + len(end_boundary)
            
            # פונקציית Streaming
            def data_generator():
                yield header_bytes
                bytes_sent = 0
                with open(file_path, 'rb') as f:
                    while True:
                        chunk = f.read(8192 * 4)
                        if not chunk: break
                        yield chunk
                        bytes_sent += len(chunk)
                        
                        # חישוב אחוזים יחסי לקובץ הנוכחי בתוך התהליך הכולל
                        file_percent = (bytes_sent / file_size)
                        total_percent = int(((index + file_percent) / total_files) * 100)
                        self.upload_progress.emit(total_percent)
                yield end_boundary

            try:
                headers = {'Content-Type': f'multipart/form-data; boundary={boundary}'}
                response = requests.post(url, data=data_generator(), headers=headers, timeout=300)
                
                if response.status_code != 200:
                    self.log_update.emit(f"שגיאה בשליחת {filename}: {response.status_code}")
                    print(f"[ERROR] Telegram Response: {response.text}")
            except Exception as e:
                self.log_update.emit(f"תקלה בשליחה: {str(e)}")

        self.upload_progress.emit(100)
        self.finished.emit()
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
            
            if self.parent_window:
                self.parent_window.add_error_to_review(text)
        else:
            # === ביטול טעות (חזרה לרגיל) ===
            # אנחנו לוקחים את הפורמט של הטקסט הכללי (לא אדום)
            default_fmt = QTextCharFormat()
            default_fmt.setForeground(self.palette().color(self.foregroundRole()))
            default_fmt.setFontUnderline(False)
            
            cursor.setCharFormat(default_fmt)
            
            if self.parent_window:
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


class AdvancedImportDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ייבוא מתקדם - בחירת עמודים וקבצים")
        self.resize(900, 500)
        self.setLayoutDirection(Qt.RightToLeft)
        
        self.layout = QVBoxLayout(self)

        lbl_info = QLabel("כאן ניתן להוסיף קבצים ולקבוע לכל אחד אילו עמודים לייבא.\n"
                          "פורמט עמודים: 1-5, 8, 10-12 (או להשאיר ריק כדי לייבא הכל).")
        lbl_info.setStyleSheet("font-size: 14px; color: #ccc;")
        self.layout.addWidget(lbl_info)

        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["קובץ", "טווח עמודים (למשל 1-3, 5)", "מידע"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Interactive)
        self.table.setColumnWidth(1, 200)
        self.layout.addWidget(self.table)

        btn_layout = QHBoxLayout()
        btn_add = QPushButton("➕ הוסף קבצים"); btn_add.clicked.connect(self.add_files)
        btn_dup = QPushButton("📑 שכפל שורה"); btn_dup.clicked.connect(self.duplicate_row)
        btn_del = QPushButton("➖ הסר"); btn_del.clicked.connect(self.remove_row)
        
        btn_layout.addWidget(btn_add); btn_layout.addWidget(btn_dup); btn_layout.addWidget(btn_del); btn_layout.addStretch()
        self.layout.addLayout(btn_layout)
        
        self.btn_import = QPushButton("⬇️ בצע ייבוא וסגור")
        self.btn_import.setStyleSheet("background-color: #27AE60; color: white; font-weight: bold; padding: 10px;")
        self.btn_import.clicked.connect(self.run_extraction)
        self.layout.addWidget(self.btn_import)
        
        self.result_text = ""

    def add_files(self):
        fnames, _ = QFileDialog.getOpenFileNames(self, "בחר קבצי PDF", "", "PDF Files (*.pdf)")
        if fnames:
            for f in sorted(fnames): self._add_row(f)

    def _add_row(self, file_path):
        row = self.table.rowCount()
        self.table.insertRow(row)
        
        item_name = QTableWidgetItem(os.path.basename(file_path))
        item_name.setToolTip(file_path)
        item_name.setData(Qt.UserRole, file_path)
        self.table.setItem(row, 0, item_name)
        
        # ברירת מחדל: מחרוזת ריקה = כל העמודים
        self.table.setItem(row, 1, QTableWidgetItem(""))
        
        try:
            with open(file_path, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
                cnt = len(reader.pages)
                self.table.setItem(row, 2, QTableWidgetItem(f"{cnt} עמודים"))
        except: self.table.setItem(row, 2, QTableWidgetItem("שגיאה"))

    def duplicate_row(self):
        curr = self.table.currentRow()
        if curr < 0: return
        path = self.table.item(curr, 0).data(Qt.UserRole)
        self._add_row(path)

    def remove_row(self):
        curr = self.table.currentRow()
        if curr >= 0: self.table.removeRow(curr)

    def parse_page_string(self, range_str, max_pages):
        """מפענח מחרוזת עם דיבאג"""
        print(f"  - [DEBUG PARSE] Input string: '{range_str}'")
        
        # אם המחרוזת ריקה - מחזירים הכל
        if not range_str or not range_str.strip():
            print("  - [DEBUG PARSE] String is empty -> Selecting ALL pages.")
            return list(range(max_pages))
            
        pages = set()
        # ניקוי רווחים מיותרים
        parts = range_str.replace(" ", "").split(',')
        
        for part in parts:
            try:
                if '-' in part:
                    start, end = map(int, part.split('-'))
                    # לולאה מ-Start עד End (כולל)
                    for i in range(start, end + 1):
                        if 1 <= i <= max_pages:
                            pages.add(i - 1) # המרה ל-0 based
                else:
                    pg = int(part)
                    if 1 <= pg <= max_pages:
                        pages.add(pg - 1)
            except ValueError:
                print(f"  - [DEBUG PARSE] Warning: Could not parse part '{part}'")
                continue
                
        result = sorted(list(pages))
        print(f"  - [DEBUG PARSE] Final indices list: {result}")
        return result

    def run_extraction(self):
        print("\n--- [DEBUG] Starting Advanced Import Process ---")
        full_text = ""
        
        rows = self.table.rowCount()
        print(f"[DEBUG] Total rows found in table: {rows}")

        for i in range(rows):
            # שליפת נתיב הקובץ
            path = self.table.item(i, 0).data(Qt.UserRole)
            
            # שליפת טווח העמודים (טקסט)
            item_range = self.table.item(i, 1)
            range_str = item_range.text().strip() if item_range else ""
            
            print(f"\n[DEBUG] Processing Row {i}:")
            print(f"  - File: {os.path.basename(path)}")
            print(f"  - Range Text from Table: '{range_str}'")
            
            try:
                with open(path, 'rb') as f:
                    reader = PyPDF2.PdfReader(f)
                    total_pages = len(reader.pages)
                    print(f"  - PDF Total Pages: {total_pages}")
                    
                    # חישוב האינדקסים
                    indices_to_extract = self.parse_page_string(range_str, total_pages)
                    
                    if not indices_to_extract:
                        print("  - [WARNING] No pages selected for this row!")
                    
                    file_text = ""
                    for idx in indices_to_extract:
                        try:
                            page_text = reader.pages[idx].extract_text()
                            if page_text:
                                lines = page_text.split('\n')
                                filtered = [l for l in lines if not re.match(r'^\s*\d+\s*$', l)]
                                file_text += " ".join(filtered) + " "
                        except Exception as e_page:
                            print(f"  - [ERROR] Failed to extract page index {idx}: {e_page}")

                    full_text += file_text + "\n\n"
                    print(f"  - Extracted {len(file_text)} chars from this row.")
                    
            except Exception as e:
                print(f"[ERROR] Failed to process row {i}: {e}")
        
        self.result_text = re.sub(r'\s+', ' ', full_text).strip()
        print("--- [DEBUG] Finished Import ---\n")
        self.accept()




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

# --- מחלקה ליצירת אודיו זמני לבדיקה ---
class AudioPreviewWorker(QThread):
    # האות מחזיר כעת שני דברים: את המפתח הייחודי ואת המידע עצמו
    finished_data = pyqtSignal(str, bytes) 

    def __init__(self, cache_key, text, voice, speed):
        super().__init__()
        self.cache_key = cache_key
        self.text = text
        self.voice = voice
        self.speed = speed

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self.generate())
        loop.close()

    async def generate(self):
        try:
            data = b""
            communicate = edge_tts.Communicate(self.text, self.voice, rate=self.speed)
            
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    data += chunk["data"]
            
            # החזרת המפתח והמידע
            self.finished_data.emit(self.cache_key, data)
            
        except Exception as e:
            print(f"Preview Memory Error: {e}")

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

class JumpSlider(QSlider):
    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self.setLayoutDirection(Qt.RightToLeft) # כיוון מימין לשמאל

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            # חישוב הערך בהתאם למיקום הלחיצה
            val = self.pixelPosToRangeValue(event.pos())
            self.setValue(val)
            
            # משדרים שהסליידר זז כדי שהנגן יתעדכן מיד
            self.sliderMoved.emit(val)
            
        # חשוב מאוד: קריאה למקור כדי לאפשר את הגרירה!
        super().mousePressEvent(event)

    def pixelPosToRangeValue(self, pos):
        # === התיקון כאן: יצירה ישירה של האובייקט ===
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        
        # חישוב האזור הפעיל של הסליידר (בלי השוליים)
        gr = self.style().subControlRect(QStyle.CC_Slider, opt, QStyle.SC_SliderGroove, self)
        sr = self.style().subControlRect(QStyle.CC_Slider, opt, QStyle.SC_SliderHandle, self)

        sliderMin = gr.x()
        sliderMax = gr.right() - sr.width() + 1
        
        # הגנה מפני חלוקה באפס (למקרה שהחלון טרם עלה)
        sliderLength = sliderMax - sliderMin
        if sliderLength <= 0: return self.minimum()

        # מיקום העכבר
        pos_x = pos.x()
        
        # המרה לאחוזים (0.0 עד 1.0)
        # בגלל RTL (ימין לשמאל), אנחנו הופכים את החישוב: ימין=0, שמאל=1
        pct = 1.0 - ((pos_x - sliderMin) / sliderLength)
        
        # הגבלות בין 0 ל-1
        pct = max(0, min(1, pct))
        
        return int(self.minimum() + pct * (self.maximum() - self.minimum()))

class KaraokeTab(QWidget):
    
    def change_playback_rate(self):
        """משנה את מהירות הניגון של ה-QMediaPlayer"""
        speed_str = self.combo_playback_speed.currentText().replace("x", "")
        try:
            speed_float = float(speed_str)
            # פקודה זו משנה את המהירות בנגן עצמו
            self.player.setPlaybackRate(speed_float)
            print(f"[DEBUG] Playback rate changed to: {speed_float}")
        except Exception as e:
            print(f"[ERROR] Failed to set playback rate: {e}")
    
    def adjust_speed_step(self, direction):
        idx = self.combo_playback_speed.currentIndex()
        new_idx = max(0, min(self.combo_playback_speed.count() - 1, idx + direction))
        self.combo_playback_speed.setCurrentIndex(new_idx)
    
    def __init__(self, output_dir, parent=None):
        super().__init__(parent)
        self.output_dir = output_dir
        self.main_window = parent
        
        # וידוא שתיקיית המסמכים קיימת
        if not os.path.exists(self.output_dir):
            try:
                os.makedirs(self.output_dir, exist_ok=True)
            except: pass

        self.current_json_data = []
        self.sentence_ranges = []
        self.current_file_id = None
        self.current_pdf_path = None 
        self.marked_errors = set() # למעקב אחרי מילים שסומנו באדום
        
        # הגדרות עיצוב ברירת מחדל
        self.styles = {
            'line_spacing': 150, 
            'active_fg': '#F1C40F', 'active_bg': 'transparent', 'active_size': 26, 
            'active_bold': True, 'active_italic': False, 'active_underline': False,
            'inactive_fg': '#BDC3C7', 'inactive_bg': 'transparent', 'inactive_size': 18, 
            'inactive_bold': False, 'inactive_italic': False, 'inactive_underline': False
        }
        
        # טעינת הגדרות שמורות
        if self.main_window and hasattr(self.main_window, 'settings'):
            saved_styles = self.main_window.settings.get("karaoke_styles", {})
            self.styles.update(saved_styles)
        
        self.is_nikud_visible = True
        self.sync_offset_ms = 0
        self.last_highlighted_index = -1
        self.auto_scroll_enabled = True 
        self.user_is_dragging = False
        self.user_is_scrolling = False

        # נגן
        self.player = QMediaPlayer(None, QMediaPlayer.StreamPlayback)
        self.player.setNotifyInterval(50)
        
        self.player.positionChanged.connect(self.on_position_changed)
        self.player.durationChanged.connect(self.on_duration_changed)
        self.player.stateChanged.connect(self.on_state_changed)
        
        self.init_ui()
        self.refresh_file_list()

    def init_ui(self):
        main_layout = QHBoxLayout(self)
        
        # === צד ימין: רשימת פרויקטים (עם קיפול) ===
        self.main_horizontal_splitter = QSplitter(Qt.Horizontal)
        
        self.files_container = QWidget()
        files_layout = QVBoxLayout(self.files_container)
        files_layout.setContentsMargins(0, 0, 5, 0)
        
        self.list_files = QTreeWidget()
        self.list_files.setHeaderHidden(True)
        self.list_files.itemClicked.connect(self.on_file_selected)
        # עיצוב העץ
        self.list_files.setStyleSheet("""
            QTreeWidget { background-color: #243B53; color: white; border: 1px solid #486581; border-radius: 4px; }
            QTreeWidget::item:selected { background-color: #F76707; }
        """)
        
        files_layout.addWidget(QLabel("📂 פרויקטים:"))
        # --- הנה הכפתור שהיה חסר ---
        btn_import = QPushButton("📥 ייבא פרויקט")
        btn_import.setStyleSheet("background-color: #2980B9; color: white; padding: 6px; font-weight: bold; border-radius: 4px;")
        btn_import.clicked.connect(self.import_external_project)
        files_layout.addWidget(btn_import)
        # ---------------------------
        files_layout.addWidget(self.list_files)
        
        self.main_horizontal_splitter.addWidget(self.files_container)
        
        # === צד שמאל: נגן ו-PDF ===
        self.content_splitter = QSplitter(Qt.Horizontal)
        
        # 1. PDF Viewer
        self.pdf_viewer = PDFViewerWidget()
        self.content_splitter.addWidget(self.pdf_viewer)
        
        # 2. אזור הנגן והטקסט
        player_area = QWidget()
        player_layout = QVBoxLayout(player_area)
        
        # -- סרגל כלים עליון (רק כפתורי תצוגה) --
        toolbar = QHBoxLayout()
        
        # כפתור קיפול רשימה
        self.btn_toggle_sidebar = QPushButton("📁")
        self.btn_toggle_sidebar.setFixedWidth(40)
        self.btn_toggle_sidebar.setToolTip("הצג/הסתר רשימת קבצים")
        self.btn_toggle_sidebar.clicked.connect(self.toggle_sidebar)
        toolbar.addWidget(self.btn_toggle_sidebar)
        
        # כפתורים מקוריים (גלילה, עיצוב, ניקוד)
        self.btn_auto_scroll = QPushButton("🔒 גלילה אוטומטית")
        self.btn_auto_scroll.setCheckable(True); self.btn_auto_scroll.setChecked(True)
        self.btn_auto_scroll.clicked.connect(self.toggle_auto_scroll)
        toolbar.addWidget(self.btn_auto_scroll)
        
        btn_style = QPushButton("🎨 עיצוב"); btn_style.clicked.connect(self.open_style_editor)
        toolbar.addWidget(btn_style)
        
        self.btn_toggle_nikud = QPushButton("הסתר ניקוד"); self.btn_toggle_nikud.setCheckable(True); self.btn_toggle_nikud.clicked.connect(self.toggle_nikud)
        toolbar.addWidget(self.btn_toggle_nikud)
        
        toolbar.addStretch()
        player_layout.addLayout(toolbar)
        
        # -- תצוגת הטקסט --
        self.text_display = QTextEdit()
        self.text_display.setReadOnly(True)
        # === הנה השורה שקובעת את הרקע השחור רק לטאב הזה ===
        self.text_display.setStyleSheet("""
            QTextEdit { 
                background-color: #000000;  /* רקע שחור/כהה */
                color: #FFFFFF;             /* טקסט לבן */
                border: none; 
                padding: 20px;
                font-size: 20px;            /* גודל פונט ברירת מחדל נוח */
            }
        """)
        self.text_display.viewport().installEventFilter(self)
        player_layout.addWidget(self.text_display)
        
        # -- פקדי נגן (למטה) --
        controls_container = QFrame()
        controls_container.setStyleSheet("background-color: #1A3C59; border-radius: 10px; padding: 10px;")
        controls_layout = QVBoxLayout(controls_container)
        
        # סליידר זמן
        slider_layout = QHBoxLayout()
        self.lbl_current_time = QLabel("00:00")
        self.lbl_total_time = QLabel("00:00")
        self.slider = JumpSlider(Qt.Horizontal)
        self.slider.sliderMoved.connect(self.on_slider_moved)
        self.slider.sliderPressed.connect(self.on_slider_pressed)
        self.slider.sliderReleased.connect(self.on_slider_released)
        
        slider_layout.addWidget(self.lbl_current_time)
        slider_layout.addWidget(self.slider)
        slider_layout.addWidget(self.lbl_total_time)
        controls_layout.addLayout(slider_layout)
        
        # כפתורי שליטה + סליידר מהירות
        btns = QHBoxLayout()
        
        # כפתורי Play/Seek
        btn_rw = QPushButton("-15"); btn_rw.setFixedSize(50, 40); btn_rw.clicked.connect(lambda: self.seek_relative(-15000))
        self.btn_play = QPushButton("▶"); self.btn_play.setFixedSize(60, 60); self.btn_play.clicked.connect(self.toggle_play)
        self.btn_play.setStyleSheet("background-color: #27AE60; font-size: 28px; border-radius: 30px; color: white;")
        btn_fw = QPushButton("+15"); btn_fw.setFixedSize(50, 40); btn_fw.clicked.connect(lambda: self.seek_relative(15000))
        
        btns.addStretch()
        btns.addWidget(btn_rw)
        btns.addWidget(self.btn_play)
        btns.addWidget(btn_fw)
        
        # --- אזור מהירות (ליד הכפתורים) ---
        btns.addSpacing(30) # רווח בין הכפתורים למהירות
        
        speed_container = QWidget()
        speed_layout = QVBoxLayout(speed_container)
        speed_layout.setContentsMargins(0,0,0,0)
        speed_layout.setSpacing(2)
        
        lbl_spd_title = QLabel("מהירות")
        lbl_spd_title.setAlignment(Qt.AlignCenter)
        lbl_spd_title.setStyleSheet("font-size: 14px; color: #BDC3C7;")
        
        speed_row = QHBoxLayout()
        self.speed_slider = QSlider(Qt.Horizontal)
        self.speed_slider.setRange(50, 200) # 0.5x עד 2.0x
        self.speed_slider.setValue(100)
        self.speed_slider.setFixedWidth(150)
        self.speed_slider.valueChanged.connect(self.change_playback_rate)
        
        self.lbl_speed_display = QLabel("1.0x")
        self.lbl_speed_display.setStyleSheet("font-weight: bold; font-size: 11px;")
        self.lbl_speed_display.setFixedWidth(50)
        self.lbl_speed_display.setAlignment(Qt.AlignCenter)
        
        speed_row.addWidget(self.speed_slider)
        speed_row.addWidget(self.lbl_speed_display)
        
        speed_layout.addWidget(lbl_spd_title)
        speed_layout.addLayout(speed_row)
        
        btns.addWidget(speed_container)
        btns.addStretch()
        
        controls_layout.addLayout(btns)
        player_layout.addWidget(controls_container)
        
        self.content_splitter.addWidget(player_area)
        self.main_horizontal_splitter.addWidget(self.content_splitter)
        self.main_horizontal_splitter.setSizes([250, 1000])
        
        main_layout.addWidget(self.main_horizontal_splitter)

    # פונקציות שליטה חדשות
    def toggle_sidebar(self):
        sizes = self.main_horizontal_splitter.sizes()
        if sizes[0] > 0:
            self.main_horizontal_splitter.setSizes([0, 1000])
        else:
            self.main_horizontal_splitter.setSizes([250, 1000])

    def change_playback_rate(self):
        """מעדכן את מהירות הנגן לפי הסליידר"""
        speed_val = self.speed_slider.value() / 100.0
        self.player.setPlaybackRate(speed_val)
        self.lbl_speed_display.setText(f"{speed_val:.1f}x")

    def on_file_selected(self, item, column=0):
        # הגנה: אם לחצו על כותרת קבוצה
        if item.childCount() > 0 or not item.parent():
            item.setExpanded(not item.isExpanded())
            return

        json_path = item.data(0, Qt.UserRole)
        if not json_path: return 

        self.save_progress()
        self.marked_errors.clear()
        
        # שימוש ב-splitext כדי להחליף סיומת בצורה בטוחה יותר
        base_path = os.path.splitext(json_path)[0]
        mp3_path = base_path + ".mp3"
        pdf_path = base_path + ".pdf"
        
        print(f"\n[DEBUG] Selected Project: {os.path.basename(json_path)}")
        print(f"[DEBUG] Looking for PDF at: {pdf_path}")

        self.current_file_id = os.path.basename(json_path)
        
        # טעינת נתונים
        self.load_project(json_path, mp3_path)
        
        # בדיקת קיום PDF וטעינתו
        if os.path.exists(pdf_path):
            print("[DEBUG] ✅ Local PDF found! Loading...")
            self.pdf_viewer.load_pdf(pdf_path)
        else:
            print("[DEBUG] ❌ Local PDF NOT found.")
            # ניסיון טעינה מהזיכרון של החלון הראשי (Fallback)
            if self.main_window and hasattr(self.main_window, 'file_path') and self.main_window.file_path:
                print(f"[DEBUG] Loading original source PDF: {self.main_window.file_path}")
                self.pdf_viewer.load_pdf(self.main_window.file_path)
            else:
                # איפוס ה-Viewer אם אין שום PDF
                self.pdf_viewer.image_label.setText("לא נמצא קובץ PDF לפרויקט זה")

    def toggle_sidebar(self):
        # בדיקה אם הרשימה כרגע גלויה (גודל גדול מ-0)
        sizes = self.main_horizontal_splitter.sizes()
        if sizes[0] > 0:
            self.main_horizontal_splitter.setSizes([0, 1000]) # קיפול
        else:
            self.main_horizontal_splitter.setSizes([250, 1000]) # הרחבה

    # === טיפול באירועי עכבר (החלק שהיה חסר) ===
    
    def eventFilter(self, source, event):
        if source is self.text_display.viewport():
            # קליק ימני - סימון טעות
            if event.type() == QEvent.MouseButtonPress and event.button() == Qt.RightButton:
                self.handle_right_click_action(event.globalPos())
                return True
            # דאבל קליק שמאלי - קפיצה בזמן
            elif event.type() == QEvent.MouseButtonDblClick and event.button() == Qt.LeftButton:
                self.handle_left_click_seek(event.pos())
                return True
        return super().eventFilter(source, event)

    def handle_right_click_action(self, global_pos):
        """טיפול בלחיצה ימנית - סימון באדום ושליחה לטבלת טעויות"""
        viewport_pos = self.text_display.viewport().mapFromGlobal(global_pos)
        cursor = self.text_display.cursorForPosition(viewport_pos)
        cursor.select(QTextCursor.WordUnderCursor)
        selected_word = cursor.selectedText().strip()
        
        if not selected_word or not any(c.isalnum() for c in selected_word):
            return
        
        # ניקוי ניקוד למפתח
        clean_key = "".join([c for c in unicodedata.normalize('NFD', selected_word) if not unicodedata.combining(c)])
        
        if not self.main_window: return

        # טוגל: אם כבר אדום -> בטל, אם לא -> סמן
        if clean_key in self.marked_errors:
            self.marked_errors.remove(clean_key)
            if hasattr(self.main_window, 'remove_error_from_review'):
                self.main_window.remove_error_from_review(selected_word)
            
            # שחזור צבע רגיל
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(self.styles['inactive_fg']))
            fmt.setFontPointSize(float(self.styles.get('inactive_size', 16)))
            cursor.setCharFormat(fmt)
        else:
            self.marked_errors.add(clean_key)
            if hasattr(self.main_window, 'add_error_to_review'):
                self.main_window.add_error_to_review(selected_word)
            
            # סימון באדום
            fmt = QTextCharFormat()
            fmt.setForeground(QColor("red"))
            fmt.setFontUnderline(True)
            fmt.setUnderlineColor(QColor("red"))
            fmt.setFontPointSize(float(self.styles.get('inactive_size', 16)))
            cursor.setCharFormat(fmt)

    def handle_left_click_seek(self, pos):
        """טיפול בדאבל קליק - קפיצה לזמן המתאים"""
        cursor = self.text_display.cursorForPosition(pos)
        clicked_idx = cursor.position()
        
        # חיפוש המשפט שלחצנו עליו
        found = -1
        for i, range_data in enumerate(self.sentence_ranges):
            if range_data: # דילוג על טריגרים מוסתרים
                start, end = range_data
                if start <= clicked_idx < end:
                    found = i
                    break
        
        if found != -1 and found < len(self.current_json_data):
            # מציאת זמן ההתחלה וקפיצה
            target_ms = self.current_json_data[found].get('start', 0)
            self.player.setPosition(target_ms)
            self.apply_highlight(found, force=True)
            print(f"[SEEK] Jumped to index {found} at {target_ms}ms")

    # === ייבוא פרויקטים (החלק שהיה חסר) ===

    def import_external_project(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "בחר קובץ MP3 או JSON", "", "Project Files (*.json *.mp3)")
        if not file_path: return
        
        filename = os.path.basename(file_path)
        # חילוץ השם ללא סיומת
        base_name = os.path.splitext(filename)[0]
        dir_name = os.path.dirname(file_path)
        
        # בניית נתיבים למקור
        source_mp3 = os.path.join(dir_name, base_name + ".mp3")
        source_json = os.path.join(dir_name, base_name + ".json")
        source_pdf = os.path.join(dir_name, base_name + ".pdf") # <--- הוספנו חיפוש PDF
        
        # בניית נתיבים ליעד
        target_mp3 = os.path.join(self.output_dir, base_name + ".mp3")
        target_json = os.path.join(self.output_dir, base_name + ".json")
        target_pdf = os.path.join(self.output_dir, base_name + ".pdf")

        # בדיקה שקבצי החובה קיימים
        if not os.path.exists(source_mp3) or not os.path.exists(source_json):
            QMessageBox.warning(self, "חסר קובץ", "כדי לייבא פרויקט, חובה שיהיו קבצי MP3 ו-JSON באותה תיקייה עם אותו שם.")
            return

        try:
            import shutil
            # העתקת קבצי חובה
            if os.path.abspath(source_mp3) != os.path.abspath(target_mp3):
                shutil.copy2(source_mp3, target_mp3)
            if os.path.abspath(source_json) != os.path.abspath(target_json):
                shutil.copy2(source_json, target_json)
            
            # העתקת PDF (אופציונלי - רק אם קיים במקור)
            if os.path.exists(source_pdf):
                if os.path.abspath(source_pdf) != os.path.abspath(target_pdf):
                    shutil.copy2(source_pdf, target_pdf)
                    print(f"[DEBUG] Imported PDF successfully: {target_pdf}")
            
            self.refresh_file_list()
            self.select_file_by_path(target_json)
            QMessageBox.information(self, "הצלחה", "הפרויקט (כולל PDF אם היה) יובא בהצלחה!")
            
        except Exception as e:
            QMessageBox.critical(self, "שגיאה", f"תקלה בייבוא: {e}")

    # === ניהול קבצים סטנדרטי ===

    def refresh_file_list(self):
        self.list_files.clear()
        if not os.path.exists(self.output_dir): return
        
        # 1. איסוף כל הקבצים ומיון לפי תאריך (הכי חדש למעלה)
        files = []
        for f in os.listdir(self.output_dir):
            if f.endswith(".json"):
                full_path = os.path.join(self.output_dir, f)
                # בודקים שיש MP3 תואם
                if os.path.exists(full_path.replace(".json", ".mp3")):
                    mod_time = os.path.getmtime(full_path)
                    files.append((f, full_path, mod_time))
        
        # מיון: מהחדש לישן
        files.sort(key=lambda x: x[2], reverse=True)
        
        # 2. יצירת קבוצות (Top Level Items)
        groups = {
            "today": QTreeWidgetItem(["📅 היום"]),
            "yesterday": QTreeWidgetItem(["⏮️ אתמול"]),
            "week": QTreeWidgetItem(["🗓️ השבוע"]),
            "month": QTreeWidgetItem(["🗄️ החודש"]),
            "older": QTreeWidgetItem(["⏳ ישנים יותר"])
        }
        
        # הוספת הקבוצות לעץ ועיצוב
        for key in ["today", "yesterday", "week", "month", "older"]:
            item = groups[key]
            # עיצוב מודגש לכותרת
            font = item.font(0)
            font.setBold(True)
            item.setFont(0, font)
            item.setForeground(0, QColor("#F1C40F")) # צבע צהבהב לכותרות
            self.list_files.addTopLevelItem(item)
            item.setExpanded(False) # ברירת מחדל: מקופל

        # נפתח את "היום" כברירת מחדל
        groups["today"].setExpanded(True)

        # 3. מיון הקבצים לתוך הקבוצות
        now = datetime.now()
        today_start = datetime(now.year, now.month, now.day).timestamp()
        
        for fname, fpath, ftime in files:
            # יצירת פריט קובץ
            display_name = os.path.splitext(fname)[0]
            file_item = QTreeWidgetItem([display_name])
            file_item.setData(0, Qt.UserRole, fpath)
            file_item.setToolTip(0, fpath)
            
            # בדיקה לאן לשייך
            diff_days = (now - datetime.fromtimestamp(ftime)).days
            
            if ftime >= today_start:
                groups["today"].addChild(file_item)
            elif diff_days == 1: # שימו לב: זה תלוי שעה, לדיוק מוחלט צריך השוואת תאריכים
                groups["yesterday"].addChild(file_item)
            elif diff_days < 7:
                groups["week"].addChild(file_item)
            elif diff_days < 30:
                groups["month"].addChild(file_item)
            else:
                groups["older"].addChild(file_item)

        # 4. ניקוי קבוצות ריקות (אופציונלי - כדי לא להציג כותרות סתם)
        root = self.list_files.invisibleRootItem()
        for i in reversed(range(root.childCount())):
            item = root.child(i)
            if item.childCount() == 0:
                root.removeChild(item)

    def on_file_selected(self, item, column=0):
        if item.childCount() > 0 or not item.parent():
            item.setExpanded(not item.isExpanded())
            return

        json_path = item.data(0, Qt.UserRole)
        if not json_path: return 

        self.save_progress()
        self.marked_errors.clear()
        
        mp3_path = json_path.replace(".json", ".mp3")
        pdf_path = json_path.replace(".json", ".pdf") # הנתיב החדש שבו ה-PDF מחכה
        
        self.current_file_id = os.path.basename(json_path)
        self.load_project(json_path, mp3_path)
        
        # טעינת ה-PDF אם הוא נמצא בתיקיית הפרויקטים
        if os.path.exists(pdf_path):
            self.pdf_viewer.load_pdf(pdf_path)
        elif self.main_window and hasattr(self.main_window, 'file_path') and self.main_window.file_path:
            self.pdf_viewer.load_pdf(self.main_window.file_path)

    def load_project(self, json_path, mp3_path):
        try:
            with open(json_path, 'r', encoding='utf-8') as f: 
                self.current_json_data = json.load(f)
            
            self.player.setMedia(QMediaContent(QUrl.fromLocalFile(mp3_path)))
            self.reload_text_content()
            self.load_progress()
            
            # ניסיון לטעון PDF
            potential_pdf = json_path.replace(".json", ".pdf")
            if os.path.exists(potential_pdf):
                self.current_pdf_path = potential_pdf
                self.pdf_viewer.load_pdf(potential_pdf)
            elif self.main_window and hasattr(self.main_window, 'file_path') and self.main_window.file_path:
                self.current_pdf_path = self.main_window.file_path
                self.pdf_viewer.load_pdf(self.current_pdf_path)
            
            self.btn_play.setText("▶")
                
        except Exception as e: 
            print(f"Error loading project: {e}")

    def manually_load_pdf(self):
        path, _ = QFileDialog.getOpenFileName(self, "בחר PDF", "", "PDF Files (*.pdf)")
        if path:
            self.current_pdf_path = path
            self.pdf_viewer.load_pdf(path)

    def select_file_by_path(self, path):
        """בחירה אוטומטית בקובץ (פותח את התיקייה הרלוונטית בעץ)"""
        target = os.path.normpath(path)
        
        # מעבר על כל הקבוצות הראשיות
        root = self.list_files.invisibleRootItem()
        for i in range(root.childCount()):
            group = root.child(i)
            # מעבר על הילדים בקבוצה
            for j in range(group.childCount()):
                child = group.child(j)
                data_path = child.data(0, Qt.UserRole)
                if data_path and os.path.normpath(data_path) == target:
                    # מצאנו!
                    group.setExpanded(True) # פותח את התיקייה
                    self.list_files.setCurrentItem(child)
                    self.list_files.scrollToItem(child)
                    self.on_file_selected(child)
                    return

    def show_file_context_menu(self, pos):
        item = self.list_files.itemAt(pos)
        # מציגים תפריט רק אם זה קובץ (יש לו הורה) ולא כותרת
        if not item or not item.parent(): return
        
        menu = QMenu()
        action_delete = menu.addAction("🗑️ מחק פרויקט")
        
        if menu.exec_(self.list_files.mapToGlobal(pos)) == action_delete:
            json_path = item.data(0, Qt.UserRole)
            if not json_path: return
            
            mp3_path = json_path.replace(".json", ".mp3")
            if QMessageBox.question(self, "מחיקה", "למחוק את הקבצים?", QMessageBox.Yes|QMessageBox.No) == QMessageBox.Yes:
                try:
                    if os.path.exists(json_path): os.remove(json_path)
                    if os.path.exists(mp3_path): os.remove(mp3_path)
                    
                    # מחיקה מהעץ ויזואלית (כדי לא לרענן הכל)
                    item.parent().removeChild(item)
                    self.text_display.clear()
                    self.player.stop()
                except: 
                    self.refresh_file_list() # במקרה של שגיאה מרעננים הכל

    # --- טעינת טקסט וסנכרון ---
    def reload_text_content(self):
        self.text_display.clear()
        cursor = self.text_display.textCursor()
        self.sentence_ranges = []
        
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(self.styles.get('inactive_fg', '#BDC3C7')))
        fmt.setFontPointSize(float(self.styles.get('inactive_size', 16)))
        
        for i, item in enumerate(self.current_json_data):
            if "page_trigger" in item and not item.get('text'):
                self.sentence_ranges.append(None)
                continue

            text = item.get('text', '')
            
            if "[IMG:" in text:
                 cursor.insertBlock()
                 cursor.insertText("[ 🖼️ תמונה ב-PDF ]\n")
                 start = cursor.position() - len("[ 🖼️ תמונה ב-PDF ]\n")
                 end = cursor.position()
                 self.sentence_ranges.append((start, end))
                 continue

            display_text = text
            if not self.is_nikud_visible:
                display_text = "".join([c for c in unicodedata.normalize('NFD', text) if not unicodedata.combining(c)])
            
            display_text += " "
            
            start = cursor.position()
            cursor.setCharFormat(fmt)
            cursor.insertText(display_text)
            end = cursor.position()
            
            self.sentence_ranges.append((start, end))
            
        self.text_display.moveCursor(QTextCursor.Start)
        # שחזור סימוני שגיאות אם יש
        self.restore_error_marks()

    def restore_error_marks(self):
        if not self.marked_errors: return
        cursor = self.text_display.textCursor()
        doc = self.text_display.document()
        
        err_fmt = QTextCharFormat()
        err_fmt.setForeground(QColor("red"))
        err_fmt.setFontUnderline(True)
        err_fmt.setUnderlineColor(QColor("red"))
        err_fmt.setFontPointSize(float(self.styles.get('inactive_size', 16)))

        for error_word in self.marked_errors:
            cursor.setPosition(0)
            while True:
                cursor = doc.find(error_word, cursor)
                if cursor.isNull(): break
                cursor.mergeCharFormat(err_fmt)

    def sync_text(self, ms):
        target = ms + self.sync_offset_ms
        idx = -1
        
        for i, item in enumerate(self.current_json_data):
            if item.get('start', 0) <= target < item.get('end', 0):
                idx = i
            
            if "page_trigger" in item:
                trigger_time = item['start']
                if trigger_time <= target <= trigger_time + 500:
                     self.trigger_page_jump(item['page_trigger'])

        if idx != -1: self.apply_highlight(idx)

    def trigger_page_jump(self, page_num):
        if self.pdf_viewer and self.pdf_viewer.current_page != page_num:
            self.pdf_viewer.show_page(page_num)

    def apply_highlight(self, index, force=False):
        if index < 0 or index >= len(self.sentence_ranges): return
        if self.sentence_ranges[index] is None: return

        if not force and index == self.last_highlighted_index: return
        
        if self.last_highlighted_index >= 0 and self.last_highlighted_index < len(self.sentence_ranges):
            range_data = self.sentence_ranges[self.last_highlighted_index]
            if range_data:
                self.apply_range_style(range_data[0], range_data[1], active=False)

        self.last_highlighted_index = index
        curr_start, curr_end = self.sentence_ranges[index]
        self.apply_range_style(curr_start, curr_end, active=True)
        
        if self.auto_scroll_enabled and not self.user_is_scrolling:
            self.scroll_to_index(index)

    def apply_range_style(self, start, end, active):
        cursor = self.text_display.textCursor()
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.KeepAnchor)
        
        prefix = 'active' if active else 'inactive'
        fmt = QTextCharFormat()
        
        # שמירה על צבע אדום אם זו שגיאה
        selected_text = cursor.selectedText().strip()
        clean_key = "".join([c for c in unicodedata.normalize('NFD', selected_text) if not unicodedata.combining(c)])
        
        if not active and clean_key in self.marked_errors:
            fmt.setForeground(QColor("red"))
            fmt.setFontUnderline(True)
            fmt.setUnderlineColor(QColor("red"))
        else:
            fg = self.styles.get(f'{prefix}_fg', '#FFFFFF')
            fmt.setForeground(QColor(fg))
            fmt.setFontUnderline(self.styles.get(f'{prefix}_underline', False))
        
        bg = self.styles.get(f'{prefix}_bg', 'transparent')
        if bg != 'transparent': fmt.setBackground(QColor(bg))
        else: fmt.setBackground(Qt.transparent)
        
        size = float(self.styles.get(f'{prefix}_size', 16))
        fmt.setFontPointSize(size)
        
        weight = QFont.Bold if self.styles.get(f'{prefix}_bold') else QFont.Normal
        fmt.setFontWeight(weight)
        
        cursor.setCharFormat(fmt)

        block_fmt = QTextBlockFormat()
        spacing = self.styles.get('line_spacing', 150)
        block_fmt.setLineHeight(spacing, QTextBlockFormat.ProportionalHeight)
        cursor.setBlockFormat(block_fmt)

    def scroll_to_index(self, index):
        if index >= len(self.sentence_ranges) or not self.sentence_ranges[index]: return
        start, end = self.sentence_ranges[index]
        
        doc = self.text_display.document()
        block = doc.findBlock(start)
        cursor = self.text_display.textCursor()
        cursor.setPosition(start)
        
        cursor_rect = self.text_display.cursorRect(cursor)
        viewport_height = self.text_display.viewport().height()
        current_scroll = self.text_display.verticalScrollBar().value()
        
        target_y = current_scroll + cursor_rect.top() - (viewport_height / 2) + (cursor_rect.height() / 2)
        self.text_display.verticalScrollBar().setValue(int(target_y))

    # --- פונקציות שליטה בנגן ---
    def toggle_play(self):
        if self.player.state() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def on_state_changed(self, state):
        self.btn_play.setText("⏸" if state == QMediaPlayer.PlayingState else "▶")
        if state == QMediaPlayer.PlayingState:
            # מוודא שהמהירות שנבחרה ב-Combo מוחלת על הנגן
            self.change_playback_rate()
        else: 
            self.save_progress()
    
    def on_position_changed(self, p):
        if not self.user_is_dragging:
            self.slider.setValue(p)
        self.lbl_current_time.setText(self.format_ms(p))
        self.sync_text(p)
        
    def on_duration_changed(self, d):
        self.slider.setRange(0, d)
        self.lbl_total_time.setText(self.format_ms(d))

    def on_slider_pressed(self): self.user_is_dragging = True
    def on_slider_released(self):
        self.user_is_dragging = False
        self.player.setPosition(self.slider.value())
    def on_slider_moved(self, val):
        self.player.setPosition(val)

    def seek_relative(self, delta):
        new_pos = self.player.position() + delta
        new_pos = max(0, min(new_pos, self.player.duration()))
        self.player.setPosition(new_pos)

    def toggle_auto_scroll(self, checked):
        self.auto_scroll_enabled = checked
        self.btn_auto_scroll.setText("🔒 גלילה אוטומטית" if checked else "🔓 גלילה חופשית")
        if checked and self.last_highlighted_index >= 0:
            self.scroll_to_index(self.last_highlighted_index)

    def on_scrollbar_pressed(self): self.user_is_scrolling = True
    def on_scrollbar_released(self): self.user_is_scrolling = False

    def open_style_editor(self):
        dlg = KaraokeStyleDialog(self.styles, self)
        if dlg.exec_() == QDialog.Accepted:
            self.styles = dlg.get_styles()
            if self.main_window:
                self.main_window.settings["karaoke_styles"] = self.styles
                self.main_window.save_settings()
            self.reload_text_content()

    def toggle_nikud(self):
        self.is_nikud_visible = not self.is_nikud_visible
        self.btn_toggle_nikud.setText("הצג ניקוד" if not self.is_nikud_visible else "הסתר ניקוד")
        self.reload_text_content()

    def save_progress(self):
        if self.current_file_id and self.main_window:
            pos = self.player.position()
            if pos > 0:
                history = self.main_window.settings.get("playback_history", {})
                history[self.current_file_id] = pos
                self.main_window.settings["playback_history"] = history
                self.main_window.save_settings()

    def load_progress(self):
        if self.current_file_id and self.main_window:
            history = self.main_window.settings.get("playback_history", {})
            saved = history.get(self.current_file_id, 0)
            if saved > 0: self.player.setPosition(saved)

    def format_ms(self, ms):
        seconds = (ms // 1000) % 60
        minutes = (ms // 60000)
        return f"{minutes:02}:{seconds:02}"


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
            if hasattr(p, 'add_or_update_word'): return p
            p = p.parent()
        return None

    def clean_string(self, text):
        if not text: return ""
        normalized = unicodedata.normalize('NFD', text)
        return "".join([c for c in normalized if not unicodedata.combining(c)])
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


class NikudEditorDialog(QDialog):
    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.setWindowTitle("עורך ניקוד מהיר")
        self.resize(600, 500)
        self.setLayoutDirection(Qt.RightToLeft)
        
        self.player = QMediaPlayer()
        self.mode = "normal" # normal / text_editor
        
        layout = QVBoxLayout(self)
        
        # --- שורה עליונה: טקסט + כפתור השמעה ---
        top_layout = QHBoxLayout()
        
        self.input_text = QLineEdit(text)
        self.input_text.setAlignment(Qt.AlignCenter)
        self.input_text.setFont(QFont("Arial", 40, QFont.Bold)) 
        self.input_text.setStyleSheet("""
            QLineEdit {
                padding: 10px;
                border: 2px solid #334E68;
                border-radius: 10px;
                background-color: #F0F4F8;
                color: #102A43;
            }
        """)
        top_layout.addWidget(self.input_text)
        
        btn_play_preview = QPushButton("🔊")
        btn_play_preview.setFixedSize(60, 80)
        btn_play_preview.setCursor(Qt.PointingHandCursor)
        btn_play_preview.setStyleSheet("""
            QPushButton {
                background-color: #334E68; border: 2px solid #102A43; border-radius: 8px; font-size: 30px;
            }
            QPushButton:hover { background-color: #27AE60; border-color: #2ECC71; }
        """)
        btn_play_preview.setFocusPolicy(Qt.NoFocus) 
        btn_play_preview.clicked.connect(self.play_preview)
        top_layout.addWidget(btn_play_preview)
        
        layout.addLayout(top_layout)
        
        # --- אפשרויות הוספה למילון (יופיעו רק כשבאים מהאדיטור) ---
        self.dict_options_frame = QFrame()
        dict_layout = QHBoxLayout(self.dict_options_frame)
        dict_layout.setContentsMargins(0, 10, 0, 10)
        
        self.chk_add_to_dict = QCheckBox("הוסף מילה זו למילון")
        self.chk_add_to_dict.setStyleSheet("font-size: 14px; font-weight: bold; color: #2C3E50;")
        
        self.combo_match_type = QComboBox()
        self.combo_match_type.addItems(["התאמה חלקית (חכם)", "התאמה מדויקת בלבד"])
        self.combo_match_type.setStyleSheet("font-size: 13px;")
        
        dict_layout.addWidget(self.chk_add_to_dict)
        dict_layout.addSpacing(10)
        dict_layout.addWidget(self.combo_match_type)
        dict_layout.addStretch()
        
        layout.addWidget(self.dict_options_frame)
        
        # --- מקלדת הניקוד (מעודכן וגדול) ---
        grid_layout = QGridLayout()
        # רשימה עם סימני עזר ויזואליים
        chars = [
            ('ְ', 'שְווא', '◌ְ'), ('ֱ', 'חטף סגול', '◌ֱ'), ('ֲ', 'חטף פתח', '◌ֲ'), ('ֳ', 'חטף קמץ', '◌ֳ'),
            ('ִ', 'חיריק', '◌ִ'), ('ֵ', 'צירה', '◌ֵ'), ('ֶ', 'סגול', '◌ֶ'), ('ַ', 'פתח', '◌ַ'),
            ('ָ', 'קמץ', '◌ָ'), ('ֹ', 'חולם', '◌ֹ'), ('ֻ', 'קובוץ', '◌ֻ'), ('ּ', 'דגש/שורוק', '◌ּ'),
            ('ׁ', 'שין ימנית', 'שׁ'), ('ׂ', 'שין שמאלית', 'שׂ'), ('ֿ', 'רפה', 'בֿ'), ('\u05bd', 'מתג (הטעמה)', '◌ֽ')
        ]
        
        row, col = 0, 0
        for char, name, display in chars:
            btn = QPushButton()
            btn.setFixedSize(100, 80) # כפתורים גדולים
            btn.setFocusPolicy(Qt.NoFocus)
            
            # עיצוב הכפתור
            btn.setStyleSheet("""
                QPushButton { 
                    background-color: #334E68; 
                    border-radius: 8px; 
                    border: 1px solid #486581;
                }
                QPushButton:hover { background-color: #27AE60; border-color: #2ECC71; }
                QPushButton:pressed { background-color: #1E8449; }
            """)
            
            # שימוש ב-HTML להצגת הניקוד בגדול
            btn_text = f"<html><div style='text-align:center;'><span style='font-size:32px; color: white; font-weight:bold;'>{display}</span><br><span style='font-size:11px; color:#D9E2EC;'>{name}</span></div></html>"
            
            # במקום setText רגיל, נשתמש ב-QLabel פנימי כדי שה-HTML יעבוד בטוח
            layout_btn = QVBoxLayout(btn)
            layout_btn.setContentsMargins(0,0,0,0)
            lbl = QLabel(btn_text)
            lbl.setAlignment(Qt.AlignCenter)
            # מעבירים את הקליקים מהלייבל לכפתור
            lbl.setAttribute(Qt.WA_TransparentForMouseEvents) 
            layout_btn.addWidget(lbl)

            btn.clicked.connect(lambda _, c=char: self.insert_char(c))
            grid_layout.addWidget(btn, row, col)
            
            col += 1
            if col > 3: 
                col = 0; row += 1
                
        layout.addLayout(grid_layout)
        
        # --- כפתורים תחתונים ---
        btn_layout = QHBoxLayout()
        
        # כפתור סמן כטעות (אדום)
        btn_mark_error = QPushButton("🚩 סמן כטעות")
        btn_mark_error.setFont(QFont("Arial", 12, QFont.Bold))
        btn_mark_error.setStyleSheet("background-color: #C0392B; color: white; padding: 10px;")
        btn_mark_error.clicked.connect(self.mark_as_error)
        btn_layout.addWidget(btn_mark_error)
        
        btn_layout.addStretch()

        btn_cancel = QPushButton("ביטול")
        btn_cancel.setStyleSheet("background-color: #7F8C8D; color: white; padding: 10px;")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)

        btn_save = QPushButton("💾 החלף בטקסט")
        btn_save.setFont(QFont("Arial", 12, QFont.Bold))
        btn_save.setStyleSheet("background-color: #27AE60; color: white; padding: 10px;")
        btn_save.clicked.connect(self.accept)
        btn_layout.addWidget(btn_save)
        
        layout.addLayout(btn_layout)
        self.input_text.setFocus()

    def insert_char(self, char):
        self.input_text.insert(char)
        self.input_text.setFocus()
        
    def get_text(self):
        return self.input_text.text()
    
    def mark_as_error(self):
        # מחזיר קוד מיוחד (222) כדי שהאדיטור ידע לצבוע באדום
        self.done(222)

    def play_preview(self):
        text = self.input_text.text().strip()
        if not text: return
        try:
            # מנסה למצוא את החלון הראשי דרך השרשור של ה-parents
            # אם הוא נפתח מתוך NikudTextEdit, ה-parent שלו הוא NikudTextEdit, וה-parent שלו הוא MainWindow
            main_win = None
            curr = self.parent()
            while curr:
                if hasattr(curr, 'combo_he'): # זיהוי של החלון הראשי
                    main_win = curr
                    break
                if hasattr(curr, 'parent_window'): # אם זה AnalysisDialog או NikudTextEdit
                    main_win = curr.parent_window
                    break
                curr = curr.parent()

            if main_win:
                voice_name = main_win.combo_he.currentText()
                voice_id = main_win.he_voices.get(voice_name, "he-IL-AvriNeural")
                speed = main_win.combo_speed.currentText()
                
                unique_str = f"{text}_{voice_id}_{speed}"
                cache_key = hashlib.md5(unique_str.encode('utf-8')).hexdigest()
                
                self.worker = AudioPreviewWorker(cache_key, text, voice_id, speed)
                self.worker.finished_data.connect(self.play_audio_bytes)
                self.worker.start()
        except Exception as e:
            print(f"Preview Error: {e}")

    def play_audio_bytes(self, cache_key, data):
        try:
            temp_path = os.path.join(tempfile.gettempdir(), "tts_editor_preview.mp3")
            with open(temp_path, "wb") as f: f.write(data)
            self.player.setMedia(QMediaContent(QUrl.fromLocalFile(temp_path)))
            self.player.play()
        except: pass
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
        self.setWindowTitle("Hebrew PDF Studio - Ultimate Edition")
        self.setGeometry(100, 100, 1300, 950)
        self.settings = self.load_settings()

        self.he_voices = {"Hila (אישה - עברית)": "he-IL-HilaNeural", "Avri (גבר - עברית)": "he-IL-AvriNeural"}
        self.en_voices = {
            "Aria (אישה - ארה\"ב)": "en-US-AriaNeural", 
            "Guy (גבר - ארה\"ב)": "en-US-GuyNeural",
            "Brian (גבר - בריטי)": "en-GB-BrianNeural"
        }
        self.file_path = ""
        self.init_ui()
        self.apply_styles()


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
        """
        שמירה בטוחה: שומרת את self.settings ישירות לקובץ.
        לא קוראת מהטבלה כדי למנוע מחיקת נתונים!
        """
        print("\n[DEBUG] >>> save_settings() CALLED")
        global TG_TOKEN, TG_CHAT_ID
        try:
            # עדכון משתנים כלליים (לא קשור למילון)
            self.settings["tg_token"] = self.input_tg_token.text().strip()
            self.settings["tg_chat_id"] = self.input_tg_chat_id.text().strip()
            self.settings["pause_lang"] = self.spin_lang.value()
            self.settings["pause_comma"] = self.spin_comma.value()
            self.settings["pause_sentence"] = self.spin_sentence.value()
            self.settings["max_concurrent"] = self.spin_concurrent.value()

            # בדיקת גודל המילון לפני השמירה
            dict_size = len(self.settings.get("nikud_dictionary", {}))
            print(f"[DEBUG] Saving dictionary with {dict_size} entries to disk...")

            # שמירה פיזית
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, indent=4, ensure_ascii=False)
            
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.lbl_status.setText(f"✅ נשמר בהצלחה! ({timestamp})")
            print(f"[DEBUG] >>> Settings saved successfully to {CONFIG_FILE}")
            
        except Exception as e:
            print(f"[ERROR SAVE] {e}")
            self.lbl_status.setText(f"❌ שגיאה בשמירה: {str(e)}")


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