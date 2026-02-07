import os
import re
import time
import PyPDF2
import fitz  # PyMuPDF
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget, 
    QTableWidgetItem, QHeaderView, QPushButton, QFileDialog
)
from PyQt5.QtCore import Qt
from src.utils.text_tools import cleanup_pdf_page, advanced_cleanup

class AdvancedImportDialog(QDialog):
    def __init__(self, arg1=None, arg2=None):
        """
        בנאי חכם התומך בשני סוגי קריאות למניעת שגיאות:
        1. (start_dir, parent) - הקריאה החדשה והתקינה
        2. (parent) - תמיכה לאחור בקריאה ישנה
        """
        start_dir = ""
        parent = None
        
        # זיהוי חכם של הפרמטרים
        if isinstance(arg1, str):
            start_dir = arg1
            parent = arg2
        elif arg1 is not None:
            parent = arg1
            start_dir = ""
            
        super().__init__(parent)
        self.start_dir = start_dir
        
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
        self.files_list = []

    def add_files(self):
        # שימוש ב-self.start_dir כנקודת התחלה
        current_dir = self.start_dir if isinstance(self.start_dir, str) and self.start_dir else os.path.expanduser("~")
        
        fnames, _ = QFileDialog.getOpenFileNames(self, "בחר קבצי PDF", current_dir, "PDF Files (*.pdf)")
        if fnames:
            # עדכון התיקייה האחרונה לפעם הבאה
            self.start_dir = os.path.dirname(fnames[0])
            for f in sorted(fnames): 
                abs_path = os.path.abspath(f)
                self._add_row(abs_path)

    def _add_row(self, file_path):
        row = self.table.rowCount()
        self.table.insertRow(row)
        
        item_name = QTableWidgetItem(os.path.basename(file_path))
        item_name.setToolTip(file_path)
        item_name.setData(Qt.UserRole, file_path)
        self.table.setItem(row, 0, item_name)
        
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
        if not range_str or not range_str.strip():
            return list(range(max_pages))
            
        pages = set()
        parts = range_str.replace(" ", "").split(',')
        
        for part in parts:
            try:
                if '-' in part:
                    start, end = map(int, part.split('-'))
                    for i in range(start, end + 1):
                        if 1 <= i <= max_pages:
                            pages.add(i - 1)
                else:
                    pg = int(part)
                    if 1 <= pg <= max_pages:
                        pages.add(pg - 1)
            except ValueError:
                continue
                
        return sorted(list(pages))

    def run_extraction(self):
        print("\n--- [DEBUG] Starting Advanced Import Process ---")
        full_text_accumulator = ""
        self.files_list = [] 

        rows = self.table.rowCount()
        
        for i in range(rows):
            path = self.table.item(i, 0).data(Qt.UserRole)
            if not path: continue

            if path not in self.files_list:
                self.files_list.append(path)
            
            # וידוא נתיב אבסולוטי
            abs_path = os.path.abspath(path)

            item_range = self.table.item(i, 1)
            range_str = item_range.text().strip() if item_range else ""
            
            try:
                doc = fitz.open(path)
                total_pages = len(doc)
                indices_to_extract = self.parse_page_string(range_str, total_pages)

                # הוספת תגית הקובץ (ללא ניקוי שישבש אותה!)
                full_text_accumulator += f"\n[FILE:{abs_path}]\n"

                for idx in indices_to_extract:
                    page_num = idx + 1
                    full_text_accumulator += f"\n\n[PAGE:{page_num}]\n"
                    page_text = doc[idx].get_text()

                    if page_text:
                        # === ניקוי ראשוני ===
                        lines = page_text.split('\n')
                        cleaned_lines = []
                        total_lines = len(lines)
                        for line_idx, line in enumerate(lines):
                            stripped = line.strip()
                            if len(stripped) == 0: continue
                            # סינון מספרי עמודים: מספר בודד שמוקף בשורות ריקות
                            if re.match(r'^\s*\d+\s*$', stripped):
                                prev_empty = (line_idx == 0) or not lines[line_idx - 1].strip()
                                next_empty = (line_idx >= total_lines - 1) or not lines[line_idx + 1].strip()
                                if prev_empty or next_empty:
                                    continue
                            if len(stripped) == 1 and not re.match(r'[.!?,;:)(a-zA-Z0-9\u0590-\u05FF]', stripped): continue
                            cleaned_lines.append(stripped)

                        # === תיקוני פיסוק ===
                        for k in range(len(cleaned_lines)):
                            cleaned_lines[k] = re.sub(r'^([.!?,;:"\u05F4]+)(\S+)', r'\2\1', cleaned_lines[k])
                            cleaned_lines[k] = re.sub(r'\.(")', r'\1.', cleaned_lines[k])

                        # === איחוד שורות ===
                        merged_lines = []
                        for line in cleaned_lines:
                            if merged_lines and re.match(r'^[.!?,;:)(–\-\]\[]+$', line):
                                merged_lines[-1] += line
                            else:
                                merged_lines.append(line)
                        cleaned_lines = merged_lines

                        # === בניית פסקה חכמה ===
                        smart_text = ""
                        for j, line in enumerate(cleaned_lines):
                            if j > 0:
                                prev_line = cleaned_lines[j-1]
                                current_starts_with_punct = line and line[0] in '.!?,;:'
                                if current_starts_with_punct: pass
                                elif prev_line.endswith(('.', '!', '?', ':', ';', '"')): smart_text += "\n"
                                else: smart_text += " "
                            smart_text += line

                        # === פוליש סופי (רק על הטקסט של העמוד!) ===
                        smart_text = advanced_cleanup(smart_text)
                        smart_text = re.sub(r'\.([^\s\n\d])', r'. \1', smart_text)
                        smart_text = re.sub(r',([^\s\n])', r', \1', smart_text)
                        smart_text = re.sub(r' {2,}', ' ', smart_text)
                        smart_text = re.sub(r'\s+([.,!?;:])', r'\1', smart_text)
                        smart_text = re.sub(r'\(\s+', '(', smart_text)
                        smart_text = re.sub(r'\s+\)', ')', smart_text)

                        full_text_accumulator += smart_text

                doc.close()

            except Exception as e:
                print(f"[ERROR] Failed to process row {i}: {e}")
        
        self.result_text = full_text_accumulator.strip()
        print("--- [DEBUG] Finished Advanced Import ---\n")
        self.accept()