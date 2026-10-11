"""Trip planner: a small chat agent on a local Ollama model with three tools.

It has no Tervik code. Use it to try connecting an agent with the Tervik
skill: copy this folder somewhere of its own, open it in your coding agent
(Claude Code, Codex, Cursor), and run the prompt from Tervik's Connect your
agent page.

    python3 agent.py
"""
import json
import os
import sys
import urllib.request

MODEL = os.environ.get("AGENT_MODEL", "llama3.2")
OLLAMA = os.environ.get("OLLAMA_CHAT_URL", "http://127.0.0.1:11434/v1/chat/completions")
SYSTEM = ("You are a friendly trip planner. Use get_weather for forecasts, convert_currency for money, "
          "and book_hotel only when the traveller asks you to book.")

WEATHER = {"paris": "18°C, light rain", "tokyo": "24°C, sunny", "goa": "31°C, humid", "london": "14°C, cloudy"}
RATES = {("usd", "eur"): 0.92, ("usd", "inr"): 83.2, ("eur", "inr"): 90.4, ("usd", "jpy"): 149.5}
BOOKINGS = []

TOOLS = [
    {"type": "function", "function": {"name": "get_weather", "description": "Get the forecast for a city.",
     "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}},
    {"type": "function", "function": {"name": "convert_currency", "description": "Convert an amount between currencies, such as 100 USD to EUR.",
     "parameters": {"type": "object", "properties": {"amount": {"type": "number"}, "from_currency": {"type": "string"},
                                                     "to_currency": {"type": "string"}}, "required": ["amount", "from_currency", "to_currency"]}}},
    {"type": "function", "function": {"name": "book_hotel", "description": "Book a hotel for the traveller.",
     "parameters": {"type": "object", "properties": {"city": {"type": "string"}, "nights": {"type": "integer"},
                                                     "guest_name": {"type": "string"}}, "required": ["city", "nights", "guest_name"]}}},
]


def get_weather(city):
    forecast = WEATHER.get(str(city).lower().strip())
    if forecast is None:
        raise ValueError(f"No forecast available for {city}")
    return {"city": city, "forecast": forecast}


def convert_currency(amount, from_currency, to_currency):
    rate = RATES.get((str(from_currency).lower(), str(to_currency).lower()))
    if rate is None:
        raise ValueError(f"No exchange rate for {from_currency} to {to_currency}")
    return {"amount": round(float(amount) * rate, 2), "currency": str(to_currency).upper()}


def book_hotel(city, nights, guest_name):
    if str(city).lower().strip() not in WEATHER:
        raise ValueError(f"No hotels available in {city}")
    BOOKINGS.append({"city": city, "nights": nights, "guest": guest_name})
    return {"booking_id": f"HTL-{len(BOOKINGS):04d}", "city": city, "nights": nights, "guest": guest_name}


HANDLERS = {"get_weather": get_weather, "convert_currency": convert_currency, "book_hotel": book_hotel}


def call_model(messages):
    body = json.dumps({"model": MODEL, "messages": [{"role": "system", "content": SYSTEM}] + messages, "tools": TOOLS}).encode()
    request = urllib.request.Request(OLLAMA, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.load(response)["choices"][0]["message"]


def run_tool(name, args):
    try:
        return json.dumps(HANDLERS[name](**args))
    except Exception as error:  # the model sees tool errors and can recover
        return f"Error: {error}"


def respond(history, message):
    """Handle one traveller message and return the assistant's reply."""
    history.append({"role": "user", "content": message})
    for _ in range(5):
        reply = call_model(history)
        history.append({"role": "assistant", "content": reply.get("content") or "",
                        **({"tool_calls": reply["tool_calls"]} if reply.get("tool_calls") else {})})
        if not reply.get("tool_calls"):
            return reply.get("content") or ""
        for call in reply["tool_calls"]:
            try:
                args = json.loads(call["function"].get("arguments") or "{}")
            except ValueError:
                args = {}
            history.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": run_tool(call["function"]["name"], args)})
    return history[-1].get("content") or ""


def main():
    history = []
    print("Trip planner. Ask about weather, money, or hotels (Ctrl+D to quit).")
    if sys.stdin.isatty():
        print("You: ", end="", flush=True)
    for line in sys.stdin:
        message = line.strip()
        if message:
            print("Assistant:", respond(history, message), flush=True)
        if sys.stdin.isatty():
            print("You: ", end="", flush=True)


if __name__ == "__main__":
    main()
