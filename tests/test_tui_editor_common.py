from __future__ import annotations

from autish.commands._tui_editor_common import word_left, word_right


def test_word_left_moves_to_previous_word_start() -> None:
    assert word_left("saluton mondo", len("saluton mondo")) == len("saluton ")


def test_word_left_skips_trailing_spaces() -> None:
    assert word_left("saluton mondo   ", len("saluton mondo   ")) == len("saluton ")


def test_word_right_moves_to_next_word_start() -> None:
    assert word_right("saluton mondo", 0) == len("saluton ")
