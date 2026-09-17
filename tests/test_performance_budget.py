"""Full-feature frame p95 guard; deterministic fixed steps through App.run."""
import unittest

from benchmark_performance import SCENARIOS, run_scenario


class PerformanceBudget(unittest.TestCase):
    def test_full_feature_scenes_fit_default_frame_budget(self):
        for scenario in (SCENARIOS[1], SCENARIOS[3]):
            with self.subTest(scene=scenario[0]):
                result = run_scenario(scenario, frames=240)
                p95 = result["metrics"]["work_ms"]["p95"]
                print("%s: mean %.2f ms, p95 %.2f ms; %d steps, %d pooled items" % (
                    scenario[0], result["metrics"]["work_ms"]["mean"], p95,
                    result["steps"], result["max_items"]), flush=True)
                self.assertLess(p95, 25., "Full-feature p95 exceeds the default 40 FPS CPU budget")
                self.assertEqual(result["steps"], 360)
                self.assertGreater(len(result["states"]), 5)


if __name__ == "__main__":
    unittest.main()
