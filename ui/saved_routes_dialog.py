"""
Dialog for browsing saved routes: load one back into the main window's map,
or delete ones you don't want anymore.
"""
from typing import Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from core import route_storage


class SavedRoutesDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("My Routes")
        self.resize(440, 420)
        self.selected_route_id: Optional[int] = None

        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(lambda _item: self._on_load())

        self.empty_label = QLabel("No saved routes yet — plan a route, then use \"Save Route\".")
        self.empty_label.setWordWrap(True)
        self.empty_label.setVisible(False)

        self._refresh()

        load_button = QPushButton("Load")
        load_button.clicked.connect(self._on_load)
        delete_button = QPushButton("Delete")
        delete_button.clicked.connect(self._on_delete)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.reject)

        button_row = QHBoxLayout()
        button_row.addWidget(load_button)
        button_row.addWidget(delete_button)
        button_row.addStretch()
        button_row.addWidget(close_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.list_widget)
        layout.addWidget(self.empty_label)
        layout.addLayout(button_row)

    def _refresh(self):
        self.list_widget.clear()
        routes = route_storage.list_routes()
        self.empty_label.setVisible(not routes)
        self.list_widget.setVisible(bool(routes))
        for summary in routes:
            item = QListWidgetItem(summary.label())
            item.setData(Qt.UserRole, summary.id)
            self.list_widget.addItem(item)

    def _on_load(self):
        item = self.list_widget.currentItem()
        if not item:
            return
        self.selected_route_id = item.data(Qt.UserRole)
        self.accept()

    def _on_delete(self):
        item = self.list_widget.currentItem()
        if not item:
            return
        confirm = QMessageBox.question(
            self,
            "Delete route",
            f"Delete \"{item.text().split('  —  ')[0]}\"? This can't be undone.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm == QMessageBox.Yes:
            route_storage.delete_route(item.data(Qt.UserRole))
            self._refresh()
