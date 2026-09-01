from PySide6.QtWidgets import QMainWindow, QLabel

class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Human Input Automation")
        self.resize(900, 600)
        self.setCentralWidget(QLabel(
            "Skeleton ready. Claude should implement the target-window selector, "
            "editor, timing controls, runner, and safety controls."
        ))
