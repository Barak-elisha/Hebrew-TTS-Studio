import os
import json
import shutil
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout,
                             QPushButton, QLabel, QFileDialog, QComboBox,
                             QMessageBox, QFrame, QSplitter, QTreeWidget, QTreeWidgetItem)
from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
from PyQt5.QtGui import QFont, QTextCursor, QTextCharFormat, QTextBlockFormat, QColor
from PyQt5.QtWidgets import (QMenu, QTextEdit, QDialog, QSlider, QInputDialog, QAction)
from PyQt5.QtCore import QEvent
import unicodedata
from datetime import datetime
from src.ui.widgets.pdf_viewer import PDFViewerWidget
from src.ui.widgets.jump_slider import JumpSlider
from src.ui.dialogs.split_dialog import KaraokeStyleDialog
from src.ui.dialogs.transcription_dialog import TranscriptionDialog
from src.workers.telegram_worker import TelegramWorker
from src.workers.transcription_worker import TranscriptionWorker

# סיומות אודיו נתמכות
AUDIO_EXTENSIONS = (".mp3", ".m4a")


def _find_audio_file(base_path):
    """מוצא קובץ אודיו תואם (mp3 או m4a) לפי שם בסיס בלי סיומת"""
    for ext in AUDIO_EXTENSIONS:
        path = base_path + ext
        if os.path.exists(path):
            return path
    return None


def _is_audio_file(filepath):
    """בודק אם הקובץ הוא קובץ אודיו נתמך"""
    return filepath.lower().endswith(AUDIO_EXTENSIONS)


def _get_audio_path_from_json(json_path):
    """מוצא קובץ אודיו תואם לקובץ JSON"""
    base = os.path.splitext(json_path)[0]
    return _find_audio_file(base)


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

        # מעקב אחרי תיקיות שבהן יש פרויקטים
        self.tracked_dirs = set()
        self.tracked_dirs.add(self.output_dir)
        # טעינת תיקיות שמורות
        if self.main_window and hasattr(self.main_window, 'settings'):
            saved_dirs = self.main_window.settings.get("tracked_project_dirs", [])
            for d in saved_dirs:
                if os.path.exists(d):
                    self.tracked_dirs.add(d)
            # טעינת מבנה תיקיות וירטואלי
            self.virtual_folders = self.main_window.settings.get("virtual_folders", {})
        else:
            self.virtual_folders = {}
        # virtual_folders = { "שם תיקייה": ["path/to/file.json", ...], ... }
        
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
        self.list_files.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.list_files.itemClicked.connect(self.on_file_selected)
        self.list_files.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_files.customContextMenuRequested.connect(self.show_file_context_menu)
        # עיצוב העץ
        self.list_files.setStyleSheet("""
            QTreeWidget { background-color: #243B53; color: white; border: 1px solid #486581; border-radius: 4px; }
            QTreeWidget::item:selected { background-color: #F76707; }
        """)

        files_layout.addWidget(QLabel("📂 פרויקטים:"))

        # כפתורי ניהול
        mgmt_row = QHBoxLayout()
        btn_import = QPushButton("📥 ייבא")
        btn_import.setStyleSheet("background-color: #2980B9; color: white; padding: 4px; font-weight: bold; border-radius: 4px;")
        btn_import.clicked.connect(self.import_external_project)
        mgmt_row.addWidget(btn_import)

        btn_new_folder = QPushButton("📁 תיקייה")
        btn_new_folder.setStyleSheet("background-color: #8E44AD; color: white; padding: 4px; font-weight: bold; border-radius: 4px;")
        btn_new_folder.clicked.connect(self.create_virtual_folder)
        mgmt_row.addWidget(btn_new_folder)
        files_layout.addLayout(mgmt_row)

        # סרגל סינון תאריך
        filter_row = QHBoxLayout()
        self.combo_date_filter = QComboBox()
        self.combo_date_filter.addItems(["הכל", "היום", "השבוע", "החודש", "השנה"])
        self.combo_date_filter.setStyleSheet("background-color: #102A43; color: white; padding: 2px; border: 1px solid #486581;")
        self.combo_date_filter.currentIndexChanged.connect(lambda: self.refresh_file_list())
        filter_row.addWidget(QLabel("🔍"))
        filter_row.addWidget(self.combo_date_filter)
        files_layout.addLayout(filter_row)

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

    # === טיפול באירועי עכבר ===
    
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
        """ייבוא פרויקטים - תומך בבחירת מספר קבצים (אודיו בלי JSON מותר)"""
        file_paths, _ = QFileDialog.getOpenFileNames(
            self, "בחר קבצי אודיו או JSON", "",
            "Audio & Project Files (*.mp3 *.m4a *.json);;MP3 (*.mp3);;M4A (*.m4a);;JSON (*.json)"
        )
        if not file_paths:
            return

        imported = 0
        skipped = 0
        first_imported_path = None

        for file_path in file_paths:
            base_name = os.path.splitext(os.path.basename(file_path))[0]
            dir_name = os.path.dirname(file_path)
            base_path = os.path.join(dir_name, base_name)

            if file_path.endswith(".json"):
                # JSON נבחר - חייב קובץ אודיו תואם
                audio = _find_audio_file(base_path)
                if not audio:
                    skipped += 1
                    continue
            elif _is_audio_file(file_path):
                # קובץ אודיו - תמיד מותר (גם בלי JSON)
                if not os.path.exists(file_path):
                    skipped += 1
                    continue
            else:
                skipped += 1
                continue

            self.track_directory(dir_name)
            imported += 1
            if first_imported_path is None:
                source_json = os.path.join(dir_name, base_name + ".json")
                if os.path.exists(source_json):
                    first_imported_path = source_json
                else:
                    first_imported_path = file_path

        self.refresh_file_list()

        if imported > 0 and first_imported_path:
            self.select_file_by_path(first_imported_path)

        msg = f"יובאו {imported} פרויקטים."
        if skipped > 0:
            msg += f"\n{skipped} קבצים דולגו."
        QMessageBox.information(self, "ייבוא", msg)

    # === ניהול קבצים סטנדרטי ===

    def _save_tracked_dirs(self):
        """שומר את רשימת התיקיות המנוטרות להגדרות"""
        if self.main_window and hasattr(self.main_window, 'settings'):
            self.main_window.settings["tracked_project_dirs"] = list(self.tracked_dirs)
            self.main_window.save_settings()

    def _save_virtual_folders(self):
        """שומר את מבנה התיקיות הוירטואליות להגדרות"""
        if self.main_window and hasattr(self.main_window, 'settings'):
            self.main_window.settings["virtual_folders"] = self.virtual_folders
            self.main_window.save_settings()

    def track_directory(self, dir_path):
        """מוסיף תיקייה למעקב (כדי שפרויקטים שלה יופיעו ברשימה)"""
        if dir_path and os.path.isdir(dir_path):
            self.tracked_dirs.add(dir_path)
            self._save_tracked_dirs()

    def _collect_all_projects(self):
        """איסוף כל הפרויקטים מכל התיקיות המנוטרות.
        מחזיר רשימת tuples: (filename, full_path, mod_time, has_json)
        - פרויקטים עם JSON: הנתיב הוא לקובץ JSON
        - אודיו בלי JSON: הנתיב הוא לקובץ האודיו (mp3/m4a)
        """
        files = []
        seen_bases = set()  # מעקב לפי base name למניעת כפילויות
        for directory in list(self.tracked_dirs):
            if not os.path.exists(directory):
                continue
            for f in os.listdir(directory):
                base_name = os.path.splitext(f)[0]
                base_key = os.path.normpath(os.path.join(directory, base_name))
                if base_key in seen_bases:
                    continue

                if f.endswith(".json"):
                    full_path = os.path.join(directory, f)
                    base_path = os.path.splitext(full_path)[0]
                    audio = _find_audio_file(base_path)
                    if audio:
                        seen_bases.add(base_key)
                        mod_time = os.path.getmtime(full_path)
                        files.append((f, full_path, mod_time, True))

                elif _is_audio_file(f):
                    json_path = os.path.join(directory, base_name + ".json")
                    if not os.path.exists(json_path):
                        # אודיו ללא JSON - פרויקט חיצוני
                        full_path = os.path.join(directory, f)
                        seen_bases.add(base_key)
                        mod_time = os.path.getmtime(full_path)
                        files.append((f, full_path, mod_time, False))

        files.sort(key=lambda x: x[2], reverse=True)
        return files

    def _passes_date_filter(self, mod_time):
        """בודק אם קובץ עובר את סינון התאריך הנבחר"""
        if not hasattr(self, 'combo_date_filter'):
            return True
        filter_idx = self.combo_date_filter.currentIndex()
        if filter_idx == 0:  # הכל
            return True
        now = datetime.now()
        diff_days = (now - datetime.fromtimestamp(mod_time)).days
        if filter_idx == 1:  # היום
            today_start = datetime(now.year, now.month, now.day).timestamp()
            return mod_time >= today_start
        elif filter_idx == 2:  # השבוע
            return diff_days < 7
        elif filter_idx == 3:  # החודש
            return diff_days < 30
        elif filter_idx == 4:  # השנה
            return diff_days < 365
        return True

    def refresh_file_list(self):
        # שמירת מצב פתוח/סגור של תיקיות ובחירה נוכחית
        expanded_folders = set()
        selected_path = None
        root = self.list_files.invisibleRootItem()
        for i in range(root.childCount()):
            item = root.child(i)
            folder_name = item.data(0, Qt.UserRole + 2)
            if folder_name and item.isExpanded():
                expanded_folders.add(folder_name)
            if item.data(0, Qt.UserRole + 1) == "unsorted_group" and item.isExpanded():
                expanded_folders.add("__unsorted__")
        current = self.list_files.currentItem()
        if current:
            selected_path = current.data(0, Qt.UserRole)

        self.list_files.clear()

        all_files = self._collect_all_projects()

        # טעינת שמות תצוגה מותאמים
        custom_names = {}
        if self.main_window and hasattr(self.main_window, 'settings'):
            custom_names = self.main_window.settings.get("project_display_names", {})

        # מיפוי קבצים שמשויכים לתיקיות וירטואליות
        files_in_virtual = set()
        for folder_name, file_list in self.virtual_folders.items():
            for fp in file_list:
                files_in_virtual.add(os.path.normpath(fp))

        # יצירת תיקיות וירטואליות בעץ
        for folder_name in sorted(self.virtual_folders.keys()):
            folder_item = QTreeWidgetItem([f"📁 {folder_name}"])
            folder_item.setData(0, Qt.UserRole + 1, "virtual_folder")
            folder_item.setData(0, Qt.UserRole + 2, folder_name)
            font = folder_item.font(0)
            font.setBold(True)
            folder_item.setFont(0, font)
            folder_item.setForeground(0, QColor("#3498DB"))
            self.list_files.addTopLevelItem(folder_item)
            # שחזור מצב פתוח (ברירת מחדל: פתוח)
            folder_item.setExpanded(folder_name in expanded_folders or len(expanded_folders) == 0)

            for fpath in self.virtual_folders[folder_name]:
                if not os.path.exists(fpath):
                    continue
                try:
                    ftime = os.path.getmtime(fpath)
                    if not self._passes_date_filter(ftime):
                        continue
                except:
                    pass
                norm_fp = os.path.normpath(fpath)
                # בדיקה אם אודיו בלי JSON
                is_audio_only = _is_audio_file(fpath) and not os.path.exists(os.path.splitext(fpath)[0] + ".json")
                base_display = custom_names.get(norm_fp, os.path.splitext(os.path.basename(fpath))[0])
                display_name = f"🎵 {base_display}" if is_audio_only else base_display
                file_item = QTreeWidgetItem([display_name])
                file_item.setData(0, Qt.UserRole, fpath)
                file_item.setData(0, Qt.UserRole + 3, not is_audio_only)
                file_item.setToolTip(0, fpath)
                if is_audio_only:
                    font = file_item.font(0)
                    font.setItalic(True)
                    file_item.setFont(0, font)
                    file_item.setForeground(0, QColor("#95A5A6"))
                folder_item.addChild(file_item)

        # קבצים שאינם בתיקיות וירטואליות - תחת "כללי"
        unsorted_item = QTreeWidgetItem(["📋 כללי"])
        unsorted_item.setData(0, Qt.UserRole + 1, "unsorted_group")
        font = unsorted_item.font(0)
        font.setBold(True)
        unsorted_item.setFont(0, font)
        unsorted_item.setForeground(0, QColor("#F1C40F"))

        for fname, fpath, ftime, has_json in all_files:
            norm_fpath = os.path.normpath(fpath)
            if norm_fpath in files_in_virtual:
                continue
            if not self._passes_date_filter(ftime):
                continue

            base_display = custom_names.get(norm_fpath, os.path.splitext(fname)[0])
            if not has_json:
                display_name = f"🎵 {base_display}"
            else:
                display_name = base_display
            file_item = QTreeWidgetItem([display_name])
            file_item.setData(0, Qt.UserRole, fpath)
            file_item.setData(0, Qt.UserRole + 3, has_json)  # סימון אם יש JSON
            file_item.setToolTip(0, fpath)
            if not has_json:
                font = file_item.font(0)
                font.setItalic(True)
                file_item.setFont(0, font)
                file_item.setForeground(0, QColor("#95A5A6"))
            unsorted_item.addChild(file_item)

        if unsorted_item.childCount() > 0:
            self.list_files.addTopLevelItem(unsorted_item)
            unsorted_item.setExpanded("__unsorted__" in expanded_folders or len(expanded_folders) == 0)

        # שחזור בחירה נוכחית
        if selected_path:
            self._restore_selection(selected_path)

    def on_file_selected(self, item, column=0):
        # אם לחצו על כותרת קבוצה/תיקייה - פתח/סגור
        if item.childCount() > 0 and not item.data(0, Qt.UserRole):
            item.setExpanded(not item.isExpanded())
            return
        # בדיקה שיש נתיב קובץ
        file_path = item.data(0, Qt.UserRole)
        if not file_path:
            item.setExpanded(not item.isExpanded())
            return

        self.save_progress()
        self.marked_errors.clear()

        # בדיקה אם זה קובץ אודיו בלי JSON
        if _is_audio_file(file_path):
            json_path = os.path.splitext(file_path)[0] + ".json"
            if os.path.exists(json_path):
                # JSON נוצר בינתיים (אחרי תמלול) - טען כרגיל
                self.current_file_id = os.path.basename(json_path)
                self.load_project(json_path, file_path)
            else:
                # אודיו בלי JSON - טען רק אודיו
                self.current_file_id = os.path.basename(file_path)
                self.load_mp3_only(file_path)
            return

        # טעינה רגילה (JSON + אודיו)
        json_path = file_path
        mp3_path = _get_audio_path_from_json(json_path) or json_path.replace(".json", ".mp3")
        pdf_path = json_path.replace(".json", ".pdf")

        self.current_file_id = os.path.basename(json_path)
        self.load_project(json_path, mp3_path)

        if os.path.exists(pdf_path):
            self.pdf_viewer.load_pdf(pdf_path)
        elif self.main_window and hasattr(self.main_window, 'tab_main') and self.main_window.tab_main.file_path:
            self.pdf_viewer.load_pdf(self.main_window.tab_main.file_path)

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

    def load_mp3_only(self, mp3_path):
        """טעינת MP3 ללא JSON - רק נגן אודיו, בלי סנכרון טקסט"""
        try:
            self.current_json_data = []
            self.sentence_ranges = []
            self.last_highlighted_index = -1
            self.current_pdf_path = None

            self.player.setMedia(QMediaContent(QUrl.fromLocalFile(mp3_path)))

            # הצגת הודעה בתצוגת הטקסט
            self.text_display.clear()
            cursor = self.text_display.textCursor()
            fmt = QTextCharFormat()
            fmt.setForeground(QColor("#95A5A6"))
            fmt.setFontPointSize(16.0)
            cursor.setCharFormat(fmt)
            cursor.insertText("🎵 קובץ אודיו ללא תמלול\n\n")
            fmt2 = QTextCharFormat()
            fmt2.setForeground(QColor("#7F8C8D"))
            fmt2.setFontPointSize(13.0)
            cursor.setCharFormat(fmt2)
            cursor.insertText("לחץ ימני על הקובץ בעץ ובחר \"🎙️ תמלל\"\nכדי ליצור תמלול אוטומטי עם טקסט מסונכרן.")

            self.btn_play.setText("▶")
            self.load_progress()

        except Exception as e:
            print(f"[ERROR] load_mp3_only: {e}")

    def manually_load_pdf(self):
        path, _ = QFileDialog.getOpenFileName(self, "בחר PDF", "", "PDF Files (*.pdf)")
        if path:
            self.current_pdf_path = path
            self.pdf_viewer.load_pdf(path)

    def select_file_by_path(self, path):
        """בחירה אוטומטית בקובץ (מחפש בכל רמות העץ)"""
        target = os.path.normpath(path)

        def search_children(parent_item):
            for j in range(parent_item.childCount()):
                child = parent_item.child(j)
                data_path = child.data(0, Qt.UserRole)
                if data_path and os.path.normpath(data_path) == target:
                    parent_item.setExpanded(True)
                    self.list_files.setCurrentItem(child)
                    self.list_files.scrollToItem(child)
                    self.on_file_selected(child)
                    return True
                # חיפוש ברמה עמוקה יותר
                if child.childCount() > 0:
                    if search_children(child):
                        return True
            return False

        root = self.list_files.invisibleRootItem()
        search_children(root)

    def _restore_selection(self, path):
        """שחזור בחירה נוכחית אחרי רענון"""
        if not path:
            return
        target = os.path.normpath(path)
        root = self.list_files.invisibleRootItem()
        for i in range(root.childCount()):
            parent = root.child(i)
            for j in range(parent.childCount()):
                child = parent.child(j)
                child_path = child.data(0, Qt.UserRole)
                if child_path and os.path.normpath(child_path) == target:
                    self.list_files.setCurrentItem(child)
                    return

    def _get_selected_project_paths(self):
        """מחזיר רשימת נתיבי JSON של כל הפרויקטים המסומנים"""
        paths = []
        for item in self.list_files.selectedItems():
            json_path = item.data(0, Qt.UserRole)
            if json_path:
                paths.append(json_path)
        return paths

    def show_file_context_menu(self, pos):
        item = self.list_files.itemAt(pos)
        if not item:
            return

        menu = QMenu()
        item_type = item.data(0, Qt.UserRole + 1)
        json_path = item.data(0, Qt.UserRole)

        if item_type == "virtual_folder":
            # תפריט לתיקייה וירטואלית
            folder_name = item.data(0, Qt.UserRole + 2)
            action_rename = menu.addAction("✏️ שנה שם תיקייה")
            action_delete_folder = menu.addAction("🗑️ מחק תיקייה")

            chosen = menu.exec_(self.list_files.mapToGlobal(pos))
            if chosen == action_rename:
                self._rename_virtual_folder(folder_name)
            elif chosen == action_delete_folder:
                self._delete_virtual_folder(folder_name)
            return

        if not json_path:
            return

        # בדיקה כמה פרויקטים מסומנים
        selected_paths = self._get_selected_project_paths()
        is_batch = len(selected_paths) > 1

        if is_batch:
            # === תפריט batch למספר פרויקטים ===
            action_download_mp3 = menu.addAction(f"💾 הורד {len(selected_paths)} קבצי אודיו")
            action_download_pdf = menu.addAction(f"📄 הורד {len(selected_paths)} קבצי PDF")
            action_telegram = menu.addAction(f"📤 שלח {len(selected_paths)} לטלגרם")
            menu.addSeparator()

            move_menu = menu.addMenu(f"📁 העבר {len(selected_paths)} לתיקייה")
            action_no_folder = move_menu.addAction("── ללא תיקייה ──")
            move_menu.addSeparator()
            folder_actions = {}
            for folder_name in sorted(self.virtual_folders.keys()):
                action = move_menu.addAction(f"📁 {folder_name}")
                folder_actions[action] = folder_name
            move_menu.addSeparator()
            action_new_folder = move_menu.addAction("➕ תיקייה חדשה...")

            menu.addSeparator()
            action_delete = menu.addAction(f"🗑️ מחק {len(selected_paths)} פרויקטים")

            chosen = menu.exec_(self.list_files.mapToGlobal(pos))

            if chosen == action_download_mp3:
                self._batch_download(selected_paths, "audio")
            elif chosen == action_download_pdf:
                self._batch_download(selected_paths, "pdf")
            elif chosen == action_telegram:
                self._batch_send_telegram(selected_paths)
            elif chosen == action_delete:
                self._batch_delete(selected_paths)
            elif chosen == action_no_folder:
                for p in selected_paths:
                    self._remove_from_all_folders(p)
            elif chosen == action_new_folder:
                name, ok = QInputDialog.getText(self, "תיקייה חדשה", "שם התיקייה:")
                if ok and name.strip():
                    name = name.strip()
                    if name not in self.virtual_folders:
                        self.virtual_folders[name] = []
                    for p in selected_paths:
                        self._move_to_folder(p, name)
            elif chosen in folder_actions:
                for p in selected_paths:
                    self._move_to_folder(p, folder_actions[chosen])
            return

        # === תפריט רגיל לפרויקט בודד ===
        action_transcribe = menu.addAction("🎙️ תמלל")
        action_rename = menu.addAction("✏️ שנה שם פרויקט")
        menu.addSeparator()
        action_download_mp3 = menu.addAction("💾 הורד אודיו")
        action_download_pdf = menu.addAction("📄 הורד PDF")
        action_telegram = menu.addAction("📤 שלח לטלגרם")
        menu.addSeparator()

        # תפריט "העבר לתיקייה"
        move_menu = menu.addMenu("📁 העבר לתיקייה")
        action_no_folder = move_menu.addAction("── ללא תיקייה ──")
        move_menu.addSeparator()
        folder_actions = {}
        for folder_name in sorted(self.virtual_folders.keys()):
            action = move_menu.addAction(f"📁 {folder_name}")
            folder_actions[action] = folder_name
        move_menu.addSeparator()
        action_new_folder = move_menu.addAction("➕ תיקייה חדשה...")

        menu.addSeparator()
        action_delete = menu.addAction("🗑️ מחק פרויקט")

        chosen = menu.exec_(self.list_files.mapToGlobal(pos))

        if chosen == action_transcribe:
            self._start_transcription(json_path)
        elif chosen == action_rename:
            self._rename_project(item, json_path)
        elif chosen == action_download_mp3:
            self._download_file(json_path, "audio")
        elif chosen == action_download_pdf:
            self._download_file(json_path, "pdf")
        elif chosen == action_telegram:
            self._send_to_telegram([json_path])
        elif chosen == action_delete:
            self._delete_project(item, json_path)
        elif chosen == action_no_folder:
            self._remove_from_all_folders(json_path)
        elif chosen == action_new_folder:
            self._move_to_new_folder(json_path)
        elif chosen in folder_actions:
            self._move_to_folder(json_path, folder_actions[chosen])

    def _delete_project(self, item, json_path):
        """מחיקת פרויקט (קבצים מהדיסק + מרשימה)"""
        if QMessageBox.question(self, "מחיקה", "למחוק את הפרויקט?",
                                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            base = os.path.splitext(json_path)[0]
            for ext in [".json", ".mp3", ".m4a", ".pdf"]:
                fpath = base + ext
                if os.path.exists(fpath):
                    os.remove(fpath)

            # הסרה מתיקיות וירטואליות
            norm = os.path.normpath(json_path)
            for folder_name in list(self.virtual_folders.keys()):
                paths = self.virtual_folders[folder_name]
                self.virtual_folders[folder_name] = [p for p in paths if os.path.normpath(p) != norm]
            self._save_virtual_folders()

            # הסרה משמות מותאמים
            if self.main_window and hasattr(self.main_window, 'settings'):
                custom_names = self.main_window.settings.get("project_display_names", {})
                custom_names.pop(norm, None)
                self.main_window.settings["project_display_names"] = custom_names
                self.main_window.save_settings()

            # הסרה מהעץ
            parent = item.parent()
            if parent:
                parent.removeChild(item)
            else:
                idx = self.list_files.indexOfTopLevelItem(item)
                if idx >= 0:
                    self.list_files.takeTopLevelItem(idx)

            self.text_display.clear()
            self.player.stop()
        except Exception as e:
            print(f"[ERROR] Delete project: {e}")
            self.refresh_file_list()

    def create_virtual_folder(self):
        """יצירת תיקייה וירטואלית חדשה"""
        name, ok = QInputDialog.getText(self, "תיקייה חדשה", "שם התיקייה:")
        if ok and name.strip():
            name = name.strip()
            if name in self.virtual_folders:
                QMessageBox.warning(self, "קיימת", f"תיקייה בשם '{name}' כבר קיימת.")
                return
            self.virtual_folders[name] = []
            self._save_virtual_folders()
            self.refresh_file_list()

    def _rename_virtual_folder(self, old_name):
        """שינוי שם תיקייה וירטואלית"""
        new_name, ok = QInputDialog.getText(self, "שינוי שם", "שם חדש:", text=old_name)
        if ok and new_name.strip() and new_name.strip() != old_name:
            new_name = new_name.strip()
            if new_name in self.virtual_folders:
                QMessageBox.warning(self, "קיימת", f"תיקייה בשם '{new_name}' כבר קיימת.")
                return
            self.virtual_folders[new_name] = self.virtual_folders.pop(old_name)
            self._save_virtual_folders()
            self.refresh_file_list()

    def _delete_virtual_folder(self, folder_name):
        """מחיקת תיקייה וירטואלית (הקבצים עצמם לא נמחקים)"""
        if QMessageBox.question(self, "מחיקת תיקייה",
                                f"למחוק את התיקייה '{folder_name}'?\n(הקבצים עצמם לא יימחקו)",
                                QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            self.virtual_folders.pop(folder_name, None)
            self._save_virtual_folders()
            self.refresh_file_list()

    def _move_to_folder(self, json_path, folder_name):
        """העברת פרויקט לתיקייה וירטואלית"""
        norm = os.path.normpath(json_path)
        # הסרה מכל תיקייה אחרת
        for fn in self.virtual_folders:
            self.virtual_folders[fn] = [p for p in self.virtual_folders[fn] if os.path.normpath(p) != norm]
        # הוספה לתיקייה הנבחרת
        if json_path not in self.virtual_folders[folder_name]:
            self.virtual_folders[folder_name].append(json_path)
        self._save_virtual_folders()
        self.refresh_file_list()

    def _remove_from_all_folders(self, json_path):
        """הסרת פרויקט מכל התיקיות הוירטואליות"""
        norm = os.path.normpath(json_path)
        for fn in self.virtual_folders:
            self.virtual_folders[fn] = [p for p in self.virtual_folders[fn] if os.path.normpath(p) != norm]
        self._save_virtual_folders()
        self.refresh_file_list()

    def _move_to_new_folder(self, json_path):
        """יצירת תיקייה חדשה והעברת פרויקט אליה"""
        name, ok = QInputDialog.getText(self, "תיקייה חדשה", "שם התיקייה:")
        if ok and name.strip():
            name = name.strip()
            if name not in self.virtual_folders:
                self.virtual_folders[name] = []
            self._move_to_folder(json_path, name)

    # === שינוי שם פרויקט ===
    def _rename_project(self, item, json_path):
        """שינוי שם תצוגה של פרויקט בעץ"""
        current_name = item.text(0)
        new_name, ok = QInputDialog.getText(self, "שינוי שם", "שם חדש:", text=current_name)
        if ok and new_name.strip() and new_name.strip() != current_name:
            new_name = new_name.strip()
            norm_path = os.path.normpath(json_path)
            # שמירת השם המותאם
            if self.main_window and hasattr(self.main_window, 'settings'):
                custom_names = self.main_window.settings.get("project_display_names", {})
                custom_names[norm_path] = new_name
                self.main_window.settings["project_display_names"] = custom_names
                self.main_window.save_settings()
            item.setText(0, new_name)

    # === הורדת קבצים ===
    def _download_file(self, file_path, file_type):
        """הורדת אודיו או PDF - שמירה למיקום שנבחר"""
        base = os.path.splitext(file_path)[0]
        if file_type == "audio":
            source = _find_audio_file(base)
            if not source:
                source = base + ".mp3"
            ext = os.path.splitext(source)[1]
            filter_str = f"Audio Files (*{ext})"
        else:
            source = base + ".pdf"
            filter_str = "PDF Files (*.pdf)"

        if not os.path.exists(source):
            QMessageBox.warning(self, "לא נמצא", f"הקובץ {os.path.basename(source)} לא נמצא.")
            return

        default_name = os.path.basename(source)
        dest_path, _ = QFileDialog.getSaveFileName(self, f"שמור {file_type.upper()}", default_name, filter_str)
        if dest_path:
            try:
                shutil.copy2(source, dest_path)
                QMessageBox.information(self, "הושלם", f"הקובץ נשמר ב:\n{dest_path}")
            except Exception as e:
                QMessageBox.critical(self, "שגיאה", f"שגיאה בשמירה: {e}")

    def _batch_download(self, file_paths, file_type):
        """הורדת מספר קבצי אודיו או PDF לתיקייה נבחרת"""
        label = "אודיו" if file_type == "audio" else "PDF"
        dest_dir = QFileDialog.getExistingDirectory(self, f"בחר תיקייה לשמירת קבצי {label}")
        if not dest_dir:
            return

        copied = 0
        missing = 0
        for fp in file_paths:
            base = os.path.splitext(fp)[0]
            if file_type == "audio":
                source = _find_audio_file(base)
            else:
                source = base + ".pdf"
                source = source if os.path.exists(source) else None

            if source and os.path.exists(source):
                try:
                    shutil.copy2(source, os.path.join(dest_dir, os.path.basename(source)))
                    copied += 1
                except:
                    pass
            else:
                missing += 1

        msg = f"הועתקו {copied} קבצי {label} ל:\n{dest_dir}"
        if missing > 0:
            msg += f"\n{missing} קבצים לא נמצאו."
        QMessageBox.information(self, "הושלם", msg)

    # === שליחה לטלגרם ===
    def _send_to_telegram(self, json_paths):
        """שליחת פרויקטים לטלגרם (MP3 + PDF)"""
        if not self.main_window or not hasattr(self.main_window, 'settings'):
            QMessageBox.warning(self, "שגיאה", "לא ניתן לגשת להגדרות.")
            return

        token = self.main_window.settings.get("tg_token", "")
        chat_id = self.main_window.settings.get("tg_chat_id", "")

        if not token or not chat_id:
            QMessageBox.warning(self, "טלגרם", "יש להגדיר Bot Token ו-Chat ID בהגדרות.")
            return

        files_to_send = []
        for jp in json_paths:
            base = os.path.splitext(jp)[0]
            audio_path = _find_audio_file(base)
            pdf_path = base + ".pdf"
            if audio_path:
                files_to_send.append((audio_path, "audio"))
            if os.path.exists(pdf_path):
                files_to_send.append((pdf_path, "document"))

        if not files_to_send:
            QMessageBox.warning(self, "טלגרם", "לא נמצאו קבצים לשליחה.")
            return

        self.tg_worker = TelegramWorker(token, chat_id, files_to_send)
        self.tg_worker.log_update.connect(lambda msg: print(f"[TELEGRAM] {msg}"))
        self.tg_worker.finished.connect(lambda: QMessageBox.information(self, "טלגרם", f"נשלחו {len(files_to_send)} קבצים לטלגרם."))
        self.tg_worker.start()

    def _batch_send_telegram(self, json_paths):
        """שליחת מספר פרויקטים לטלגרם"""
        self._send_to_telegram(json_paths)

    # === מחיקה מרובה ===
    def _batch_delete(self, json_paths):
        """מחיקת מספר פרויקטים"""
        if QMessageBox.question(self, "מחיקה",
                                f"למחוק {len(json_paths)} פרויקטים?",
                                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return

        for jp in json_paths:
            try:
                base = os.path.splitext(jp)[0]
                for ext in [".json", ".mp3", ".m4a", ".pdf"]:
                    fpath = base + ext
                    if os.path.exists(fpath):
                        os.remove(fpath)
                # הסרה מתיקיות וירטואליות
                norm = os.path.normpath(jp)
                for folder_name in list(self.virtual_folders.keys()):
                    paths = self.virtual_folders[folder_name]
                    self.virtual_folders[folder_name] = [p for p in paths if os.path.normpath(p) != norm]
                # הסרה משמות מותאמים
                if self.main_window and hasattr(self.main_window, 'settings'):
                    custom_names = self.main_window.settings.get("project_display_names", {})
                    custom_names.pop(norm, None)
                    self.main_window.settings["project_display_names"] = custom_names
            except Exception as e:
                print(f"[ERROR] Delete project: {e}")

        self._save_virtual_folders()
        if self.main_window:
            self.main_window.save_settings()
        self.text_display.clear()
        self.player.stop()
        self.refresh_file_list()

    # === תמלול ===
    def _start_transcription(self, file_path):
        """התחלת תמלול קובץ אודיו"""
        # מציאת נתיב האודיו
        if file_path.endswith(".json"):
            base = os.path.splitext(file_path)[0]
            mp3_path = _find_audio_file(base)
            if not mp3_path:
                mp3_path = base + ".mp3"
        else:
            mp3_path = file_path

        if not os.path.exists(mp3_path):
            QMessageBox.warning(self, "שגיאה", f"קובץ אודיו לא נמצא:\n{mp3_path}")
            return

        # הצגת דיאלוג הגדרות
        default_model = "large"
        default_lang = "he"
        if self.main_window and hasattr(self.main_window, 'settings'):
            default_model = self.main_window.settings.get("transcription_model", "large")
            default_lang = self.main_window.settings.get("transcription_language", "he")

        dlg = TranscriptionDialog(default_model, default_lang, self)
        if dlg.exec_() != QDialog.Accepted:
            return

        settings = dlg.get_settings()

        # עדכון שורת סטטוס
        if self.main_window:
            self.main_window.lbl_status.setText("🎙️ מתמלל...")
            self.main_window.progress_bar.setValue(0)

        # הפעלת worker
        self._transcription_mp3_path = mp3_path
        self.transcription_worker = TranscriptionWorker(
            mp3_path, settings["model"], settings["language"]
        )
        self.transcription_worker.progress_update.connect(self._on_transcription_progress)
        self.transcription_worker.log_update.connect(self._on_transcription_log)
        self.transcription_worker.finished_success.connect(self._on_transcription_success)
        self.transcription_worker.finished_error.connect(self._on_transcription_error)
        self.transcription_worker.start()

    def _on_transcription_progress(self, value):
        if self.main_window:
            self.main_window.progress_bar.setValue(value)

    def _on_transcription_log(self, msg):
        if self.main_window:
            self.main_window.lbl_status.setText(f"🎙️ {msg}")
        print(f"[TRANSCRIPTION] {msg}")

    def _on_transcription_success(self, json_path, karaoke_data):
        """callback כשתמלול הושלם בהצלחה"""
        if self.main_window:
            self.main_window.lbl_status.setText("✅ תמלול הושלם!")
            self.main_window.progress_bar.setValue(100)

        # רענון העץ וטעינת הפרויקט
        self.refresh_file_list()

        # טעינת הפרויקט המתומלל
        self.select_file_by_path(json_path)

        QMessageBox.information(self, "תמלול הושלם",
                                f"התמלול הושלם בהצלחה!\n{len(karaoke_data)} קטעים זוהו.")

    def _on_transcription_error(self, error_msg):
        """callback כשתמלול נכשל"""
        if self.main_window:
            self.main_window.lbl_status.setText("❌ תמלול נכשל")
            self.main_window.progress_bar.setValue(0)

        QMessageBox.critical(self, "שגיאת תמלול", error_msg)

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

