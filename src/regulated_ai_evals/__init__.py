"""regulated-ai-evals: an evidence-producing evaluation harness.

The one name most callers need is `verifies`, the marker that links a test to
the requirements it provides evidence for.
"""

from .pytest_plugin import verifies

__all__ = ["verifies"]
