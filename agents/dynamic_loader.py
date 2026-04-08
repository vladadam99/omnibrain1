
import os, importlib.util, glob

RUNS_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "bob_runs"))

def _load_module_from_path(py_path):
    spec = importlib.util.spec_from_file_location(os.path.basename(py_path), py_path)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod

def load_synth_agents(run_id: str):
    run_dir = None
    for name in os.listdir(RUNS_ROOT):
        if run_id in name: run_dir = os.path.join(RUNS_ROOT, name); break
    if not run_dir: return []
    agent_dirs = glob.glob(os.path.join(run_dir, "trials", "*", "agent_sources"))
    if not agent_dirs: agent_dirs = glob.glob(os.path.join(run_dir, "agent_sources", "*"))
    out = []
    for asrc in sorted(agent_dirs, reverse=True)[:1]:
        for py in glob.glob(os.path.join(asrc, "*.py")):
            try:
                mod = _load_module_from_path(py)
                fn = getattr(mod, "generate_signal", None)
                if callable(fn): out.append((os.path.splitext(os.path.basename(py))[0], fn))
            except Exception: pass
    return out
