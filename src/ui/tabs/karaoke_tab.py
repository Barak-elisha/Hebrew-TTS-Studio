import os
import json
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QLabel, QFileDialog, 
                             QMessageBox, QFrame, QSplitter, QTreeWidget, QTreeWidgetItem)
from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
from PyQt5.QtGui import QFont, QTextCursor, QTextCharFormat, QTextBlockFormat, QColor
from PyQt5.QtWidgets import (QMenu, QTextEdit, QDialog, QSlider)
from PyQt5.QtCore import QEvent
import unicodedata
from datetime import datetime
from src.ui.widgets.pdf_viewer import PDFViewerWidget
from src.ui.widgets.jump_slider import JumpSlider
from src.ui.dialogs.split_dialog import KaraokeStyleDialog


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

