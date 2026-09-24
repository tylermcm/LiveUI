import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

# Keep the demo directly runnable without installing the examples as a package.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from main_window import MainWindow


def main() -> int:
    application = QApplication(sys.argv)
    window = MainWindow()
    window.resize(640, 520)
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())

