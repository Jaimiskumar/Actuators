"""Root-level re-export for ai.py matching PROJECT_BRIEF module specification."""

from logdetective.ai import build_compact_prompt, generate_ai_summary, synthesize_heuristic_summary

__all__ = ["build_compact_prompt", "generate_ai_summary", "synthesize_heuristic_summary"]
