"""Simple FRIDAY window. Start with friday_gui.bat or: python start_friday.py --gui"""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import scrolledtext

import friday


class FridayApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title(f"FRIDAY v{friday.VERSION}")
        self.root.geometry("640x520")
        self.busy = False

        self.log = scrolledtext.ScrolledText(self.root, wrap=tk.WORD, state=tk.DISABLED)
        self.log.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

        row = tk.Frame(self.root)
        row.pack(fill=tk.X, padx=10, pady=(0, 8))
        self.entry = tk.Entry(row)
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.entry.bind("<Return>", self.on_send)
        tk.Button(row, text="Send", command=self.on_send).pack(side=tk.RIGHT, padx=(8, 0))
        tk.Button(self.root, text="Speak", command=self.on_voice).pack(pady=(0, 10))

        self._append("FRIDAY", f"v{friday.VERSION} ready. Type or click Speak.")
        self.entry.focus_set()

    def _append(self, who: str, text: str) -> None:
        self.log.configure(state=tk.NORMAL)
        self.log.insert(tk.END, f"{who}: {text}\n\n")
        self.log.see(tk.END)
        self.log.configure(state=tk.DISABLED)

    def on_send(self, event=None) -> None:
        msg = self.entry.get().strip()
        self.entry.delete(0, tk.END)
        if not msg or self.busy:
            return
        self._run_user(msg)

    def on_voice(self) -> None:
        if self.busy:
            return
        self.busy = True
        self._append("FRIDAY", "Listening...")

        def work() -> None:
            try:
                said = friday.listen()
            except Exception as e:
                self.root.after(0, lambda: self._done_voice("", f"Voice failed: {e}"))
                return
            self.root.after(0, lambda: self._done_voice(said, ""))

        threading.Thread(target=work, daemon=True).start()

    def _done_voice(self, said: str, err: str) -> None:
        self.busy = False
        if err:
            self._append("FRIDAY", err)
            return
        if not said:
            self._append("FRIDAY", "I didn't catch that.")
            return
        self._run_user(said)

    def _run_user(self, msg: str) -> None:
        self.busy = True
        self._append("You", msg)

        def work() -> None:
            try:
                reply = friday.chat_with_friday(msg)
            except Exception as e:
                reply = f"Error: {e}"
            self.root.after(0, lambda: self._done_chat(reply))

        threading.Thread(target=work, daemon=True).start()

    def _done_chat(self, reply: str) -> None:
        self.busy = False
        self._append("FRIDAY", reply)
        threading.Thread(target=lambda: friday.speak(reply), daemon=True).start()

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    FridayApp().run()


if __name__ == "__main__":
    main()