"""Repeatable CPU benchmark through the real fixed-step/render callback.

Run with --repeats 3 --output report.json; --source-root compares an archived
source tree using the same fixture. Windows keeps its Tk window withdrawn, so
these numbers exclude visible desktop composition and real Explorer latency.
Linux requires the same isolated Xvfb environment as the acceptance suite.
"""
import argparse
from contextlib import ExitStack
import json
import math
import os
import random
import statistics
import sys
import time
from types import SimpleNamespace
from unittest import mock

import harness


SCENARIOS = (
    ("default_2", 2, (), 16),
    ("mixed_10", 10, ("crate", "seesaw", "ramp", "fan", "conveyor"), 16),
    ("crates_10", 10, ("crate",) * 6, 16),
    ("dense_400", 10, ("crate",) * 6, 400),
)


def distribution(values):
    ordered = sorted(values)
    return dict(mean=statistics.mean(values),
                p95=ordered[max(0, math.ceil(len(ordered) * .95) - 1)],
                maximum=max(values))


def run_scenario(scenario, frames=400, warmup=480):
    name, crowd, props, count = scenario
    gm = harness.load("performance_budget", crowd=crowd, group_scenes=True,
                      parkour=True, toy_props=True, react_to_windows=False,
                      auto_quality=False)
    app = None
    real_tk = gm.tk.Tk

    def hidden_root():
        root = real_tk()
        root.withdraw()
        return root

    try:
        with ExitStack() as patches:
            patches.enter_context(mock.patch.object(gm.tk, "Tk", hidden_root))
            patches.enter_context(mock.patch.object(gm, "virtual_screen", return_value=(0, 0, 1920, 1080)))
            patches.enter_context(mock.patch.object(gm, "monitors", return_value=[
                ((0, 0, 1920, 1080), (0, 0, 1920, 1040))]))
            random.seed(724)
            app = harness.build(gm)
            app.fx_random.seed(725)
            if app.x11_overlay is not None:
                app.x11_overlay.hide()
            icons = [("Icon %d" % i, 40 + i % 20 * 88, 180 + i // 20 * 38,
                      104 + i % 20 * 88, 212 + i // 20 * 38, i) for i in range(count)]
            harness.fake_terrain(app, icons=icons, windows=[
                ("Ledge", 250, 550, 650, 800, 101),
                ("High ledge", 1050, 300, 1600, 780, 102)])
            app.terrain_changed()
            for i, kind in enumerate(props):
                prop = app.motion.add_prop(kind, 140 + i * 310, 1040)
                assert prop is not None
                prop["life"] = 1000
            app.motion._build_in = 1000 if props else 12

            scheduled = []
            app.root.after = lambda delay, fn=None: scheduled.append(fn)
            app.root.mainloop = lambda: None
            app.tray.pump = app.tray.drain = lambda: None
            # Controlled 40 Hz frame arrivals, real CPU time within each tick.
            # This exercises App.run's accumulator, coalescing and paint flush.
            clock = {"frame": 100.0, "mark": time.perf_counter(), "first": True}
            def now():
                if clock["first"]:
                    clock["first"] = False
                    return clock["frame"]
                return clock["frame"] + time.perf_counter() - clock["mark"]
            gm.time = SimpleNamespace(perf_counter=now, strftime=time.strftime,
                                      localtime=lambda: time.struct_time((2026, 9, 16, 12, 0, 0, 2, 259, -1)))
            app.run()
            rows = {k: [] for k in ("update_ms", "draw_ms", "work_ms")}
            states, steps = {}, 0
            max_items = max_shots = 0
            for i in range(warmup + frames):
                callback = scheduled.pop()
                assert callback is not None and not scheduled
                clock["frame"], clock["mark"] = 100 + (i + 1) / 40, time.perf_counter()
                clock["first"] = True
                started = time.perf_counter()
                callback()
                work = (time.perf_counter() - started) * 1000
                assert not app._frame_errs, "Frame callback swallowed an exception"
                if i >= warmup:
                    sample = app.performance.samples[-1]
                    rows["update_ms"].append(sample[1])
                    rows["draw_ms"].append(sample[2])
                    rows["work_ms"].append(work)
                    steps += sample[3]
                    max_items = max(max_items, len(app.canvas.find_all()))
                    max_shots = max(max_shots, len(app.shots) + len(app.arsenal.shots))
                    for actor in app.fighters:
                        states[actor.state] = states.get(actor.state, 0) + 1
            assert abs(steps - frames * 1.5) <= 1, (steps, frames)
            return dict(scenario=name, frames=frames, steps=steps,
                        metrics={k: distribution(v) for k, v in rows.items()},
                        max_items=max_items, max_shots=max_shots, states=states)
    finally:
        harness.teardown(gm, app)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--frames", type=int, default=400)
    parser.add_argument("--source-root")
    parser.add_argument("--output")
    args = parser.parse_args()
    if sys.platform == "linux" and os.environ.get("GREMLIN_ISOLATED_X11") != "1":
        parser.error("Use isolated Xvfb with GREMLIN_ISOLATED_X11=1")
    if args.repeats < 1 or args.frames < 40:
        parser.error("Use at least one repetition and 40 frames")
    if args.source_root:
        source = os.path.abspath(args.source_root)
        harness.SRC = os.path.join(source, "desktop_gremlin.py")
        sys.path.insert(0, source)
    results = []
    for scenario in SCENARIOS:
        for repeat in range(args.repeats):
            result = run_scenario(scenario, frames=args.frames)
            results.append(result)
            print(json.dumps(result), flush=True)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as out:
            json.dump(dict(platform=sys.platform, python=sys.version,
                           visible_composition=False, results=results), out, indent=2)


if __name__ == "__main__":
    main()
