import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from fetch_transcript import windows_of

CASES = [
    (150,  [(0, 150)]),
    (1800, [(0, 1800)]),
    (2300, [(0, 2300)]),                                   # 500s tail merges
    (2401, [(0, 1800), (1800, 2401)]),                     # 601s tail stays
    (3600, [(0, 1800), (1800, 3600)]),
    (5400, [(0, 1800), (1800, 3600), (3600, 5400)]),
    (5990, [(0, 1800), (1800, 3600), (3600, 5990)]),       # 590s tail merges
]

def main():
    for dur, want in CASES:
        got = windows_of(dur)
        assert got == want, f"windows_of({dur}) = {got}, want {want}"
    print("test_windows_of: OK")

if __name__ == "__main__":
    main()
