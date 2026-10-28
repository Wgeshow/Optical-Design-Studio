"""Bounded undo history for raw geometry drafts, without parsing physics values."""
from contextlib import contextmanager
from copy import deepcopy


class GeometryHistory:
    def __init__(self, snapshot, restore, changed=lambda: None, limit=100):
        self.snapshot, self.restore, self.changed = snapshot, restore, changed
        self.limit = limit
        self._busy = 0
        self.reset()

    def reset(self):
        self._states = [deepcopy(self.snapshot())]
        self._cursor = 0
        self.changed()

    @property
    def can_undo(self):
        return self._cursor > 0

    @property
    def can_redo(self):
        return self._cursor + 1 < len(self._states)

    def record(self):
        if self._busy:
            return
        state = self.snapshot()
        if state == self._states[self._cursor]:
            return
        self._states = self._states[:self._cursor + 1]
        self._states.append(deepcopy(state))
        self._states = self._states[-self.limit:]
        self._cursor = len(self._states) - 1
        self.changed()

    @contextmanager
    def transaction(self):
        self._busy += 1
        try:
            yield
        finally:
            self._busy -= 1
            self.record()

    def _select(self, cursor):
        if not 0 <= cursor < len(self._states):
            return False
        self._busy += 1
        try:
            self.restore(deepcopy(self._states[cursor]))
            self._cursor = cursor
        finally:
            self._busy -= 1
        self.changed()
        return True

    def undo(self):
        return self._select(self._cursor - 1)

    def redo(self):
        return self._select(self._cursor + 1)
