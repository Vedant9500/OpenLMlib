"""
Tests for caveman ultra compression.

Tests cover:
- Ultra compression intensity levels
- Technical content preservation (code, URLs, paths)
- Context block compression
- Observation summary compression
- Integration with context builder and compressor
"""

import pytest
import sqlite3
from openlmlib.memory.caveman_compress import (
    caveman_compress,
    compress_context_block,
    compress_observation_summary,
    _is_technical_line,
    _count_tokens,
)


@pytest.fixture
def db_conn():
    """Create in-memory SQLite database for testing."""
    conn = sqlite3.connect(":memory:")
    yield conn
    conn.close()


# ==================== Basic Compression Tests ====================

class TestCavemanCompress:
    """Test basic caveman compression functionality."""

    def test_ultra_compression_basic(self):
        """Test ultra compression removes fluff words."""
        text = "The file contains a function that handles user authentication."
        compressed, stats = caveman_compress(text, intensity='ultra')
        
        assert len(compressed) < len(text)
        assert stats['reduction_percent'] > 0
        # Should remove articles
        assert " the " not in compressed.lower() or "the" not in compressed.lower().split()

    def test_full_compression_basic(self):
        """Test full compression removes articles and filler."""
        text = "The system will basically just validate the user credentials."
        compressed, stats = caveman_compress(text, intensity='full')
        
        assert len(compressed) < len(text)
        assert "basically" not in compressed.lower()
        assert "just" not in compressed.lower()

    def test_lite_compression_basic(self):
        """Test lite compression removes only filler words."""
        text = "The system will basically validate credentials."
        compressed, stats = caveman_compress(text, intensity='lite')
        
        assert len(compressed) < len(text)
        assert "basically" not in compressed.lower()

    def test_ultra_converts_to_fragments(self):
        """Test ultra compression converts sentences to fragments."""
        text = "The function reads the file and then processes the data."
        compressed, stats = caveman_compress(text, intensity='ultra')
        
        # Should have fragment structure
        assert '.' in compressed or len(compressed.split()) < len(text.split())

    def test_empty_text(self):
        """Test compression handles empty text."""
        compressed, stats = caveman_compress("")
        
        assert compressed == ""
        assert stats['original_tokens'] == 0

    def test_none_text(self):
        """Test compression handles None text."""
        compressed, stats = caveman_compress(None)
        
        assert compressed is None


# ==================== Technical Content Preservation ====================

class TestTechnicalPreservation:
    """Test that technical content is preserved unchanged."""

    def test_preserves_code_blocks(self):
        """Test code blocks are not compressed."""
        text = """
        Use this function:
        ```python
        def authenticate(user, password):
            if user and password:
                return True
        ```
        The function validates credentials.
        """
        compressed, stats = caveman_compress(text, intensity='ultra')
        
        assert "```python" in compressed
        assert "def authenticate(user, password):" in compressed
        assert "if user and password:" in compressed

    def test_preserves_urls(self):
        """Test URLs are not compressed."""
        text = "Visit https://example.com/docs for more information about the API."
        compressed, stats = caveman_compress(text, intensity='ultra')
        
        assert "https://example.com/docs" in compressed

    def test_preserves_file_paths(self):
        """Test file paths are not compressed."""
        text = "The configuration is in /etc/app/config/settings.json file."
        compressed, stats = caveman_compress(text, intensity='ultra')
        
        assert "/etc/app/config/settings.json" in compressed

    def test_preserves_commands(self):
        """Test shell commands are not compressed."""
        text = "Run the following command: $ npm install openlmlib"
        compressed, stats = caveman_compress(text, intensity='ultra')
        
        assert "$ npm install openlmlib" in compressed

    def test_preserves_headings(self):
        """Test markdown headings are not compressed."""
        text = "## Installation Guide\nThe package installs automatically."
        compressed, stats = caveman_compress(text, intensity='ultra')
        
        assert "## Installation Guide" in compressed

    def test_preserves_multiple_technical_elements(self):
        """Test multiple technical elements preserved."""
        text = """
        ## Setup
        Run: $ pip install openlmlib
        See https://docs.example.com
        Config: /etc/openlmlib/config.json
        ```python
        import openlmlib
        ```
        The installation completes automatically.
        """
        compressed, stats = caveman_compress(text, intensity='ultra')
        
        assert "## Setup" in compressed
        assert "$ pip install openlmlib" in compressed
        assert "https://docs.example.com" in compressed
        assert "/etc/openlmlib/config.json" in compressed
        assert "import openlmlib" in compressed


# ==================== Token Count Tests ====================

class TestTokenCounts:
    """Test token counting and statistics."""

    def test_token_count_basic(self):
        """Test token counting approximation."""
        text = "The quick brown fox jumps over the lazy dog."
        tokens = _count_tokens(text)
        
        assert tokens > 0
        # Should be approximately words * 1.3
        word_count = len(text.split())
        assert tokens >= word_count

    def test_compression_stats(self):
        """Test compression returns valid statistics."""
        text = "The function will basically just validate the credentials properly."
        compressed, stats = caveman_compress(text, intensity='ultra')
        
        assert 'original_tokens' in stats
        assert 'compressed_tokens' in stats
        assert 'reduction_percent' in stats
        assert stats['original_tokens'] > stats['compressed_tokens']
        assert stats['reduction_percent'] > 0

    def test_high_reduction_ratio(self):
        """Test ultra achieves high reduction on verbose text."""
        text = "The system will basically just automatically and essentially validate the user credentials in order to ensure that everything is working properly."
        compressed, stats = caveman_compress(text, intensity='ultra')
        
        # Should achieve at least 30% reduction (realistic for ultra)
        assert stats['reduction_percent'] >= 30


# ==================== Convenience Functions ====================

class TestConvenienceFunctions:
    """Test convenience wrapper functions."""

    def test_compress_context_block(self):
        """Test context block compression."""
        context = """
        <openlmlib-memory-context>
        # Retrieved Knowledge (5 items)
        
        ## 1. The function handles authentication
        **Type**: discovery
        **Summary**: The function validates user credentials properly.
        
        </openlmlib-memory-context>
        """
        compressed, stats = compress_context_block(context, intensity='ultra')
        
        assert isinstance(compressed, str)
        assert len(compressed) <= len(context)
        assert stats['reduction_percent'] >= 0

    def test_compress_observation_summary(self):
        """Test observation summary compression."""
        summary = {
            'title': 'The Function Handles Authentication',
            'narrative': 'The function will basically just validate the user credentials.',
            'facts': ['Fact 1', 'Fact 2'],
            'concepts': ['Authentication', 'Validation'],
        }
        
        compressed_summary, stats = compress_observation_summary(
            summary, intensity='ultra'
        )
        
        assert 'title' in compressed_summary
        assert 'narrative' in compressed_summary
        assert stats['reduction_percent'] >= 0


# ==================== Integration Tests ====================

class TestIntegration:
    """Test integration with memory system components."""

    def test_context_builder_with_caveman(self, db_conn):
        """Test context builder with caveman enabled."""
        from openlmlib.memory import MemoryStorage, ProgressiveRetriever
        from openlmlib.memory.context_builder import ContextBuilder
        
        storage = MemoryStorage(db_conn)
        retriever = ProgressiveRetriever(storage)
        builder = ContextBuilder(
            retriever,
            caveman_enabled=True,
            caveman_intensity='ultra'
        )
        
        # Add test data
        session_id = "test_session"
        storage.create_session(session_id, "user")
        storage.add_observation({
            "session_id": session_id,
            "tool_name": "Read",
            "tool_output": "Python code with functions",
        })
        
        # Build context (should be compressed)
        context = builder.build_session_start_context("new_session", limit=10)
        
        # Context should exist (compression applied)
        assert isinstance(context, str)

    def test_compressor_with_caveman(self):
        """Test compressor with caveman enabled."""
        from openlmlib.memory.compressor import MemoryCompressor
        
        compressor = MemoryCompressor(
            caveman_enabled=True,
            caveman_intensity='ultra'
        )
        
        observation = {
            "tool_name": "Read",
            "tool_output": "The file contains a function that handles user authentication and validates credentials.",
        }
        
        summary = compressor.compress(observation)
        
        assert summary.get('caveman_enabled') is True
        assert summary.get('narrative') is not None
        assert summary['token_count_compressed'] > 0

    def test_context_builder_without_caveman(self, db_conn):
        """Test context builder with caveman disabled."""
        from openlmlib.memory import MemoryStorage, ProgressiveRetriever
        from openlmlib.memory.context_builder import ContextBuilder
        
        storage = MemoryStorage(db_conn)
        retriever = ProgressiveRetriever(storage)
        builder = ContextBuilder(
            retriever,
            caveman_enabled=False
        )
        
        session_id = "test_session"
        storage.create_session(session_id, "user")
        storage.add_observation({
            "session_id": session_id,
            "tool_name": "Read",
            "tool_output": "Python code",
        })
        
        context = builder.build_session_start_context("new_session", limit=10)
        
        assert isinstance(context, str)


# ==================== Edge Cases ====================

class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_very_long_text(self):
        """Test compression handles very long text."""
        text = "The function does X. " * 100
        compressed, stats = caveman_compress(text, intensity='ultra')
        
        assert len(compressed) < len(text)
        assert stats['reduction_percent'] > 0

    def test_only_technical_content(self):
        """Test text with only technical content passes through."""
        text = """
        ```python
        def foo():
            pass
        ```
        """
        compressed, stats = caveman_compress(text, intensity='ultra')
        
        # Should be largely unchanged
        assert "def foo():" in compressed

    def test_mixed_prose_and_technical(self):
        """Test mixed content compresses prose, preserves technical."""
        text = """
        The function is basically a helper that validates input.
        
        ```python
        def validate(input):
            return len(input) > 0
        ```
        
        The implementation is straightforward.
        """
        compressed, stats = caveman_compress(text, intensity='ultra')
        
        # Prose should be compressed
        # Technical should be preserved
        assert "def validate(input):" in compressed

    def test_unicode_content(self):
        """Test compression handles unicode characters."""
        text = "The file contains naïve résumé with café names."
        compressed, stats = caveman_compress(text, intensity='ultra')
        
        assert isinstance(compressed, str)
        assert len(compressed) > 0

    def test_newlines_preserved(self):
        """Test compression preserves line structure."""
        text = "Line one.\nLine two.\nLine three."
        compressed, stats = caveman_compress(text, intensity='ultra')
        
        assert '\n' in compressed


# ==================== Intensity Level Comparisons ====================

class TestIntensityLevels:
    """Test different intensity levels produce expected results."""

    def test_ultra_vs_full(self):
        """Test ultra is more aggressive than full."""
        text = "The function will basically just validate the credentials."
        
        compressed_full, stats_full = caveman_compress(text, 'full')
        compressed_ultra, stats_ultra = caveman_compress(text, 'ultra')
        
        assert stats_ultra['compressed_tokens'] <= stats_full['compressed_tokens']

    def test_full_vs_lite(self):
        """Test full is more aggressive than lite."""
        text = "The function will basically just validate the credentials."
        
        compressed_lite, stats_lite = caveman_compress(text, 'lite')
        compressed_full, stats_full = caveman_compress(text, 'full')
        
        assert stats_full['compressed_tokens'] <= stats_lite['compressed_tokens']

    def test_intensity_ordering(self):
        """Test intensity ordering: ultra <= full <= lite."""
        text = "The system will basically just automatically validate credentials."
        
        _, stats_ultra = caveman_compress(text, 'ultra')
        _, stats_full = caveman_compress(text, 'full')
        _, stats_lite = caveman_compress(text, 'lite')
        
        assert stats_ultra['compressed_tokens'] <= stats_full['compressed_tokens']
        assert stats_full['compressed_tokens'] <= stats_lite['compressed_tokens']


# ==================== Technical Line Detection ====================

class TestTechnicalLineDetection:
    """Test technical line detection logic."""

    def test_code_block(self):
        assert _is_technical_line("```python") is True
        assert _is_technical_line("```") is True

    def test_command(self):
        assert _is_technical_line("$ npm install") is True
        assert _is_technical_line("> echo hello") is True

    def test_url(self):
        assert _is_technical_line("Visit https://example.com") is True

    def test_file_path(self):
        assert _is_technical_line("File: /etc/config.json") is True
        assert _is_technical_line("Path: C:\\Users\\config.ini") is True

    def test_heading(self):
        assert _is_technical_line("# Title") is True
        assert _is_technical_line("## Subtitle") is True

    def test_prose(self):
        assert _is_technical_line("The function validates input") is False
        assert _is_technical_line("This is normal text") is False
