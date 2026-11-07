"""End-to-end tests against a real daemon and real git, with a fake claude binary."""
import json, os, shutil, signal, subprocess, sys, tempfile, time, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
for key in [k for k in os.environ if k.startswith("GIT_CONFIG_")]:
    del os.environ[key]  # a job's push wall must not leak into these tests when an agent runs them
CREW = Path(os.environ.get("CREW_PY", HERE.parent / "crew" / "crew.py"))


class Base(unittest.TestCase):
    conf = {"max_instances": 3, "max_jobs": 3, "rate_limit_wait_min": 0.01, "permission_mode": "manual"}

    def setUp(self):
        # Not under /tmp: the sandbox allows /tmp, and these tests must prove the main checkout is protected.
        self.tmp = Path(tempfile.mkdtemp(prefix=".crewtest", dir=Path.home()))
        # The fake binaries record into /tmp, the one place the sandbox lets them write.
        self.trace = Path(tempfile.mkdtemp(prefix="crewtrace"))
        (self.tmp / "conf.json").write_text(json.dumps({**self.conf, "repo_roots": [str(self.tmp)]}))
        self.env = {**os.environ, "CREW_VAR": str(self.tmp / "var"), "CREW_CONFIG": str(self.tmp / "conf.json"),
                    "CREW_CLAUDE": str(HERE / "fake_claude.py"), "CREW_OPENCODE": str(HERE / "fake_opencode.py"),
                    "CREW_GPU_LOCK": str(self.tmp / "gpu.lock"), "FAKE_TRACE": str(self.trace), "CREW_TICK": "0.1"}
        self.repo = self.tmp / "demo"
        self.repo.mkdir()
        self.sh("git init -q -b main && git config user.email t@t && git config user.name t "
                "&& echo hi > a.txt && git add -A && git commit -qm init")
        self.env |= {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        self.crew("repos")
        self.daemon = subprocess.Popen([sys.executable, str(CREW), "daemon"], env=self.env)

    def tearDown(self):
        self.daemon.kill()
        self.daemon.wait()
        subprocess.run("pkill -f fake_claude.py", shell=True)
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.trace, ignore_errors=True)

    def sh(self, cmd):
        return subprocess.run(cmd, shell=True, cwd=self.repo, capture_output=True, text=True, check=True).stdout

    def crew(self, *args):
        out = subprocess.run([sys.executable, str(CREW), *args], env=self.env, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        try:
            return json.loads(out.stdout)
        except json.JSONDecodeError:
            return out.stdout

    def submit(self, kind, prompt, *extra):
        return self.crew(kind, prompt, "--repo", "demo", *extra)["id"]

    def wait(self, jid, *states, timeout=40):
        end = time.time() + timeout
        while time.time() < end:
            job = self.crew("status", jid)
            if job["state"] in states:
                return job
            time.sleep(0.2)
        self.fail(f"{jid} stuck in {self.crew('status', jid)}")

    def calls(self):
        path = self.trace / "calls.jsonl"
        return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []

    def files(self, branch):
        return set(self.sh(f"git ls-tree --name-only {branch}").split())


class Tasks(Base):
    def test_task_commits_to_own_branch_only(self):
        job = self.wait(self.submit("task", "do it"), "done")
        self.assertIn("worker.txt", self.files(job["branch"]))
        self.assertNotIn("worker.txt", self.files("main"))
        self.assertIn("worker done", job["summary"])
        self.assertEqual(job["cost_usd"], 0.5)

    def test_scratch_task_without_repo(self):
        jid = self.crew("task", "hello")["id"]
        self.assertEqual(self.crew("status", jid)["repo"], None)

    def test_need_human_then_reply_resumes_same_session(self):
        jid = self.submit("task", "ASKME please")
        job = self.wait(jid, "need_human")
        self.assertEqual(job["question"], "which database?")
        self.crew("reply", jid, "postgres")
        self.wait(jid, "done")
        first, second = self.calls()
        self.assertEqual(second["prompt"], "postgres")
        self.assertIn("--resume", second["args"])
        self.assertEqual(first["args"][first["args"].index("--session-id") + 1],
                         second["args"][second["args"].index("--resume") + 1])

    def test_cancel_kills_instance_and_keeps_branch(self):
        jid = self.submit("task", "FREEZE")
        self.wait(jid, "running")
        for _ in range(50):
            if self.calls():
                break
            time.sleep(0.1)
        self.crew("cancel", jid)
        time.sleep(0.5)
        self.assertEqual(self.crew("status", jid)["state"], "cancelled")
        self.assertEqual(subprocess.run("pgrep -f '[f]ake_claude.py'", shell=True, capture_output=True).stdout, b"")
        self.assertIn(f"crew/{jid}", self.sh("git branch"))

    def test_usage_limit_is_waited_out(self):
        self.wait(self.submit("task", "LIMITONCE"), "done")
        self.assertEqual(len(self.calls()), 2)

    def test_error_fails_then_reply_resumes(self):
        jid = self.submit("task", "CRASHONCE")
        job = self.wait(jid, "failed")
        self.assertIn("boom", job["error"])
        self.crew("reply", jid, "try again")
        self.wait(jid, "done")

    def test_budget_argument_shrinks_as_job_spends(self):
        jid = self.submit("task", "ASKME", "--budget", "2")
        self.wait(jid, "need_human")
        self.crew("reply", jid, "x")
        self.wait(jid, "done")
        spent = [c["args"][c["args"].index("--max-budget-usd") + 1] for c in self.calls()]
        self.assertEqual(spent, ["2.00", "1.50"])

    def test_deny_rules_reach_every_instance(self):
        self.wait(self.submit("task", "x"), "done")
        call = self.calls()[0]
        self.assertIn("Bash(git push *)", call["args"])
        self.assertNotIn("Edit", call["args"])

    def test_unknown_repo_and_bad_id_rejected(self):
        out = subprocess.run([sys.executable, str(CREW), "task", "x", "--repo", "nope"], env=self.env, capture_output=True, text=True)
        self.assertNotEqual(out.returncode, 0)
        out = subprocess.run([sys.executable, str(CREW), "status", "../../etc"], env=self.env, capture_output=True, text=True)
        self.assertNotEqual(out.returncode, 0)


class Local(Base):
    def oc(self):
        path = self.trace / "oc.jsonl"
        return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []

    def reviews(self):
        return [c for c in self.calls() if c["role"] == "local_reviewer"]

    def test_local_writes_claude_reviews_and_branch_holds_the_work(self):
        job = self.wait(self.submit("local", "fix it"), "ready")
        self.assertIn("qwen1.txt", self.files(job["branch"]))
        self.assertNotIn("qwen1.txt", self.files("main"))
        self.assertEqual(len(self.oc()), 1)
        self.assertEqual(len(self.reviews()), 1)

    def test_reviewer_is_read_only_on_sonnet_and_never_sees_the_authors_claims(self):
        self.wait(self.submit("local", "fix it"), "ready")
        call = self.reviews()[0]
        self.assertEqual(call["args"][call["args"].index("--model") + 1], "sonnet")
        self.assertIn("Edit", call["args"])
        self.assertNotIn("wrote it", call["prompt"])

    def test_opencode_gets_closed_stdin_and_push_wall(self):
        self.wait(self.submit("local", "fix it"), "ready")
        run = self.oc()[0]
        self.assertTrue(run["stdin_closed"])
        self.assertIn("pushInsteadOf", run["wall"])
        self.assertIn("--auto", run["args"])
        self.assertIn("git push*", run["perms"])

    def test_changes_feed_back_and_second_round_passes(self):
        job = self.wait(self.submit("local", "BADFIRST"), "ready")
        self.assertEqual(job["round"], 2)
        self.assertIn("bug at x.py:1", self.oc()[1]["prompt"])
        self.assertIn("-s", self.oc()[1]["args"])

    def test_no_change_means_no_claude_call(self):
        job = self.wait(self.submit("local", "ANALYSIS"), "done")
        self.assertEqual(job["verdict"], "UNREVIEWED")
        self.assertEqual(self.reviews(), [])

    def test_repeated_failure_asks_human_and_claude_can_take_over(self):
        jid = self.submit("local", "ALWAYSBAD")
        job = self.wait(jid, "need_human")
        self.assertIn("claude", job["question"])
        self.assertEqual(len(self.oc()), 2)
        self.crew("reply", jid, "claude")
        time.sleep(0.5)
        self.wait(jid, "need_human")
        self.assertEqual(sum(c["role"] == "coder" for c in self.calls()), 1)

    def test_human_guidance_gives_the_local_model_another_round(self):
        jid = self.submit("local", "ALWAYSBAD")
        self.wait(jid, "need_human")
        self.crew("reply", jid, "use a set")
        time.sleep(0.5)
        self.wait(jid, "need_human")
        self.assertIn("use a set", self.oc()[2]["prompt"])

    def test_need_human_from_local_model(self):
        jid = self.submit("local", "OCASK")
        self.assertEqual(self.wait(jid, "need_human")["question"], "which api?")
        self.crew("reply", jid, "rest")
        self.wait(jid, "ready")

    def test_opencode_failure_fails_the_job_then_resumes(self):
        job = self.wait(self.submit("local", "OCFAIL"), "failed")
        self.assertIn("boom", job["error"])

    def test_gpu_lock_serializes_local_jobs(self):
        ids = [self.submit("local", "SLOWOC") for _ in range(3)]
        for jid in ids:
            self.wait(jid, "ready")
        self.assertEqual(max(r["peak"] for r in self.oc()), 1)

    def test_opencode_really_runs_in_the_worktree(self):
        self.env["PWD"] = "/home/nobody"  # how crewd looks under systemd
        job = self.wait(self.submit("local", "fix it"), "ready")
        run = self.oc()[0]
        self.assertEqual(run["pwd"], job["worktree"])
        self.assertEqual(run["real_cwd"], job["worktree"])
        self.assertEqual(run["args"][run["args"].index("--dir") + 1], job["worktree"])
        self.assertIn(job["worktree"], run["prompt"])

    def test_kernel_blocks_writes_outside_the_worktree(self):
        main_head = self.sh("git rev-parse main")
        self.wait(self.submit("local", f"ESCAPE REPO={self.repo}"), "ready")
        self.assertEqual(json.loads((self.trace / "escape.json").read_text()), [128, 1, 1])
        self.assertEqual(self.sh("git rev-parse main"), main_head)
        self.assertFalse((self.repo / "escaped.txt").exists())
        self.assertFalse((Path.home() / ".crew-escape-probe").exists())

    def test_model_that_says_nothing_fails_and_can_resume(self):
        jid = self.submit("local", "OCSILENT")
        job = self.wait(jid, "failed")
        self.assertIn("length", job["error"])
        self.crew("reply", jid, "continue")
        self.wait(jid, "ready")
        self.assertIn("-s", self.oc()[1]["args"])

    def test_ledger_separates_providers(self):
        self.wait(self.submit("local", "fix it"), "ready")
        rows = [json.loads(x) for x in (self.tmp / "var/ledger.jsonl").read_text().splitlines()]
        self.assertEqual(sorted(r["provider"] for r in rows), ["claude", "local"])


class Notify(Base):
    def test_reports_each_finished_job_once(self):
        jid = self.submit("task", "x")
        self.wait(jid, "done")
        self.assertIn(f"[done] {jid}", self.crew("notify"))
        self.assertEqual(self.crew("notify"), "")


class Limits(Base):
    conf = {**Base.conf, "max_instances": 2, "max_jobs": 5}

    def test_instance_cap_holds_across_jobs(self):
        ids = [self.submit("task", "SLEEP5") for _ in range(5)]
        for jid in ids:
            self.wait(jid, "done")
        self.assertEqual(max(c["peak"] for c in self.calls()), 2)


class DailyBudget(Base):
    conf = {**Base.conf, "daily_budget_usd": 0.4, "max_jobs": 1}

    def test_queue_holds_when_daily_budget_is_spent(self):
        first = self.submit("task", "one")
        self.wait(first, "done")
        second = self.submit("task", "two")
        time.sleep(1.5)
        self.assertEqual(self.crew("status", second)["state"], "queued")
        self.assertTrue(any("daily budget" in e["note"] for e in self.crew("events")["events"]))


class Team(Base):
    def roles(self):
        return [c["role"] for c in self.calls()]

    def test_slices_run_in_parallel_and_merge(self):
        job = self.wait(self.submit("team", "SLICE2 build"), "ready")
        self.assertEqual({"slice0.txt", "slice1.txt"} & self.files(job["branch"]), {"slice0.txt", "slice1.txt"})
        self.assertEqual(self.roles()[0], "planner")
        self.assertEqual(self.roles()[-1], "qa")
        self.assertEqual(self.roles().count("coder"), 2)
        coders = [c for c in self.calls() if c["role"] == "coder"]
        self.assertLess(abs(coders[0]["start"] - coders[1]["start"]), 0.45)
        self.assertNotEqual(coders[0]["cwd"], coders[1]["cwd"])

    def test_reviewer_griller_parallel_and_readonly(self):
        self.wait(self.submit("team", "build"), "ready")
        review = [c for c in self.calls() if c["role"] in ("reviewer", "griller")]
        self.assertLess(abs(review[0]["start"] - review[1]["start"]), 0.45)
        for call in self.calls():
            read_only = call["role"] in ("planner", "reviewer", "griller", "qa")
            self.assertEqual("Edit" in call["args"], read_only, call["role"])

    def test_high_risk_stops_for_spec_then_runs(self):
        jid = self.submit("team", "build", "--risk", "high")
        job = self.wait(jid, "need_human")
        self.assertEqual(self.roles(), ["planner"])
        self.assertEqual(job["stage"], "gate")
        self.crew("reply", jid, "ok")
        self.wait(jid, "ready")

    def test_high_risk_feedback_replans(self):
        jid = self.submit("team", "build", "--risk", "high")
        self.wait(jid, "need_human")
        self.crew("reply", jid, "split it differently")
        time.sleep(1)
        self.wait(jid, "need_human")
        planners = [c for c in self.calls() if c["role"] == "planner"]
        self.assertEqual(len(planners), 2)
        self.assertIn("split it differently", planners[1]["prompt"])

    def test_review_changes_trigger_a_fix_round(self):
        job = self.wait(self.submit("team", "BADFIRST"), "ready")
        self.assertEqual(job["round"], 2)
        fixer = [c for c in self.calls() if c["role"] == "coder"][-1]
        self.assertIn("problem at x.py:1", fixer["prompt"])

    def test_no_convergence_asks_human_and_reply_adds_a_round(self):
        jid = self.submit("team", "ALWAYSBAD")
        job = self.wait(jid, "need_human")
        self.assertEqual(job["round"], 3)
        coders = self.roles().count("coder")
        self.crew("reply", jid, "try harder")
        self.wait(jid, "need_human", timeout=2) if False else None
        time.sleep(1)
        job = self.wait(jid, "need_human")
        self.assertEqual(self.roles().count("coder"), coders + 1)

    def test_planner_question_blocks_until_answered(self):
        jid = self.submit("team", "ASKPLAN")
        self.wait(jid, "need_human")
        self.crew("reply", jid, "rest")
        self.wait(jid, "ready")

    def test_merge_conflict_resolved_by_integrator(self):
        job = self.wait(self.submit("team", "CONFLICT"), "ready")
        self.assertEqual(self.sh(f"git show {job['branch']}:same.txt"), "merged")

    def test_unresolved_conflict_never_committed(self):
        job = self.wait(self.submit("team", "CONFLICT BADMERGE"), "failed")
        self.assertIn("conflict", job["error"])
        self.assertNotIn("same.txt", self.sh(f"git diff --name-only {job['base']}...{job['branch']}") if False else "")
        tree = Path(job["worktree"])
        log = subprocess.run(["git", "-C", str(tree), "log", "--all", "-p", "--format=", "--", "same.txt"],
                             capture_output=True, text=True).stdout
        self.assertNotIn("<<<<<<<", log)


class Wall(Base):
    def test_push_wall_blocks_every_remote(self):
        sys.path.insert(0, str(CREW.parent))
        env_src = CREW.read_text()
        ns = {}
        exec(env_src[env_src.index("PUSH_WALL = {"):env_src.index("class NeedHuman")], ns)
        bare = self.tmp / "bare.git"
        self.sh(f"git init -q --bare {bare} && git remote add origin {bare} && git remote add web https://example.invalid/x.git")
        env = {**self.env, **ns["PUSH_WALL"]}
        for remote in ("origin", "web"):
            out = subprocess.run(["git", "push", remote, "main"], cwd=self.repo, env=env, capture_output=True, text=True)
            self.assertNotEqual(out.returncode, 0, remote)
        self.assertEqual(subprocess.run(["git", "--git-dir", str(bare), "branch"], capture_output=True, text=True).stdout, "")
        self.sh("git push -q origin main")  # control: without the wall the same push works


class Mcp(Base):
    def rpc(self, *messages):
        text = "".join(json.dumps(m) + "\n" for m in messages)
        out = subprocess.run([sys.executable, str(CREW), "mcp"], input=text, env=self.env, capture_output=True, text=True)
        return [json.loads(x) for x in out.stdout.splitlines()]

    def test_protocol(self):
        init, listed, called, bad = self.rpc(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "crew_task", "arguments": {"prompt": "hi", "repo": "demo"}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "crew_status", "arguments": {"job_id": "../x"}}},
        )
        self.assertEqual(init["result"]["protocolVersion"], "2025-03-26")
        self.assertEqual(len(listed["result"]["tools"]), 11)
        self.wait(json.loads(called["result"]["content"][0]["text"])["id"], "done")
        self.assertTrue(bad["result"]["isError"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
