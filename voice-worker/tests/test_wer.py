from __future__ import annotations

from aurevia_voice.wer import word_error_rate


def test_word_error_rate() -> None:
    assert word_error_rate("We have forty staff.", "we have 40 staff") == 0.0
    assert word_error_rate("call me back next week", "call me next week") == 0.2  # 1 deletion
    assert word_error_rate("a b c d", "a x c d e") == 0.5  # 1 substitution + 1 insertion
    assert word_error_rate("", "") == 0.0
