# Testing a web app in a browser

Use when asked to check that a page or a flow actually works — "does the login
work?", "is it rendering?", "take a look at the site" — and to verify front-end
changes you just made.

You have a real headless browser: the `browse` tool runs the page's JavaScript.
`curl` cannot — it returns the empty shell of anything client-rendered, so a
`curl` that "looks fine" proves very little about a modern front end.

## What to do

1. **Look at the rendered page.** `browse` with `action: text` gives you what a
   user would read. If the text you expect isn't there, the page didn't render —
   that is the finding.
2. **Take a screenshot** when layout matters, or when the user asks what it
   looks like. Screenshots are full-page by default.
3. **Check the console and the network** for the real cause of a blank page:
   ```bash
   curl -sS -o /dev/null -w '%{http_code}\n' http://localhost:3000/api/health
   ```
   A page that renders "Loading…" forever is almost always a failing request
   behind it, not a rendering bug.
4. **Report what you saw**, not what should have happened.

## Rules

- **Verify, don't assume.** "The build succeeded" is not "the page works". Load
  it.
- **Start the server yourself if it isn't running**, and remember it is a
  long-running command: send it to the background rather than blocking on it.
- **Check the error path too** — the 404, the empty state, the failed submit.
  They are where the bugs live and where nobody looks.
- **Don't paste the whole DOM** into the chat. Quote the line that matters.
