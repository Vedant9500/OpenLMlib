"""
Tests for caveman ultra compression.

Tests cover:
- Ultra compression intensity levels
- Technical content preservation (code, URLs, paths)
- Context block compression
- Observation summary compression
- Integration with context builder and compressor
"""

import unittest
import sqlite3
from openlmlib.memory.caveman_compress import (
    caveman_compress,
    compress_context_block,
    compress_observation_summary,
    _is_technical_line,
    _count_tokens,
)


# ==================== Basic Compression Tests ====================

class TestCavemanCompress(unittest.TestCase):
    """Test basic caveman compression functionality."""

    def test_ultra_compression_basic(self):
        """Test ultra compression removes fluff words."""
        text = "The file contains a function that handles user authentication."
        compressed, stats = caveman_compress(text, intensity='ultra')
        
        self.assertLess(len(compressed), len(text))
        self.assertGreater(stats['reduction_percent'], 0)
        # Should remove articles
        self.assertTrue(" the " not in compressed.lower() or "the" not in compressed.lower().split())

    def test_full_compression_basic(self):
        """Test full compression removes articles and filler."""
        text = "The system will basically just validate the user credentials."
        compressed, stats = caveman_compress(text, intensity='full')
        
        self.assertLess(len(compressed), len(text))
        self.assertNotIn("basically", compressed.lower())
        self.assertNotIn("just", compressed.lower())

    def test_lite_compression_basic(self):
        """Test lite compression removes only filler words."""
        text = "The system will basically validate credentials."
        compressed, stats = caveman_compress(text, intensity='lite')
        
        self.assertLess(len(compressed), len(text))
        self.assertNotIn("basically", compressed.lower())

    def test_ultra_converts_to_fragments(self):
        """Test ultra compression converts sentences to fragments."""
        text = "The function reads the file and then processes the data."
        compressed, stats = caveman_compress(text, intensity='ultra')
        
        # Should have fragment structure
        self.assertTrue('.' in compressed or len(compressed.split()) < len(text.split()))

    def test_empty_text(self):
        """Test compression handles empty text."""
        compressed, stats = caveman_compress("")
        
        self.assertEqual(compressed, "")
        self.assertEqual(stats['original_tokens'], 0)

    def test_none_text(self):
        """Test compression handles None text."""
        compressed, stats = caveman_compress(None)
        
        self.assertIsNone(compressed)


# ==================== Technical Content Preservation ====================

class TestTechnicalPreservation(unittest.TestCase):
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
        
        self.assertIn("```python", compressed)
        self.assertIn("def authenticate(user, password):", compressed)
        self.assertIn("if user and password:", compressed)

    def test_preserves_urls(self):
        """Test URLs are not compressed."""
        text = "Visit https://example.com/docs for more information about the API."
        compressed, stats = caveman_compress(text, intensity='ultra')
        
        self.assertIn("https://example.com/docs", compressed)

    def test_preserves_file_paths(self):
        """Test file paths are not compressed."""
        text = "The configuration is in /etc/app/config/settings.json file."
        compressed, stats = caveman_compress(text, intensity='ultra')
        
        self.assertIn("/etc/app/config/settings.json", compressed)

    def test_preserves_commands(self):
        """Test shell commands are not compressed."""
        text = "Run the following command: $ npm install openlmlib"
        compressed, stats = caveman_compress(text, intensity='ultra')
        
        self.assertIn("$ npm install openlmlib", compressed)

    def test_preserves_headings(self):
        """Test markdown headings are not compressed."""
        text = "## Installation Guide\nThe package installs automatically."
        compressed, stats = caveman_compress(text, intensity='ultra')
        
        self.assertIn("## Installation Guide", compressed)

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
        
        self.assertIn("## Setup", compressed)
        self.assertIn("$ pip install openlmlib", compressed)
        self.assertIn("https://docs.example.com", compressed)
        self.assertIn("/etc/openlmlib/config.json", compressed)
        self.assertIn("import openlmlib", compressed)


# ==================== Token Count Tests ====================

class TestTokenCounts(unittest.TestCase):
    """Test token counting and statistics."""

    def test_token_count_basic(self):
        """Test token counting approximation."""
        text = "The quick brown fox jumps over the lazy dog."
        tokens = _count_tokens(text)
        
        self.assertGreater(tokens, 0)
        # Should be approximately words * 1.3
        word_count = len(text.split())
        self.assertGreaterEqual(tokens, word_count)

    def test_compression_stats(self):
        """Test compression returns valid statistics."""
        text = "The function will basically just validate the credentials properly."
        compressed, stats = caveman_compress(text, intensity='ultra')
        
        self.assertIn('original_tokens', stats)
        self.assertIn('compressed_tokens', stats)
        self.assertIn('reduction_percent', stats)
        self.assertGreater(stats['original_tokens'], stats['compressed_tokens'])
        self.assertGreater(stats['reduction_percent'], 0)

    def test_high_reduction_ratio(self):
        """Test ultra achieves high reduction on verbose text."""
        text = "The system will basically just automatically and essentially validate the user credentials in order to ensure that everything is working properly."
        compressed, stats = caveman_compress(text, intensity='ultra')
        
        # Should achieve at least 30% reduction (realistic for ultra)
        self.assertGreaterEqual(stats['reduction_percent'], 30)


# ==================== Convenience Functions ====================

class TestConvenienceFunctions(unittest.TestCase):
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
        
        self.assertIsInstance(compressed, str)
        self.assertLessEqual(len(compressed), len(context))
        self.assertGreaterEqual(stats['reduction_percent'], 0)

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
        
        self.assertIn('title', compressed_summary)
        self.assertIn('narrative', compressed_summary)
        self.assertGreaterEqual(stats['reduction_percent'], 0)


# ==================== Integration Tests ====================

class TestIntegration(unittest.TestCase):
    """Test integration with memory system components."""

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")

    def tearDown(self):
        self.conn.close()

    def test_context_builder_with_caveman(self):
        """Test context builder with caveman enabled."""
        from openlmlib.memory import MemoryStorage, ProgressiveRetriever
        from openlmlib.memory.context_builder import ContextBuilder
        
        storage = MemoryStorage(self.conn)
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
        self.assertIsInstance(context, str)

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
        
        self.assertTrue(summary.get('caveman_enabled'))
        self.assertIsNotNone(summary.get('narrative'))
        self.assertGreater(summary['token_count_compressed'], 0)

    def test_context_builder_without_caveman(self):
        """Test context builder with caveman disabled."""
        from openlmlib.memory import MemoryStorage, ProgressiveRetriever
        from openlmlib.memory.context_builder import ContextBuilder
        
        storage = MemoryStorage(self.conn)
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
        
        self.assertIsInstance(context, str)


# ==================== Edge Cases ====================

class TestEdgeCases(unittest.TestCase):
    """Test edge cases and boundary conditions."""

    def test_very_long_text(self):
        """Test compression handles very long text."""
        text = "The function does X. " * 100
        compressed, stats = caveman_compress(text, intensity='ultra')
        
        self.assertLess(len(compressed), len(text))
        self.assertGreater(stats['reduction_percent'], 0)

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
        self.assertIn("def foo():", compressed)

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
        self.assertIn("def validate(input):", compressed)

    def test_unicode_content(self):
        """Test compression handles unicode characters."""
        text = "The file contains naïve résumé with café names."
        compressed, stats = caveman_compress(text, intensity='ultra')
        
        self.assertIsInstance(compressed, str)
        self.assertGreater(len(compressed), 0)

    def test_newlines_preserved(self):
        """Test compression preserves line structure."""
        text = "Line one.\nLine two.\nLine three."
        compressed, stats = caveman_compress(text, intensity='ultra')
        
        self.assertIn('\n', compressed)


# ==================== Intensity Level Comparisons ====================

class TestIntensityLevels(unittest.TestCase):
    """Test different intensity levels produce expected results."""

    def test_ultra_vs_full(self):
        """Test ultra is more aggressive than full."""
        text = "The function will basically just validate the credentials."
        
        compressed_full, stats_full = caveman_compress(text, 'full')
        compressed_ultra, stats_ultra = caveman_compress(text, 'ultra')
        
        self.assertLessEqual(stats_ultra['compressed_tokens'], stats_full['compressed_tokens'])

    def test_full_vs_lite(self):
        """Test full is more aggressive than lite."""
        text = "The function will basically just validate the credentials."
        
        compressed_lite, stats_lite = caveman_compress(text, 'lite')
        compressed_full, stats_full = caveman_compress(text, 'full')
        
        self.assertLessEqual(stats_full['compressed_tokens'], stats_lite['compressed_tokens'])

    def test_intensity_ordering(self):
        """Test intensity ordering: ultra <= full <= lite."""
        text = "The system will basically just automatically validate credentials."
        
        _, stats_ultra = caveman_compress(text, 'ultra')
        _, stats_full = caveman_compress(text, 'full')
        _, stats_lite = caveman_compress(text, 'lite')
        
        self.assertLessEqual(stats_ultra['compressed_tokens'], stats_full['compressed_tokens'])
        self.assertLessEqual(stats_full['compressed_tokens'], stats_lite['compressed_tokens'])


# ==================== Technical Line Detection ====================

class TestTechnicalLineDetection(unittest.TestCase):
    """Test technical line detection logic."""

    def test_code_block(self):
        self.assertTrue(_is_technical_line("```python"))
        self.assertTrue(_is_technical_line("```"))

    def test_command(self):
        self.assertTrue(_is_technical_line("$ npm install"))
        self.assertTrue(_is_technical_line("> echo hello"))

    def test_url(self):
        self.assertTrue(_is_technical_line("Visit https://example.com"))

    def test_file_path(self):
        self.assertTrue(_is_technical_line("File: /etc/config.json"))
        self.assertTrue(_is_technical_line("Path: C:\\Users\\config.ini"))

    def test_heading(self):
        self.assertTrue(_is_technical_line("# Title"))
        self.assertTrue(_is_technical_line("## Subtitle"))

    def test_prose(self):
        self.assertFalse(_is_technical_line("The function validates input"))
        self.assertFalse(_is_technical_line("This is normal text"))


if __name__ == "__main__":
    unittest.main()
