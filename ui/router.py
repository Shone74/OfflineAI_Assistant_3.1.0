"""Centralized navigation router for the main application window."""

from __future__ import annotations

from PySide6.QtWidgets import QStackedWidget, QWidget


class Router:
    """Maps route keys to widgets and handles navigation."""

    def __init__(self, stack: QStackedWidget) -> None:
        self._stack = stack
        self._routes: dict[str, QWidget] = {}
        self._history: list[str] = []
        self._current_route: str | None = None

    def register(self, key: str, widget: QWidget) -> None:
        self._routes[key] = widget
        if widget not in [self._stack.widget(i) for i in range(self._stack.count())]:
            self._stack.addWidget(widget)

    def navigate(self, key: str) -> None:
        if key not in self._routes:
            return
        if self._current_route is not None:
            self._history.append(self._current_route)
        self._stack.setCurrentWidget(self._routes[key])
        self._current_route = key

    def back(self) -> None:
        if self._history:
            previous = self._history.pop()
            self._stack.setCurrentWidget(self._routes[previous])
            self._current_route = previous

    @property
    def current_route(self) -> str | None:
        return self._current_route

    @property
    def routes(self) -> dict[str, QWidget]:
        return dict(self._routes)
