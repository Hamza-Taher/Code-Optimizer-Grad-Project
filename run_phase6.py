from repo_analyzer.phase1_filter import filter_repo
from repo_analyzer.phase2_discovery import discover
from repo_analyzer.phase3_static import analyze_repository   # عدّل الاسم
from repo_analyzer.phase4_recipe import extract_recipes      # عدّل الاسم
from repo_analyzer.phase5_sandbox import verify_recipes
from repo_analyzer.phase6_profile import build_profile, write_profile, write_llm_view

f = filter_repo("test_repo")
d = discover(f)
st = analyze_repository(d)
r = extract_recipes(d)
s = verify_recipes(d, r)

p = build_profile(d, r, s, st)
write_profile(p, "profile.json")
write_llm_view(p, "profile_llm_view.json")

print(p.handoff)
for sp in p.sub_projects:
    print(sp.id, sp.confidence, sp.verification.status)
print(p.warnings)