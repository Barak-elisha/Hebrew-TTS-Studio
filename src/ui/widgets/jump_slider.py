from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QSlider, QStyle, QStyleOptionSlider)


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
