"""Action list editor and the per-action dialog."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..core.actions import Action
from ..core.errors import ValidationError
from .models import (
    ACTION_SPECS,
    ActionSpec,
    FieldKind,
    FieldSpec,
    action_error_message,
    action_row_text,
    action_to_values,
    build_action,
    spec_for_action,
    spec_for_kind,
)

#: Spin-box value meaning "use the timing profile's action delay".
_USE_PROFILE = -1.0


class ActionDialog(QDialog):
    """Edits one action.

    Fields are generated from the action's :class:`FieldSpec` list, so adding a
    new action type to ``ui.models`` gives it an editor for free.
    """

    def __init__(
        self,
        kind: str | None = None,
        action: Action | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit action" if action is not None else "Add action")
        self._editors: dict[str, QWidget] = {}
        self._action: Action | None = None

        spec = spec_for_action(action) if action is not None else None
        self._kind = spec.kind if spec is not None else (kind or ACTION_SPECS[0].kind)

        layout = QVBoxLayout(self)

        self.kind_combo = QComboBox()
        self.kind_combo.setAccessibleName("Action type")
        for candidate in ACTION_SPECS:
            self.kind_combo.addItem(candidate.label, candidate.kind)
        self.kind_combo.setCurrentIndex(self.kind_combo.findData(self._kind))
        self.kind_combo.setEnabled(action is None)
        self.kind_combo.currentIndexChanged.connect(self._on_kind_changed)

        kind_row = QFormLayout()
        kind_row.addRow("Action", self.kind_combo)

        self.form_host = QWidget()
        self.form = QFormLayout(self.form_host)

        self.delay_spin = QDoubleSpinBox()
        self.delay_spin.setRange(_USE_PROFILE, 600_000)
        self.delay_spin.setDecimals(0)
        self.delay_spin.setSuffix(" ms")
        self.delay_spin.setSpecialValueText("(use timing profile)")
        self.delay_spin.setValue(_USE_PROFILE)
        self.delay_spin.setAccessibleName("Delay after this action")

        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)
        self.error_label.setAccessibleName("Action validation error")

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        layout.addLayout(kind_row)
        layout.addWidget(self.form_host)
        delay_form = QFormLayout()
        delay_form.addRow("Delay after", self.delay_spin)
        layout.addLayout(delay_form)
        layout.addWidget(self.error_label)
        layout.addWidget(self.buttons)

        self._rebuild_fields()
        if action is not None:
            self.set_values(action_to_values(action))
            if action.delay_after_ms is not None:
                self.delay_spin.setValue(float(action.delay_after_ms))

    # -- state -------------------------------------------------------------
    @property
    def kind(self) -> str:
        return str(self.kind_combo.currentData())

    @property
    def action(self) -> Action | None:
        """The action built by the last successful :meth:`try_build`."""
        return self._action

    def values(self) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for name, editor in self._editors.items():
            if isinstance(editor, QPlainTextEdit):
                values[name] = editor.toPlainText()
            elif isinstance(editor, QLineEdit):
                values[name] = editor.text()
            elif isinstance(editor, QCheckBox):
                values[name] = editor.isChecked()
            elif isinstance(editor, QComboBox):
                values[name] = editor.currentText()
            elif isinstance(editor, QSpinBox):
                values[name] = editor.value()
            elif isinstance(editor, QDoubleSpinBox):
                values[name] = None if editor.value() < 0 else editor.value()
        return values

    def set_values(self, values: dict[str, Any]) -> None:
        for name, value in values.items():
            editor = self._editors.get(name)
            if editor is None:
                continue
            if isinstance(editor, QPlainTextEdit):
                editor.setPlainText(str(value))
            elif isinstance(editor, QLineEdit):
                editor.setText(str(value))
            elif isinstance(editor, QCheckBox):
                editor.setChecked(bool(value))
            elif isinstance(editor, QComboBox):
                index = editor.findText(str(value))
                if index >= 0:
                    editor.setCurrentIndex(index)
            elif isinstance(editor, QSpinBox):
                editor.setValue(int(value or 0))
            elif isinstance(editor, QDoubleSpinBox):
                editor.setValue(_USE_PROFILE if value is None else float(value))

    @property
    def delay_after_ms(self) -> float | None:
        value = float(self.delay_spin.value())
        return None if value < 0 else value

    def try_build(self) -> Action | None:
        """Build the action, showing a readable error instead of raising."""
        try:
            action = build_action(self.kind, self.values(), self.delay_after_ms)
        except ValidationError as error:
            self._show_error(action_error_message(error))
            return None
        except (ValueError, TypeError) as error:
            self._show_error(str(error))
            return None
        self._show_error("")
        self._action = action
        return action

    def accept(self) -> None:
        """Only close when the action is valid."""
        if self.try_build() is not None:
            super().accept()

    # -- internals ---------------------------------------------------------
    def _on_kind_changed(self) -> None:
        self._rebuild_fields()

    def _rebuild_fields(self) -> None:
        while self.form.rowCount():
            self.form.removeRow(0)
        self._editors.clear()
        spec: ActionSpec = spec_for_kind(self.kind)
        for field in spec.fields:
            editor = self._make_editor(field)
            self._editors[field.name] = editor
            self.form.addRow(field.label, editor)
            if field.help_text:
                editor.setToolTip(field.help_text)
            editor.setAccessibleName(field.label)

    def _make_editor(self, field: FieldSpec) -> QWidget:
        if field.kind is FieldKind.MULTILINE:
            text_editor = QPlainTextEdit()
            text_editor.setPlainText(str(field.default or ""))
            text_editor.setMaximumHeight(90)
            return text_editor
        if field.kind is FieldKind.TEXT:
            return QLineEdit(str(field.default or ""))
        if field.kind is FieldKind.BOOL:
            check = QCheckBox()
            check.setChecked(bool(field.default))
            return check
        if field.kind is FieldKind.CHOICE:
            combo = QComboBox()
            combo.addItems(list(field.choices))
            combo.setCurrentIndex(max(0, combo.findText(str(field.default))))
            return combo
        if field.kind is FieldKind.INT:
            spin = QSpinBox()
            spin.setRange(int(field.minimum), int(field.maximum))
            spin.setValue(int(field.default or 0))
            return spin
        double = QDoubleSpinBox()
        optional = field.default is None
        double.setRange(_USE_PROFILE if optional else field.minimum, field.maximum)
        double.setDecimals(0)
        if optional:
            double.setSpecialValueText("(use timing profile)")
            double.setValue(_USE_PROFILE)
        else:
            double.setValue(float(field.default or 0))
        double.setSuffix(field.suffix)
        return double

    def _show_error(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.setVisible(bool(message))

    @property
    def error_text(self) -> str:
        return self.error_label.text()


class ActionEditor(QGroupBox):
    """Ordered list of actions with add/edit/delete/reorder.

    The list *is* the plan's action sequence; the widget holds domain actions
    and never a parallel representation that could drift.
    """

    actions_changed = Signal()

    def __init__(self) -> None:
        super().__init__("Actions")
        self._actions: list[Action] = []

        layout = QVBoxLayout(self)

        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setAccessibleName("Automation actions")
        self.list.itemDoubleClicked.connect(lambda _item: self.edit_selected())

        self.add_button = QPushButton("Add")
        self.edit_button = QPushButton("Edit")
        self.delete_button = QPushButton("Delete")
        self.up_button = QPushButton("Move up")
        self.down_button = QPushButton("Move down")

        self.add_button.clicked.connect(self.add_with_dialog)
        self.edit_button.clicked.connect(self.edit_selected)
        self.delete_button.clicked.connect(self.delete_selected)
        self.up_button.clicked.connect(lambda: self.move_selected(-1))
        self.down_button.clicked.connect(lambda: self.move_selected(1))

        buttons = QHBoxLayout()
        for button, name in (
            (self.add_button, "Add action"),
            (self.edit_button, "Edit selected action"),
            (self.delete_button, "Delete selected action"),
            (self.up_button, "Move action up"),
            (self.down_button, "Move action down"),
        ):
            button.setAccessibleName(name)
            buttons.addWidget(button)
        buttons.addStretch(1)

        layout.addWidget(self.list)
        layout.addLayout(buttons)

    # -- state -------------------------------------------------------------
    @property
    def plan_actions(self) -> tuple[Action, ...]:
        """The edited action sequence.

        Not called ``actions``: ``QWidget.actions()`` already exists and means
        something entirely different (the widget's ``QAction`` list).
        """
        return tuple(self._actions)

    def set_actions(self, actions: Sequence[Action]) -> None:
        self._actions = list(actions)
        self._refresh()

    @property
    def selected_index(self) -> int:
        return self.list.currentRow()

    def select(self, index: int) -> None:
        self.list.setCurrentRow(index)

    # -- editing operations (dialog-free, so they are directly testable) ----
    def add_action(self, action: Action) -> None:
        self._actions.append(action)
        self._refresh()
        self.select(len(self._actions) - 1)

    def replace_action(self, index: int, action: Action) -> None:
        if 0 <= index < len(self._actions):
            self._actions[index] = action
            self._refresh()
            self.select(index)

    def delete_selected(self) -> None:
        index = self.selected_index
        if 0 <= index < len(self._actions):
            del self._actions[index]
            self._refresh()
            self.select(min(index, len(self._actions) - 1))

    def move_selected(self, offset: int) -> None:
        index = self.selected_index
        target = index + offset
        if 0 <= index < len(self._actions) and 0 <= target < len(self._actions):
            self._actions[index], self._actions[target] = (
                self._actions[target],
                self._actions[index],
            )
            self._refresh()
            self.select(target)

    def set_locked(self, locked: bool) -> None:
        for widget in (
            self.list,
            self.add_button,
            self.edit_button,
            self.delete_button,
            self.up_button,
            self.down_button,
        ):
            widget.setEnabled(not locked)

    # -- dialog wrappers ---------------------------------------------------
    def add_with_dialog(self) -> None:
        dialog = ActionDialog(parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.action is not None:
            self.add_action(dialog.action)

    def edit_selected(self) -> None:
        index = self.selected_index
        if not 0 <= index < len(self._actions):
            return
        dialog = ActionDialog(action=self._actions[index], parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.action is not None:
            self.replace_action(index, dialog.action)

    # -- internals ---------------------------------------------------------
    def _refresh(self) -> None:
        self.list.clear()
        for index, action in enumerate(self._actions):
            self.list.addItem(action_row_text(index, action))
        self.actions_changed.emit()
