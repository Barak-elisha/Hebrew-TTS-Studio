import os
import re
import time
import PyPDF2
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget, 
    QTableWidgetItem, QHeaderView, QPushButton, QFileDialog
)
from PyQt5.QtCore import Qt

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
