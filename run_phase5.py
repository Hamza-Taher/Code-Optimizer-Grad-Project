from repo_analyzer.phase1_filter import filter_repo
from repo_analyzer.phase2_discovery import discover
from repo_analyzer.phase4_recipe import extract_recipes
from repo_analyzer.phase5_sandbox import verify_recipes

f = filter_repo("test_repo")
d = discover(f)
r = extract_recipes(d)
s = verify_recipes(d, r)

for v in s.results:
    print(v.sub_project or "(root)", v.status, v.confidence, v.tests_collected, v.attempts)
    for n in v.notes:
        print("  ", n)
    for st in v.steps:
        print("  ", st.name, st.exit_code, st.duration_s)
print(s.warnings)