# setup

`@IMGAgent setup <reuse|aisignoff|citation|docs>` sets up one file of the repository from a template. It needs no text: IMGAgent answers with a form whose defaults are already filled in from the repository and from you. When you tick **Done**, IMGAgent turns the form into the file and opens a pull request for you to review. No AI is involved, so the pull request is declared G0.

| Command | Creates |
|---|---|
| `setup reuse` | `REUSE.toml`, and the license texts in `LICENSES/` |
| `setup aisignoff` | `SIGNOFF.toml` |
| `setup citation` | `CITATION.cff` |
| `setup docs` | `zensical.toml`, and `docs/index.md` if missing |

If the file already exists, IMGAgent says so and changes nothing. To change an existing file, use `@IMGAgent update REUSE.toml` (or another file name) and say what to change; `make docs` also rebuilds the nav of `zensical.toml`.

## Filling in a template

- **Boxes** can be ticked right in the comment, without editing it. Where a group says *tick one*, tick exactly one box.
- **Values** stand between backticks, such as `` `main` ``. To change one, open the comment's menu (*⋯ → Edit*) and change the text between the backticks. An empty value is written `` ` ` ``.
- **Done**: tick the box at the end, or reply `@IMGAgent setup <target> done`. Then IMGAgent reads the form.

Every line ends with an invisible marker (`<!-- f:... -->`) that IMGAgent reads the line by, so you may change the wording around the values, but keep the markers.

If something in the form can't be used, such as a malformed license or two ticked boxes in a *tick one* group, IMGAgent unticks **Done**, puts the problem on top of the form and replies with it. Fix it and tick **Done** again. After the pull request is opened, **Done** is replaced by its link, so the form can't run twice.

Only people with write access are answered, and only templates that IMGAgent itself posted are read.

## setup reuse

The template asks for:

- **Copyright**: the notice for every file, by default the year and the name of the repository's owner.
- **Licenses**: the common ones as boxes (MIT, Apache 2.0, BSD 3-Clause, GPL, LGPL and AGPL 3.0 or later, MPL 2.0, EUPL 1.2, CC BY 4.0, CC BY-SA 4.0, CC0 1.0), each with the folders it is for. The repository's license, as GitHub detects it, is already ticked for `.`, which means everything. Two more lines take any other SPDX identifier or expression, such as `MIT OR Apache-2.0` or `LicenseRef-Own`.

Folders are comma-separated. A folder becomes `<folder>/**`; a file or a glob (`docs/**/*.png`) is used as it is; every folder or file must exist. Each folder becomes one `[[annotations]]` table of the [REUSE specification](https://reuse.software/spec/), with everything (`**`) first, since the last matching annotation wins. Two licenses ticked for the same folder are combined with `AND`.

IMGAgent downloads the text of every license that `LICENSES/` lacks from the [SPDX license list](https://github.com/spdx/license-list-data) and adds it to the pull request. A `LicenseRef-` license, or one whose text can't be fetched, is listed in the pull request to add by hand. Check the result with `pipx run reuse lint`.

## setup aisignoff

The template asks for:

- **Default declaration**: the paths (`**`, every file), `Reviewed-by` (your GitHub name), `Assisted-by`, `AI-Reviewed-by`, and the levels: G0, H2 and A0 by default, or TODO for a person to fill in later.
- **History**: `[history]` is on, with the repository's default branch, the merge method (merge, squash or rebase) and what commits that declare nothing mean.
- **More**: files that need no declaration (`exclude`), the minimum review levels (`[policy]`), and the folder where AI reviews are recorded (`[review] dir`, default `reviews`; empty for none).

The result is checked with aisignoff before the pull request: the file must be readable, and the default declaration must fit together (for example, G1 to G3 need `Assisted-by`). Once `SIGNOFF.toml` is merged, [signoff](signoff.md) and the signoff form work in the repository.

## setup citation

The template asks for the fields of a [Citation File Format](https://citation-file-format.github.io) file: title (the repository name), message, type (software or dataset), up to three authors (you first, as `Given Family` or `Family, Given`, each with an optional ORCID), version, release date (`YYYY-MM-DD`), license (the repository's), repository address, website, DOI, abstract (the repository description) and keywords (the repository topics). At least one author is needed.

## setup docs

The template asks for the site name (the repository name), description (the repository description) and address (the repository's homepage, or `https://<owner>.github.io/<repo>/`; empty for none). IMGAgent writes the same `zensical.toml` as [make docs](make-docs.md) (site settings, theme, Markdown extensions), with a nav of the pages already in `docs/`: top-level pages first, then one section per folder, titled by each page's first heading. Without `docs/index.md`, a placeholder home page is added. To write the pages themselves from the code, use `@IMGAgent make docs`.
