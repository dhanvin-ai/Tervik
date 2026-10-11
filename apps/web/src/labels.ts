// Short names for what went wrong, shown on rows, banners, messages, and chat replies.
const FAILURE_LABELS: Record<string, string> = {
  correction: 'User corrected the agent',
  frustration: 'User was frustrated',
  repetition: 'User repeated a request',
  unresolved: 'User said it is not solved',
  tool_error: 'Tool call failed',
  tool_timeout: 'Tool call timed out',
  unsupported_claim: 'Claimed an action without a tool',
  rule_violation: 'Broke a behavior rule',
  policy_violation: 'Broke a policy',
  tool_bad_input: 'Made-up tool values',
  unrequested_action: 'Action nobody asked for',
};

export function failureLabel(kind: string) {
  return FAILURE_LABELS[kind] || kind.replaceAll('_', ' ').replace(/^./, c => c.toUpperCase());
}
