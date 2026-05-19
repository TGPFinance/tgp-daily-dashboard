import anthropic
import os
from datetime import date

client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
today = date.today().strftime("%B %d, %Y")

# ---------------------------------------------------------------
# CUSTOMIZE YOUR PROMPT HERE
# Tell Claude what dashboard to generate — what data, metrics,
# sections, style, etc. The more specific, the better the output.
# ---------------------------------------------------------------
DASHBOARD_PROMPT = f"""
Generate a complete, self-contained HTML dashboard for {today}.

Include:
- Header with the date and title
- Key metrics cards (use placeholder numbers for now)
- A summary section
- Clean modern styling using only inline CSS
- No external libraries or dependencies — fully self-contained

Return ONLY the raw HTML. No markdown, no code fences, no explanation.
"""
# ---------------------------------------------------------------

print(f"Generating dashboard for {today}...")

message = client.messages.create(
    model="claude-opus-4-5",
    max_tokens=4096,
    messages=[
        {"role": "user", "content": DASHBOARD_PROMPT}
    ]
)

html = message.content[0].text.strip()

# Strip markdown fences if the model adds them
if html.startswith("```"):
    lines = html.split("\n")
    html = "\n".join(lines[1:-1]).strip()

with open("index.html", "w") as f:
    f.write(html)

print("index.html written successfully.")
