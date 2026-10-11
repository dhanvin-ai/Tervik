"""Recipe helper: a small chat agent on a local Ollama model with three tools,
connected to Tervik the way the Tervik skill connects a customer's agent.

    TERVIK_PROJECT_ID=PASTE_PROJECT_ID python3 examples/recipe-agent/agent.py
    TERVIK_PROJECT_ID=PASTE_PROJECT_ID TERVIK_ENDPOINT=https://api.tervik.in python3 examples/recipe-agent/agent.py
"""
import json
import os
import sys
import urllib.request
import uuid
from pathlib import Path

try:
    import tervik_client as tervik  # in your project, a copy of the skill's scripts/tervik_client.py
except ImportError:  # running from the Tervik repository
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "tervik" / "scripts"))
    import tervik_client as tervik

MODEL = "llama3.2"
OLLAMA = "http://127.0.0.1:11434/v1/chat/completions"
SYSTEM = ("You are a friendly cooking assistant. Use search_recipes to find recipes, convert_units for "
          "measurement conversions, and add_to_shopping_list only when the user asks to add something.")

RECIPES = {
    "tomato": ["Tomato basil pasta", "Shakshuka"],
    "chicken": ["Chicken tikka masala", "Lemon roast chicken"],
    "rice": ["Vegetable fried rice", "Lemon rice"],
}
UNITS = {("cup", "ml"): 240, ("tbsp", "ml"): 15, ("tsp", "ml"): 5, ("oz", "g"): 28.35, ("lb", "g"): 453.6}
SHOPPING = []

TOOLS = [
    {"type": "function", "function": {"name": "search_recipes", "description": "Find recipes that use an ingredient.",
     "parameters": {"type": "object", "properties": {"ingredient": {"type": "string"}}, "required": ["ingredient"]}}},
    {"type": "function", "function": {"name": "convert_units", "description": "Convert a kitchen measurement, such as 2 cup to ml.",
     "parameters": {"type": "object", "properties": {"amount": {"type": "number"}, "from_unit": {"type": "string"},
                                                     "to_unit": {"type": "string"}}, "required": ["amount", "from_unit", "to_unit"]}}},
    {"type": "function", "function": {"name": "add_to_shopping_list", "description": "Add an item to the user's shopping list.",
     "parameters": {"type": "object", "properties": {"item": {"type": "string"}}, "required": ["item"]}}},
]


def search_recipes(ingredient):
    found = RECIPES.get(str(ingredient).lower().strip())
    if not found:
        raise ValueError(f"No recipes found for {ingredient}")
    return {"ingredient": ingredient, "recipes": found}


def convert_units(amount, from_unit, to_unit):
    factor = UNITS.get((str(from_unit).lower().rstrip("s"), str(to_unit).lower()))
    if factor is None:
        raise ValueError(f"Cannot convert {from_unit} to {to_unit}")
    return {"amount": round(float(amount) * factor, 1), "unit": to_unit}


def add_to_shopping_list(item):
    SHOPPING.append(item)
    return {"added": item, "items": len(SHOPPING)}


HANDLERS = {"search_recipes": search_recipes, "convert_units": convert_units, "add_to_shopping_list": add_to_shopping_list}


def call_model(messages):
    body = json.dumps({"model": MODEL, "messages": [{"role": "system", "content": SYSTEM}] + messages, "tools": TOOLS}).encode()
    request = urllib.request.Request(OLLAMA, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.load(response)["choices"][0]["message"]


def run_tool(turn, name, args):
    call = turn.tool(name, args)  # tervik.instrumented
    try:
        output = json.dumps(HANDLERS[name](**args))
        call.end(output)
        return output
    except Exception as error:  # the model sees tool errors and can recover
        call.end(f"Error: {error}", success=False)
        return f"Error: {error}"


def respond(history, message, conversation_id, user_id):
    """Handle one user message and return the assistant's reply."""
    # tervik.instrumented: one Tervik turn per user message, tool calls nested under it.
    turn = tervik.begin(user_id=user_id, agent_name="recipe-helper", input=message, conversation_id=conversation_id)
    turn.set_property("model", MODEL)
    try:
        history.append({"role": "user", "content": message})
        answer = ""
        for _ in range(5):
            reply = call_model(history)
            history.append({"role": "assistant", "content": reply.get("content") or "", **({"tool_calls": reply["tool_calls"]} if reply.get("tool_calls") else {})})
            if not reply.get("tool_calls"):
                answer = reply.get("content") or ""
                break
            for call in reply["tool_calls"]:
                args = json.loads(call["function"].get("arguments") or "{}")
                history.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": run_tool(turn, call["function"]["name"], args)})
        else:
            answer = history[-1].get("content") or ""
        turn.end(output=answer)
        return answer
    except Exception as error:
        turn.end(output=f"Error: {error}", success=False)
        raise


def main():
    # tervik.instrumented
    if not os.environ.get("TERVIK_PROJECT_ID"):
        raise SystemExit("Set TERVIK_PROJECT_ID to the project ID from Tervik's Connect your agent page.")
    tervik.init(os.environ["TERVIK_PROJECT_ID"], endpoint=os.environ.get("TERVIK_ENDPOINT", "http://127.0.0.1:8000"))
    conversation_id, history = str(uuid.uuid4()), []
    user_id = os.environ.get("RECIPE_USER", "local-user")  # pseudonymous
    print("Recipe helper. Ask me anything about cooking (Ctrl+D to quit).")
    if sys.stdin.isatty():
        print("You: ", end="", flush=True)
    try:
        for line in sys.stdin:
            message = line.strip()
            if message:
                print("Assistant:", respond(history, message, conversation_id, user_id), flush=True)
            if sys.stdin.isatty():
                print("You: ", end="", flush=True)
    finally:
        tervik.shutdown()


if __name__ == "__main__":
    main()
