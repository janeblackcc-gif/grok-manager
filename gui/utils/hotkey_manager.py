from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass
class HotkeyResult:
    active: bool
    errors: list[str]


class HotkeyManager:

    def __init__(self) -> None:
        self._bindings: dict[str, str] = {}
        self._keyboard = None
        self._handles: list[object] = []

    @property
    def bindings(self) -> dict[str, str]:
        return dict(self._bindings)

    def register(
        self,
        bindings: dict[str, str],
        callbacks: dict[str, Callable[[], None]],
    ) -> HotkeyResult:
        combos = {name: (combo or "").strip().lower() for name, combo in bindings.items()}
        errors: list[str] = []
        seen: dict[str, str] = {}
        for action, combo in combos.items():
            if not combo:
                errors.append(f"{action} hotkey is empty")
                continue
            if combo in seen:
                errors.append(f"{action} conflicts with {seen[combo]}")
            else:
                seen[combo] = action
        if errors:
            return HotkeyResult(active=False, errors=errors)

        try:
            import keyboard

            self._keyboard = keyboard
            self._register_hotkeys(keyboard, combos, callbacks, suppress_floating=True)
            self._bindings = combos
            return HotkeyResult(active=True, errors=[])
        except ImportError:
            return HotkeyResult(active=False, errors=["keyboard library not installed"])
        except Exception as exc:
            if "blocking_hotkeys" in str(exc):
                try:
                    self._register_hotkeys(keyboard, combos, callbacks, suppress_floating=False)
                    self._bindings = combos
                    return HotkeyResult(active=True, errors=[])
                except Exception as retry_exc:
                    return HotkeyResult(active=False, errors=[str(retry_exc)])
            return HotkeyResult(active=False, errors=[str(exc)])

    def clear(self) -> None:
        if self._keyboard is None:
            try:
                import keyboard

                self._keyboard = keyboard
            except Exception:
                return
        self._clear_registered_hotkeys(self._keyboard)
        self._bindings = {}

    def _clear_registered_hotkeys(self, keyboard) -> None:
        while self._handles:
            handle = self._handles.pop()
            try:
                keyboard.remove_hotkey(handle)
            except Exception:
                pass

    def _register_hotkeys(self, keyboard, combos: dict[str, str], callbacks: dict[str, Callable[[], None]], *, suppress_floating: bool) -> None:
        self._clear_registered_hotkeys(keyboard)
        for action, combo in combos.items():
            handle = keyboard.add_hotkey(
                combo,
                callbacks[action],
                suppress=suppress_floating and action == "floating_search",
            )
            self._handles.append(handle)
