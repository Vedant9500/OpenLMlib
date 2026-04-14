"""
Memory compression for observation summarization.

Compresses raw tool outputs into semantic summaries with:
- Title, subtitle, narrative
- Key facts and concepts
- Observation type classification
- Token count tracking

Uses extractive summarization based on existing summary_gen module.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class MemoryCompressor:
    """Compresses observations into semantic summaries."""

    def __init__(
        self,
        max_narrative_length: int = 300,
        max_facts: int = 5,
        max_concepts: int = 10,
        caveman_enabled: bool = True,
        caveman_intensity: str = 'ultra',
    ):
        """
        Initialize compressor.

        Args:
            max_narrative_length: Max chars for narrative
            max_facts: Max facts to extract
            max_concepts: Max concepts to extract
            caveman_enabled: Enable ultra linguistic compression
            caveman_intensity: Compression level
        """
        self.max_narrative_length = max_narrative_length
        self.max_facts = max_facts
        self.max_concepts = max_concepts
        self.caveman_enabled = caveman_enabled
        self.caveman_intensity = caveman_intensity

    def compress(self, observation: Dict[str, Any]) -> Dict[str, Any]:
        """
        Compress raw observation into semantic summary.

        Extracts: title, subtitle, narrative, facts, concepts, type

        Args:
            observation: Observation dict with tool_name, tool_output, etc.

        Returns:
            Compressed summary dict

        Raises:
            ValueError: If observation is not a dict
        """
        if not isinstance(observation, dict):
            raise ValueError(
                f"Expected dict observation, got {type(observation).__name__}"
            )

        tool_output = observation.get("tool_output", "")
        tool_name = observation.get("tool_name", "unknown")

        summary = {
            "title": self._extract_title(tool_name, tool_output),
            "subtitle": self._extract_subtitle(tool_output),
            "narrative": self._extract_narrative(tool_output),
            "facts": self._extract_facts(tool_output),
            "concepts": self._extract_concepts(tool_output),
            "type": self._classify_observation(tool_name, tool_output),
            "token_count_original": self._count_tokens(tool_output),
            "token_count_compressed": 0,
        }

        # Count compressed tokens
        compressed_text = " ".join([
            summary["title"],
            summary["subtitle"],
            summary["narrative"],
            " ".join(summary["facts"]),
        ])
        summary["token_count_compressed"] = self._count_tokens(compressed_text)

        # Apply caveman compression to narrative and title
        if self.caveman_enabled:
            from .caveman_compress import caveman_compress
            
            if summary.get("narrative"):
                summary["narrative"], caveman_stats = caveman_compress(
                    summary["narrative"],
                    intensity=self.caveman_intensity
                )
                summary["token_count_compressed"] = caveman_stats.get(
                    "compressed_tokens", summary["token_count_compressed"]
                )
            
            if summary.get("title"):
                compressed_title, _ = caveman_compress(
                    summary["title"],
                    intensity=self.caveman_intensity
                )
                summary["title"] = compressed_title

            summary["caveman_enabled"] = True
            summary["caveman_intensity"] = self.caveman_intensity

        # Log compression ratio
        original = summary["token_count_original"]
        compressed = summary["token_count_compressed"]
        if original > 0:
            ratio = original / max(compressed, 1)
            logger.debug(
                f"Compressed observation: {original} → {compressed} tokens "
                f"({ratio:.1f}x reduction)"
            )

        return summary

    def _extract_title(self, tool_name: str, output: str) -> str:
        """
        Extract concise title from observation.

        Uses first meaningful line or output summary.
        """
        if not output:
            return f"{tool_name} execution"

        # Try to get first non-empty line
        lines = output.strip().split("\n")
        for line in lines:
            line = line.strip()
            if line and len(line) > 10:
                # Truncate to reasonable length
                return line[:120]

        return f"{tool_name} output"

    def _extract_subtitle(self, output: str) -> str:
        """
        Extract key outcome or status.

        Looks for success/failure indicators.
        """
        if not output:
            return ""

        output_lower = output.lower()

        # Check for error patterns
        if any(pattern in output_lower for pattern in [
            "error", "failed", "exception", "traceback"
        ]):
            return "Execution failed or encountered error"

        # Check for success patterns
        if any(pattern in output_lower for pattern in [
            "success", "completed", "done", "finished"
        ]):
            return "Executed successfully"

        # Check for file operations
        if "read" in output_lower and "file" in output_lower:
            return "File content retrieved"

        if "edit" in output_lower or "modified" in output_lower:
            return "File modified"

        return ""

    def _extract_narrative(self, output: str) -> str:
        """
        Extract narrative description.

        Truncates to reasonable length while preserving context.
        """
        if not output:
            return ""

        # Clean up whitespace
        narrative = re.sub(r'\s+', ' ', output).strip()

        # Truncate to max length
        if len(narrative) > self.max_narrative_length:
            # Try to break at sentence boundary
            truncated = narrative[:self.max_narrative_length]
            last_period = truncated.rfind('.')
            if last_period > self.max_narrative_length * 0.7:
                truncated = truncated[:last_period + 1]
            else:
                truncated = truncated.rstrip() + "..."

            narrative = truncated

        return narrative

    def _extract_facts(self, output: str) -> List[str]:
        """
        Extract key factual statements.

        Looks for bullet points, numbered lists, or key statements.
        """
        if not output:
            return []

        facts = []

        # Extract bullet points
        for line in output.split("\n"):
            line = line.strip()

            # Check for bullet markers
            if line.startswith(("-", "*", "•", "+")):
                fact = line[1:].strip()
                if fact and len(fact) > 10:
                    facts.append(fact)

            # Check for numbered lists
            elif re.match(r'^\d+[\.\)]\s+', line):
                fact = re.sub(r'^\d+[\.\)]\s+', '', line)
                if fact and len(fact) > 10:
                    facts.append(fact)

        # If no bullets found, try to extract key sentences
        if not facts:
            sentences = re.split(r'[.!?]+', output)
            for sentence in sentences:
                sentence = sentence.strip()
                if len(sentence) > 20 and len(sentence) < 200:
                    facts.append(sentence)
                    if len(facts) >= self.max_facts:
                        break

        return facts[:self.max_facts]

    def _extract_concepts(self, output: str) -> List[str]:
        """
        Extract key concepts and technical terms.

        Uses simple heuristic: capitalized phrases and technical terms.
        """
        if not output:
            return []

        concepts = set()

        # Extract capitalized phrases (potential technical terms)
        matches = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', output)
        concepts.update(matches)

        # Extract technical terms (alphanumeric with hyphens/underscores)
        tech_terms = re.findall(r'\b[a-z]+[-_][a-z]+\b', output.lower())
        concepts.update(term.replace('_', '-').replace('-', ' ').title() for term in tech_terms)

        # Filter out common non-concept words
        stop_words = {
            "The", "This", "That", "These", "Those",
            "A", "An", "And", "Or", "But", "In", "On", "At",
            "Is", "Are", "Was", "Were", "Be", "Been",
            "Have", "Has", "Had", "Do", "Does", "Did",
            "Will", "Would", "Could", "Should", "May", "Might",
            "File", "Path", "Line", "Code", "Text",
        }

        concepts = [c for c in concepts if c not in stop_words]

        return list(concepts)[:self.max_concepts]

    def _classify_observation(self, tool_name: str, output: str) -> str:
        """
        Classify observation type.

        Categories: discovery, change, experiment, bugfix, decision, general
        """
        tool_name_lower = tool_name.lower()
        output_lower = output.lower()

        # File read operations
        if tool_name_lower in ["read", "read_file", "cat"]:
            return "discovery"

        # File write/edit operations
        if tool_name_lower in ["edit", "write", "write_file", "save"]:
            return "change"

        # Command execution
        if tool_name_lower in [
            "run_shell_command", "bash", "shell", "execute"
        ]:
            if "test" in output_lower or "pytest" in output_lower:
                return "experiment"
            if "error" in output_lower or "failed" in output_lower:
                return "bugfix"
            return "experiment"

        # Search operations
        if tool_name_lower in ["grep", "search", "find"]:
            return "discovery"

        # Decision indicators
        if any(word in output_lower for word in [
            "decided", "chose", "selected", "opted", "determined"
        ]):
            return "decision"

        # Error/bug fix
        if "error" in output_lower or "bug" in output_lower:
            return "bugfix"

        return "general"

    def _count_tokens(self, text: str) -> int:
        """
        Rough token count approximation.

        Uses word count * 1.3 as heuristic.
        """
        if not text:
            return 0

        # Simple heuristic: words * 1.3
        word_count = len(text.split())
        return int(word_count * 1.3)
