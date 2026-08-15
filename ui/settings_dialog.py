"""
Settings dialog for entering/updating API keys, so users don't need to
manually edit a .env file next to the app. Saves via
config.save_env_values(), which preserves any other existing lines/vars
untouched and updates os.environ immediately so most changes take effect
without restarting the app (the caller is still responsible for rebuilding
RouteEngine's provider list afterward — see MainWindow._on_settings_clicked).
"""
from PyQt5.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from config import mask_key, read_current_env_values, save_env_values

FIELDS = [
    {
        "key": "GEMINI_API_KEY",
        "label": "Google Gemini API Key (Optional AI Provider)",
        "help": "AI prompt parser powered by Google Gemini (gemini-2.0-flash). Generous free tier.",
        "signup_url": "https://aistudio.google.com/app/apikey",
        "signup_label": "Get a free Gemini API key",
    },
    {
        "key": "OPENAI_API_KEY",
        "label": "OpenAI API Key (Optional AI Provider)",
        "help": "AI prompt parser powered by OpenAI (GPT-4o-mini).",
        "signup_url": "https://platform.openai.com/api-keys",
        "signup_label": "Get an OpenAI API key",
    },
    {
        "key": "ANTHROPIC_API_KEY",
        "label": "Anthropic API Key (Optional AI Provider)",
        "help": "AI prompt parser powered by Anthropic Claude.",
        "signup_url": "https://console.anthropic.com/settings/keys",
        "signup_label": "Get an Anthropic API key",
    },
    {
        "key": "ORS_API_KEY",
        "label": "OpenRouteService API Key",
        "help": "Primary routing provider — elevation data, surface composition, and accurate loop/distance targeting. Free tier, no card required. Strongly recommended.",
        "signup_url": "https://openrouteservice.org/dev/#/signup",
        "signup_label": "Get a free ORS API key",
    },
    {
        "key": "MAPBOX_API_KEY",
        "label": "Mapbox API Key (Optional)",
        "help": "Optional secondary routing provider for extra alternates while editing a route. Its free tier requires a card on file.",
        "signup_url": "https://account.mapbox.com/access-tokens/",
        "signup_label": "Get a Mapbox API key",
    },
]


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings — API Keys")
        self.resize(480, 480)
        self._inputs: dict[str, QLineEdit] = {}

        layout = QVBoxLayout(self)

        intro = QLabel(
            "Keys are stored in a .env file next to the app and used only to "
            "talk directly to each service's own API — never sent anywhere "
            "else. Leave a field blank to keep its current value unchanged."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #94a3b8;")
        layout.addWidget(intro)

        current_values = read_current_env_values()

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #334155;")
        layout.addWidget(sep)

        for field in FIELDS:
            layout.addWidget(self._build_field(field, current_values.get(field["key"], "")))
            separator = QFrame()
            separator.setFrameShape(QFrame.HLine)
            separator.setStyleSheet("color: #334155;")
            layout.addWidget(separator)

        layout.addStretch()

        button_row = QHBoxLayout()
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        save_button = QPushButton("Save")
        save_button.setObjectName("primaryButton")
        save_button.clicked.connect(self._on_save)
        button_row.addStretch()
        button_row.addWidget(cancel_button)
        button_row.addWidget(save_button)
        layout.addLayout(button_row)

    def _build_field(self, field: dict, current_value: str) -> QWidget:
        container = QWidget()
        v = QVBoxLayout(container)
        v.setContentsMargins(0, 6, 0, 6)

        title = QLabel(field["label"])
        title.setStyleSheet("font-weight: 700;")
        v.addWidget(title)

        help_label = QLabel(field["help"])
        help_label.setWordWrap(True)
        help_label.setStyleSheet("color: #94a3b8; font-size: 12px;")
        v.addWidget(help_label)

        row = QHBoxLayout()
        line_edit = QLineEdit()
        line_edit.setEchoMode(QLineEdit.Password)
        if current_value:
            line_edit.setPlaceholderText(f"Currently set ({mask_key(current_value)}) — leave blank to keep")
        else:
            line_edit.setPlaceholderText("Not set")
        self._inputs[field["key"]] = line_edit
        row.addWidget(line_edit, 1)

        show_button = QPushButton("Show")
        show_button.setCheckable(True)
        show_button.setFixedWidth(56)

        def toggle_visibility(checked, le=line_edit, btn=show_button):
            le.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)
            btn.setText("Hide" if checked else "Show")

        show_button.toggled.connect(toggle_visibility)
        row.addWidget(show_button)
        v.addLayout(row)

        link_label = QLabel(f'<a href="{field["signup_url"]}">{field["signup_label"]} \u2192</a>')
        link_label.setOpenExternalLinks(True)
        link_label.setStyleSheet("font-size: 12px;")
        v.addWidget(link_label)

        return container

    def _on_save(self):
        updates = {}
        for key, line_edit in self._inputs.items():
            value = line_edit.text().strip()
            if value:
                updates[key] = value

        if not updates:
            # Nothing typed in any field — treat Save the same as Cancel
            # rather than rewriting the file for no reason.
            self.reject()
            return

        try:
            save_env_values(updates)
        except Exception as e:
            QMessageBox.warning(self, "Save failed", f"Couldn't save settings: {e}")
            return

        self.accept()
