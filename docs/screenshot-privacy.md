# Screenshot privacy and safer desktop operation

The screenshot path is shared by the desktop operator, `look_at_screen`, and the eval frame recorder. It now supports local, optional filtering before a screenshot is published to its normal output directory or encoded for the model. No external OCR service or additional model call is used.

## Configuration

| Variable | Default | Behavior |
| --- | --- | --- |
| `SCREENSHOT_PRIVACY` | `off` | `off`: no image parsing or OCR. `masks`: fixed regions only. `ocr`: fixed regions plus local sensitive-text detection. |
| `SCREENSHOT_MASKS` | `[]` | JSON array of `[x, y, width, height]` rectangles, normalized to the original screenshot, with origin at the top left. Values must stay within the image. |
| `SCREENSHOT_KEEP` | `100` | Maximum `screen-*.jpg` captures kept in each capture directory; positive integer. |

Install Pillow for either enabled filtering mode:

```sh
uv sync --extra screenshot-privacy
```

OCR additionally requires the `tesseract` executable on PATH and its default language data. Missing tooling, timeouts, malformed OCR output, image-processing failures, and invalid configuration block the capture rather than falling back to an unfiltered image. Configure the environment before launching the process; privacy configuration is independent of telemetry, graph, and verification flags.

For example, mask the upper-right quarter of the main display without running OCR:

```sh
SCREENSHOT_PRIVACY=masks SCREENSHOT_MASKS='[[0.75,0,0.25,0.25]]' DESKTOP_CONTROL=1 uv run agent.py
```

Run local OCR detection in addition to any masks:

```sh
SCREENSHOT_PRIVACY=ocr DESKTOP_CONTROL=1 uv run agent.py
```

An explicit `SCREENSHOT_PRIVACY=off` restores the unfiltered screenshot path. Masks supplied with `off` are rejected to prevent accidentally ignoring a configured privacy region.

## Processing and data handling

A capture first goes into a mode-0700 temporary directory inside the capture directory. The raw file is mode 0600 once capture returns. Filtering happens at the original resolution; solid black rectangles with padding cover sensitive word bounds and configured regions. The image is then resized to the existing 1280-pixel width and atomically moved to its final path with mode 0600. Image dimensions and click-coordinate conventions remain unchanged. The private temporary directory is removed on normal success and handled failures. A forced process termination or machine crash can leave private temporary files; this is not secure erasure or a memory-only capture mechanism.

OCR patterns identify common email addresses, North American phone numbers, US SSN-like identifiers, 13–19-digit card-like sequences, selected API-key formats, bearer tokens, and labeled secret/password assignments. Text is grouped by OCR line so identifiers split across words can be masked. OCR text and matched secret values are never logged. Operator events record the selected mode, number of configured masks, retention setting, number of redacted regions, and total capture-processing duration. These counts are diagnostic, not a measure of privacy coverage.

Retention only removes regular `screen-*.jpg` files directly inside the current capture directory. It does not follow symlinks, recurse into earlier runs, remove action logs, delete graph snapshots, or bound renamed eval `frames/*.jpg`. Existing images and exported copies are not retroactively sanitized. Review and remove those separately when needed.

## Limits and experiment interpretation

Detection is best effort. OCR can miss small, stylized, obscured, or non-default-language text. Regex patterns can both miss sensitive data and mask harmless task content. Names, faces, postal addresses, arbitrary passwords, and text spanning lines are not comprehensively detected. Use fixed masks for known sensitive regions and avoid capturing sensitive desktops when possible.

This feature protects newly captured screenshot pixels only. Accessibility telemetry, document inspection, the knowledge graph, task text, action logs, saved sessions, and third-party agents' own screenshots have separate data paths and are not comprehensively sanitized by this change. Existing textual redaction remains in place. Skill instructions discourage disclosing or bypassing hidden content, but they are model guidance rather than a security boundary.

The optional modes add image processing; OCR also launches a local subprocess per capture, with a 15-second timeout. The default remains off to avoid silently changing existing runtime comparisons. Use identical privacy mode and masks for all comparable experimental arms, record them, and report masking-induced unavailable information. The operator records its configuration, while eval `run.json` records the recorder configuration; inline command environment overrides can differ from the recorder environment. The recorder's filtering does not control external agents' private capture mechanisms. Do not compare filtered and unfiltered conditions as evidence of a graph effect.

## General skill changes and validation

The always-loaded desktop skill now addresses instructions embedded in untrusted screen content, respecting privacy masks, checking authorization before external effects, establishing focus before typing, taking reversible steps, and resolving conflicts using fresh evidence. These habits apply to every task and contain no task IDs, expected answers, grader internals, or benchmark-specific solutions. They do not add tools or model turns. Improved task completion has not been established experimentally.

Offline tests use generated images, synthetic OCR TSV, and mocked capture commands. They check pixel masking, span detection, missing/failed OCR, malformed configuration and output, unchanged off-mode bytes, restricted output permissions, cleanup, bounded retention, and operator termination when protection fails. Run them with:

```sh
uv run pytest -q
```

No paid model evaluation or real private-screen capture is required by these tests. An additional integration test runs genuine Tesseract recognition on a fabricated desktop image containing an email address and an SSN-like identifier; it checks both redactions and preservation of ordinary task text, and skips when Tesseract is unavailable. Local validation recognized and redacted both fields in approximately 1.9 seconds on one 1600-by-900 image. This is one synthetic example, not a detection-accuracy or runtime benchmark. Synthetic capture through the real macOS sips resize command was also checked; capture of a real desktop has not been tested as part of this change.
