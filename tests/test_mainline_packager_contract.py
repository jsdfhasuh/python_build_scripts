import re
import unittest
from pathlib import Path
import yaml

P=Path(".github/workflows/windows-package-mainline-v2.yml")
RAW=P.read_text(encoding="utf-8")
WF=yaml.load(RAW,Loader=yaml.BaseLoader)
WIN=WF["jobs"]["windows"]

class RoutedPackagerContract(unittest.TestCase):
    def test_target_modes_and_conflict(self):
        modes=WF["on"]["workflow_call"]["inputs"]
        self.assertEqual(modes["designer_only"]["default"],"false")
        self.assertEqual(modes["runtime_only"]["default"],"false")
        self.assertEqual(WIN["needs"],"validate_selection")
        self.assertIn("inputs.designer_only && inputs.runtime_only",RAW)
        self.assertIn('["emo-master","emo-master-runtime"]',WIN["strategy"]["matrix"]["target"])

    def test_exact_candidate_caller_paths_and_actor(self):
        cond=WIN["if"]
        self.assertNotIn("refs/heads/",cond)
        self.assertNotIn("github.event_name == 'push'",cond)
        self.assertIn("github.event_name == 'workflow_dispatch'",cond)
        for path in ("dispatch-runtime-windows-candidate.yml",
                     "dispatch-windows-package-candidate.yml"):
            self.assertIn(path,cond)
        self.assertIn("github.workflow_sha == vars.EMO_CI_CANDIDATE_WORKER_SHA",cond)
        self.assertIn("github.actor_id == vars.EMO_CI_CANDIDATE_BROKER_ACTOR_ID",cond)
        self.assertIn("github.run_attempt == '1'",cond)

    def test_version_comes_from_exact_checkout_and_reuses_one_tag(self):
        steps={step.get("name"):step for step in WIN["steps"]}
        identity=steps["Record Runtime build identity"]["run"]
        self.assertLess(identity.index("Checkout identity mismatch"),identity.index("APP_VERSION"))
        self.assertLess(identity.index("release_tag=v"),identity.index("emo-master-runtime"))
        self.assertNotIn("v0.6.6",RAW)
        for name in ("Build Windows artifacts","Verify Runtime archive and native cycles",
                     "Verify Designer icons","Validate original frozen startup and workflow contracts",
                     "Seal exact target files with reviewed age"):
            self.assertIn("steps.identity.outputs.release_tag",steps[name]["env"]["RELEASE_TAG_INPUT"])
            self.assertIn("$env:RELEASE_TAG_INPUT",steps[name]["run"])

    def test_builder_recipients_and_no_release_permission(self):
        self.assertIn("ref: e0204fe6fe83b0f31818d88e4f296c70e230d172",RAW)
        self.assertIn("-BuildOnly",RAW)
        self.assertNotRegex(RAW,r"secrets:|contents: write|gh release")
        self.assertIn('retention-days:',RAW)
