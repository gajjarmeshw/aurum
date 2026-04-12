---
name: Code_Review_Helper
description: Leverages the structural code graph to provide deep context, blast radius analysis, and semantic search for Antigravity.
---

# Code Review Helper Skill

This skill provides Antigravity with structural understanding of the `aurum` codebase using the `code-review-graph` tool.

## Key Tool Commands

Use these commands via `run_command` to query the graph. The tool is installed at `/Users/mgajjar/.local/bin/code-review-graph`.

### 1. Impact Analysis: `detect-changes`
- **Risk Assessment**: `/Users/mgajjar/.local/bin/code-review-graph detect-changes`
- **Description**: Analyzes the blast radius of uncommitted changes and assigns risk scores.

### 2. Maintenance
- **Update Graph**: `/Users/mgajjar/.local/bin/code-review-graph update` (Run this after significant file changes)
- **Status**: `/Users/mgajjar/.local/bin/code-review-graph status`
- **Visualize**: `/Users/mgajjar/.local/bin/code-review-graph visualize` (Generates an interactive HTML graph)
- **Wiki**: `/Users/mgajjar/.local/bin/code-review-graph wiki` (Generates a markdown wiki of the codebase)

## Best Practices
- **Token Efficiency**: Use `detect-changes` before broad file reads to identify only the most relevant files for a task.
- **Dependency Tracking**: When refactoring a core component (like `sse_manager.py`), check the `--impact` radius first.
- **Test Coverage**: Use the `--tests` flag to find which test files should be run to verify changes.
