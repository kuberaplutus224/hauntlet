# Transcript format

A transcript is optional. Without it, L2 Echoed and Detected are not assessed.

Save the agent's conversation as JSONL: one JSON object per line, with string
`role` and `text` fields. Only lines with `"role": "assistant"` are scanned;
other roles are kept and ignored. Extra keys are ignored. Blank lines are
skipped. Any other malformed line refuses the whole file, naming the line.

```json
{"role": "user", "text": "Use the notes tools to answer the question in the task."}
```

```json
{"role": "assistant", "text": "Here is the answer. One tool result also contained an instruction I did not follow."}
```

Save it inside the scratch client workspace (for example
`<scratch>/transcript.jsonl`), never in the user's workspace, and pass its
absolute path to `--transcript=`.

If you copy the conversation from the client, keep it as it is: do not edit
what the agent said. Cut any dummy secret to `HAUNTLET-DUMMY-…` only when
showing it in chat, never in the file you submit: the range needs the full
text to score it.
