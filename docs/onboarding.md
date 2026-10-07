# Tervik pilot onboarding

For the three paid-beta teams in the Phase 7 completion gate. Each team
runs this checklist independently; a Tervik engineer only observes.

## 1. Install (two steps)

```bash
npx skills add dhanvin-ai/tervik --skill tervik
```

```text
Use the tervik skill to add Tervik analytics to this agent.
```

## 2. Connect

1. Sign up in the dashboard (or ask for an account) and create a project.
2. Create an ingest credential for the `production` environment.
3. Set `TERVIK_API_KEY` and `TERVIK_ENDPOINT` in server-side secrets only.

## 3. Verify (without our help)

1. Trigger one real agent interaction through the real entrypoint.
2. Open the project's setup page: events received should be > 0.
3. Open Conversations, find the interaction by user/time/content, confirm
   messages, tool spans, latency, and cost.

## 4. Investigate one useful finding

1. Open Failure clusters or Discovery and pick a real signal.
2. Confirm the evidence links to recorded messages/spans.
3. Mark it resolved or add a behavior rule for it.

## 5. Receive one actionable alert

1. Add an alert rule (threshold or daily summary) with a team webhook.
2. Confirm the delivery arrives exactly once per cooldown window.

## Exit criteria per team

Setup completion + time to first real event, one investigated finding,
one received alert. Report drop counters (`inspect()`) and any step that
needed assistance — that step is a product bug.
