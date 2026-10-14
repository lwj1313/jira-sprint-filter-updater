# Jira filter updater: every other Thursday

This GitHub Actions automation updates these Jira saved filters to the next sprint on board `3674`:

`98500, 98499, 98498, 98497, 98496, 98495, 98494, 98492, 98491, 98489, 98490, 98488, 98487, 98484, 98485`

The first scheduled update is **Thursday, October 15, 2026 at 9:00 AM America/New_York**. It repeats every 14 days.

## Setup

1. Copy `.github/workflows/update-jira-filters.yml` and `scripts/update_jira_filters.py` into your GitHub repository.
2. Add these GitHub repository secrets:
   - `JIRA_BASE_URL`
   - `JIRA_EMAIL`
   - `JIRA_API_TOKEN`
3. Run the workflow manually or let the schedule run. It defaults to **dry-run mode**.
4. Review the proposed JQL changes in the Actions log.
5. Create a repository variable named `JIRA_FILTER_UPDATE_DRY_RUN` with value `false` to enable live updates.

The Jira account must be able to view and edit every listed saved filter and view sprints on board `3674`.

## Behavior

- Selects the active sprint on board `3674`; if none is active, selects the earliest future sprint.
- Replaces hard-coded sprint clauses with `sprint = <next sprint ID>`.
- Leaves `sprint in openSprints()` unchanged.
- Skips filters without a hard-coded sprint clause.
- Runs at 9:00 AM Eastern every other Thursday.
