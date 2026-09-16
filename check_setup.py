"""
Run this to check whether your qa-framework folder is set up correctly.
It does NOT run the framework itself -- it just checks that everything
it needs is in the right place, with clear pass/fail messages.

Usage: from inside your qa-framework folder, run:
    python check_setup.py
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()  # loads your .env file automatically, same as run.py does

CHECK = "  [OK]  "
CROSS = "  [MISSING]  "

problems = []


def report(passed: bool, label: str, fix_hint: str = ""):
    if passed:
        print(f"{CHECK}{label}")
    else:
        print(f"{CROSS}{label}")
        if fix_hint:
            print(f"           -> {fix_hint}")
        problems.append(label)


print("Checking your qa-framework folder...\n")

root = Path(os.environ.get("QA_FRAMEWORK_ROOT", ".")).resolve()
print(f"Looking in: {root}\n")

# 1. Core files that should sit directly in the folder
core_files = ["AGENT_INSTRUCTIONS.md", "state.py", "llm_gateway.py", "nodes.py", "graph.py", "run.py", "requirements.txt"]
for filename in core_files:
    report((root / filename).exists(), f"{filename} present", f"Save {filename} directly inside {root}")

# 2. The skills folder and all 11 skill files, with the exact names llm_gateway.py expects
expected_skills = [
    "S1_input_normalization.md",
    "S2_ambiguity_detection.md",
    "S3_test_case_generation.md",
    "S4_test_data_generation.md",
    "S5_test_script_generation.md",
    "S6_execution_orchestration.md",
    "S7_failure_classification.md",
    "S8_security_boundary_scan.md",
    "S9_reporting_aggregation.md",
    "S10_release_readiness_summary.md",
    "S11_cicd_gate_adapter.md",
]
skills_dir = root / "skills"
report(skills_dir.exists(), "skills/ folder present", "Create a folder named exactly 'skills' inside your qa-framework folder")

if skills_dir.exists():
    for skill_file in expected_skills:
        exact_match = (skills_dir / skill_file).exists()
        if exact_match:
            report(True, f"skills/{skill_file}")
        else:
            # Help spot near-misses -- e.g. a slightly different filename
            close_matches = [f.name for f in skills_dir.glob("*.md") if skill_file.split("_")[0] in f.name]
            hint = f"Found similarly named file(s): {close_matches} -- rename to exactly '{skill_file}'" if close_matches else f"File not found -- add it as skills/{skill_file}"
            report(False, f"skills/{skill_file}", hint)

print()

# 3. The .env file and whether it defines the three required variables
env_path = root / ".env"
report(env_path.exists(), ".env file present", "Create a file named exactly '.env' inside your qa-framework folder")

if env_path.exists():
    env_text = env_path.read_text(encoding="utf-8")
    required_vars = ["ANTHROPIC_API_KEY", "QA_FRAMEWORK_DATABASE_URL", "QA_FRAMEWORK_ROOT"]
    for var in required_vars:
        has_var = any(line.strip().startswith(f"{var}=") and len(line.strip()) > len(var) + 1 for line in env_text.splitlines())
        report(has_var, f".env defines {var}", f"Add a line to .env: {var}=your-value-here")

print()

# 4. Python packages actually installed
packages = {"langgraph": "langgraph", "langgraph.checkpoint.postgres": "langgraph-checkpoint-postgres", "psycopg": "psycopg[binary,pool]", "anthropic": "anthropic", "dotenv": "python-dotenv"}
for import_name, pip_name in packages.items():
    try:
        __import__(import_name)
        report(True, f"Python package '{import_name}' installed")
    except ImportError:
        report(False, f"Python package '{import_name}' installed", f"Run: pip install {pip_name}")

print()

# 5. Can we actually reach the Postgres database?
db_url = os.environ.get("QA_FRAMEWORK_DATABASE_URL")
if db_url:
    try:
        import psycopg
        with psycopg.connect(db_url, connect_timeout=5) as conn:
            report(True, "Database is reachable")
    except Exception as e:
        report(False, "Database is reachable", f"Make sure Docker Desktop is open and you ran the 'docker run' command from step 4. Error detail: {e}")
else:
    report(False, "Database is reachable", "QA_FRAMEWORK_DATABASE_URL isn't set -- check your .env file, or that you loaded it (see note below)")

print()

# 6. Playwright browsers and the Allure commandline tool
import shutil
import subprocess

try:
    import playwright  # noqa: F401
    report(True, "Python package 'playwright' installed")
    # Check the actual browser binaries are downloaded, not just the library
    check = subprocess.run(["playwright", "install", "--dry-run"], capture_output=True, text=True)
    report("chromium" in check.stdout.lower() or check.returncode == 0, "Playwright browsers downloaded", "Run: playwright install")
except ImportError:
    report(False, "Python package 'playwright' installed", "Run: pip install playwright")

allure_path = shutil.which("allure")
report(allure_path is not None, "Allure commandline tool available", "Install Allure -- see the setup steps for your OS (requires Java)")

print("\n" + "=" * 50)
if not problems:
    print("Everything looks good. You're ready to try: python run.py requirement.txt")
else:
    print(f"{len(problems)} thing(s) need fixing before you run the framework:")
    for p in problems:
        print(f"  - {p}")
print("=" * 50)
