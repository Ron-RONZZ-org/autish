"""Tests for rubo recycle bin command."""

import pytest
from pathlib import Path
from tempfile import TemporaryDirectory
from typer.testing import CliRunner
from autish.commands.rubo import app
from autish.services.recycle_bin import RecycleBinDB, TrashItem

runner = CliRunner()


@pytest.fixture
def temp_trash():
    """Create a temporary trash directory for testing."""
    with TemporaryDirectory() as tmpdir:
        # Override trash directory
        original_get_trash_dir = RecycleBinDB._get_trash_dir
        RecycleBinDB._get_trash_dir = staticmethod(lambda: Path(tmpdir))
        yield Path(tmpdir)
        RecycleBinDB._get_trash_dir = original_get_trash_dir


@pytest.fixture
def temp_files():
    """Create temporary test files."""
    with TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        (base / "file1.txt").write_text("test content 1")
        (base / "file2.txt").write_text("test content 2")
        (base / "file3.pdf").write_text("test pdf content")
        (base / "subdir").mkdir()
        (base / "subdir" / "file4.txt").write_text("nested file")
        yield base


class TestRecycleBinDB:
    """Tests for RecycleBinDB service."""

    def test_init_creates_database(self, temp_trash):
        """Test that database is created on init."""
        db = RecycleBinDB()
        assert db.db_path.exists()

    def test_add_and_get_item(self, temp_trash, temp_files):
        """Test adding and retrieving trash items."""
        db = RecycleBinDB()
        file_path = str(temp_files / "file1.txt")
        
        uid = db.move_to_trash(file_path)
        assert uid is not None
        
        item = db.get_item(uid)
        assert item is not None
        assert item.uid == uid
        assert "file1.txt" in item.original_path

    def test_move_to_trash(self, temp_trash, temp_files):
        """Test moving files to trash."""
        db = RecycleBinDB()
        file_path = temp_files / "file1.txt"
        
        assert file_path.exists()
        uid = db.move_to_trash(str(file_path))
        assert uid is not None
        assert not file_path.exists()

    def test_list_items(self, temp_trash, temp_files):
        """Test listing trash items."""
        db = RecycleBinDB()
        
        # Add multiple files
        uid1 = db.move_to_trash(str(temp_files / "file1.txt"))
        uid2 = db.move_to_trash(str(temp_files / "file2.txt"))
        
        items = db.list_items()
        assert len(items) >= 2
        assert any(item.uid == uid1 for item in items)
        assert any(item.uid == uid2 for item in items)

    def test_search_items_wildcard(self, temp_trash, temp_files):
        """Test searching trash with wildcards."""
        db = RecycleBinDB()
        
        db.move_to_trash(str(temp_files / "file1.txt"))
        db.move_to_trash(str(temp_files / "file2.txt"))
        db.move_to_trash(str(temp_files / "file3.pdf"))
        
        # Search for txt files
        results = db.search_items("*.txt", use_regex=False)
        assert len(results) >= 2
        assert all("file" in item.original_path for item in results)

    def test_search_items_regex(self, temp_trash, temp_files):
        """Test searching trash with regex."""
        db = RecycleBinDB()
        
        db.move_to_trash(str(temp_files / "file1.txt"))
        db.move_to_trash(str(temp_files / "file3.pdf"))
        
        # Search for files ending in .txt
        results = db.search_items(r"\.txt$", use_regex=True)
        assert len(results) >= 1
        assert any(".txt" in item.original_path for item in results)

    def test_restore_item(self, temp_trash, temp_files):
        """Test restoring files from trash."""
        db = RecycleBinDB()
        file_path = temp_files / "file1.txt"
        original_content = file_path.read_text()
        
        uid = db.move_to_trash(str(file_path))
        assert not file_path.exists()
        
        success = db.restore_item(uid)
        assert success
        assert file_path.exists()
        assert file_path.read_text() == original_content

    def test_delete_item_permanent(self, temp_trash, temp_files):
        """Test permanently deleting trash items."""
        db = RecycleBinDB()
        
        uid = db.move_to_trash(str(temp_files / "file1.txt"))
        assert db.get_item(uid) is not None
        
        success = db.delete_item(uid)
        assert success
        assert db.get_item(uid) is None

    def test_uid_never_recycled(self, temp_trash, temp_files):
        """Test that UIDs increase monotonically within a session."""
        db = RecycleBinDB()
        
        uid1 = db.move_to_trash(str(temp_files / "file1.txt"))
        uid2 = db.move_to_trash(str(temp_files / "file2.txt"))
        uid3 = db.move_to_trash(str(temp_files / "file3.pdf"))
        
        # UIDs should increase
        assert int(uid1) < int(uid2) < int(uid3)


class TestRuboCommands:
    """Tests for rubo CLI commands."""

    def test_forigi_command(self, temp_trash, temp_files):
        """Test rubo forigi command."""
        file_path = str(temp_files / "file1.txt")
        result = runner.invoke(app, ["forigi", file_path])
        
        assert result.exit_code == 0
        assert "[✓]" in result.stdout
        assert not Path(file_path).exists()

    def test_forigi_nonexistent_file(self, temp_trash):
        """Test forigi with non-existent file."""
        result = runner.invoke(app, ["forigi", "/nonexistent/file.txt"])
        
        # Should complete but show error message
        assert "Ne trovita" in result.output or "[!]" in result.output

    def test_rm_alias(self, temp_trash, temp_files):
        """Test rm alias for forigi."""
        file_path = str(temp_files / "file1.txt")
        result = runner.invoke(app, ["rm", file_path])
        
        assert result.exit_code == 0
        assert "[✓]" in result.stdout

    def test_ls_command(self, temp_trash, temp_files):
        """Test rubo ls command."""
        db = RecycleBinDB()
        db.move_to_trash(str(temp_files / "file1.txt"))
        db.move_to_trash(str(temp_files / "file2.txt"))
        
        result = runner.invoke(app, ["ls"])
        
        assert result.exit_code == 0
        assert "UID" in result.stdout or "file" in result.stdout

    def test_ls_empty(self, temp_trash):
        """Test ls with empty trash."""
        result = runner.invoke(app, ["ls"])
        
        assert result.exit_code == 0
        assert "malplena" in result.stdout or "empty" in result.stdout.lower()

    def test_serci_command(self, temp_trash, temp_files):
        """Test rubo serci command."""
        db = RecycleBinDB()
        db.move_to_trash(str(temp_files / "file1.txt"))
        db.move_to_trash(str(temp_files / "file2.txt"))
        db.move_to_trash(str(temp_files / "file3.pdf"))
        
        result = runner.invoke(app, ["serci", "*.txt"])
        
        assert result.exit_code == 0
        assert "rezultoj" in result.stdout or "results" in result.stdout.lower()

    def test_serci_regex(self, temp_trash, temp_files):
        """Test serci with regex."""
        db = RecycleBinDB()
        db.move_to_trash(str(temp_files / "file1.txt"))
        db.move_to_trash(str(temp_files / "file3.pdf"))
        
        result = runner.invoke(app, ["serci", r"\.txt$", "-R"])
        
        assert result.exit_code == 0

    def test_restarigi_command(self, temp_trash, temp_files):
        """Test rubo restarigi command."""
        db = RecycleBinDB()
        file_path = temp_files / "file1.txt"
        
        uid = db.move_to_trash(str(file_path))
        assert not file_path.exists()
        
        result = runner.invoke(app, ["restarigi", uid])
        
        assert result.exit_code == 0
        assert "[✓]" in result.stdout
        assert file_path.exists()

    def test_rs_alias(self, temp_trash, temp_files):
        """Test rs alias for restarigi."""
        db = RecycleBinDB()
        file_path = temp_files / "file1.txt"
        
        uid = db.move_to_trash(str(file_path))
        
        result = runner.invoke(app, ["rs", uid])
        
        assert result.exit_code == 0
        assert file_path.exists()

    def test_forigi_cxape_command(self, temp_trash, temp_files):
        """Test rubo forigi-cxape permanent delete command."""
        db = RecycleBinDB()
        
        uid = db.move_to_trash(str(temp_files / "file1.txt"))
        
        result = runner.invoke(app, ["forigi-cxape", uid])
        
        assert result.exit_code == 0
        assert "[✓]" in result.stdout
        assert db.get_item(uid) is None
