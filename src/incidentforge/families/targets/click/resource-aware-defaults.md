In click the sizes are help and output widths: `HelpFormatter(width, max_width)` and
`Context(terminal_width, max_content_width)` fall back to the terminal size (`shutil.get_terminal_size`,
which already honours `COLUMNS`) clamped to 80 columns with a floor of 50, and the progress bar derives
its bar width from the terminal. "The configured limit" is the width the developer passes or the
terminal width; "startup" is building the context or formatter.

Good features: reject a width or max width that is zero, negative or below the floor click can lay out,
with an error naming the argument and value; reject `max_content_width` below `terminal_width` when both
are given (naming both); or make the floor and clamp explicit, documented and configurable instead of the
hardcoded 50/80. Test with explicit widths or `monkeypatch.setenv("COLUMNS", ...)`, never a real
terminal. Keep today's defaults when nothing is configured.
