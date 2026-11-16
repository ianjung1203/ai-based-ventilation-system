from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

from .data import group_runs, load_csv, save_csv


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="열어조 AI: 시계열 예측, 학습, 모형 개폐 시뮬레이션")
    sub = parser.add_subparsers(dest="command", required=True)
    synth = sub.add_parser("simulate", help="generate clearly labelled synthetic experiments")
    synth.add_argument("--output", default="data/synthetic.csv")
    synth.add_argument("--runs", type=int, default=48)
    synth.add_argument("--seed", type=int, default=2026)
    training = sub.add_parser("train", help="train and evaluate on independent runs")
    training.add_argument("--data", required=True)
    training.add_argument("--output", default="artifacts/demo_model")
    training.add_argument("--epochs", type=int, default=220)
    infer = sub.add_parser("predict", help="offline replay of the last history window")
    infer.add_argument("--data", required=True)
    infer.add_argument("--model", default="artifacts/demo_model")
    infer.add_argument("--output", default="artifacts/prediction.json")
    bench = sub.add_parser("benchmark", help="paired simulation of three control strategies")
    bench.add_argument("--model", default="artifacts/demo_model")
    bench.add_argument("--output", default="artifacts/controller_comparison.json")
    serving = sub.add_parser("serve", help="local prediction API and interactive model viewer")
    serving.add_argument("--model", default="artifacts/demo_model")
    serving.add_argument("--port", type=int, default=8765)
    serving.add_argument("--db", default="artifacts/telemetry.sqlite3")
    args = parser.parse_args()
    if args.command == "simulate":
        from .simulation import generate_runs
        if args.runs < 1:
            parser.error("--runs must be positive")
        rows = generate_runs(args.runs, args.seed)
        save_csv(args.output, rows)
        # Copyable schema examples, with explicit source and UTC timestamps.
        example = rows[90:121]
        write_json("examples/history.json", {"history": [r.to_dict() for r in example]})
        save_csv("examples/telemetry_template.csv", rows[:3])
        print(f"Saved {len(rows)} SYNTHETIC readings to {args.output}")
    elif args.command == "train":
        from .training import train
        report = train(load_csv(args.data), args.output, epochs=args.epochs)
        print(json.dumps({"model_dir": args.output, "source": report["evaluation_scope"],
                          "training_seconds": report["training_seconds"]}, ensure_ascii=False))
    elif args.command == "predict":
        from .predictor import Predictor
        rows = list(group_runs(load_csv(args.data)).values())[-1][-31:]
        result = Predictor(args.model).forecast(rows, now=rows[-1].timestamp)
        result["execution_mode"] = "OFFLINE_REPLAY"
        write_json(args.output, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "benchmark":
        from .benchmark import compare_controllers
        from .predictor import Predictor
        result = compare_controllers(Predictor(args.model))
        write_json(args.output, result)
        print(json.dumps(result["mean_metrics"], ensure_ascii=False, indent=2))
    elif args.command == "serve":
        from .server import serve
        serve(args.model, args.port, args.db)


if __name__ == "__main__":
    main()
