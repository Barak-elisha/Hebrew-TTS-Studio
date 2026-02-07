import os
import hashlib
import tempfile

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, 
    QFrame, QCheckBox, QComboBox, QGridLayout, QLabel
)
from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtGui import QFont
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent

# ייבוא ה-Worker של האודיו
from src.workers.tts_worker import AudioPreviewWorker

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
        
        # --- אפשרויות הוספה למילון ---
        self.dict_options_frame = QFrame()
        dict_layout = QHBoxLayout(self.dict_options_frame)
        dict_layout.setContentsMargins(0, 10, 0, 10)
        
        self.chk_add_to_dict = QCheckBox("הוסף מילה זו למילון")
        self.chk_add_to_dict.setStyleSheet("font-size: 14px; font-weight: bold; color: #2C3E50;")
        self.chk_add_to_dict.setChecked(True) # ברירת מחדל
        
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
        chars = [
            ('ְ', 'שְווא', '◌ְ'), ('ֱ', 'חטף סגול', '◌ֱ'), ('ֲ', 'חטף פתח', '◌ֲ'), ('ֳ', 'חטף קמץ', '◌ֳ'),
            ('ִ', 'חיריק', '◌ִ'), ('ֵ', 'צירה', '◌ֵ'), ('ֶ', 'סגול', '◌ֶ'), ('ַ', 'פתח', '◌ַ'),
            ('ָ', 'קמץ', '◌ָ'), ('ֹ', 'חולם', '◌ֹ'), ('ֻ', 'קובוץ', '◌ֻ'), ('ּ', 'דגש/שורוק', '◌ּ'),
            ('ׁ', 'שין ימנית', 'שׁ'), ('ׂ', 'שין שמאלית', 'שׂ'), ('ֿ', 'רפה', 'בֿ'), ('\u05bd', 'מתג (הטעמה)', '◌ֽ')
        ]
        
        row, col = 0, 0
        for char, name, display in chars:
            btn = QPushButton()
            btn.setFixedSize(100, 80)
            btn.setFocusPolicy(Qt.NoFocus)
            
            btn.setStyleSheet("""
                QPushButton { 
                    background-color: #334E68; 
                    border-radius: 8px; 
                    border: 1px solid #486581;
                }
                QPushButton:hover { background-color: #27AE60; border-color: #2ECC71; }
                QPushButton:pressed { background-color: #1E8449; }
            """)
            
            btn_text = f"<html><div style='text-align:center;'><span style='font-size:32px; color: white; font-weight:bold;'>{display}</span><br><span style='font-size:11px; color:#D9E2EC;'>{name}</span></div></html>"
            
            layout_btn = QVBoxLayout(btn)
            layout_btn.setContentsMargins(0,0,0,0)
            lbl = QLabel(btn_text)
            lbl.setAlignment(Qt.AlignCenter)
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
        self.done(222)

    def play_preview(self):
        """מנגן את הטקסט, תוך חיפוש חכם של הגדרות הקול בטאב העריכה"""
        text = self.input_text.text().strip()
        if not text: return
        
        try:
            # 1. איתור החלון הראשי (MainWindow) בצורה בטוחה
            main_win = None
            
            # בדיקה אם הועבר לנו parent_window מפורש (כמו שעשינו בטבלה)
            if hasattr(self, 'parent_window') and self.parent_window:
                # בדיקה אם זה כבר החלון הראשי או שצריך לעלות למעלה
                if hasattr(self.parent_window, 'tab_edit'):
                    main_win = self.parent_window
                elif hasattr(self.parent_window, 'main_window'):
                    main_win = self.parent_window.main_window
            
            # אם לא מצאנו, ננסה לטפס בהיררכיה הרגילה של Qt
            if not main_win:
                curr = self.parent()
                while curr:
                    if hasattr(curr, 'tab_edit'): # זה הסימן המובהק ל-MainWindow החדש
                        main_win = curr
                        break
                    curr = curr.parent()

            # 2. שליפת ההגדרות מתוך MainEditTab
            voice_id = "he-IL-AvriNeural" # ברירת מחדל
            speed = "+0%"

            if main_win and hasattr(main_win, 'tab_edit'):
                tab = main_win.tab_edit
                # וודא שהרכיבים קיימים בטאב
                if hasattr(tab, 'combo_he'):
                    voice_name = tab.combo_he.currentText()
                    voice_id = tab.he_voices.get(voice_name, voice_id)
                if hasattr(tab, 'combo_speed'):
                    speed = tab.combo_speed.currentText()
            
            # 3. הפעלת ה-Worker להשמעה
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