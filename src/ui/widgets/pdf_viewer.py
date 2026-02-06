
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QLabel, QComboBox) 
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QScrollArea, QLabel
from PIL import Image as PILImage
from PyQt5.QtGui import QImage, QPixmap
from pdf2image import convert_from_path




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
            