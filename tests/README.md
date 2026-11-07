# Tests

```bash
python3 -m unittest discover -s tests      # from the repo root, on Linux; ~1 minute
```

`fake_claude.py` and `fake_opencode.py` stand in for the real CLIs: their behaviour is chosen by keywords in the job title (`BADFIRST`, `ALWAYSBAD`, `OCASK`, `ESCAPE`, ...). The suite covers queueing, budgets, team stages, the push wall, Landlock escapes, the GPU lock, local review rounds, need_human, takeover and the media bots. Landlock tests need Linux; on macOS the local-job tests fail.
