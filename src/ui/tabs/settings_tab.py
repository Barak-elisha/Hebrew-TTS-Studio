from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, 
                             QGroupBox, QLabel, QLineEdit, QSpinBox, 
                             QTableWidget, QTableWidgetItem, QHeaderView, QPushButton)
from PyQt5.QtCore import Qt

class SettingsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = parent
        self.init_ui()
        self.load_values()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # --- קבוצה 1: טלגרם ---
        group_tg = QGroupBox("🤖 הגדרות טלגרם")
        layout_tg = QGridLayout(group_tg)
        
        self.input_tg_token = QLineEdit()
        self.input_tg_token.setPlaceholderText("הדבק כאן את הטוקן של הבוט")
        
        self.input_tg_chat_id = QLineEdit()
        self.input_tg_chat_id.setPlaceholderText("הדבק כאן את ה-Chat ID שלך")
        
        layout_tg.addWidget(QLabel("Bot Token:"), 0, 0)
        layout_tg.addWidget(self.input_tg_token, 0, 1)
        layout_tg.addWidget(QLabel("Chat ID:"), 1, 0)
        layout_tg.addWidget(self.input_tg_chat_id, 1, 1)
        
        layout.addWidget(group_tg)

        # --- קבוצה 2: השהיות ---
        group_pauses = QGroupBox("⏱️ השהיות אוטומטיות (אלפיות שנייה)")
        layout_pauses = QHBoxLayout(group_pauses)
        
        self.spin_lang = QSpinBox(); self.spin_lang.setRange(0, 5000); self.spin_lang.setSuffix(" ms")
        self.spin_comma = QSpinBox(); self.spin_comma.setRange(0, 5000); self.spin_comma.setSuffix(" ms")
        self.spin_sentence = QSpinBox(); self.spin_sentence.setRange(0, 10000); self.spin_sentence.setSuffix(" ms")
        
        layout_pauses.addWidget(QLabel("חילוף שפה:"))
        layout_pauses.addWidget(self.spin_lang)
        layout_pauses.addSpacing(20)
        layout_pauses.addWidget(QLabel("פסיק:"))
        layout_pauses.addWidget(self.spin_comma)
        layout_pauses.addSpacing(20)
        layout_pauses.addWidget(QLabel("סוף משפט:"))
        layout_pauses.addWidget(self.spin_sentence)
        
        layout.addWidget(group_pauses)

        # --- קבוצה 3: ביצועים ---
        group_perf = QGroupBox("🚀 ביצועים")
        layout_perf = QHBoxLayout(group_perf)
        
        self.spin_concurrent = QSpinBox()
        self.spin_concurrent.setRange(1, 50)
        self.spin_concurrent.setToolTip("כמות המשפטים שיעובדו במקביל. מחשב חזק יכול להתמודד עם 20+.")
        
        layout_perf.addWidget(QLabel("מספר המרות במקביל (Threads):"))
        layout_perf.addWidget(self.spin_concurrent)
        layout_perf.addStretch()
        
        layout.addWidget(group_perf)

        # --- קבוצה 4: סמלים מיוחדים ---
        group_symbols = QGroupBox("🔣 סמלים מיוחדים והשהיות")
        layout_symbols = QVBoxLayout(group_symbols)
        
        self.table_symbols = QTableWidget(0, 2)
        self.table_symbols.setHorizontalHeaderLabels(["סמל בטקסט", "השהייה (ms)"])
        self.table_symbols.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout_symbols.addWidget(self.table_symbols)
        
        btn_layout = QHBoxLayout()
        btn_add = QPushButton("➕ הוסף סמל"); btn_add.clicked.connect(self.add_symbol_row)
        btn_del = QPushButton("🗑️ מחק סמל"); btn_del.clicked.connect(self.delete_symbol_row)
        
        btn_layout.addWidget(btn_add)
        btn_layout.addWidget(btn_del)
        layout_symbols.addLayout(btn_layout)
        
        layout.addWidget(group_symbols)
        
        # כפתור שמירה ידני (לנוחות)
        btn_save = QPushButton("💾 שמור הגדרות")
        btn_save.setStyleSheet("background-color: #27AE60; color: white; font-weight: bold; padding: 10px;")
        btn_save.clicked.connect(self.force_save)
        layout.addWidget(btn_save)

        layout.addStretch()

    def load_values(self):
        """טעינת הערכים מההגדרות לשדות"""
        if not self.main_window: return
        settings = self.main_window.settings
        
        self.input_tg_token.setText(settings.get("tg_token", ""))
        self.input_tg_chat_id.setText(settings.get("tg_chat_id", ""))
        
        self.spin_lang.setValue(settings.get("pause_lang", 80))
        self.spin_comma.setValue(settings.get("pause_comma", 250))
        self.spin_sentence.setValue(settings.get("pause_sentence", 600))
        self.spin_concurrent.setValue(settings.get("max_concurrent", 5))
        
        # טעינת סמלים
        self.table_symbols.setRowCount(0)
        custom_symbols = settings.get("custom_symbols", {"***": 1000})
        for sym, dur in custom_symbols.items():
            self.add_row_ui(sym, dur)

    def apply_settings_to_memory(self):
        """מעדכן את אובייקט ההגדרות הראשי מהשדות בטאב"""
        if not self.main_window: return
        
        s = self.main_window.settings
        s["tg_token"] = self.input_tg_token.text().strip()
        s["tg_chat_id"] = self.input_tg_chat_id.text().strip()
        s["pause_lang"] = self.spin_lang.value()
        s["pause_comma"] = self.spin_comma.value()
        s["pause_sentence"] = self.spin_sentence.value()
        s["max_concurrent"] = self.spin_concurrent.value()
        
        # איסוף סמלים מהטבלה
        new_symbols = {}
        for row in range(self.table_symbols.rowCount()):
            sym_item = self.table_symbols.item(row, 0)
            dur_item = self.table_symbols.item(row, 1)
            if sym_item and dur_item:
                try:
                    new_symbols[sym_item.text()] = int(dur_item.text())
                except: pass
        s["custom_symbols"] = new_symbols

    def force_save(self):
        """שמירה יזומה ע'י המשתמש"""
        self.apply_settings_to_memory()
        self.main_window.save_settings()

    # --- טבלה ---
    def add_symbol_row(self):
        self.add_row_ui("...", 500)

    def add_row_ui(self, symbol, duration):
        row = self.table_symbols.rowCount()
        self.table_symbols.insertRow(row)
        self.table_symbols.setItem(row, 0, QTableWidgetItem(str(symbol)))
        self.table_symbols.setItem(row, 1, QTableWidgetItem(str(duration)))

    def delete_symbol_row(self):
        curr = self.table_symbols.currentRow()
        if curr >= 0:
            self.table_symbols.removeRow(curr)