"""The main window's primary button derives its action from account state
plus whether a valid game directory is configured (see CLAUDE.md UX notes)."""

from tclauncher.ui.main_window import primary_action


def test_signed_out_logs_in_regardless_of_game_dir():
    assert primary_action("signed_out", game_dir_ok=False) == "login"
    assert primary_action("signed_out", game_dir_ok=True) == "login"


def test_expired_session_logs_in_regardless_of_game_dir():
    assert primary_action("expired", game_dir_ok=False) == "login"
    assert primary_action("expired", game_dir_ok=True) == "login"


def test_signed_in_without_game_dir_locates_game_files():
    assert primary_action("signed_in", game_dir_ok=False) == "locate"


def test_signed_in_with_game_dir_plays():
    assert primary_action("signed_in", game_dir_ok=True) == "play"
