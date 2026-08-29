"""strikeone.ai — the narration layer. AI is disabled by default; nothing
in this package is imported by the deterministic commands. The LLM never
computes or alters risk, selects thresholds, chooses actions, touches the
holdout, modifies any metric, or produces any number that appears on a
judging slide: it receives a finished evidence contract and returns prose
whose every factual claim is re-checked against that contract before
printing (strikeone.ai.validator)."""
