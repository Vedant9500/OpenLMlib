"""
Privacy filtering for memory injection system.

Detects and filters sensitive content from observations before storage.
Supports <private> tags and pattern-based detection of secrets.
"""

from __future__ import annotations

import re
import logging
from typing import Set

logger = logging.getLogger(__name__)

# Patterns to detect private/sensitive content
PRIVATE_PATTERNS = [
    # API keys and tokens (generic)
    r'API_KEY\s*=\s*\S+',
    r'API_SECRET\s*=\s*\S+',
    r'SECRET_KEY\s*=\s*\S+',
    r'ACCESS_TOKEN\s*=\s*\S+',
    r'AUTH_TOKEN\s*=\s*\S+',
    r'TOKEN\s*=\s*\S+',
    r'PRIVATE_KEY\s*=\s*\S+',

    # Passwords
    r'PASSWORD\s*=\s*\S+',
    r'PASSWD\s*=\s*\S+',
    r'DB_PASSWORD\s*=\s*\S+',
    r'DATABASE_PASSWORD\s*=\s*\S+',
    r'MYSQL_ROOT_PASSWORD\s*=\s*\S+',

    # Live API keys (OpenAI, Anthropic, etc.)
    r'sk-live-[a-zA-Z0-9]+',
    r'sk-test-[a-zA-Z0-9]+',
    r'sk-proj-[a-zA-Z0-9]+',
    r'anthropic-[a-zA-Z0-9]+',
    r'openai-[a-zA-Z0-9]+',
    r'xai-[a-zA-Z0-9]+',

    # GitHub tokens
    r'ghp_[a-zA-Z0-9]{36}',
    r'gho_[a-zA-Z0-9]{36}',
    r'github_pat_[a-zA-Z0-9_]{22,}',

    # AWS keys
    r'AKIA[0-9A-Z]{16}',

    # JWT tokens
    r'eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}',

    # Slack tokens
    r'xox[bpsar]-[a-zA-Z0-9-]+',

    # Private keys
    r'-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----',
    r'-----BEGIN\s+EC\s+PRIVATE\s+KEY-----',
    r'-----BEGIN\s+DSA\s+PRIVATE\s+KEY-----',
    r'-----BEGIN\s+OPENSSH\s+PRIVATE\s+KEY-----',
    r'-----BEGIN\s+PGP\s+PRIVATE\s+KEY BLOCK-----',

    # Connection strings with credentials
    r'mongodb(\+srv)?://\S+:\S+@',
    r'postgres(ql)?://\S+:\S+@',
    r'mysql://\S+:\S+@',
    r'redis://:\S+@',
    r'amqp://\S+:\S+@',
    r'smtp://\S+:\S+@',

    # Bearer tokens
    r'[Bb]earer\s+[a-zA-Z0-9\-._~+/]+=*',

    # Email addresses (sometimes considered private)
    # r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',  # Uncomment if needed
]

# Compiled patterns for performance
_COMPILED_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in PRIVATE_PATTERNS
]


def contains_private(text: str) -> bool:
    """
    Check if text contains private/sensitive content.
    
    Args:
        text: Text to check
        
    Returns:
        True if private content detected
    """
    if not text:
        return False
    
    # Check for <private> tags
    if "<private>" in text and "</private>" in text:
        return True
    
    # Check for secret patterns
    for pattern in _COMPILED_PATTERNS:
        if pattern.search(text):
            return True
    
    return False


def filter_private(text: str) -> str:
    """
    Remove private content wrapped in <private> tags.
    
    Args:
        text: Text with potential <private> sections
        
    Returns:
        Text with private content replaced
    """
    if not text:
        return text
    
    # Remove content between <private> and </private>
    pattern = r'<private>.*?</private>'
    filtered = re.sub(
        pattern,
        '[PRIVATE CONTENT REMOVED]',
        text,
        flags=re.DOTALL
    )
    
    return filtered


def sanitize_for_storage(text: str) -> str:
    """
    Sanitize text before storage.
    Removes private content and patterns.
    
    Args:
        text: Text to sanitize
        
    Returns:
        Sanitized text safe for storage
    """
    if not text:
        return text
    
    # First, filter <private> tagged sections
    result = filter_private(text)
    
    # Then, check for patterns and redact
    for pattern in _COMPILED_PATTERNS:
        # Replace matches with [REDACTED]
        result = pattern.sub('[REDACTED]', result)
    
    return result


def extract_private_sections(text: str) -> list[str]:
    """
    Extract all private sections from text.
    Useful for logging/auditing what was filtered.
    
    Args:
        text: Text to extract private sections from
        
    Returns:
        List of private section contents
    """
    if not text:
        return []
    
    pattern = r'<private>(.*?)</private>'
    matches = re.findall(pattern, text, flags=re.DOTALL)
    
    return [match.strip() for match in matches]


class PrivacyFilter:
    """Stateful privacy filter with statistics."""
    
    def __init__(self):
        self.filtered_count = 0
        self.private_tags_found = 0
        self.patterns_matched = 0
    
    def filter_text(self, text: str) -> tuple[str, bool]:
        """
        Filter text and return (filtered_text, was_filtered).
        
        Args:
            text: Text to filter
            
        Returns:
            Tuple of (filtered text, whether filtering occurred)
        """
        if not text:
            return text, False
        
        was_filtered = contains_private(text)
        
        if was_filtered:
            self.filtered_count += 1
            
            # Track what was found
            if "<private>" in text:
                self.private_tags_found += 1
            
            for pattern in _COMPILED_PATTERNS:
                if pattern.search(text):
                    self.patterns_matched += 1
                    break  # Count once per text
            
            text = sanitize_for_storage(text)
        
        return text, was_filtered
    
    def stats(self) -> dict:
        """Get filter statistics."""
        return {
            "filtered_count": self.filtered_count,
            "private_tags_found": self.private_tags_found,
            "patterns_matched": self.patterns_matched,
        }
    
    def reset(self) -> None:
        """Reset statistics."""
        self.filtered_count = 0
        self.private_tags_found = 0
        self.patterns_matched = 0
