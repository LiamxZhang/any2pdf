# Queue cards, ordering and PDF merge

The upload area now renders each accepted input as a compact card with filename, count for merged items, and status. The cards are derived from the current session queue and provide immediate visible feedback after chooser or drag/drop acceptance.

The queue table uses extended row selection. Move up/down changes the pending task order and table order. A merge action requires at least two queued tasks, collects their source lists in visible row order, replaces them with one batch history task, and sends one worker request. The worker renders each source to an isolated temporary PDF, appends pages in request order, validates the merged PDF, and atomically publishes one output. Original files remain untouched; intermediate PDFs are removed with the workspace.

Batch history rows retain a JSON source list in a migrated SQLite column. Existing databases fall back to the legacy single source field. Display shows the first filename and a count suffix, while tooltips and worker requests retain every path. Errors use stable localized codes, including insufficient merge selection and merge failure.

Tests cover card creation, queue reordering, multi-row selection, ordered merged page extraction, history source migration, and existing single-file conversion behavior.
