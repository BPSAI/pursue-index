---
description: Analyze conversations and suggest skill improvements
allowed-tools: Bash(bpsai-pair:*)
---

Analyze the current conversation for:
1. Repeated workflows not captured in existing skills
2. Commands or patterns used frequently
3. Gaps where a skill would have helped

Then run skill suggestions:

```bash
bpsai-pair skill suggest
```

If user approves a suggestion:

```bash
bpsai-pair skill suggest --create <number>
bpsai-pair skill validate
```
