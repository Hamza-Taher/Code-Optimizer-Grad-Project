from helpers import write
from repo_analyzer import discover, filter_repo
from repo_analyzer.phase3_static import analyze_repository

def test_static_analysis_ast_and_risks(tmp_path):
    code_content = """
def sample_function():
    return 42

class SampleClass:
    def method(self):
        pass

def risky_function(user_input):
    return eval(user_input)
"""
    write(tmp_path, "main.py", code_content)
    
    filtered = filter_repo(tmp_path)
    discovered = discover(filtered)
    result = analyze_repository(discovered)

    assert len(result.file_results) == 1
    file_res = result.file_results[0]
    assert file_res.file_path == "main.py"

    fact_names = [fact.name for fact in file_res.ast_facts]
    assert "sample_function" in fact_names
    assert "SampleClass" in fact_names
    assert "method" in fact_names
    assert "risky_function" in fact_names

    assert len(file_res.risks) == 1
    assert file_res.risks[0].risk_type == "Dangerous Execution"