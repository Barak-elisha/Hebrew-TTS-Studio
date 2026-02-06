from PyQt5.QtCore import QObject, pyqtSignal

class ProcessingWorker(QObject):
    finished = pyqtSignal()
    progress = pyqtSignal(str)  # חיווי טקסטואלי
    percent = pyqtSignal(int)   # חיווי למד התקדמות

    def process_files(self, files):
        for i, file in enumerate(files):
            # כאן נכנס הלוגיקה של ה-Trim וה-Decode
            msg = f"Processing sentence {i}..."
            self.progress.emit(msg) # שולח עדכון לממשק מבלי לעצור
            
            # ביצוע העיבוד בפועל...
            
            self.percent.emit(int((i+1)/len(files)*100))
        self.finished.emit()