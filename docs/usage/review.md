# review

`@IMGAgent review` gives a quick AI review of the folders you name, optionally checked against other folders, and records it as an aisignoff **A1** attestation (a context-free AI review) in a pull request. It is a light check by `claude-sonnet-5-5` at low effort, not an exhaustive review.

## Writing the command

```
@IMGAgent review docs with src
```

reviews the files in `docs`, using `src` as context: for example, whether the docs still describe what the code does. Problems in `src` are not reported.

- The folders before `with` are reviewed; the `with` folders are only read. See [Commands](index.md) for the general syntax.
- Text after the command is optional and tells Claude what to look at, e.g. `@IMGAgent review docs with src check the install steps`.
- It always reviews the files as they are on the default branch, also when the command is in a pull request.

## What happens

1. IMGAgent clones the default branch and checks that every named folder exists.
2. `scripts/repo/review.py` sends the reviewed files and the context (together at most about 150k tokens, the same file rules as [ask](ask.md#which-files-claude-reads)) to Claude, which returns at most 10 findings, each with a severity in aisignoff's terms: **critical**, **major**, **minor** or **trivial**. Findings about files outside the reviewed folders are dropped.
3. The highest severity is the review's `AI-Review-Findings` (`none` when there are none).
4. If the repository has a `SIGNOFF.toml`, IMGAgent runs

    ```
    aisignoff attest <reviewed files> -a A1 --findings <highest> \
        --ai-reviewed-by "Claude Sonnet 5.5 (Anthropic), new session without the generating conversation, quick review requested in <comment>"
    ```

    which writes a new record file in the review folder (`reviews/` unless `SIGNOFF.toml` sets `[review] dir`), and opens a pull request that only adds that file. Such a pull request needs no AI declaration.
5. It answers with the findings, the lines to copy into a pull request description, and the link to the pull request:

    ```
    AI-Review: A1
    AI-Reviewed-by: Claude Sonnet 5.5 (Anthropic), new session without the generating conversation, quick review requested in <comment>
    AI-Review-Findings: minor
    ```

Once the pull request is merged, the lines of the reviewed files show the findings level (**F0** for none or trivial, **F1** minor, **F2** major, **F3** critical) until they change. Only files that need a declaration in `SIGNOFF.toml` are attested. Without a `SIGNOFF.toml`, or if aisignoff refuses the record, you get the review and the reason, and no pull request. aisignoff notes, such as that attestations only count with `[history]` enabled, are passed on in the pull request.

## Model and cost

| Variable | Default | Meaning |
|---|---|---|
| `REVIEW_MODEL` | `claude-sonnet-5-5` | the reviewing model |
| `REVIEW_MODEL_NAME` | `Claude Sonnet 5.5 (Anthropic)` | its name in `AI-Reviewed-by`; keep it in step with `REVIEW_MODEL` |
| `REVIEW_EFFORT` | `low` | the effort |

A1 is the right level whatever the model: A2 and A3 need a different, capable model and a committed report.

## Running review.py locally

```bash
pip install anthropic
export ANTHROPIC_API_KEY=sk-ant-...
TARGETS=docs CONTEXT=src python path/to/imgagent/scripts/repo/review.py "check the install steps"
```

It prints the findings level and the review, or writes them as JSON to the file in `REVIEW_FILE`.
