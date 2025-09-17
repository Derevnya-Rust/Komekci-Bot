from pathlib import Path
SKIP = {"venv","__pycache__","assets","logs","dist","build","static",".git"}

def pytest_generate_tests(metafunc):
    files=[]
    root=Path(__file__).resolve().parents[1]
    for p in root.rglob("*.py"):
        if any(part in SKIP for part in p.parts):
            continue
        files.append(p)
    metafunc.parametrize("path", sorted(files), ids=[str(p.relative_to(root)) for p in files])

def test_compile(path: Path):
    src = path.read_text(encoding="utf-8")
    compile(src, str(path), "exec")
