"""Runs on latte's gateway: report finished or blocked latte-crew jobs to the owner's DM."""
import os
import subprocess

from kiro_crew.cron_script import Skip


def run(ctx):
    crew = os.path.expanduser("~/latte-crew/crew.py")
    got = subprocess.run(["/usr/bin/python3", crew, "notify"], capture_output=True, text=True, timeout=25)
    text = got.stdout.strip()
    if got.returncode or not text:
        raise Skip()
    ctx.notify(f"任务更新:\n{text}", session="slack")
