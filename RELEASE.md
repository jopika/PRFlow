# Release Process

Releases are managed by GitHub Actions with Release Please.

## Commit Message Format

Release Please only opens release PRs for releasable commits it can parse. In practice, that means merge commits and direct commits to `main` should use Conventional Commits:

- `feat: add interactive commit picker`
- `fix: preserve staged files when commit is cancelled`
- `deps: update click to 8.1.8`

## Release Cycle

1. Merge normal feature and fix PRs into `main`.
2. Every push to `main` runs the Release Please workflow.
3. If there are unreleased changes, Release Please opens or updates a dedicated release PR.
4. That release PR carries the proposed version bump and changelog updates.
5. Review the release PR like any other change. Edit the changelog text if the generated summary needs cleanup.
6. Merge the release PR when you are ready to publish.
7. Merging the release PR creates the Git tag, publishes the GitHub Release, builds the package artifacts, and uploads them to the release page.

## What Release Please Updates

- `pyproject.toml` for the package version
- `CHANGELOG.md` for release notes
- `.release-please-manifest.json` to track the latest released version

The CLI version shown by `prflow --version` reads from installed package metadata and falls back to `pyproject.toml` in a local checkout, so the release version stays aligned with the packaged build.

## Release Artifacts

When a release is created, GitHub Actions builds and attaches:

- `prflow-<version>.tar.gz`
- `prflow-<version>.zip`
- `prflow-<version>-py3-none-any.whl`

The workflow validates the built Python package metadata with `twine check` before uploading the assets.

## Day-to-Day Maintainer Flow

- Merge regular work into `main`.
- Wait for Release Please to open or refresh the release PR.
- Review the proposed version and `CHANGELOG.md`.
- Edit the changelog in the release PR if you want cleaner notes.
- Merge the release PR to publish the release.

## Notes

- You only need to create a release tag by hand once, during the initial bootstrap.
- After bootstrap, do not create release tags by hand; Release Please will create them when the release PR is merged.
- If Release Please logs `commit could not be parsed`, check that the merged commit titles follow Conventional Commits.
- You do not need to manually edit the version in multiple files.
- CI in `.github/workflows/ci.yml` verifies tests and packaging on pull requests and on pushes to `main`.
