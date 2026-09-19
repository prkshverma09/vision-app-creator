"""Canonical deterministic verification entrypoint for all task families."""
import argparse, json, os, subprocess, sys, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
PROFILES=("cpu","vision","cloud","ci")

def run(command: list[str], env: dict[str,str]) -> dict[str,object]:
    started=time.monotonic(); print("+", " ".join(command), flush=True)
    result=subprocess.run(command, cwd=ROOT, env=env, check=False)
    return {"command":command,"exit_code":result.returncode,"duration_ms":round((time.monotonic()-started)*1000)}

def parser() -> argparse.ArgumentParser:
    p=argparse.ArgumentParser(description="Vision App Creator verification runner")
    p.add_argument("--profile", choices=PROFILES, default="cpu"); p.add_argument("--report", default="artifacts/verify-report.json")
    sub=p.add_subparsers(dest="command", required=True)
    sub.add_parser("static"); sub.add_parser("contracts")
    c=sub.add_parser("component"); c.add_argument("--area", required=True)
    i=sub.add_parser("integration"); i.add_argument("--suite", required=True)
    e=sub.add_parser("e2e"); e.add_argument("--journey", required=True)
    sub.add_parser("all")
    return p

def commands(args: argparse.Namespace) -> list[list[str]]:
    py=sys.executable
    static=[[py,"-m","ruff","check","--select","F","backend/src","backend/tests","tools"],[py,"-m","mypy","backend/src"],["pnpm","--filter","@vision-app/web","typecheck"],[py,"tools/validate_plan.py"]]
    contracts=[[py,"tools/export_contracts.py"],[py,"-m","pytest","backend/tests/contracts","backend/tests/component/contracts"]]
    if args.command=="static": return static
    if args.command=="contracts": return contracts
    if args.command=="component": return [[py,"-m","pytest",f"backend/tests/component/{args.area}"]]
    if args.command=="integration": return [[py,"-m","pytest",f"backend/tests/integration/{args.suite}"]]
    if args.command=="e2e": return [["pnpm","exec","playwright","test","--config","infra/playwright.config.ts","--grep",args.journey]]
    return static+contracts+[[py,"-m","pytest","backend/tests/component"],["pnpm","--filter","@vision-app/web","test"]]

def main() -> int:
    args=parser().parse_args(); env=os.environ.copy(); env["VISION_APP_TEST_PROFILE"]=args.profile
    env["VISION_APP_NETWORK_POLICY"]="cloud" if args.profile=="cloud" else "deny"
    if args.profile=="cloud" and not any(k in env for k in ("GOOGLE_API_KEY","GOOGLE_APPLICATION_CREDENTIALS")):
        print("cloud profile requires provider credentials",file=sys.stderr); return 2
    results=[]
    for command in commands(args):
        item=run(command,env); results.append(item)
        if item["exit_code"] != 0: break
    report=ROOT/args.report; report.parent.mkdir(parents=True,exist_ok=True)
    success=bool(results) and all(item["exit_code"]==0 for item in results)
    report.write_text(json.dumps({"profile":args.profile,"command":args.command,"success":success,"results":results},indent=2)+"\n")
    print(f"report: {report}"); return 0 if success else 1
if __name__=="__main__": raise SystemExit(main())
