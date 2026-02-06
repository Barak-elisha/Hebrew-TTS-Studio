MAIN_STYLE = """
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

    }
"""