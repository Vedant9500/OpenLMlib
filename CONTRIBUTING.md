# Contributing

Thanks for your interest in improving LMlib/OpenLMlib.

## Development Setup
1. Clone the repository.
2. Create and activate a virtual environment.
3. Install dependencies:

```bash
pip install -r requirements.txt
```

4. Run tests:

```bash
python -m unittest discover -s tests -p "test_*.py"
```

## Workflow
1. Create a branch from `main`.
2. Make focused changes with clear commit messages.
3. Add or update tests for behavior changes.
4. Run the test suite locally.
5. Open a pull request with context and verification notes.

## Pull Request Guidelines
- Keep PRs small and focused.
- Explain what changed and why.
- Include testing steps and outcomes.
- Reference related issues when applicable.
- Update docs when behavior or interfaces change.

## Coding Guidelines
- Follow existing code style and file organization.
- Prefer clear naming and small functions.
- Avoid unrelated refactors in the same PR.
- Preserve backward compatibility unless discussed.

## Reporting Bugs
Use the bug issue template and provide:
- Reproduction steps
- Expected behavior
- Actual behavior
- Environment details

## Feature Requests
Use the feature request template and describe:
- Problem statement
- Proposed solution
- Alternatives considered
- Potential impact

Thanks for contributing.
