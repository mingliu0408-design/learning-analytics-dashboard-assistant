"""Run the unchanged M0 lexical harness once, redirecting ONLY its owned output root."""
from m1_common import OWNED
import run_diagnostics as m0

if __name__ == '__main__':
    # M0 fixture_validation's default still points at the immutable M0 fixtures.
    # No retrieval function, fixture, ranking parameter or threshold is replaced.
    m0.OWNED = OWNED
    m0.main()
