import sys
import os
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QTabWidget, QFrame, QProgressBar, QLabel)
from PyQt5.QtCore import Qt

from src.ui.tabs.main_edit_tab import MainEditTab
from src.ui.tabs.karaoke_tab import KaraokeTab
from src.ui.tabs.dictionary_tab import DictionaryTab
from src.ui.tabs.settings_tab import SettingsTab
# ייבוא רכיבים גלובליים
from src.ui.widgets.nikud_keyboard import NikudKeyboard
from src.utils.settings_manager import SettingsManager
from src.ui.styles import MAIN_STYLE

# הגדרת נתיבים
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")

# הגדרות ברירת מחדל (למקרה שהקובץ לא קיים)
DEFAULT_SETTINGS = {
    "pause_lang": 80,
    "pause_hyphen": 450,
    "pause_comma": 250,
    "pause_sentence": 600,
    "max_concurrent": 50,
    "custom_symbols": {"***": 1000},
    "nikud_dictionary": {}
}

class HebrewTTSStudio(QMainWindow):
    def __init__(self):
        super().__init__()
        
        # 1. טעינת הגדרות
        self.settings_manager = SettingsManager(CONFIG_FILE)
        self.settings = self.settings_manager.load_settings(DEFAULT_SETTINGS)

        # 2. הגדרות חלון בסיסיות
        self.setWindowTitle("Hebrew TTS Studio - Modular Edition")
        self.setGeometry(100, 100, 1400, 900)
        
        # 3. אתחול ממשק משתמש
        self.init_ui()
        
        # 4. החלת עיצוב
        self.setStyleSheet(MAIN_STYLE)

    def init_ui(self):
        """בניית הממשק: טאבים ושורת סטטוס"""
        
        # קונטיינר ראשי
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        # יצירת מנהל הטאבים
        self.tabs = QTabWidget()
        self.tabs.setLayoutDirection(Qt.RightToLeft)
        
        # --- חיבור הטאבים ---
        
        # טאב 1: עריכה והמרה
        self.tab_main = MainEditTab(self)
        self.tabs.addTab(self.tab_main, "🏠 עריכה והמרה")
        
        # טאב 2: מילון ניקוד
        self.tab_dictionary = DictionaryTab(self)
        self.tabs.addTab(self.tab_dictionary, "📘 מילון")

        # טאב 3: הגדרות מתקדמות
        self.tab_settings = SettingsTab(self)
        self.tabs.addTab(self.tab_settings, "🔧 הגדרות")

        # טאב 4: נגן וקבצים (קריוקי)
        output_dir = os.path.expanduser("~/Documents")
        self.tab_karaoke = KaraokeTab(output_dir, self)
        self.tabs.addTab(self.tab_karaoke, "🎵 נגן וקבצים")
        
        main_layout.addWidget(self.tabs)

        # --- שורת סטטוס משותפת ---
        status_frame = QFrame()
        status_frame.setStyleSheet("background-color: #1A3C59; border-top: 2px solid #486581; padding: 5px;")
        status_layout = QVBoxLayout(status_frame)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setAlignment(Qt.AlignCenter)
        self.progress_bar.setStyleSheet("QProgressBar { border: 2px solid #334E68; border-radius: 5px; text-align: center; color: white; } QProgressBar::chunk { background-color: #F76707; }")
        
        self.lbl_status = QLabel("מוכן")
        self.lbl_status.setAlignment(Qt.AlignCenter)
        self.lbl_status.setStyleSheet("font-size: 14px; font-weight: bold; color: white;")
        
        status_layout.addWidget(self.progress_bar)
        status_layout.addWidget(self.lbl_status)
        main_layout.addWidget(status_frame)

    def save_settings(self):
        """פונקציית שמירה מרכזית - אוספת מידע מכל הטאבים ושומרת לדיסק"""
        print("[DEBUG] Saving global settings...")
        
        # עדכון הזיכרון מתוך טאב ההגדרות (אם יש שינויים שלא נשמרו)
        if hasattr(self, 'tab_settings'):
            self.tab_settings.apply_settings_to_memory()
            
        # שמירה פיזית לקובץ JSON
        success, msg = self.settings_manager.save_to_disk(self.settings)
        
        if success:
            self.lbl_status.setText("✅ ההגדרות נשמרו בהצלחה.")
        else:
            self.lbl_status.setText(f"❌ שגיאה בשמירה: {msg}")

    def open_nikud_keyboard(self):
        """פתיחת מקלדת הניקוד (פונקציה גלובלית לשימוש מכל טאב)"""
        if not hasattr(self, 'nikud_kb_window'):
            self.nikud_kb_window = NikudKeyboard(self)
        self.nikud_kb_window.show()
        self.nikud_kb_window.raise_()
        self.nikud_kb_window.activateWindow()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = HebrewTTSStudio()
    window.show()
    sys.exit(app.exec_())