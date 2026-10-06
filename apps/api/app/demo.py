from datetime import timedelta
from uuid import NAMESPACE_URL, uuid5
from .schemas import EventInput

DEMO_PROJECT_ID = str(uuid5(NAMESPACE_URL, "tervik-demo-project-v1"))


def demo_events(now):
    """Deterministic IDs prevent duplicate sample messages on subsequent seeding."""
    requests = [
        ("Find my latest invoice", "Your latest invoice is available in Billing → Invoices."),
        ("How do I invite a teammate?", "Open Settings → Members and select Invite teammate."),
        ("Can I export the report as CSV?", "Yes. Open the report and select Export → CSV."),
        ("Help me change my billing address", "You can update your billing address in Settings → Billing."),
        ("Show the status of my order", "Your order has shipped. Its tracking details are in Orders."),
        ("How do I reset my password?", "Use Reset password on the sign-in screen. We will email a secure link."),
    ]
    result = []
    for number in range(54):
        prompt, reply = requests[number % len(requests)]
        when = now - timedelta(days=number % 6, hours=1 + number % 12, minutes=number)
        conversation = f"sample-conversation-{number:03}"
        user = f"sample-user-{number % 29:03}"
        messages = [("user", prompt, "success", None), ("assistant", reply, "success", None)]
        kind = number % 9
        if kind == 0:
            messages += [("user", "That's not what I asked. I meant the previous month's invoice.", "success", None),
                         ("assistant", "Thanks for clarifying. Choose the previous month in Billing → Invoices.", "success", None)]
        elif kind == 1:
            messages += [("user", "This is frustrating. You keep ignoring my request.", "success", None),
                         ("assistant", "I understand. Let me check the request again.", "success", None)]
        elif kind == 2:
            messages += [("user", prompt, "success", None),
                         ("assistant", reply, "success", None)]
        elif kind == 3:
            messages += [("tool", "HTTP 503: Billing service unavailable", "error", "billing.lookup"),
                         ("assistant", "The billing service is temporarily unavailable. Please try again shortly.", "success", None)]
        elif kind == 4:
            messages += [("tool", "Request timed out after 2000 ms", "error", "orders.lookup"),
                         ("assistant", "I could not retrieve the order. You can also check the Orders page.", "success", None)]
        else:
            messages += [("user", "Thank you, that helped.", "success", None)]
        for turn, (role, content, status, name) in enumerate(messages):
            span_id = f"sample-span-{number}-{turn}" if role in ("tool", "assistant") else None
            result.append(EventInput(
                id=f"sample-event-{number}-{turn}", conversation_id=conversation, user_id=user,
                role=role, content=content, timestamp=when + timedelta(seconds=turn * 3),
                status=status, name=name, trace_id=f"sample-trace-{number}", span_id=span_id,
                parent_span_id=f"sample-span-{number}-1" if role == "tool" else None,
                latency_ms=(2000 if status == "error" else 480 + number * 17) if span_id else None,
                tokens=80 + number if role == "assistant" else None,
                cost_usd=0.0006 + number * 0.00001 if role == "assistant" else None,
                model="sample-agent-v1" if role == "assistant" else None,
                metadata={"sample": True, "input": prompt, "output": content} if span_id else {"sample": True},
            ))
    return result
