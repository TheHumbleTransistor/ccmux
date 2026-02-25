# Workflow

When working on GitHub issues, follow this process exactly:

1. **Review the issue** — Read the GitHub issue provided by the user
2. **Plan in plan mode** — Explore the codebase, design an approach, and present a plan for user approval
3. **Create a feature branch** — Branch from master with naming convention `feature/issue-<number>-<short-description>`
4. **Implement** — Execute the approved plan
5. **Iterate on review** — Address user feedback until they approve
6. **Commit and push** — Commit changes with a descriptive message and push the branch
7. **Create a PR** — Open a pull request against master using `gh pr create`
8. **Update the issue** — Comment on the GitHub issue with a link to the PR

## Branch Naming
- Always create feature branches: `feature/issue-<number>-<short-description>`
- Never work directly on master
