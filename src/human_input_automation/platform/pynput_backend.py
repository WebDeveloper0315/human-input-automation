from pynput import keyboard, mouse

class PynputBackend:
    def __init__(self) -> None:
        self.keyboard = keyboard.Controller()
        self.mouse = mouse.Controller()

    def activate_target(self, target_id: str) -> None:
        # Window activation belongs in a separate platform/window adapter.
        pass

    def type_text(self, text: str) -> None:
        self.keyboard.type(text)

    def press_key(self, key: str) -> None:
        self.keyboard.press(key)
        self.keyboard.release(key)

    def move_mouse(self, x: int, y: int, duration_ms: int) -> None:
        self.mouse.position = (x, y)

    def click(self, x: int, y: int) -> None:
        self.mouse.position = (x, y)
        self.mouse.click(mouse.Button.left)
